from __future__ import annotations

import base64
import io
from datetime import date

import pytest
from finance_helpers import (
    build_portfolio,
    make_material,
    make_purchase,
    make_supplier,
    move,
    receipt,
)
from helpers import log_work, make_employee, make_project
from openpyxl import load_workbook

from ks_yonetim import clock, exports
from ks_yonetim.pdf_exports import money

API = "/api/v1"
REPORTS = f"{API}/reports/finance"
ALL_REPORTS = [
    "project-profitability", "budget-variance", "project-comparison", "customer-aging", "supplier-aging",
    "customer-advances", "cash-forecast-13w", "upcoming-schedule", "staff-balances",
    "attendance-overtime-leave", "labor-cost", "material-price-history", "waste-rework-cost",
    "purchase-lifecycle", "material-usage",
]


def report(client, name, **params):
    response = client.get(f"{REPORTS}/{name}", params={"limit": 2000, **params})
    assert response.status_code == 200, response.text
    return response.json()


def rows_by(body, key):
    return {row[key]: row for row in body["rows"]}


def assert_formats_agree(client, monkeypatch, name, **params):
    """JSON, XLSX ve PDF aynı satır sayısını ve aynı toplamları taşır."""
    body = report(client, name, **params)
    money_keys = [c["key"] for c in body["columns"] if c["kind"] == "money"]

    workbook = load_workbook(io.BytesIO(client.get(f"{REPORTS}/{name}/export.xlsx", params=params).content))
    sheet = workbook.active
    assert [c.value for c in sheet[1]] == [c["label"] for c in body["columns"]]
    data = [r for r in sheet.iter_rows(min_row=2, values_only=True) if r[0] is not None]
    total_row = next((r for r in data if r[0] == "TOPLAM"), None)
    detail = [r for r in data if r[0] != "TOPLAM" and not (isinstance(r[0], str) and len(r) > 0 and all(v is None for v in r[1:]) and r[0] in body["notes"] + [w["message"] for w in body["warnings"]])]
    assert len(detail) == body["row_count"]
    if body["totals"]:
        assert total_row is not None
        for index, column in enumerate(body["columns"]):
            if column["key"] in money_keys and column["key"] in body["totals"]:
                assert round(total_row[index] * 100) == body["totals"][column["key"]], (name, column["key"])
    else:
        assert total_row is None

    captured = {}

    def fake_build_pdf(title, headers, rows, notes=None):
        captured.update(title=title, headers=headers, rows=rows, notes=notes or [])
        return b"%PDF-captured"

    monkeypatch.setattr(exports, "build_pdf", fake_build_pdf)
    pdf = client.get(f"{REPORTS}/{name}/export.pdf", params=params)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert captured["headers"] == [c["label"] for c in body["columns"]]
    assert captured["title"] == body["title"]
    assert len(captured["rows"]) == body["row_count"] + (1 if body["totals"] else 0)
    if body["totals"]:
        last = captured["rows"][-1]
        for index, column in enumerate(body["columns"]):
            if column["key"] in money_keys and column["key"] in body["totals"]:
                assert last[index] == money(body["totals"][column["key"]]), (name, column["key"])
    notes = body["notes"] + [w["message"] for w in body["warnings"] if w.get("message")]
    assert captured["notes"] == notes
    return body


@pytest.fixture
def portfolio(client):
    return build_portfolio(client)


def test_every_report_has_identical_json_xlsx_and_pdf_totals(client, portfolio, monkeypatch):
    names = {item["name"] for item in client.get(REPORTS).json()}
    assert set(ALL_REPORTS) | {"customer-statement", "supplier-statement"} == names
    params = {"date_from": "2026-01-01", "date_to": "2026-03-10"}
    for name in ALL_REPORTS:
        assert_formats_agree(client, monkeypatch, name, **params)
    assert_formats_agree(client, monkeypatch, "customer-statement", customer_id=portfolio["customer_id"])
    assert_formats_agree(client, monkeypatch, "supplier-statement", supplier_id=portfolio["supplier"]["id"])


