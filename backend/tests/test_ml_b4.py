from __future__ import annotations

from datetime import date, timedelta

from finance_helpers import make_material, make_purchase, make_supplier
from helpers import make_project
from sqlalchemy import func, select

from ks_yonetim.database import SessionLocal
from ks_yonetim.models import (
    EmployeeFinancialMovement,
    Payment,
    Purchase,
    PurchaseReceipt,
)

API = "/api/v1"
ML = f"{API}/analytics/ml"
MODELS = {
    "price_anomaly", "reorder", "project_budget_risk", "supplier_price_comparison", "payroll_load",
    "employee_debt_risk",
}


def counts():
    with SessionLocal() as session:
        return {
            model.__name__: session.scalar(select(func.count()).select_from(model))
            for model in (Purchase, Payment, EmployeeFinancialMovement, PurchaseReceipt)
        }


def test_insufficient_data_means_ready_false_empty_predictions_and_clear_message(client):
    insights = client.get(f"{ML}/insights").json()
    assert insights["status"]["ready"] is False
    assert insights["price_anomalies"] == [] and insights["reorder_forecasts"] == [] and insights["project_risks"] == []
    assert insights["read_only"] is True and insights["automatic_actions"] == []
    models = {m["model_name"]: m for m in insights["models"]}
    assert set(models) == MODELS
    for model in models.values():
        assert model["ready"] is False and model["prediction_count"] == 0 and model["sample_count"] == 0
        assert model["model_version"] == "1.0"
        assert model["message"].startswith("Yetersiz veri:") and model["requirement"] in model["message"]
        assert model["confidence"] is None

    status = client.get(f"{ML}/status").json()
    assert status["read_only"] is True and status["automatic_actions"] == [] and status["local_only"] is True
    for model in status["models"]:
        assert model["ready"] is False and model["message"].startswith("Yetersiz veri")
        assert model["sample_count"] == 0 and model["last_run_at"] is None

    run = client.post(f"{ML}/run", json={}).json()
    assert len(run["runs"]) == 6
    for item in run["runs"]:
        assert item["prediction_count"] == 0
        assert item["metrics"]["status"] == "insufficient_data" and item["metrics"]["ready"] is False
        assert item["metrics"]["message"].startswith("Yetersiz veri")
        assert item["model_version"] == "1.0"
    assert client.get(f"{ML}/predictions").json() == []


def build_price_series(client):
    supplier, material = make_supplier(client, "Fiyat Tedarikçi"), make_material(client, "Anomali Boya")
    project = make_project(client, "Risk Projesi", budget_kurus=1_000_000, contract_amount_kurus=3_000_000)
    start = date(2026, 1, 5)
    prices = [1000, 1010, 990, 1005, 1000, 2500]
    for index, price in enumerate(prices):
        day = start + timedelta(days=index * 10)
        make_purchase(
            client, supplier, material, project["id"], price * 10, f"pur-ml-{index:06d}", quantity="10.000",
            unit="levha", purchase_date=day.isoformat(),
        )
    return supplier, material, project


def test_ready_models_report_version_samples_confidence_and_last_run(client):
    supplier, material, project = build_price_series(client)
    insights = client.get(f"{ML}/insights").json()
    models = {m["model_name"]: m for m in insights["models"]}
    assert models["price_anomaly"]["ready"] is True and models["price_anomaly"]["sample_count"] == 6
    assert models["reorder"]["ready"] is True and models["reorder"]["message"] is None
    assert models["price_anomaly"]["confidence"] is not None
    assert insights["price_anomalies"][0]["is_anomaly"] is True

    run = client.post(f"{ML}/run", json={"as_of": "2026-03-10"}).json()
    by_name = {r["model_name"]: r for r in run["runs"]}
    assert by_name["price_anomaly"]["prediction_count"] == 1 and by_name["price_anomaly"]["sample_count"] == 6
    assert by_name["supplier_price_comparison"]["metrics"]["status"] == "insufficient_data"  # tek tedarikçi
    status = client.get(f"{ML}/status", params={"as_of": "2026-03-10"}).json()
    price = next(m for m in status["models"] if m["model_name"] == "price_anomaly")
    assert price["ready"] is True and price["sample_count"] == 6 and price["confidence"] > 0
    assert price["last_run_id"] == by_name["price_anomaly"]["id"] and price["last_run_at"]

    # Geriye uyumlu: geçmiş, tahminler, geri bildirim ve değerlendirme çalışır.
    history = client.get(f"{ML}/runs", params={"model_name": "price_anomaly"}).json()
    assert history[0]["id"] == by_name["price_anomaly"]["id"]
    predictions = client.get(f"{ML}/predictions", params={"prediction_type": "price_anomaly"}).json()
    assert len(predictions) == 1
    feedback = client.post(f"{ML}/predictions/{predictions[0]['id']}/feedback", json={"feedback": "useful"})
    assert feedback.status_code == 200
    evaluated = client.post(f"{ML}/evaluate", json={"as_of": "2026-04-30"})
    assert evaluated.status_code == 200 and "metrics" in evaluated.json()
    assert project["id"] and material["id"] and supplier["id"]


