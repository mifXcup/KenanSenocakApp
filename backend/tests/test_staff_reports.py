from __future__ import annotations

import io

from helpers import log_work, make_employee, make_project, make_site
from openpyxl import load_workbook

from ks_yonetim.staff_reports import BUILDERS

BASE = "/api/v1/reports/staff"
MOVES = "/api/v1/employee-finance/movements"


def move(client, employee_id, kind, amount, key, day, **extra):
    response = client.post(MOVES, json={"employee_id": employee_id, "movement_type": kind,
                                        "amount_kurus": amount, "movement_date": day,
                                        "idempotency_key": key, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def scenario(client):
    project = make_project(client)
    site = make_site(client, project["id"])
    ahmet = make_employee(client, "Ahmet", "daily", 80000)
    mehmet = make_employee(client, "Mehmet", "monthly", 3100000)
    for day in ("2026-10-05", "2026-10-06"):
        log_work(client, ahmet["id"], day, project_id=project["id"], site_id=site["id"])
    log_work(client, mehmet["id"], "2026-10-07", project_id=project["id"], work_status="absent")
    move(client, ahmet["id"], "advance", 50000, "rep-adv-0001", "2026-10-02")
    move(client, mehmet["id"], "employee_debt", 70000, "rep-debt-001", "2026-10-03", due_date="2026-10-20")
    period = client.post("/api/v1/payroll-periods",
                         json={"period_start": "2026-10-01", "period_end": "2026-10-31"}).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/finalize").status_code == 200
    move(client, mehmet["id"], "payroll_payment", 1000000, "rep-pay-0001", "2026-11-02",
         payroll_period_id=period["id"])
    move(client, ahmet["id"], "advance", 20000, "rep-adv-0002", "2026-11-01")
    # ML: değerlendirilmiş bir tahmin
    supplier = client.post("/api/v1/suppliers", json={"name": "Firma X"}).json()
    material = client.post("/api/v1/materials", json={"name": "Malzeme X", "default_unit": "adet",
                                                      "tracking_mode": "estimated"}).json()
    for index, day in enumerate(["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]):
        client.post("/api/v1/purchases", json={"supplier_id": supplier["id"], "material_id": material["id"],
                                               "purchase_date": day, "quantity": "1", "unit": "adet",
                                               "unit_price_kurus": 100, "idempotency_key": f"rep-buy-{index:05d}"})
    client.post("/api/v1/analytics/ml/run", json={"as_of": "2026-09-23", "models": ["reorder"]})
    client.post("/api/v1/purchases", json={"supplier_id": supplier["id"], "material_id": material["id"],
                                           "purchase_date": "2026-09-30", "quantity": "1", "unit": "adet",
                                           "unit_price_kurus": 100, "idempotency_key": "rep-buy-99999"})
    client.post("/api/v1/analytics/ml/evaluate", json={"as_of": "2026-10-05"})
    return {"project": project, "site": site, "ahmet": ahmet, "mehmet": mehmet, "period": period}


def params_for(name, data):
    if name == "employee-statement":
        return {"employee_id": data["mehmet"]["id"]}
    if name == "payroll-period-summary":
        return {"payroll_period_id": data["period"]["id"]}
    if name == "upcoming-payments":
        return {"date_to": "2026-11-05"}
    if name in {"employee-advances", "employee-debts", "debt-aging"}:
        return {"date_to": "2026-11-05"}
    return {}


def test_every_report_has_json_xlsx_pdf_with_identical_totals(client):
    data = scenario(client)
    assert {item["name"] for item in client.get(BASE).json()} == set(BUILDERS)
    assert len(BUILDERS) == 12
    for name in BUILDERS:
        params = params_for(name, data)
        body = client.get(f"{BASE}/{name}", params=params)
        assert body.status_code == 200, (name, body.text)
        table = body.json()
        assert table["name"] == name and table["columns"] and "totals" in table

        xlsx = client.get(f"{BASE}/{name}/export.xlsx", params=params)
        assert xlsx.status_code == 200, name
        sheet = load_workbook(io.BytesIO(xlsx.content)).active
        assert sheet.max_row - 1 - (1 if table["totals"] else 0) == table["row_count"], name
        if table["totals"]:
            header = [c.value for c in sheet[1]]
            total_row = [c.value for c in sheet[sheet.max_row]]
            for column in table["columns"]:
                if column["key"] in table["totals"] and column["kind"] == "money":
                    cell = total_row[header.index(column["label"])]
                    assert round(cell * 100) == table["totals"][column["key"]], (name, column["key"])
        pdf = client.get(f"{BASE}/{name}/export.pdf", params=params)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF"), name


def test_report_contents_filters_and_validation(client):
    data = scenario(client)
    ahmet, mehmet = data["ahmet"]["id"], data["mehmet"]["id"]

    statement = client.get(f"{BASE}/employee-statement", params={"employee_id": mehmet}).json()
    assert statement["totals"]["running_company_owes_kurus"] == 3000000 - 1000000
    assert statement["totals"]["running_employee_owes_kurus"] == 70000
    assert client.get(f"{BASE}/employee-statement").status_code == 422
    assert client.get(f"{BASE}/employee-statement", params={"employee_id": "nope"}).status_code == 404

    summary = client.get(f"{BASE}/payroll-period-summary",
                         params={"payroll_period_id": data["period"]["id"]}).json()
    assert summary["row_count"] == 2
    one = client.get(f"{BASE}/payroll-period-summary",
                     params={"payroll_period_id": data["period"]["id"], "employee_id": ahmet}).json()
    assert one["row_count"] == 1 and one["totals"]["net_due_kurus"] < summary["totals"]["net_due_kurus"]
    # Ekrandaki toplam dönem API'sindeki toplamla aynıdır.
    period = client.get(f"/api/v1/payroll-periods/{data['period']['id']}").json()
    assert summary["totals"]["net_due_kurus"] == period["totals"]["net_due_kurus"]

    unpaid = client.get(f"{BASE}/unpaid-payroll").json()
    assert unpaid["totals"]["remaining_kurus"] == period["totals"]["remaining_kurus"]
    assert client.get(f"{BASE}/unpaid-payroll", params={"employee_id": mehmet}).json()["row_count"] == 1

    advances = client.get(f"{BASE}/employee-advances", params={"date_to": "2026-11-05"}).json()
    assert advances["rows"][0]["employee_name"] == "Ahmet"
    assert advances["totals"]["outstanding_kurus"] == 20000  # ilk avans maaşta mahsup edildi
    debts = client.get(f"{BASE}/employee-debts", params={"date_to": "2026-11-05"}).json()
    assert debts["totals"]["outstanding_kurus"] == 70000

    history = client.get(f"{BASE}/payment-history", params={"payroll_period_id": data["period"]["id"]}).json()
    assert [r["amount_kurus"] for r in history["rows"]] == [1000000]

    project_labor = client.get(f"{BASE}/project-labor", params={"project_id": data["project"]["id"]}).json()
    assert project_labor["totals"]["amount_kurus"] == 160000 + 0 and project_labor["row_count"] == 1
    site_labor = client.get(f"{BASE}/site-labor", params={"site_id": data["site"]["id"]}).json()
    assert site_labor["rows"][0]["name"] == "Villa Şantiyesi" and site_labor["totals"]["amount_kurus"] == 160000
    dated = client.get(f"{BASE}/project-labor", params={"date_from": "2026-10-06", "date_to": "2026-10-06"}).json()
    assert dated["totals"]["amount_kurus"] == 80000

    monthly = client.get(f"{BASE}/monthly-staff-cost").json()
    assert monthly["rows"][0]["month"] == "2026-10"
    assert monthly["rows"][0]["labor_accrual_kurus"] == 160000
    assert monthly["rows"][0]["payroll_net_kurus"] == period["totals"]["net_due_kurus"]

    upcoming = client.get(f"{BASE}/upcoming-payments", params={"date_to": "2026-11-05"}).json()
    assert upcoming["totals"]["remaining_kurus"] == period["totals"]["remaining_kurus"]
    assert all(r["days_overdue"] == 5 for r in upcoming["rows"])
    nothing = client.get(f"{BASE}/upcoming-payments", params={"date_to": "2026-09-01", "horizon_days": 1}).json()
    assert nothing["row_count"] == 0

    aging = client.get(f"{BASE}/debt-aging", params={"date_to": "2026-11-05"}).json()
    assert {c["key"] for c in aging["columns"]} >= {"not_due", "1_30", "31_60", "61_90", "90_plus", "no_due_date"}

    ml = client.get(f"{BASE}/ml-prediction-vs-actual").json()
    assert ml["row_count"] == 1 and ml["rows"][0]["prediction_type"] == "reorder"
    assert ml["rows"][0]["actual_value"] is not None

    bad = client.get(f"{BASE}/project-labor", params={"date_from": "2026-12-01", "date_to": "2026-01-01"})
    assert bad.status_code == 422
    assert client.get(f"{BASE}/does-not-exist").status_code == 404

    page = client.get(f"{BASE}/payment-history", params={"limit": 1}).json()
    assert len(page["rows"]) == 1 and page["row_count"] >= 1