def test_project_profitability_matches_endpoint_and_returns_unlinked_advance_warning(client, portfolio):
    pid = portfolio["project"]["id"]
    profit = client.get(f"{API}/projects/{pid}/profitability").json()
    row = rows_by(report(client, "project-profitability"), "project_name")["Villa Projesi"]
    for key in ("revised_contract_kurus", "actual_cost_kurus", "commitment_kurus", "remaining_estimate_kurus",
                "forecast_cost_at_completion_kurus", "estimated_profit_kurus", "estimated_margin_percent"):
        assert row[key] == profit[key], key
    assert profit["revised_contract_kurus"] == 3_100_000 and profit["commitment_kurus"] > 0

    # Tahsilat yalnız projeye bağlı / projenin planlarına dağıtılmış tutarı kullanır.
    collections = profit["collections"]
    assert collections["collected_kurus"] == 100_000 and collections["net_collected_kurus"] == 100_000
    assert collections["open_receivable_kurus"] == 300_000
    assert collections["unlinked_customer_advance_kurus"] == 30_000
    assert [w["code"] for w in profit["warnings"]] == ["unlinked_customer_advance"]
    assert profit["warnings"][0]["amount_kurus"] == 30_000
    assert row["net_collected_kurus"] == 100_000
    body = report(client, "project-profitability")
    assert body["warnings"][0]["code"] == "unlinked_customer_advance"
    assert any("bağlantısız" in w["message"] or "bağlanmamış" in w["message"] for w in body["warnings"])
    assert body["totals"]["actual_cost_kurus"] == sum(r["actual_cost_kurus"] for r in body["rows"])


def test_allocating_unlinked_collection_moves_advance_into_the_project(client, portfolio):
    pid, cid = portfolio["project"]["id"], portfolio["customer_id"]
    before = report(client, "customer-advances")
    assert rows_by(before, "link_status")["Bağlantısız"]["unlinked_advance_kurus"] == 30_000
    assert before["totals"]["unlinked_advance_kurus"] == 30_000 and before["totals"]["project_advance_kurus"] == 0

    allocation = client.post(
        f"{API}/customer-payment-allocations",
        json={"collection_id": portfolio["unlinked_collection"]["id"],
              "receivable_schedule_id": portfolio["plan_a"]["id"], "amount_kurus": 20_000,
              "idempotency_key": "dagit-b4-0000001"},
    )
    assert allocation.status_code == 201, allocation.text
    after = client.get(f"{API}/projects/{pid}/profitability").json()
    assert after["collections"]["collected_kurus"] == 120_000  # 100.000 doğrudan + 20.000 plana dağıtılan
    assert after["collections"]["unlinked_customer_advance_kurus"] == 10_000
    assert after["warnings"][0]["amount_kurus"] == 10_000

    # Tamamı dağıtılınca uyarı ve bağlantısız avans kalmaz.
    client.post(
        f"{API}/customer-payment-allocations",
        json={"collection_id": portfolio["unlinked_collection"]["id"],
              "receivable_schedule_id": portfolio["plan_a"]["id"], "amount_kurus": 10_000,
              "idempotency_key": "dagit-b4-0000002"},
    )
    final = client.get(f"{API}/projects/{pid}/profitability").json()
    assert final["warnings"] == [] and final["collections"]["collected_kurus"] == 130_000
    assert report(client, "customer-advances")["rows"] == []
    assert cid


def test_project_and_unlinked_advances_are_reported_separately(client):
    project = make_project(client, "Avanslı Proje", customer_name="Avans Müşteri")
    cid = project["customer_id"]
    move(client, cid, "accrual", 100_000, "tahakkuk-av-0001", day="2026-02-01", project_id=project["id"])
    move(client, cid, "collection", 100_000, "tahsilat-av-001", day="2026-02-02", project_id=project["id"])
    move(client, cid, "collection", 60_000, "tahsilat-av-002", day="2026-02-03", project_id=project["id"])
    move(client, cid, "collection", 30_000, "tahsilat-av-003", day="2026-02-04")
    body = report(client, "customer-advances")
    by_link = rows_by(body, "link_status")
    assert by_link["Projeye bağlı"]["project_advance_kurus"] == 60_000
    assert by_link["Bağlantısız"]["unlinked_advance_kurus"] == 30_000
    assert body["totals"] == {"project_advance_kurus": 60_000, "unlinked_advance_kurus": 30_000}
    aging = rows_by(report(client, "customer-aging"), "customer_name")["Avans Müşteri"]
    assert (aging["project_advance_kurus"], aging["unlinked_advance_kurus"]) == (60_000, 30_000)
    assert aging["total_open_kurus"] == 0 and aging["overdue_kurus"] == 0  # avans gecikmiş alacak değildir
    profit = client.get(f"{API}/projects/{project['id']}/profitability").json()
    assert profit["collections"]["project_advance_kurus"] == 60_000
    assert profit["collections"]["net_collected_kurus"] == 160_000  # bağlantısız 30.000 sayılmaz
    assert profit["warnings"][0]["amount_kurus"] == 30_000
    assert client.get(f"{API}/customers/{cid}").json()["credit_kurus"] == 90_000  # müşteri toplam kredisi değişmedi


