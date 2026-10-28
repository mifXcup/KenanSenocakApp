from __future__ import annotations

from datetime import date

import pytest
from helpers import log_work, make_employee
from sqlalchemy.exc import IntegrityError

from ks_yonetim.attendance import derive_due_date
from ks_yonetim.database import SessionLocal
from ks_yonetim.models import WorkLog

API = "/api/v1"


def set_settings(client, **body):
    response = client.put(f"{API}/settings/attendance", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def make_period(client, start, end, title="Dönem"):
    response = client.post(
        f"{API}/payroll-periods", json={"period_start": start, "period_end": end, "title": title}
    )
    assert response.status_code == 201, response.text
    return response.json()


def calculate(client, period_id):
    response = client.post(f"{API}/payroll-periods/{period_id}/calculate", json={})
    assert response.status_code == 200, response.text


def finalize(client, period_id, **body):
    return client.post(f"{API}/payroll-periods/{period_id}/finalize", json=body)


def log_days(client, employee_id, days):
    for day in days:
        assert log_work(client, employee_id, day).status_code == 201


def test_settings_roundtrip_validation_and_clearing(client):
    initial = client.get(f"{API}/settings/attendance").json()
    assert initial == {
        "attendance_enforcement_start_date": None,
        "default_salary_day": None,
        "allow_negative_leave_balance": False,
    }
    updated = set_settings(
        client, attendance_enforcement_start_date="2026-11-01", default_salary_day=5,
        allow_negative_leave_balance=True,
    )
    assert updated["attendance_enforcement_start_date"] == "2026-11-01"
    assert updated["default_salary_day"] == 5 and updated["allow_negative_leave_balance"] is True
    cleared = set_settings(client, attendance_enforcement_start_date=None, default_salary_day=None)
    assert cleared["attendance_enforcement_start_date"] is None and cleared["default_salary_day"] is None
    assert cleared["allow_negative_leave_balance"] is True  # gönderilmeyen ayar korunur
    for bad in ({}, {"default_salary_day": 0}, {"default_salary_day": 32}, {"allow_negative_leave_balance": None}):
        assert client.put(f"{API}/settings/attendance", json=bad).status_code == 422


def test_holidays_are_unique_per_active_date_and_cancellable(client):
    created = client.post(f"{API}/holidays", json={"holiday_date": "2026-10-29", "name": "Cumhuriyet Bayramı"})
    assert created.status_code == 201
    duplicate = client.post(f"{API}/holidays", json={"holiday_date": "2026-10-29", "name": "Tekrar"})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "duplicate_holiday"
    client.post(f"{API}/holidays", json={"holiday_date": "2027-01-01", "name": "Yılbaşı"})
    assert [h["name"] for h in client.get(f"{API}/holidays", params={"year": 2026}).json()] == ["Cumhuriyet Bayramı"]
    cancelled = client.post(f"{API}/holidays/{created.json()['id']}/cancel")
    assert cancelled.status_code == 200
    assert client.post(f"{API}/holidays/{created.json()['id']}/cancel").status_code == 409
    again = client.post(f"{API}/holidays", json={"holiday_date": "2026-10-29", "name": "Yeniden"})
    assert again.status_code == 201  # iptal edilen kayıt tarihi serbest bırakır
    assert len(client.get(f"{API}/holidays", params={"include_cancelled": True}).json()) == 3


def test_weekly_plans_company_employee_and_closing(client):
    worker = make_employee(client, "Planlı Usta")
    other = make_employee(client, "Diğer Usta")
    base = client.get(
        f"{API}/employees/{worker['id']}/work-calendar", params={"date_from": "2026-10-03", "date_to": "2026-10-05"}
    ).json()["days"]
    # Varsayılan: Pazartesi–Cumartesi çalışma, Pazar haftalık izin.
    assert [(d["date"], d["day_type"]) for d in base] == [
        ("2026-10-03", "workday"), ("2026-10-04", "weekly_rest"), ("2026-10-05", "workday")
    ]

    company = client.post(f"{API}/weekly-work-plans", json={"effective_from": "2026-10-01", "workdays": [1, 2, 3, 4, 5]})
    assert company.status_code == 201 and company.json()["workday_numbers"] == [1, 2, 3, 4, 5]
    own = client.post(
        f"{API}/weekly-work-plans",
        json={"employee_id": worker["id"], "effective_from": "2026-10-01", "workdays": [1, 2, 3, 4, 5, 6]},
    )
    assert own.status_code == 201

    def kinds(employee):
        rows = client.get(
            f"{API}/employees/{employee['id']}/work-calendar", params={"date_from": "2026-10-03", "date_to": "2026-10-04"}
        ).json()["days"]
        return [d["day_type"] for d in rows]

    assert kinds(other) == ["weekly_rest", "weekly_rest"]  # şirket planı: Cumartesi de izin
    assert kinds(worker) == ["workday", "weekly_rest"]  # personel planı önceliklidir

    newer = client.post(f"{API}/weekly-work-plans", json={"effective_from": "2026-11-01", "workdays": [1, 2, 3, 4, 5, 6]})
    assert newer.status_code == 201
    plans = client.get(f"{API}/weekly-work-plans", params={"company_only": True}).json()
    assert [(p["effective_from"], p["effective_to"]) for p in plans] == [
        ("2026-10-01", "2026-10-31"), ("2026-11-01", None)
    ]
    stale = client.post(f"{API}/weekly-work-plans", json={"effective_from": "2026-10-15", "workdays": [1]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "plan_order"
    for bad in ([0], [8], [1, 1]):
        assert client.post(f"{API}/weekly-work-plans", json={"effective_from": "2027-01-01", "workdays": bad}).status_code == 422
    assert client.post(f"{API}/weekly-work-plans", json={"employee_id": "yok", "effective_from": "2027-01-01", "workdays": [1]}).status_code == 404


def test_old_behavior_is_kept_until_enforcement_start_date(client):
    employee = make_employee(client, "Aylık Usta", "monthly", 3100000)
    log_work(client, employee["id"], "2026-10-05")  # eksik günlerin çoğu puantajsız
    period = make_period(client, "2026-10-01", "2026-10-07")
    calculate(client, period["id"])
    assert finalize(client, period["id"]).status_code == 200  # ayar yok: eski davranış

    other = make_period(client, "2026-11-01", "2026-11-07")
    set_settings(client, attendance_enforcement_start_date="2026-12-01")  # dönemden sonra
    calculate(client, other["id"])
    assert finalize(client, other["id"]).status_code == 200


def test_missing_required_days_block_finalize_after_enforcement(client):
    full = make_employee(client, "Aylık A", "monthly", 3100000)
    empty = make_employee(client, "Aylık B", "monthly", 3100000)
    set_settings(client, attendance_enforcement_start_date="2026-10-01")
    # 1-7 Ekim: Per, Cum, Cts, (Paz izin), Pzt, Sal, Çar -> 6 zorunlu gün.
    log_days(client, full["id"], ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05", "2026-10-06"])
    period = make_period(client, "2026-10-01", "2026-10-07")
    calculate(client, period["id"])

    blocked = finalize(client, period["id"])
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    assert error["code"] == "attendance_incomplete"
    rows = {r["employee_name"]: r for r in error["details"]["employees"]}
    assert rows["Aylık A"]["missing_dates"] == ["2026-10-07"] and rows["Aylık A"]["missing_count"] == 1
    assert rows["Aylık B"]["missing_count"] == 6
    assert client.get(f"{API}/payroll-periods/{period['id']}").json()["state"] == "calculated"

    log_days(client, full["id"], ["2026-10-07"])
    log_days(client, empty["id"], ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05", "2026-10-06", "2026-10-07"])
    calculate(client, period["id"])
    assert finalize(client, period["id"]).status_code == 200


def test_enforcement_applies_only_from_start_date_inside_a_period(client):
    employee = make_employee(client, "Aylık Usta", "monthly", 3100000)
    set_settings(client, attendance_enforcement_start_date="2026-10-05")
    log_days(client, employee["id"], ["2026-10-05", "2026-10-06", "2026-10-07"])
    period = make_period(client, "2026-10-01", "2026-10-07")
    calculate(client, period["id"])
    assert finalize(client, period["id"]).status_code == 200  # 1-3 Ekim eski davranış


def test_holidays_weekly_rest_and_employment_window_are_not_required(client):
    employee = make_employee(client, "Yeni Başlayan", "monthly", 3100000, employment_start_date="2026-10-03")
    client.post(f"{API}/holidays", json={"holiday_date": "2026-10-06", "name": "Resmî tatil"})
    set_settings(client, attendance_enforcement_start_date="2026-10-01")
    # Gerekli günler: 3 Cts, 5 Pzt, 7 Çar (4 Pazar izin, 6 tatil, 1-2 işe girişten önce).
    log_days(client, employee["id"], ["2026-10-03", "2026-10-05", "2026-10-07"])
    period = make_period(client, "2026-10-01", "2026-10-07")
    calculate(client, period["id"])
    assert finalize(client, period["id"]).status_code == 200


def test_check_endpoint_reports_missing_and_inconsistent_days(client):
    employee = make_employee(client, "Kontrol Usta", "daily", 80000, employment_end_date="2026-10-09")
    client.post(f"{API}/holidays", json={"holiday_date": "2026-10-07", "name": "Resmî tatil"})
    set_settings(client, attendance_enforcement_start_date="2026-10-05")
    log_days(client, employee["id"], ["2026-10-04", "2026-10-07"])  # Pazar ve tatilde çalışılmış
    for day, status in (("2026-10-03", "worked"),):
        log_work(client, employee["id"], day, work_status=status)
    report = client.get(f"{API}/attendance/check", params={"date_from": "2026-10-01", "date_to": "2026-10-12"}).json()
    assert report["enforcement_start_date"] == "2026-10-05" and report["employees_checked"] == 1
    issues = {(i["code"], i["date"]): i for i in report["employees"][0]["issues"]}
    assert issues[("missing_required_day", "2026-10-01")]["enforced"] is False  # enforcement öncesi
    assert issues[("missing_required_day", "2026-10-05")]["enforced"] is True
    assert ("missing_required_day", "2026-10-06") in issues and ("missing_required_day", "2026-10-09") in issues
    assert ("missing_required_day", "2026-10-08") in issues
    assert ("missing_required_day", "2026-10-10") not in issues  # işten ayrılıştan sonra
    assert ("worked_on_weekly_rest", "2026-10-04") in issues
    assert ("worked_on_public_holiday", "2026-10-07") in issues
    assert ("missing_required_day", "2026-10-07") not in issues
    totals = report["totals"]
    assert totals["enforced_missing_day"] == 4 and totals["inconsistency"] == 2

    by_period = make_period(client, "2026-10-05", "2026-10-06")
    scoped = client.get(f"{API}/attendance/check", params={"payroll_period_id": by_period["id"]}).json()
    assert (scoped["date_from"], scoped["date_to"]) == ("2026-10-05", "2026-10-06")
    assert client.get(f"{API}/attendance/check").status_code == 422
    assert client.get(f"{API}/attendance/check", params={"date_from": "2026-10-09", "date_to": "2026-10-01"}).status_code == 422
    clean = client.get(f"{API}/attendance/check", params={"date_from": "2026-10-04", "date_to": "2026-10-04", "include_clean": True}).json()
    assert len(clean["employees"]) == 1


def test_database_level_unique_active_work_log(client):
    employee = make_employee(client)
    created = log_work(client, employee["id"], "2026-10-05").json()
    api_duplicate = log_work(client, employee["id"], "2026-10-05")
    assert api_duplicate.status_code == 409 and api_duplicate.json()["error"]["code"] == "duplicate_work_log"

    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            WorkLog(
                employee_id=employee["id"], work_date=date(2026, 10, 5), hours=8, amount_kurus=1,
                normal_hours=8, overtime_hours=0, work_status="worked",
            )
        )
        session.commit()

    # İptal edilmiş kayıt kısıtı tutmaz; yeni aktif kayıt girilebilir.
    assert client.post(f"{API}/work-logs/{created['id']}/cancel").status_code == 200
    assert log_work(client, employee["id"], "2026-10-05").status_code == 201
    assert client.get(f"{API}/attendance/duplicate-reports").json() == []


def test_new_work_statuses_and_leave_managed_guard(client):
    employee = make_employee(client, "Durumlu Usta", "monthly", 3100000)
    for status in ("annual_leave", "sick_leave", "excused_leave"):
        rejected = log_work(client, employee["id"], "2026-10-05", work_status=status)
        assert rejected.status_code == 422  # yalnız izin talebiyle üretilir
    rest = log_work(client, employee["id"], "2026-10-04", work_status="weekly_rest")
    assert rest.status_code == 201 and rest.json()["amount_kurus"] == 0 and rest.json()["hours"] == "0.00"
    bad_hours = log_work(client, employee["id"], "2026-10-11", work_status="weekly_rest", normal_hours="4")
    assert bad_hours.status_code == 422 and bad_hours.json()["error"]["code"] == "invalid_hours"
    again = log_work(client, employee["id"], "2026-10-04", work_status="weekly_rest")
    assert again.status_code == 409 and again.json()["error"]["code"] == "duplicate_work_log"
    holiday = log_work(client, employee["id"], "2026-10-29", work_status="public_holiday")
    assert holiday.status_code == 201 and holiday.json()["hours"] == "8.00"

    # Haftalık izin aylıkta kesinti yapmaz; resmî tatil ücretli sayılır.
    period = make_period(client, "2026-10-01", "2026-10-31")
    calculate(client, period["id"])
    entry = client.get(f"{API}/payroll-periods/{period['id']}/entries").json()[0]
    assert entry["base_earning_kurus"] == 3100000


def test_derive_due_date_is_deterministic():
    assert derive_due_date(date(2026, 10, 31), 5) == date(2026, 11, 5)
    assert derive_due_date(date(2026, 10, 31), 31) == date(2026, 11, 30)  # ay sonuna indirilir
    assert derive_due_date(date(2026, 12, 31), 5) == date(2027, 1, 5)  # yıl sınırı
    assert derive_due_date(date(2026, 10, 10), 20) == date(2026, 10, 20)  # dönem içinde kalan gün
    assert derive_due_date(date(2026, 10, 20), 20) == date(2026, 11, 20)  # bitişin kendisi sayılmaz
    assert derive_due_date(date(2026, 1, 31), 30) == date(2026, 2, 28)  # şubat
    assert derive_due_date(date(2028, 1, 31), 30) == date(2028, 2, 29)  # artık yıl


def test_salary_due_date_uses_employee_exception_then_company_default(client):
    plain = make_employee(client, "Varsayılan Gün", "daily", 80000)
    custom = make_employee(client, "Özel Gün", "daily", 80000, salary_day=15)
    edge = make_employee(client, "Ay Sonu", "daily", 80000, salary_day=31)
    for person in (plain, custom, edge):
        log_days(client, person["id"], ["2026-10-05"])
    period = make_period(client, "2026-10-01", "2026-10-31")
    calculate(client, period["id"])

    # Ayar yokken eski davranış: dönem bitişi.
    preview = client.get(f"{API}/payroll-periods/{period['id']}/salary-due-dates").json()
    assert {e["employee_name"]: (e["due_date"], e["source"]) for e in preview["employees"]} == {
        "Varsayılan Gün": ("2026-10-31", "period_end"),
        "Özel Gün": ("2026-11-15", "employee"),
        "Ay Sonu": ("2026-11-30", "employee"),
    }
    set_settings(client, default_salary_day=5)
    preview = client.get(f"{API}/payroll-periods/{period['id']}/salary-due-dates").json()
    assert {e["employee_name"]: e["due_date"] for e in preview["employees"]}["Varsayılan Gün"] == "2026-11-05"

    assert finalize(client, period["id"]).status_code == 200

    def due(employee):
        rows = client.get(
            f"{API}/employee-finance/movements",
            params={"employee_id": employee["id"], "movement_type": "payroll_accrual"},
        ).json()
        return rows[0]["due_date"]

    assert (due(plain), due(custom), due(edge)) == ("2026-11-05", "2026-11-15", "2026-11-30")


def test_explicit_payment_due_date_overrides_derived_dates(client):
    worker = make_employee(client, "Açık Tarih", "daily", 80000, salary_day=15)
    log_days(client, worker["id"], ["2026-10-05"])
    set_settings(client, default_salary_day=5)
    period = make_period(client, "2026-10-01", "2026-10-31")
    calculate(client, period["id"])
    assert finalize(client, period["id"], payment_due_date="2026-12-24").status_code == 200
    rows = client.get(
        f"{API}/employee-finance/movements", params={"employee_id": worker["id"], "movement_type": "payroll_accrual"}
    ).json()
    assert rows[0]["due_date"] == "2026-12-24"


def test_employee_profile_fields(client):
    created = client.post(
        f"{API}/employees",
        json={
            "name": "Profil Usta", "wage_type": "daily", "current_rate_kurus": 80000,
            "email": "usta@example.com", "address": "Bursa", "skill": "Kalfa",
            "emergency_contact_name": "Eşi", "emergency_contact_phone": "0555", "emergency_contact_relation": "Eş",
            "payment_method": "bank_transfer", "salary_day": 10,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["email"], body["skill"], body["payment_method"], body["salary_day"]) == (
        "usta@example.com", "Kalfa", "bank_transfer", 10
    )
    assert body["emergency_contact_name"] == "Eşi" and body["emergency_contact_relation"] == "Eş"
    patched = client.patch(f"{API}/employees/{body['id']}", json={"salary_day": 20, "payment_method": "cash", "skill": "Usta"})
    assert patched.status_code == 200 and patched.json()["salary_day"] == 20
    for bad in ({"salary_day": 0}, {"salary_day": 32}, {"payment_method": "kripto"}):
        assert client.patch(f"{API}/employees/{body['id']}", json=bad).status_code == 422
    assert client.get(f"{API}/employees").json()[0]["emergency_contact_phone"] == "0555"
