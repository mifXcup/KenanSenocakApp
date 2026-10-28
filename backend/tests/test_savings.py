from __future__ import annotations

from datetime import date, timedelta

from finance_helpers import build_portfolio, make_material, make_purchase, make_supplier
from helpers import log_work, make_employee, make_project
from sqlalchemy import func, select

from ks_yonetim.database import SessionLocal
from ks_yonetim.models import AuditLog, CustomerFinancialMovement, Purchase

API = "/api/v1"
SAVINGS = f"{API}/analytics/savings"
SEVERITIES = {"high", "medium", "low"}


def by_type(body):
    grouped = {}
    for item in body["opportunities"]:
        grouped.setdefault(item["type"], []).append(item)
    return grouped


def add_price_and_supplier_history(client):
    """Fiyat anomalisi + net daha uygun tedarikçi + fazla mesai + projesiz gider verisi."""
    cheap, dear = make_supplier(client, "Ucuz Tedarikçi"), make_supplier(client, "Pahalı Tedarikçi")
    paint = make_material(client, "Boya")
    start = date(2026, 1, 5)
    for index in range(4):
        day = (start + timedelta(days=index * 15)).isoformat()
        make_purchase(client, cheap, paint, None, 10 * 1000, f"pur-sv-c{index:05d}", quantity="10.000", unit="kutu", purchase_date=day)
        make_purchase(client, dear, paint, None, 10 * 1400, f"pur-sv-d{index:05d}", quantity="10.000", unit="kutu", purchase_date=day)
    anomaly = make_material(client, "Vernik")
    for index, price in enumerate([1000, 1010, 990, 1005, 1000, 2600]):
        day = (start + timedelta(days=index * 9)).isoformat()
        make_purchase(client, cheap, anomaly, None, price * 5, f"pur-sv-a{index:05d}", quantity="5.000", unit="litre", purchase_date=day)
    worker = make_employee(client, "Mesaili Usta", "daily", 80000)
    for index in range(12):
        log_work(client, worker["id"], (date(2026, 2, 1) + timedelta(days=index)).isoformat(),
                 work_status="overtime", overtime_hours="4")
    return worker


def test_all_opportunity_types_are_explainable_and_consistent(client):
    add_price_and_supplier_history(client)  # Şubat dönemi kesinleşmeden önce kurulmalıdır
    portfolio = build_portfolio(client)
    with SessionLocal() as session:
        before = (
            session.scalar(select(func.count()).select_from(Purchase)),
            session.scalar(select(func.count()).select_from(CustomerFinancialMovement)),
            session.scalar(select(func.count()).select_from(AuditLog)),
        )
    body = client.get(SAVINGS, params={"as_of": "2026-03-10"}).json()
    types = by_type(body)
    assert {
        "budget_overrun", "price_anomaly", "cheaper_supplier", "overtime_concentration", "rework_increase",
        "unlinked_expense", "uncollected_change_order", "unlinked_customer_advance",
    } <= set(types)
    assert body["read_only"] is True and body["automatic_actions"] == []

    for item in body["opportunities"]:
        assert item["severity"] in SEVERITIES
        assert item["reason"] and any(ch in item["reason"] for ch in "ıiğüşöç ")
        assert item["title"] and item["opportunity_id"].startswith(item["type"])
        assert set(item["data_sufficiency"]) == {"sample_count", "minimum_samples", "sufficient"}
        assert item["confidence"] in ("high", "medium", "low")
        assert item["deep_link"]["entity"] and item["deep_link"]["entity_id"]
        assert item["estimated_impact_kurus"] is None or item["estimated_impact_kurus"] >= 0
        for source in item["sources"]:
            assert source["source_type"] and source["source_id"]
    # Toplam / tür dökümü kayıtlarla tutarlı.
    assert body["total_estimated_impact_kurus"] == sum(i["estimated_impact_kurus"] or 0 for i in body["opportunities"])
    assert sum(v["count"] for v in body["by_type"].values()) == body["count"] == len(body["opportunities"])
    for kind, slot in body["by_type"].items():
        assert slot["estimated_impact_kurus"] == sum(i["estimated_impact_kurus"] or 0 for i in types[kind])
    assert sum(body["by_severity"].values()) == body["count"]

    # Bütçe sapması: etki = tahmini bitiş − bütçe; kaynaklar kategori toplamlarına eşit.
    pid = portfolio["project"]["id"]
    overrun = next(i for i in types["budget_overrun"] if i["project_id"] == pid and i["category"] == "material")
    profit = client.get(f"{API}/projects/{pid}/profitability").json()
    material = next(c for c in profit["categories"] if c["category"] == "material")
    assert overrun["estimated_impact_kurus"] == -material["variance_kurus"] > 0
    costs = [s for s in overrun["sources"] if s.get("role") in ("actual", "commitment")]
    assert sum(s["amount_kurus"] for s in costs if s["role"] == "actual") == material["actual_kurus"]
    assert sum(s["amount_kurus"] for s in costs if s["role"] == "commitment") == material["commitment_kurus"]
    assert any(s["source_type"] == "project_budget_line" for s in overrun["sources"])

    # Fiyat anomalisi: fazla ödeme = (son fiyat − beklenen) × miktar.
    anomaly = types["price_anomaly"][0]
    assert anomaly["estimated_impact_kurus"] and anomaly["sources"][0]["source_type"] == "purchase"
    assert anomaly["data_sufficiency"]["sufficient"] is True

    cheaper = types["cheaper_supplier"][0]
    assert cheaper["cheapest_supplier_id"] and cheaper["saving_percent"] > 20
    assert cheaper["estimated_impact_kurus"] == int(
        sum(s["amount_kurus"] for s in cheaper["sources"]) * cheaper["saving_percent"] / 100
    )
    overtime = types["overtime_concentration"][0]
    assert overtime["overtime_hours"] == "48.00" and overtime["overtime_ratio_percent"] == 33.33
    assert len(overtime["sources"]) == 12 and overtime["data_sufficiency"]["sufficient"] is True
    assert overtime["estimated_impact_kurus"] > 0

    rework = next(i for i in types["rework_increase"] if i["project_id"] == pid)
    assert rework["estimated_impact_kurus"] == rework["recent_kurus"] - rework["prior_kurus"] == 25_000
    assert sum(s["amount_kurus"] for s in rework["sources"]) == 25_000  # gider + fire hareketi

    unlinked = {i["opportunity_id"]: i for i in types["unlinked_expense"]}
    purchases = unlinked["unlinked_expense:purchases"]
    assert purchases["estimated_impact_kurus"] is None and purchases["related_amount_kurus"] == sum(s["amount_kurus"] for s in purchases["sources"])

    order = types["uncollected_change_order"][0]
    assert order["estimated_impact_kurus"] == 100_000 and order["project_id"] == pid
    assert order["sources"][0]["source_type"] == "project_change_order"
    advance = types["unlinked_customer_advance"][0]
    assert advance["related_amount_kurus"] == 30_000 and advance["estimated_impact_kurus"] is None
    assert advance["deep_link"]["entity"] == "customer"
    assert any(s["source_id"] == portfolio["unlinked_collection"]["id"] for s in advance["sources"])

    # Salt-okunur: hiçbir kayıt yazılmadı.
    with SessionLocal() as session:
        after = (
            session.scalar(select(func.count()).select_from(Purchase)),
            session.scalar(select(func.count()).select_from(CustomerFinancialMovement)),
            session.scalar(select(func.count()).select_from(AuditLog)),
        )
    assert after == before


