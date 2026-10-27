from __future__ import annotations

import ast
import sqlite3
from contextlib import closing
from pathlib import Path

from helpers import make_employee, make_project

import ks_yonetim.ml as ml_module
from ks_yonetim.backup import backup_manager

ML = "/api/v1/analytics/ml"


def supplier(client, name="Firma A"):
    return client.post("/api/v1/suppliers", json={"name": name}).json()


def material(client, name="MDF", unit="levha"):
    return client.post(
        "/api/v1/materials",
        json={"name": name, "default_unit": unit, "tracking_mode": "estimated"},
    ).json()


_counter = {"n": 0}


def buy(client, supplier_id, material_id, day, price, unit="levha", qty="1", key=None, project=None):
    _counter["n"] += 1
    response = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier_id,
            "material_id": material_id,
            "project_id": project,
            "purchase_date": day,
            "quantity": qty,
            "unit": unit,
            "unit_price_kurus": price,
            "idempotency_key": key or f"ml-buy-{_counter['n']:06d}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def insights(client, as_of="2026-12-01"):
    response = client.get(f"{ML}/insights", params={"as_of": as_of})
    assert response.status_code == 200, response.text
    return response.json()


WEEKLY = ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"]


def test_minimum_data_thresholds(client):
    sup, mat = supplier(client), material(client)
    for day, price in zip(WEEKLY[:4], [10000, 10100, 9900, 20000], strict=True):
        buy(client, sup["id"], mat["id"], day, price)
    body = insights(client)
    assert body["price_anomalies"] == []  # 4 kayıt < 5
    assert len(body["reorder_forecasts"]) == 1  # 4 benzersiz tarih yeterli
    buy(client, sup["id"], mat["id"], WEEKLY[4], 10000)
    assert len(insights(client)["price_anomalies"]) == 1

    status = client.get(f"{ML}/status").json()
    assert status["local_only"] is True and status["external_services"] == []
    by_name = {m["model_name"]: m for m in status["models"]}
    assert set(by_name) == set(ml_module.MODEL_NAMES)
    assert by_name["payroll_load"]["ready"] is False


def test_opening_balances_and_cancelled_records_are_excluded(client):
    sup, mat = supplier(client), material(client)
    for index, day in enumerate(WEEKLY):
        buy(client, sup["id"], mat["id"], day, 10000, key=f"opening:abc{index:06d}")
    body = insights(client)
    assert body["price_anomalies"] == [] and body["reorder_forecasts"] == []
    assert body["status"]["purchase_count"] == 0

    # Açılış bakiyesi malzemesi altındaki kayıtlar da dışarıda kalır.
    opening_material = material(client, "Açılış Bakiyesi", "tutar")
    for day in WEEKLY:
        buy(client, sup["id"], opening_material["id"], day, 5000)
    assert insights(client)["reorder_forecasts"] == []

    real = [buy(client, sup["id"], mat["id"], day, 10000) for day in WEEKLY]
    assert len(insights(client)["price_anomalies"]) == 1
    assert client.post(f"/api/v1/purchases/{real[2]['id']}/cancel").status_code == 200
    body = insights(client)
    assert body["price_anomalies"] == []  # iptal sonrası 4 kayıt
    assert len(body["reorder_forecasts"]) == 1


def test_different_units_are_not_mixed(client):
    sup, mat = supplier(client), material(client)
    for index, day in enumerate(WEEKLY[:3]):
        buy(client, sup["id"], mat["id"], day, 10000 + index, unit="levha")
        buy(client, sup["id"], mat["id"], day.replace("-09-", "-10-"), 50000, unit="m2")
    assert insights(client)["price_anomalies"] == []  # her seri 3 kayıt; karışmadı
    for day in WEEKLY[3:]:
        buy(client, sup["id"], mat["id"], day, 10002, unit="levha")
        buy(client, sup["id"], mat["id"], day.replace("-09-", "-10-"), 50000, unit="m2")
    rows = insights(client)["price_anomalies"]
    assert sorted(r["unit"] for r in rows) == ["levha", "m2"]
    assert all(r["is_anomaly"] is False for r in rows)