def test_project_budget_risk_uses_forecast_cost_at_completion(client):
    _, _, project = build_price_series(client)
    pid = project["id"]
    auto = next(r for r in client.get(f"{ML}/insights", params={"as_of": "2026-03-10"}).json()["project_risks"] if r["project_id"] == pid)
    profit = client.get(f"{API}/projects/{pid}/profitability").json()
    assert auto["forecast_cost_at_completion_kurus"] == profit["forecast_cost_at_completion_kurus"]
    assert auto["forecast_overrun_kurus"] == 0 and auto["forecast_source"] == "auto"
    assert auto["risk_level"] in ("low", "medium") and auto["budget_basis"] == "project_budget"
    assert auto["current_cost_kurus"] == profit["actual_cost_kurus"]  # olaylar teslim fişlerinden

    # Yönetici tahmini tahmini bitiş maliyetini bütçenin üstüne taşıyınca risk yüksek olur.
    client.put(
        f"{API}/projects/{pid}/cost-forecasts",
        json={"items": [{"category": "labor", "remaining_estimate_kurus": 2_000_000, "as_of_date": "2026-03-01",
                         "reason": "Montaj ekibi büyüdü"}]},
    )
    manual = next(r for r in client.get(f"{ML}/insights", params={"as_of": "2026-03-10"}).json()["project_risks"] if r["project_id"] == pid)
    after = client.get(f"{API}/projects/{pid}/profitability").json()
    assert manual["forecast_cost_at_completion_kurus"] == after["forecast_cost_at_completion_kurus"]
    assert manual["forecast_overrun_kurus"] == after["forecast_cost_at_completion_kurus"] - 1_000_000 > 0
    assert manual["risk_level"] == "high" and manual["forecast_source"] == "manual"
    assert "tahmini bitiş maliyeti" in manual["explanation"] and "yönetici tahmini" in manual["explanation"]
    # Tahmin kaydı risk modelini de kalıcı sonuca taşır.
    run = client.post(f"{ML}/run", json={"models": ["project_budget_risk"], "as_of": "2026-03-10"}).json()["runs"][0]
    prediction = client.get(f"{ML}/predictions", params={"run_id": run["id"]}).json()[0]
    assert prediction["explanation"]["forecast_cost_at_completion_kurus"] == after["forecast_cost_at_completion_kurus"]


def test_reorder_model_makes_no_stock_claim_and_no_model_acts_automatically(client):
    build_price_series(client)
    before = counts()
    insights = client.get(f"{ML}/insights", params={"as_of": "2026-03-10"}).json()
    forecast = insights["reorder_forecasts"][0]
    assert forecast["stock_claim"] is False and forecast["basis"] == "purchase_interval"
    assert "stok miktarı veya tükenme iddiası içermez" in forecast["disclaimer"]
    assert "stok" not in forecast["explanation"].casefold()
    client.post(f"{ML}/run", json={"as_of": "2026-03-10"})
    client.post(f"{ML}/evaluate", json={})
    assert counts() == before  # sipariş, ödeme veya maaş hareketi oluşmadı
    status = client.get(f"{ML}/status").json()
    assert status["read_only"] is True and status["automatic_actions"] == []