def test_budget_variance_and_comparison_reports(client, portfolio):
    pid = portfolio["project"]["id"]
    profit = client.get(f"{API}/projects/{pid}/profitability").json()
    body = report(client, "budget-variance", project_id=pid)
    material = rows_by(body, "category")["material"]
    category = next(c for c in profit["categories"] if c["category"] == "material")
    assert material["original_budget_kurus"] == 100_000 and material["actual_kurus"] == category["actual_kurus"]
    assert material["variance_kurus"] == category["variance_kurus"] < 0
    assert material["variance_percent"] == round(category["variance_kurus"] / 100_000 * 100, 2)
    assert body["totals"]["actual_kurus"] == sum(r["actual_kurus"] for r in body["rows"])

    comparison = report(client, "project-comparison")
    ranks = [(r["rank"], r["project_name"]) for r in comparison["rows"]]
    assert [rank for rank, _ in ranks] == [1, 2]
    assert comparison["rows"][0]["estimated_margin_percent"] >= (comparison["rows"][1]["estimated_margin_percent"] or -999)
    shares = [r["cost_share_percent"] for r in comparison["rows"] if r["cost_share_percent"] is not None]
    assert round(sum(shares)) == 100


def test_customer_and_supplier_aging_and_statements(client, portfolio):
    cid, s1 = portfolio["customer_id"], portfolio["supplier"]["id"]
    aging = rows_by(report(client, "customer-aging"), "customer_name")["Güneş İnşaat"]
    api_aging = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-03-10"}).json()
    assert aging["total_open_kurus"] == api_aging["open_receivable_kurus"]
    assert aging["overdue_kurus"] == api_aging["overdue_kurus"]
    supplier_row = rows_by(report(client, "supplier-aging"), "supplier_name")["Birinci Tedarikçi"]
    supplier_api = client.get(f"{API}/suppliers/{s1}/aging", params={"as_of": "2026-03-10"}).json()
    assert supplier_row["total_open_kurus"] == supplier_api["total_open_kurus"]

    statement = report(client, "customer-statement", customer_id=cid)
    api_statement = client.get(f"{API}/customers/{cid}/statement").json()
    assert statement["totals"]["increase_kurus"] == api_statement["total_increase_kurus"]
    assert statement["rows"][-1]["balance_kurus"] == api_statement["closing_balance_kurus"]
    ledger = report(client, "supplier-statement", supplier_id=s1)
    assert ledger["rows"][-1]["balance_kurus"] == client.get(f"{API}/suppliers/{s1}/balance").json()["remaining_kurus"]
    assert client.get(f"{REPORTS}/customer-statement").status_code == 422
    assert client.get(f"{REPORTS}/supplier-statement").json()["error"]["code"] == "supplier_required"