def test_known_price_anomaly_is_explained_and_runs_are_deterministic(client):
    sup, mat = supplier(client), material(client)
    for day, price in zip(WEEKLY, [10000, 10200, 10100, 9900, 20000], strict=True):
        buy(client, sup["id"], mat["id"], day, price)
    anomaly = insights(client)["price_anomalies"][0]
    assert anomaly["is_anomaly"] and anomaly["deviation_percent"] > 80
    assert anomaly["latest_unit_price_kurus"] == 20000 and anomaly["expected_unit_price_kurus"] < 11000
    assert "anomali" in anomaly["explanation"]

    first = client.post(f"{ML}/run", json={"as_of": "2026-10-01"}).json()
    second = client.post(f"{ML}/run", json={"as_of": "2026-10-01"}).json()
    assert [r["model_name"] for r in first["runs"]] == list(ml_module.MODEL_NAMES)

    def snapshot(run_ids):
        rows = []
        for run_id in run_ids:
            for item in client.get(f"{ML}/predictions", params={"run_id": run_id}).json():
                rows.append((item["prediction_type"], item["entity_id"], item["predicted_value"],
                             item["confidence"], str(item["explanation"])))
        return sorted(rows)

    assert snapshot([r["id"] for r in first["runs"]]) == snapshot([r["id"] for r in second["runs"]])
    assert len(client.get(f"{ML}/runs").json()) == 12
    assert len(client.get(f"{ML}/runs", params={"model_name": "reorder"}).json()) == 2
    run = client.get(f"{ML}/runs", params={"model_name": "price_anomaly"}).json()[0]
    assert run["sample_count"] == 5 and run["trained_from"] == "2026-09-01"
    assert run["model_version"] and run["metrics"]["anomalies"] == 1


def test_regular_and_irregular_reorder_intervals(client):
    sup = supplier(client)
    regular, irregular = material(client, "Düzenli"), material(client, "Düzensiz")
    for day in WEEKLY:
        buy(client, sup["id"], regular["id"], day, 1000)
    for day in ["2026-07-01", "2026-07-04", "2026-08-20", "2026-08-22", "2026-09-30"]:
        buy(client, sup["id"], irregular["id"], day, 1000)
    forecasts = {f["material_name"]: f for f in insights(client, "2026-10-01")["reorder_forecasts"]}
    assert forecasts["Düzenli"]["confidence"] == "high"
    assert forecasts["Düzenli"]["next_expected_date"] == "2026-10-06"
    assert forecasts["Düzensiz"]["confidence"] == "low"
    assert forecasts["Düzensiz"]["confidence_score"] < forecasts["Düzenli"]["confidence_score"]


def test_project_budget_overrun_uses_purchases_labor_accrual_and_expenses(client):
    project = make_project(client, budget_kurus=1000000)
    employee = make_employee(client, "Usta", "daily", 200000)
    sup, mat = supplier(client), material(client)
    buy(client, sup["id"], mat["id"], "2026-09-01", 100000, project=project["id"])
    for day in ("2026-09-02", "2026-09-03"):
        client.post("/api/v1/work-logs", json={"employee_id": employee["id"], "work_date": day,
                                                "project_id": project["id"]})
    client.post("/api/v1/project-expenses", json={"project_id": project["id"], "expense_date": "2026-09-04",
                                                  "category": "other", "amount_kurus": 50000})
    body = insights(client, "2026-09-05")
    risk = body["project_risks"][0]
    assert risk["sample_count"] == 4 and risk["current_cost_kurus"] == 550000
    assert risk["risk_level"] == "high" and risk["projected_usage_percent"] >= 100
    assert risk["projected_30d_cost_kurus"] >= risk["current_cost_kurus"]