def test_filters_and_ordering(client):
    add_price_and_supplier_history(client)  # Şubat dönemi kesinleşmeden önce kurulmalıdır
    portfolio = build_portfolio(client)
    full = client.get(SAVINGS, params={"as_of": "2026-03-10"}).json()
    severities = [{"high": 0, "medium": 1, "low": 2}[i["severity"]] for i in full["opportunities"]]
    assert severities == sorted(severities)

    only_project = client.get(SAVINGS, params={"as_of": "2026-03-10", "project_id": portfolio["project"]["id"]}).json()
    assert {i["type"] for i in only_project["opportunities"]} <= {"budget_overrun", "rework_increase", "uncollected_change_order"}
    assert all(i["project_id"] == portfolio["project"]["id"] for i in only_project["opportunities"])
    high = client.get(SAVINGS, params={"as_of": "2026-03-10", "min_severity": "high"}).json()
    assert all(i["severity"] == "high" for i in high["opportunities"]) and high["count"] < full["count"]
    assert client.get(SAVINGS, params={"project_id": "yok"}).status_code == 404
    assert client.get(SAVINGS, params={"min_severity": "extreme"}).status_code == 422


def test_empty_database_returns_no_opportunities(client):
    body = client.get(SAVINGS).json()
    assert body["count"] == 0 and body["opportunities"] == [] and body["total_estimated_impact_kurus"] == 0
    make_project(client)
    assert client.get(SAVINGS).json()["count"] == 0


def test_insufficient_samples_lower_confidence(client):
    cheap, dear = make_supplier(client, "A Tedarik"), make_supplier(client, "B Tedarik")
    material = make_material(client, "Az Veri")
    for index, supplier in enumerate((cheap, dear)):
        for k in range(2):
            make_purchase(client, supplier, material, None, 10 * (1000 if index == 0 else 1600), f"pur-az-{index}{k:05d}", quantity="10.000", unit="adet", purchase_date=f"2026-02-{10 + k:02d}")
    body = client.get(SAVINGS, params={"as_of": "2026-03-10"}).json()
    cheaper = by_type(body).get("cheaper_supplier", [])
    assert cheaper and cheaper[0]["data_sufficiency"]["sample_count"] == 4
    assert cheaper[0]["data_sufficiency"]["sufficient"] is True and cheaper[0]["confidence"] == "medium"
