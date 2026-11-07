from helpers import log_work, make_employee


def test_fixed_period_daily_rate_absence_and_special_day_pay(client):
    employee = make_employee(
        client, "Emir Şenocak", "monthly", 3_000_000,
        employment_start_date="2026-10-07",
    )
    assert log_work(client, employee["id"], "2026-10-08", work_status="absent").status_code == 201
    assert log_work(client, employee["id"], "2026-10-09", work_status="notified_absent").status_code == 201
    assert log_work(client, employee["id"], "2026-10-10", work_status="overtime", overtime_hours="2").status_code == 201
    assert log_work(client, employee["id"], "2026-10-11", work_status="worked").status_code == 201
    assert client.post("/api/v1/holidays", json={"holiday_date": "2026-10-29", "name": "Cumhuriyet Bayramı"}).status_code == 201
    assert log_work(client, employee["id"], "2026-10-29", work_status="worked").status_code == 201

    invalid = client.post("/api/v1/payroll-periods", json={"period_start": "2026-10-01", "period_end": "2026-10-31"})
    assert invalid.status_code == 422
    created = client.post("/api/v1/payroll-periods", json={"period_start": "2026-10-06", "period_end": "2026-11-05"})
    assert created.status_code == 201, created.text
    assert created.json()["overtime_multiplier_percent"] == 150
    period_id = created.json()["id"]
    calculated = client.post(f"/api/v1/payroll-periods/{period_id}/calculate", json={})
    assert calculated.status_code == 200, calculated.text
    row = client.get(f"/api/v1/payroll-periods/{period_id}/entries").json()[0]
    assert row["base_earning_kurus"] == 2_800_000  # 30 gün × 1.000 TL, iki gün gelmedi
    assert row["overtime_earning_kurus"] == 233_333  # iki özel gün + 2 saat × 1,5
    assert row["calculation_detail"]["unnotified_absence_extra_for_review_kurus"] == 50_000
    days = {item["date"]: item for item in row["calculation_detail"]["daily_breakdown"]}
    assert days["2026-10-07"]["daily_rate_kurus"] == 100_000
    assert days["2026-10-07"]["hourly_rate_kurus"] == 11_111
    assert days["2026-10-08"]["absence_kurus"] == 100_000
    assert days["2026-10-11"]["sunday_holiday_extra_kurus"] == 100_000
    assert days["2026-10-29"]["sunday_holiday_extra_kurus"] == 100_000
    assert row["net_due_kurus"] == 3_033_333  # ek ceza otomatik düşülmez
    due = client.get(f"/api/v1/payroll-periods/{period_id}/salary-due-dates").json()
    assert due["employees"][0]["due_date"] == "2026-11-10"
    assert client.post(f"/api/v1/payroll-periods/{period_id}/finalize", json={"payment_due_date": "2026-11-15"}).status_code == 422
    finalized = client.post(f"/api/v1/payroll-periods/{period_id}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    movements = client.get("/api/v1/employee-finance/movements", params={"payroll_period_id": period_id}).json()
    accrual = next(item for item in movements if item["movement_type"] == "payroll_accrual")
    assert accrual["due_date"] == "2026-11-10"


def test_full_monthly_salary_is_stable_across_period_lengths(client):
    make_employee(client, "Aylık Personel", "monthly", 3_000_000)
    for start, end, adjustment in (
        ("2026-10-06", "2026-11-05", -100_000),
        ("2027-02-06", "2027-03-05", 200_000),
    ):
        created = client.post("/api/v1/payroll-periods", json={"period_start": start, "period_end": end})
        assert created.status_code == 201, created.text
        period_id = created.json()["id"]
        assert client.post(f"/api/v1/payroll-periods/{period_id}/calculate", json={}).status_code == 200
        row = client.get(f"/api/v1/payroll-periods/{period_id}/entries").json()[0]
        assert row["base_earning_kurus"] == 3_000_000
        assert row["calculation_detail"]["period_length_adjustment_kurus"] == adjustment