def test_cash_forecast_has_no_bank_balance_and_correct_weeks(client, monkeypatch):
    monkeypatch.setattr(clock, "business_today", lambda: date(2026, 3, 10))
    project = make_project(client, "Nakit Projesi", customer_name="Nakit Müşteri")
    cid = project["customer_id"]
    move(client, cid, "accrual", 900_000, "tahakkuk-nk-0001", day="2026-03-01")
    for title, amount, due in (("Gecikmiş", 10_000, "2026-03-01"), ("Hafta 1", 20_000, "2026-03-10"),
                               ("Hafta 2", 30_000, "2026-03-17"), ("Son gün", 40_000, "2026-06-08"),
                               ("Kapsam dışı", 50_000, "2026-06-09")):
        client.post(f"{API}/receivable-schedules", json={"customer_id": cid, "title": title, "amount_kurus": amount, "due_date": due})
    supplier, material = make_supplier(client, "Nakit Tedarikçi"), make_material(client)
    make_purchase(client, supplier, material, None, 70_000, "pur-nk-000001", due_date="2026-03-12")
    worker = make_employee(client, "Nakit Usta", "daily", 80000)
    log_work(client, worker["id"], "2026-02-02")
    client.put(f"{API}/settings/attendance", json={"default_salary_day": 24})
    period = client.post(f"{API}/payroll-periods", json={"period_start": "2026-02-01", "period_end": "2026-02-28"}).json()
    client.post(f"{API}/payroll-periods/{period['id']}/calculate", json={})
    client.post(f"{API}/payroll-periods/{period['id']}/finalize", json={})

    body = report(client, "cash-forecast-13w")
    rows = {r["period_label"]: r for r in body["rows"]}
    assert rows["Vadesi geçmiş (devreden)"]["planned_inflow_kurus"] == 10_000
    assert rows["Hafta 1"]["planned_inflow_kurus"] == 20_000 and rows["Hafta 1"]["planned_outflow_kurus"] == 70_000
    assert rows["Hafta 2"]["planned_inflow_kurus"] == 30_000
    assert rows["Hafta 13"]["planned_inflow_kurus"] == 40_000 and rows["Hafta 13"]["week_end"] == "2026-06-08"
    assert rows["Hafta 3"]["planned_outflow_kurus"] == 80_000  # 24 Mart maaş vadesi
    assert sum(r["planned_inflow_kurus"] for r in body["rows"]) == 100_000  # 50.000 kapsam dışı
    assert body["totals"]["net_change_kurus"] == body["totals"]["planned_inflow_kurus"] - body["totals"]["planned_outflow_kurus"]
    assert body["rows"][-1]["cumulative_net_change_kurus"] == body["totals"]["net_change_kurus"]
    # Banka bakiyesi iddiası yok: ne sütun ne not.
    text = str(body["columns"]).casefold()
    assert "bakiye" not in text and "balance" not in text
    assert "banka veya kasa bakiyesi içermez" in " ".join(body["notes"])


def test_upcoming_schedule_and_staff_balances(client, portfolio):
    upcoming = report(client, "upcoming-schedule", horizon_days=30)
    kinds = {r["kind_label"] for r in upcoming["rows"]}
    assert {"Tahsilat", "Tedarikçi ödemesi", "Maaş / personel ödemesi"} <= kinds
    assert upcoming["totals"]["inflow_kurus"] == sum(r["inflow_kurus"] for r in upcoming["rows"])
    assert all(r["state"] in ("overdue", "today", "upcoming") for r in upcoming["rows"])

    staff = rows_by(report(client, "staff-balances"), "employee_name")["Ahmet Usta"]
    entry = client.get(f"{API}/payroll-periods/{portfolio['period']['id']}/entries").json()[0]
    assert staff["unpaid_payroll_kurus"] == entry["net_due_kurus"] == 160_000


def test_attendance_labor_and_leave_reports(client, monkeypatch):
    worker = make_employee(client, "Mesaili Usta", "daily", 80000)
    project = make_project(client, "Mesai Projesi")
    log_work(client, worker["id"], "2026-03-02", project_id=project["id"], work_status="overtime", overtime_hours="4")
    log_work(client, worker["id"], "2026-03-03", project_id=project["id"])
    client.post(f"{API}/employees/{worker['id']}/leave-ledger", json={"entry_type": "grant", "quantity_days": "5", "entry_date": "2026-01-01", "idempotency_key": "hak-b4-0000001"})
    leave = client.post(f"{API}/leave-requests", json={"employee_id": worker["id"], "leave_type_code": "annual", "start_date": "2026-03-04", "end_date": "2026-03-04", "idempotency_key": "izin-b4-0000001"}).json()
    client.post(f"{API}/leave-requests/{leave['id']}/approve")
    body = report(client, "attendance-overtime-leave", date_from="2026-03-02", date_to="2026-03-07", employee_id=worker["id"])
    row = body["rows"][0]
    assert row["worked_day_count"] == 2 and row["overtime_hours"] == 4.0 and row["normal_hours"] == 16.0
    assert row["annual_leave_hours"] == 8.0 and row["overtime_ratio_percent"] == 20.0
    assert row["missing_required_day_count"] == 3  # 5, 6, 7 Mart (Pazartesi–Cumartesi planı)
    labor = report(client, "labor-cost", project_id=project["id"])
    assert labor["totals"]["labor_kurus"] == client.get(f"{API}/projects/{project['id']}/cost-summary").json()["labor_kurus"]
    assert labor["totals"]["log_count"] == 2