def test_supplier_price_comparison_guards(client):
    mat = material(client, "Çivi", "kg")
    cheap, dear, lone = supplier(client, "Ucuz"), supplier(client, "Pahalı"), supplier(client, "Tek")
    for index, day in enumerate(["2026-09-01", "2026-09-10", "2026-09-20"]):
        buy(client, cheap["id"], mat["id"], day, 1000, unit="kg", qty="10")
        buy(client, dear["id"], mat["id"], day, 1300, unit="kg", qty="12")
    buy(client, lone["id"], mat["id"], "2026-09-25", 500, unit="kg", qty="10")  # tek kayıt: elenir
    rows = insights(client)["supplier_comparisons"]
    assert len(rows) == 1
    row = rows[0]
    assert row["comparable"] is True and row["cheapest_supplier_name"] == "Ucuz"
    assert row["saving_percent"] > 20
    assert {s["supplier_name"] for s in row["suppliers"]} == {"Ucuz", "Pahalı"}

    # Miktar farkı büyükse "en ucuz" denmez.
    other = material(client, "Vida", "kg")
    for day in ["2026-09-01", "2026-09-10"]:
        buy(client, cheap["id"], other["id"], day, 100, unit="kg", qty="1")
        buy(client, dear["id"], other["id"], day, 130, unit="kg", qty="100")
    vida = next(r for r in insights(client)["supplier_comparisons"] if r["material_name"] == "Vida")
    assert vida["comparable"] is False and "quantity_gap" in vida["caveats"]
    assert vida["cheapest_supplier_id"] is None

    # Dönemleri hiç örtüşmeyen firmalar karşılaştırılamaz.
    late = material(client, "Boya", "lt")
    for day in ["2026-01-01", "2026-01-05"]:
        buy(client, cheap["id"], late["id"], day, 100, unit="lt", qty="5")
    for day in ["2026-08-01", "2026-08-05"]:
        buy(client, dear["id"], late["id"], day, 90, unit="lt", qty="5")
    boya = next(r for r in insights(client)["supplier_comparisons"] if r["material_name"] == "Boya")
    assert "period_gap" in boya["caveats"] and boya["comparable"] is False

    # Tek firmalı seri için sonuç üretilmez.
    solo = material(client, "Tutkal", "kg")
    for day in ["2026-09-01", "2026-09-05", "2026-09-09"]:
        buy(client, cheap["id"], solo["id"], day, 100, unit="kg", qty="5")
    assert "Tutkal" not in {r["material_name"] for r in insights(client)["supplier_comparisons"]}


def close_month(client, start, end):
    period = client.post("/api/v1/payroll-periods", json={"period_start": start, "period_end": end}).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/finalize").status_code == 200
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/close", json={"allow_unpaid": True}).status_code == 200
    return period


def test_payroll_load_needs_three_closed_periods_and_is_evaluated(client):
    make_employee(client, "Aylık", "monthly", 3000000)
    close_month(client, "2026-07-01", "2026-07-31")
    close_month(client, "2026-08-01", "2026-08-31")
    body = insights(client, "2026-09-15")
    assert body["payroll_forecast"] is None  # yetersiz payroll dönemi
    run = client.post(f"{ML}/run", json={"as_of": "2026-09-15", "models": ["payroll_load"]}).json()
    assert run["runs"][0]["prediction_count"] == 0
    assert run["runs"][0]["metrics"]["status"] == "insufficient_data"

    close_month(client, "2026-09-01", "2026-09-30")
    forecast = insights(client, "2026-10-02")["payroll_forecast"]
    assert forecast["period_start"] == "2026-10-01" and forecast["period_end"] == "2026-10-31"
    assert forecast["closed_period_count"] == 3
    # Aylık sabit 3.000.000 TL: günlük ortalama tüm aylarda aynı → 31 gün × 100.000
    assert abs(forecast["predicted_net_due_kurus"] - 3000000) <= 100

    result = client.post(f"{ML}/run", json={"as_of": "2026-10-02", "models": ["payroll_load"]}).json()
    prediction = client.get(f"{ML}/predictions", params={"run_id": result["runs"][0]["id"]}).json()[0]
    assert prediction["actual_value"] is None and prediction["target_date"] == "2026-10-31"

    # Dönem gerçekleşince tahmin gerçek değerle değerlendirilir.
    close_month(client, "2026-10-01", "2026-10-31")
    evaluated = client.post(f"{ML}/evaluate", json={"as_of": "2026-11-05"}).json()
    assert evaluated["evaluated_predictions"] == 1
    assert evaluated["metrics"]["payroll_load"]["evaluated"] == 1
    updated = client.get(f"{ML}/predictions", params={"evaluated": "true"}).json()[0]
    assert updated["actual_value"] == 3000000 and updated["evaluated_at"]
    assert abs(updated["predicted_value"] - updated["actual_value"]) <= 100


