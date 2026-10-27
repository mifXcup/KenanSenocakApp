from __future__ import annotations

import io

from helpers import log_work, make_employee
from openpyxl import load_workbook

from ks_yonetim.backup import backup_manager

OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31", "title": "Ekim 2026"}


def make_period(client, **overrides):
    response = client.post("/api/v1/payroll-periods", json={**OCT, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def calc(client, period_id, **body):
    response = client.post(f"/api/v1/payroll-periods/{period_id}/calculate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def entries(client, period_id):
    response = client.get(f"/api/v1/payroll-periods/{period_id}/entries")
    assert response.status_code == 200
    return {item["employee_name"]: item for item in response.json()}


def test_period_validation_and_overlap(client):
    make_period(client)
    overlap = client.post(
        "/api/v1/payroll-periods",
        json={"period_start": "2026-10-31", "period_end": "2026-11-15"},
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "payroll_period_overlap"
    back = client.post(
        "/api/v1/payroll-periods", json={"period_start": "2026-12-05", "period_end": "2026-12-01"}
    )
    assert back.status_code == 422
    assert make_period(client, period_start="2026-11-01", period_end="2026-11-30")["state"] == "draft"
    listed = client.get("/api/v1/payroll-periods").json()
    assert [p["period_start"] for p in listed] == ["2026-11-01", "2026-10-01"]
    assert client.get("/api/v1/payroll-periods", params={"state": "closed"}).json() == []
    assert client.get("/api/v1/payroll-periods/missing").status_code == 404


def test_monthly_daily_and_hourly_calculation_rules(client):
    monthly = make_employee(client, "Aylık Usta", "monthly", 3100000)
    daily = make_employee(client, "Günlük Usta", "daily", 80000)
    hourly = make_employee(client, "Saatlik Usta", "hourly", 10000)
    for day in ("2026-10-05", "2026-10-06"):
        assert log_work(client, monthly["id"], day, work_status="absent").status_code == 201
    assert log_work(client, monthly["id"], "2026-10-07", work_status="unpaid_leave").status_code == 201
    assert log_work(
        client, monthly["id"], "2026-10-08", work_status="overtime", overtime_hours="2"
    ).status_code == 201
    log_work(client, daily["id"], "2026-10-05")
    log_work(client, daily["id"], "2026-10-06", work_status="half_day")
    log_work(client, daily["id"], "2026-10-07", work_status="overtime", overtime_hours="2")
    log_work(client, daily["id"], "2026-10-08", manual_amount_kurus=50000)
    log_work(client, hourly["id"], "2026-10-05", normal_hours="6.5")

    period = make_period(client)
    result = calc(client, period["id"])
    assert result["state"] == "calculated" and result["entry_count"] == 3
    rows = entries(client, period["id"])

    m = rows["Aylık Usta"]
    # 3.100.000 − 3 gün × 100.000 = 2.800.000; fazla mesai 2 sa × 12.500 × 1,5
    assert (m["wage_type"], m["base_earning_kurus"], m["overtime_earning_kurus"]) == (
        "monthly",
        2800000,
        37500,
    )
    assert m["calculation_detail"]["unpaid_days"] == 3
    assert m["gross_earning_kurus"] == m["net_due_kurus"] == 2837500
    assert m["remaining_kurus"] == 2837500 and m["paid_kurus"] == 0

    d = rows["Günlük Usta"]
    # 80.000 + 40.000 + 80.000 (normal kısım) + 50.000 (manuel gün); mesai 2 sa × 10.000 × 1,5
    assert d["base_earning_kurus"] == 250000
    assert d["overtime_earning_kurus"] == 30000
    assert d["overtime_hours"] == "2.00"
    assert d["worked_days"] == "3.50"

    h = rows["Saatlik Usta"]
    assert (h["base_earning_kurus"], h["normal_hours"]) == (65000, "6.50")
    assert client.get(f"/api/v1/payroll-periods/{period['id']}").json()["totals"][
        "net_due_kurus"
    ] == 2837500 + 280000 + 65000


def test_monthly_rate_change_prorates_by_calendar_days(client):
    employee = make_employee(client, "Zamlı Usta", "monthly", 3100000)
    client.post(
        f"/api/v1/employees/{employee['id']}/wage-rates",
        json={"effective_from": "2026-10-16", "wage_type": "monthly", "rate_kurus": 6200000},
    )
    period = make_period(client)
    calc(client, period["id"])
    # 15 gün × 100.000 + 16 gün × 200.000
    assert entries(client, period["id"])["Zamlı Usta"]["base_earning_kurus"] == 4700000
    # Kısmi dönem: 10 günlük dönemde yalnız o günler.
    partial = make_period(client, period_start="2026-11-01", period_end="2026-11-10")
    calc(client, partial["id"])
    # Kasım 30 gün: 10 × 6.200.000/30
    assert entries(client, partial["id"])["Zamlı Usta"]["base_earning_kurus"] == 2066667


def test_employment_dates_limit_monthly_pay(client):
    make_employee(client, "Yeni Başlayan", "monthly", 3100000, employment_start_date="2026-10-16")
    make_employee(client, "Ayrılan", "monthly", 3100000, employment_end_date="2026-10-10")
    make_employee(client, "Önce Ayrıldı", "monthly", 3100000, employment_end_date="2026-09-30")
    period = make_period(client)
    calc(client, period["id"])
    rows = entries(client, period["id"])
    assert rows["Yeni Başlayan"]["base_earning_kurus"] == 1600000
    assert rows["Ayrılan"]["base_earning_kurus"] == 1000000
    assert "Önce Ayrıldı" not in rows


def test_recalculation_is_deterministic_and_follows_draft_changes(client):
    employee = make_employee(client, "Usta")
    log_work(client, employee["id"], "2026-10-05")
    period = make_period(client)
    first = calc(client, period["id"])
    first_rows = entries(client, period["id"])
    second = calc(client, period["id"])
    second_rows = entries(client, period["id"])
    assert first["totals"] == second["totals"]
    strip = lambda rows: {
        name: {k: v for k, v in row.items() if k not in {"id"}} for name, row in rows.items()
    }
    assert strip(first_rows) == strip(second_rows)
    assert first_rows["Usta"]["id"] == second_rows["Usta"]["id"]

    log_work(client, employee["id"], "2026-10-06")
    third = calc(client, period["id"])
    assert third["totals"]["net_due_kurus"] == 160000

    # Puantaj iptal edilince personel dönemden çıkar (kayıt silinmez, iptal olur).
    for item in client.get("/api/v1/work-logs", params={"employee_id": employee["id"]}).json():
        client.post(f"/api/v1/work-logs/{item['id']}/cancel")
    fourth = calc(client, period["id"])
    assert fourth["entry_count"] == 0


def test_finalize_takes_backup_locks_period_and_close_flow(client):
    employee = make_employee(client, "Usta")
    log_work(client, employee["id"], "2026-10-05")
    period = make_period(client)

    early = client.post(f"/api/v1/payroll-periods/{period['id']}/finalize")
    assert early.status_code == 409 and early.json()["error"]["code"] == "period_not_calculated"
    calc(client, period["id"])

    # Hesaptan sonra değişen puantaj eski toplamın kesinleşmesini engeller.
    log_work(client, employee["id"], "2026-10-06")
    stale = client.post(f"/api/v1/payroll-periods/{period['id']}/finalize")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "payroll_stale"
    calc(client, period["id"])

    before = len(backup_manager.list())
    finalized = client.post(f"/api/v1/payroll-periods/{period['id']}/finalize")
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["state"] == "finalized" and finalized.json()["finalized_at"]
    new_backups = backup_manager.list()[: len(backup_manager.list()) - before + 1]
    assert any(b.kind == "pre_finalize" for b in new_backups)

    # Kesinleşmiş dönem sessizce değişmez.
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/calculate").status_code == 409
    locked = log_work(client, employee["id"], "2026-10-07")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "period_locked"
    existing = client.get("/api/v1/work-logs", params={"employee_id": employee["id"]}).json()[0]
    assert client.post(f"/api/v1/work-logs/{existing['id']}/cancel").status_code == 409
    assert (
        client.patch(f"/api/v1/work-logs/{existing['id']}", json={"note": "x"}).status_code == 409
    )
    retro = client.post(
        f"/api/v1/employees/{employee['id']}/wage-rates",
        json={"effective_from": "2026-10-15", "wage_type": "daily", "rate_kurus": 1},
    )
    assert retro.status_code == 409 and retro.json()["error"]["code"] == "period_locked"
    # İleri tarihli ücret değişikliği serbesttir.
    assert (
        client.post(
            f"/api/v1/employees/{employee['id']}/wage-rates",
            json={"effective_from": "2026-11-01", "wage_type": "daily", "rate_kurus": 90000},
        ).status_code
        == 201
    )

    unpaid = client.post(f"/api/v1/payroll-periods/{period['id']}/close")
    assert unpaid.status_code == 409 and unpaid.json()["error"]["code"] == "period_has_unpaid"
    closed = client.post(f"/api/v1/payroll-periods/{period['id']}/close", json={"allow_unpaid": True})
    assert closed.json()["state"] == "closed" and closed.json()["closed_at"]
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/finalize").status_code == 409


def test_period_exports_share_totals_with_json(client):
    employee = make_employee(client, "Usta")
    log_work(client, employee["id"], "2026-10-05")
    period = make_period(client)
    detail = calc(client, period["id"])

    xlsx = client.get(f"/api/v1/payroll-periods/{period['id']}/export.xlsx")
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith("application/vnd.openxmlformats")
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    header = [cell.value for cell in sheet[1]]
    total_row = [cell.value for cell in sheet[sheet.max_row]]
    net_index = header.index("Net ödenecek")
    assert total_row[0] == "TOPLAM"
    assert round(total_row[net_index] * 100) == detail["totals"]["net_due_kurus"]

    pdf = client.get(f"/api/v1/payroll-periods/{period['id']}/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