def test_material_price_history_waste_and_purchase_lifecycle(client, portfolio):
    material = portfolio["material"]
    history = report(client, "material-price-history", material_id=material["id"])
    dated = [r for r in history["rows"] if r["unit"] == "levha"]
    first = dated[0]
    assert first["unit_price_kurus"] == 15_000 and first["price_change_percent"] is None
    assert any(r["price_change_percent"] is not None for r in dated)
    assert history["totals"]["amount_kurus"] == sum(r["amount_kurus"] for r in history["rows"])

    waste = report(client, "waste-rework-cost", project_id=portfolio["project"]["id"])
    assert {r["source_type"] for r in waste["rows"]} == {"project_expense", "material_movement"}
    assert waste["totals"]["amount_kurus"] == 25_000

    life = report(client, "purchase-lifecycle")
    by_state = {}
    for r in life["rows"]:
        by_state.setdefault(r["lifecycle_state"], []).append(r)
    planned = by_state["planned"][0]
    assert planned["received_kurus"] == 0 and planned["commitment_kurus"] == 60_000 and planned["lifecycle_label"] == "Planlandı"
    assert life["totals"]["commitment_kurus"] == 60_000  # planlı kayıt taahhüttür, maliyet değil
    assert life["totals"]["received_kurus"] == 150_000 + 90_000 + 80_000
    assert "total_kurus" not in life["totals"]  # sipariş tutarı toplanmaz
    # Planlı satın alma proje maliyetine girmez.
    cost = client.get(f"{API}/projects/{portfolio['project']['id']}/cost-summary").json()
    assert cost["purchase_kurus"] == 150_000 + 90_000


def test_quantity_over_received_is_a_warning_not_a_block(client, portfolio):
    pu3 = portfolio["pu3"]
    rows = client.get(f"{API}/purchases/{pu3['id']}/receipts").json()
    assert len(rows) == 3
    warning = rows[0]["warnings"][0]
    assert warning["code"] == "quantity_over_received" and warning["excess_quantity"] == "1.000"
    assert warning["purchase_quantity"] == "9.000" and warning["received_quantity"] == "10.000"
    assert "aşıyor" in warning["message"]
    # Yeni teslim de engellenmez; yanıt uyarıyı taşır.
    extra = make_purchase(client, portfolio["supplier"], portfolio["material"], None, 20_000, "pur-b4-000009", state="ordered", quantity="2.000", unit="levha")
    created = receipt(client, extra["id"], "2026-03-08", 20_000, "teslim-b4-000090", quantity="5.000")
    assert created.status_code == 201 and created.json()["warnings"][0]["excess_quantity"] == "3.000"
    life = report(client, "purchase-lifecycle")
    flagged = [r for r in life["rows"] if r["warning"] == "quantity_over_received"]
    assert {r["purchase_id"] for r in flagged} == {pu3["id"], extra["id"]}
    assert any(w["code"] == "quantity_over_received" for w in life["warnings"])
    assert client.get(f"{API}/purchases/{pu3['id']}/receipts").json()[0]["warnings"][0]["code"] == "quantity_over_received"


def test_legacy_purchase_exports_follow_the_lifecycle(client, portfolio):
    xlsx = client.get(f"{API}/exports/purchases").json()
    sheet = load_workbook(io.BytesIO(base64.b64decode(xlsx["content_base64"]))).active
    header = [c.value for c in sheet[1]]
    assert "Durum" in header and "Teslim alınan (gerçek) (TL)" in header and "Bekleyen taahhüt (TL)" in header
    states = {row[header.index("Durum")] for row in sheet.iter_rows(min_row=2, values_only=True)}
    assert {"Planlandı", "Teslim edildi"} <= states
    total = next(row for row in sheet.iter_rows(min_row=2, values_only=True) if row[0] == "TOPLAM")
    assert total[header.index("Teslim alınan (gerçek) (TL)")] == (150_000 + 90_000 + 80_000) / 100
    assert total[header.index("Bekleyen taahhüt (TL)")] == 60_000 / 100
    pdf = client.get(f"{API}/exports/purchases/pdf").json()
    assert base64.b64decode(pdf["content_base64"]).startswith(b"%PDF")