def test_reorder_prediction_is_evaluated_with_actual_next_purchase(client):
    sup, mat = supplier(client), material(client)
    for day in WEEKLY:
        buy(client, sup["id"], mat["id"], day, 1000)
    run = client.post(f"{ML}/run", json={"as_of": "2026-10-01", "models": ["reorder"]}).json()
    prediction = client.get(f"{ML}/predictions", params={"run_id": run["runs"][0]["id"]}).json()[0]
    assert prediction["predicted_value"] == 5  # 2026-10-06 - 2026-10-01
    assert client.post(f"{ML}/evaluate", json={"as_of": "2026-10-02"}).json()["evaluated_predictions"] == 0
    buy(client, sup["id"], mat["id"], "2026-10-08", 1000)
    done = client.post(f"{ML}/run", json={"as_of": "2026-10-10", "models": ["reorder"]}).json()
    assert done["evaluated_predictions"] == 1
    evaluated = client.get(f"{ML}/predictions", params={"evaluated": "true"}).json()[0]
    assert evaluated["actual_value"] == 7  # 2026-10-01 → 2026-10-08

    feedback = client.post(f"{ML}/predictions/{evaluated['id']}/feedback", json={"feedback": "useful", "note": "İyi"})
    assert feedback.status_code == 200 and feedback.json()["user_feedback"] == "useful"
    assert client.post(f"{ML}/predictions/{evaluated['id']}/feedback", json={"feedback": "bad"}).status_code == 422
    assert client.post(f"{ML}/predictions/nope/feedback", json={"feedback": "wrong"}).status_code == 404


def test_debt_risk_flags_overdue_without_creating_movements(client):
    employee = make_employee(client, "Borçlu", "monthly", 3100000)
    period = client.post("/api/v1/payroll-periods", json={"period_start": "2026-08-01", "period_end": "2026-08-31"}).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    client.post(f"/api/v1/payroll-periods/{period['id']}/finalize")
    client.post("/api/v1/employee-finance/movements", json={
        "employee_id": employee["id"], "movement_type": "employee_debt", "amount_kurus": 100000,
        "movement_date": "2026-08-15", "due_date": "2026-09-01", "idempotency_key": "ml-debt-0001"})
    before = len(client.get("/api/v1/employee-finance/movements").json())

    body = insights(client, "2026-10-15")
    risk = body["debt_risks"][0]
    assert risk["employee_id"] == employee["id"]
    assert risk["overdue_company_debt_kurus"] == 3100000
    assert risk["payment_need_30d_kurus"] == 3100000
    assert "overdue_company_debt" in risk["flags"] and "overdue_employee_debt" in risk["flags"]
    assert risk["risk_level"] in {"medium", "high"}

    client.post(f"{ML}/run", json={"as_of": "2026-10-15", "models": ["employee_debt_risk"]})
    assert len(client.get("/api/v1/employee-finance/movements").json()) == before  # hareket üretilmez
    prediction = client.get(f"{ML}/predictions", params={"prediction_type": "employee_debt_risk"}).json()[0]
    assert prediction["predicted_value"] == 3100000


def test_ml_modules_never_import_network_libraries():
    forbidden = {"socket", "http", "urllib", "requests", "httpx", "aiohttp", "smtplib", "ftplib",
                 "openai", "anthropic", "websockets"}
    source = Path(ml_module.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & forbidden


def test_ml_tables_exist_in_database(client):
    client.post(f"{ML}/run", json={"as_of": "2026-10-01"})
    with closing(sqlite3.connect(backup_manager.database_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ml_runs").fetchone()[0] == 6