def test_pdf_font_fallback_keeps_turkish_characters(monkeypatch):
    from pathlib import Path

    from reportlab.pdfbase import pdfmetrics

    from ks_yonetim import pdf_exports

    bundled = pdf_exports._bundled_font()
    real_exists = Path.exists
    # Sistem yazı tipleri yokmuş gibi: reportlab'in paketlediği Vera'ya düşmeli (Helvetica'ya değil).
    monkeypatch.setattr(Path, "exists", lambda self: real_exists(self) if self == bundled else False)
    name = pdf_exports.register_font()
    assert name == "KSUnicodeVera"
    face = pdfmetrics.getFont(name).face
    for letter in "ğĞıİşŞçÇöÖüÜ":
        assert ord(letter) in face.charToGlyph, letter
    table = exports.ReportTable(
        "turkce", "Türkçe Başlık: ğüşiöç İI ı", [exports.Column("ad", "Müşteri Adı"), exports.Column("tutar", "Tutar", "money")],
        [{"ad": "Çığ Şahin Öztürk", "tutar": 123456}], {"tutar": 123456}, notes=["Açıklama: ğüşıöçĞÜŞİÖÇ"],
    )
    raw = exports.table_pdf(table)
    assert raw.startswith(b"%PDF") and b"Vera" in raw
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert pdf_exports.register_font() == "Helvetica"  # yalnız yazı tipi hiç yoksa son çare


def test_report_validation_and_pagination(client, portfolio):
    assert client.get(f"{REPORTS}/yok").json()["error"]["code"] == "not_found"
    assert client.get(f"{REPORTS}/labor-cost", params={"date_from": "2026-03-10", "date_to": "2026-01-01"}).status_code == 422
    assert client.get(f"{REPORTS}/project-profitability", params={"project_id": "yok"}).status_code == 404
    full = report(client, "supplier-aging")
    page = client.get(f"{REPORTS}/supplier-aging", params={"limit": 1, "offset": 0}).json()
    assert len(page["rows"]) == 1 and page["totals"] == full["totals"]  # toplamlar tüm satırlardan


def test_material_usage_report_groups_by_project_material_and_unit(client):
    project = make_project(client, name="Kullanım Projesi")
    material = client.post("/api/v1/materials", json={"name": "MDF", "default_unit": "levha", "tracking_mode": "exact"}).json()
    supplier = client.post("/api/v1/suppliers", json={"name": "Levha Tedarik"}).json()
    bought = client.post("/api/v1/purchases", json={
        "supplier_id": supplier["id"], "material_id": material["id"], "project_id": project["id"],
        "purchase_date": "2026-03-04", "quantity": "10", "unit": "levha", "unit_price_kurus": 100_000,
        "idempotency_key": "usage-report-purchase",
    })
    assert bought.status_code == 201, bought.text  # teslim alınan alış, malzeme hareketini otomatik üretir
    base = {"material_id": material["id"], "project_id": project["id"], "movement_date": "2026-03-05", "confidence": "exact", "unit": "levha"}
    for kind, quantity in (("use", "6"), ("waste", "1"), ("return", "0.5")):
        extra = {"amount_kurus": 25_000} if kind == "waste" else {}
        assert client.post("/api/v1/material-movements", json={**base, "movement_type": kind, "quantity": quantity, **extra}).status_code == 201
    other_unit = {**base, "unit": "kg", "movement_type": "use", "quantity": "3"}
    assert client.post("/api/v1/material-movements", json=other_unit).status_code == 201

    body = report(client, "material-usage", project_id=project["id"])
    rows = {row["unit"]: row for row in body["rows"]}
    levha = rows["levha"]
    assert (levha["purchased"], levha["used"], levha["waste"], levha["returned"]) == (10.0, 6.0, 1.0, 0.5)
    assert levha["net"] == 3.5 and levha["waste_cost_kurus"] == 25_000
    assert rows["kg"]["used"] == 3.0 and rows["kg"]["net"] == -3.0
