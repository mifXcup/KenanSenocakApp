from __future__ import annotations

from helpers import log_work, make_employee
from sqlalchemy import select

from ks_yonetim.database import SessionLocal
from ks_yonetim.models import LeaveLedgerEntry, RecordStatus, WorkLog

API = "/api/v1"
_counter = {"n": 0}


def key(prefix="k"):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:08d}"


def grant(client, employee_id, days, day="2026-01-01", valid_to=None, entry_type="grant", **extra):
    body = {
        "entry_type": entry_type, "quantity_days": str(days), "entry_date": day,
        "idempotency_key": key("grant"), **extra,
    }
    if valid_to:
        body["valid_to"] = valid_to
    return client.post(f"{API}/employees/{employee_id}/leave-ledger", json=body)


def request_leave(client, employee_id, start, end, code="annual", **extra):
    return client.post(
        f"{API}/leave-requests",
        json={
            "employee_id": employee_id, "leave_type_code": code, "start_date": start, "end_date": end,
            "idempotency_key": key("leave"), **extra,
        },
    )


def decide(client, request_id, action, note=None):
    return client.post(f"{API}/leave-requests/{request_id}/{action}", json={"note": note} if note else None)


def balance(client, employee_id, as_of="2026-12-31", code="annual"):
    return client.get(
        f"{API}/employees/{employee_id}/leave-ledger", params={"as_of": as_of, "leave_type_code": code}
    ).json()["balance"]


def logs(client, employee_id, **params):
    return client.get(f"{API}/work-logs", params={"employee_id": employee_id, "limit": 100, **params}).json()


def make_period(client, start, end):
    response = client.post(f"{API}/payroll-periods", json={"period_start": start, "period_end": end})
    assert response.status_code == 201, response.text
    return response.json()


def calc_entries(client, start, end):
    period = make_period(client, start, end)
    assert client.post(f"{API}/payroll-periods/{period['id']}/calculate", json={}).status_code == 200
    return period, {
        e["employee_name"]: e for e in client.get(f"{API}/payroll-periods/{period['id']}/entries").json()
    }


def test_default_leave_types_and_custom_types(client):
    types = {t["code"]: t for t in client.get(f"{API}/leave-types").json()}
    assert set(types) == {"annual", "sick", "other_paid", "unpaid", "excused"}
    assert types["annual"]["deducts_entitlement"] is True and types["annual"]["work_status"] == "annual_leave"
    assert types["sick"]["work_status"] == "sick_leave" and types["unpaid"]["work_status"] == "unpaid_leave"
    created = client.post(
        f"{API}/leave-types", json={"code": "dogum", "name": "Doğum izni", "work_status": "paid_leave"}
    )
    assert created.status_code == 201 and created.json()["is_system"] is False
    dup = client.post(f"{API}/leave-types", json={"code": "dogum", "name": "Tekrar", "work_status": "paid_leave"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_leave_type"
    assert client.post(f"{API}/leave-types", json={"code": "x1", "name": "Hatalı", "work_status": "worked"}).status_code == 422
    assert client.post(f"{API}/leave-types/{created.json()['id']}/archive").status_code == 200
    system = client.post(f"{API}/leave-types/{types['annual']['id']}/archive")
    assert system.status_code == 409 and system.json()["error"]["code"] == "system_leave_type"
    assert "dogum" not in {t["code"] for t in client.get(f"{API}/leave-types").json()}


def test_ledger_entries_validation_and_idempotency(client):
    employee = make_employee(client, "Hak Usta")
    created = grant(client, employee["id"], 14)
    assert created.status_code == 201 and created.json()["quantity_hours"] == "112.00"
    summary = balance(client, employee["id"])
    assert (summary["granted_days"], summary["balance_hours"]) == ("14.00", "112.00")
    assert grant(client, employee["id"], 2, entry_type="accrual", day="2026-06-01").status_code == 201
    in_hours = client.post(
        f"{API}/employees/{employee['id']}/leave-ledger",
        json={"entry_type": "grant", "quantity_hours": "4", "entry_date": "2026-02-01", "idempotency_key": key()},
    )
    assert in_hours.status_code == 201 and in_hours.json()["quantity_hours"] == "4.00"
    body = {"entry_type": "grant", "quantity_days": "1", "entry_date": "2026-03-01", "idempotency_key": "tekrar-anahtar-1"}
    first = client.post(f"{API}/employees/{employee['id']}/leave-ledger", json=body)
    again = client.post(f"{API}/employees/{employee['id']}/leave-ledger", json=body)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    for bad in (
        {"entry_type": "grant", "quantity_days": "1", "quantity_hours": "8"},
        {"entry_type": "grant"},
        {"entry_type": "grant", "quantity_days": "0"},
        {"entry_type": "grant", "quantity_days": "-1"},
        {"entry_type": "use", "quantity_days": "1"},
        {"entry_type": "adjustment", "quantity_days": "1", "valid_to": "2026-12-31"},
        {"entry_type": "grant", "quantity_days": "1", "valid_from": "2026-05-01", "valid_to": "2026-04-01"},
    ):
        response = client.post(
            f"{API}/employees/{employee['id']}/leave-ledger",
            json={"entry_date": "2026-01-01", "idempotency_key": key(), **bad},
        )
        assert response.status_code == 422, bad
    no_pool = client.post(
        f"{API}/employees/{employee['id']}/leave-ledger",
        json={"leave_type_code": "sick", "entry_type": "grant", "quantity_days": "1", "entry_date": "2026-01-01", "idempotency_key": key()},
    )
    assert no_pool.status_code == 422 and no_pool.json()["error"]["code"] == "leave_type_without_entitlement"


def test_approved_annual_leave_creates_attendance_and_uses_entitlement(client):
    employee = make_employee(client, "Yıllık Usta", "daily", 80000)
    grant(client, employee["id"], 10, valid_to="2026-12-31")
    created = request_leave(client, employee["id"], "2026-10-05", "2026-10-09")
    assert created.status_code == 201 and created.json()["request_state"] == "pending"
    assert logs(client, employee["id"]) == []  # onaysız talep puantaj üretmez

    approved = decide(client, created.json()["id"], "approve", "Uygundur")
    assert approved.status_code == 200
    body = approved.json()
    assert body["request_state"] == "approved" and body["total_hours"] == "40.00"
    assert body["decision_note"] == "Uygundur" and len(body["work_log_ids"]) == 5
    rows = logs(client, employee["id"])
    assert {r["work_status"] for r in rows} == {"annual_leave"}
    assert {(r["normal_hours"], r["amount_kurus"], r["leave_hours"], r["source"]) for r in rows} == {
        ("8.00", 80000, "8.00", "leave")
    }
    assert {r["leave_request_id"] for r in rows} == {created.json()["id"]}
    summary = balance(client, employee["id"])
    assert (summary["used_hours"], summary["available_hours"], summary["balance_days"]) == ("40.00", "40.00", "5.00")

    # Puantaj izin talebine bağlıdır; doğrudan değiştirilemez veya iptal edilemez.
    patch = client.patch(f"{API}/work-logs/{rows[0]['id']}", json={"note": "x"})
    cancel = client.post(f"{API}/work-logs/{rows[0]['id']}/cancel")
    assert patch.status_code == cancel.status_code == 409
    assert patch.json()["error"]["code"] == "leave_managed"
    assert client.post(f"{API}/leave-requests/{created.json()['id']}/approve").json()["error"]["code"] == "invalid_transition"

    _, entries = calc_entries(client, "2026-10-05", "2026-10-09")
    assert entries["Yıllık Usta"]["base_earning_kurus"] == 400000  # ücretli izin günleri ödenir


def test_insufficient_balance_blocks_unless_negative_allowed(client):
    employee = make_employee(client, "Bakiye Usta")
    grant(client, employee["id"], 2)
    created = request_leave(client, employee["id"], "2026-10-05", "2026-10-07").json()
    blocked = decide(client, created["id"], "approve")
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    assert error["code"] == "insufficient_leave_balance"
    assert (error["details"]["available_hours"], error["details"]["required_hours"]) == ("16.00", "24.00")
    # Hiçbir iz bırakmaz: talep beklemede, puantaj ve kullanım yok.
    assert client.get(f"{API}/leave-requests/{created['id']}").json()["request_state"] == "pending"
    assert logs(client, employee["id"]) == []
    assert balance(client, employee["id"])["used_hours"] == "0.00"

    client.put(f"{API}/settings/attendance", json={"allow_negative_leave_balance": True})
    assert decide(client, created["id"], "approve").status_code == 200
    summary = balance(client, employee["id"])
    assert (summary["balance_hours"], summary["overdrawn_hours"]) == ("-8.00", "8.00")


def test_negative_adjustment_respects_balance_setting(client):
    employee = make_employee(client, "Düzeltme Usta")
    grant(client, employee["id"], 3)
    too_much = grant(client, employee["id"], -5, entry_type="adjustment", day="2026-02-01")
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "insufficient_leave_balance"
    ok = grant(client, employee["id"], -1, entry_type="adjustment", day="2026-02-01")
    assert ok.status_code == 201 and balance(client, employee["id"])["balance_days"] == "2.00"
    client.put(f"{API}/settings/attendance", json={"allow_negative_leave_balance": True})
    assert grant(client, employee["id"], -5, entry_type="adjustment", day="2026-03-01").status_code == 201
    assert balance(client, employee["id"])["balance_days"] == "-3.00"


def test_holidays_and_weekly_rest_are_skipped_in_leave_days(client):
    employee = make_employee(client, "Tatil Usta", "daily", 80000)
    grant(client, employee["id"], 10)
    client.post(f"{API}/holidays", json={"holiday_date": "2026-10-29", "name": "Cumhuriyet Bayramı"})
    # 28 Çar, 29 Per (tatil), 30 Cum
    wed = request_leave(client, employee["id"], "2026-10-28", "2026-10-30").json()
    approved = decide(client, wed["id"], "approve").json()
    assert approved["total_hours"] == "16.00"
    assert sorted(r["work_date"] for r in logs(client, employee["id"])) == ["2026-10-28", "2026-10-30"]
    # 3 Cts ... 5 Pzt: Pazar atlanır.
    weekend = request_leave(client, employee["id"], "2026-11-07", "2026-11-09").json()
    assert decide(client, weekend["id"], "approve").json()["total_hours"] == "16.00"

    only_rest = request_leave(client, employee["id"], "2026-11-15", "2026-11-15").json()  # Pazar
    blocked = decide(client, only_rest["id"], "approve")
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "leave_no_working_days"
    assert blocked.json()["error"]["details"]["skipped"][0]["day_type"] == "weekly_rest"
    only_holiday = request_leave(client, employee["id"], "2026-10-29", "2026-10-29")
    assert only_holiday.status_code == 409  # mevcut talep (28–30) ile çakışır
    assert balance(client, employee["id"])["used_hours"] == "32.00"


def test_half_day_hourly_and_partial_unpaid_leave(client):
    daily = make_employee(client, "Yarım Gün Usta", "daily", 80000)
    grant(client, daily["id"], 5)
    half = request_leave(client, daily["id"], "2026-10-05", "2026-10-05", day_part="half_am").json()
    decide(client, half["id"], "approve")
    hourly = request_leave(client, daily["id"], "2026-10-06", "2026-10-06", day_part="hourly", hours="2").json()
    decide(client, hourly["id"], "approve")
    by_day = {r["work_date"]: r for r in logs(client, daily["id"])}
    assert (by_day["2026-10-05"]["leave_hours"], by_day["2026-10-05"]["normal_hours"]) == ("4.00", "8.00")
    assert (by_day["2026-10-06"]["leave_hours"], by_day["2026-10-06"]["normal_hours"]) == ("2.00", "8.00")
    assert balance(client, daily["id"])["used_hours"] == "6.00"

    # Ücretsiz yarım gün: çalışılan 4 saat ücretlenir, izin saati düşer.
    unpaid = request_leave(client, daily["id"], "2026-10-07", "2026-10-07", code="unpaid", day_part="half_pm").json()
    decide(client, unpaid["id"], "approve")
    log = next(r for r in logs(client, daily["id"]) if r["work_date"] == "2026-10-07")
    assert (log["work_status"], log["normal_hours"], log["leave_hours"], log["amount_kurus"]) == (
        "unpaid_leave", "4.00", "4.00", 40000
    )
    assert balance(client, daily["id"])["used_hours"] == "6.00"  # ücretsiz izin hak düşmez

    monthly = make_employee(client, "Aylık Yarım Gün", "monthly", 3100000)
    sick = request_leave(client, monthly["id"], "2026-10-06", "2026-10-06", code="sick").json()
    decide(client, sick["id"], "approve")
    half_unpaid = request_leave(client, monthly["id"], "2026-10-07", "2026-10-07", code="unpaid", day_part="half_am").json()
    decide(client, half_unpaid["id"], "approve")
    _, entries = calc_entries(client, "2026-10-01", "2026-10-31")
    # Gün değeri 100.000: raporlu tam gün -100.000, ücretsiz yarım gün -50.000.
    assert entries["Aylık Yarım Gün"]["base_earning_kurus"] == 3100000 - 100000 - 50000
    # Günlük çalışan: 5 Ekim (ücretli yarım gün izin) ve 6 Ekim tam gün; 7 Ekim 4 saat çalışılmış.
    assert entries["Yarım Gün Usta"]["base_earning_kurus"] == 80000 + 80000 + 40000


def test_partial_leave_validation(client):
    employee = make_employee(client, "Doğrulama Usta")
    base = {"employee_id": employee["id"], "leave_type_code": "annual", "idempotency_key": key()}
    multi = client.post(f"{API}/leave-requests", json={**base, "start_date": "2026-10-05", "end_date": "2026-10-06", "day_part": "half_am"})
    assert multi.status_code == 422
    no_hours = client.post(f"{API}/leave-requests", json={**base, "idempotency_key": key(), "start_date": "2026-10-05", "end_date": "2026-10-05", "day_part": "hourly"})
    assert no_hours.status_code == 422
    stray = client.post(f"{API}/leave-requests", json={**base, "idempotency_key": key(), "start_date": "2026-10-05", "end_date": "2026-10-05", "hours": "2"})
    assert stray.status_code == 422
    too_long = request_leave(client, employee["id"], "2026-10-05", "2026-10-05", day_part="hourly", hours="9")
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "invalid_hours"
    assert request_leave(client, employee["id"], "2026-10-09", "2026-10-05").status_code == 422
    assert request_leave(client, employee["id"], "2026-10-05", "2026-10-05", code="bilinmeyen").status_code == 404


def test_employment_window_overlap_and_idempotency(client):
    employee = make_employee(
        client, "Sınırlı Usta", employment_start_date="2026-10-12", employment_end_date="2026-10-30"
    )
    early = request_leave(client, employee["id"], "2026-10-05", "2026-10-14")
    assert early.status_code == 422 and early.json()["error"]["code"] == "leave_outside_employment"
    late = request_leave(client, employee["id"], "2026-10-28", "2026-11-03")
    assert late.status_code == 422 and late.json()["error"]["code"] == "leave_outside_employment"

    first = request_leave(client, employee["id"], "2026-10-13", "2026-10-14", code="excused")
    assert first.status_code == 201
    same = client.post(
        f"{API}/leave-requests",
        json={"employee_id": employee["id"], "leave_type_code": "excused", "start_date": "2026-10-13",
              "end_date": "2026-10-14", "idempotency_key": first.json()["idempotency_key"]},
    )
    assert same.status_code == 201 and same.json()["id"] == first.json()["id"]
    changed = client.post(
        f"{API}/leave-requests",
        json={"employee_id": employee["id"], "leave_type_code": "excused", "start_date": "2026-10-20",
              "end_date": "2026-10-21", "idempotency_key": first.json()["idempotency_key"]},
    )
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
    overlap = request_leave(client, employee["id"], "2026-10-14", "2026-10-15")
    assert overlap.status_code == 409 and overlap.json()["error"]["code"] == "leave_overlap"
    assert decide(client, first.json()["id"], "cancel").status_code == 200
    assert request_leave(client, employee["id"], "2026-10-14", "2026-10-15").status_code == 201


def test_reject_cancel_and_double_decisions(client):
    employee = make_employee(client, "Karar Usta")
    grant(client, employee["id"], 10)
    pending = request_leave(client, employee["id"], "2026-10-05", "2026-10-06").json()
    assert decide(client, pending["id"], "reject", "Yoğun dönem").json()["request_state"] == "rejected"
    for action in ("approve", "reject", "cancel"):
        again = decide(client, pending["id"], action)
        assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    assert logs(client, employee["id"]) == [] and balance(client, employee["id"])["used_hours"] == "0.00"

    second = request_leave(client, employee["id"], "2026-10-05", "2026-10-06").json()
    assert decide(client, second["id"], "approve").status_code == 200
    assert decide(client, second["id"], "approve").json()["error"]["code"] == "invalid_transition"
    assert decide(client, second["id"], "reject").status_code == 409
    assert balance(client, employee["id"])["used_hours"] == "16.00"

    cancelled = decide(client, second["id"], "cancel", "Vazgeçti")
    assert cancelled.status_code == 200 and cancelled.json()["request_state"] == "cancelled"
    assert cancelled.json()["work_log_ids"] == []
    assert logs(client, employee["id"]) == []  # puantaj iptal edildi
    assert len(logs(client, employee["id"], include_cancelled=True)) == 2  # ama silinmedi
    restored = balance(client, employee["id"])
    assert (restored["used_hours"], restored["available_hours"]) == ("0.00", "80.00")
    with SessionLocal() as session:
        entries = session.scalars(select(LeaveLedgerEntry).where(LeaveLedgerEntry.entry_type == "reversal")).all()
        assert len(entries) == 2 and {e.source for e in entries} == {"system"}
    assert decide(client, second["id"], "cancel").status_code == 409
    # Tarihler tekrar alınabilir.
    assert request_leave(client, employee["id"], "2026-10-05", "2026-10-06").status_code == 201


def test_existing_attendance_conflicts_with_approval(client):
    employee = make_employee(client, "Çakışan Usta")
    grant(client, employee["id"], 5)
    worked = log_work(client, employee["id"], "2026-10-06").json()
    pending = request_leave(client, employee["id"], "2026-10-05", "2026-10-07").json()
    blocked = decide(client, pending["id"], "approve")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "attendance_conflict"
    assert blocked.json()["error"]["details"]["dates"] == ["2026-10-06"]
    assert balance(client, employee["id"])["used_hours"] == "0.00"
    client.post(f"{API}/work-logs/{worked['id']}/cancel")
    assert decide(client, pending["id"], "approve").status_code == 200
    assert len(logs(client, employee["id"])) == 3


def test_leave_cannot_touch_finalized_or_closed_payroll_periods(client):
    employee = make_employee(client, "Kilitli Usta", "monthly", 3100000)
    grant(client, employee["id"], 20)
    # Eylül iznini onayla, sonra Eylül dönemini kesinleştir.
    sept = request_leave(client, employee["id"], "2026-09-07", "2026-09-08").json()
    assert decide(client, sept["id"], "approve").status_code == 200
    period = make_period(client, "2026-09-01", "2026-09-30")
    client.post(f"{API}/payroll-periods/{period['id']}/calculate", json={})
    assert client.post(f"{API}/payroll-periods/{period['id']}/finalize", json={}).status_code == 200

    locked_cancel = decide(client, sept["id"], "cancel")
    assert locked_cancel.status_code == 409 and locked_cancel.json()["error"]["code"] == "period_locked"
    assert client.get(f"{API}/leave-requests/{sept['id']}").json()["request_state"] == "approved"
    assert len(logs(client, employee["id"])) == 2

    new_in_locked = request_leave(client, employee["id"], "2026-09-14", "2026-09-15")
    assert new_in_locked.status_code == 409 and new_in_locked.json()["error"]["code"] == "period_locked"
    # Ay sınırı: 30 Eylül kilitli olduğundan Eylül–Ekim arası talep de engellenir; Ekim'den başlayan serbest.
    crossing = request_leave(client, employee["id"], "2026-09-29", "2026-10-02")
    assert crossing.status_code == 409 and crossing.json()["error"]["code"] == "period_locked"
    october = request_leave(client, employee["id"], "2026-10-01", "2026-10-02")
    assert october.status_code == 201 and decide(client, october.json()["id"], "approve").status_code == 200

    # Kapanmış dönem de aynı korumaya sahiptir.
    assert client.post(f"{API}/payroll-periods/{period['id']}/close", json={"allow_unpaid": True}).status_code == 200
    assert decide(client, sept["id"], "cancel").json()["error"]["code"] == "period_locked"
    # Kilitli döneme manuel puantaj da girilemez.
    assert log_work(client, employee["id"], "2026-09-20").json()["error"]["code"] == "period_locked"


def test_leave_approval_into_locked_period_is_blocked_even_if_created_earlier(client):
    employee = make_employee(client, "Sonradan Kilit", "monthly", 3100000)
    grant(client, employee["id"], 20)
    pending = request_leave(client, employee["id"], "2026-09-14", "2026-09-15").json()
    period = make_period(client, "2026-09-01", "2026-09-30")
    client.post(f"{API}/payroll-periods/{period['id']}/calculate", json={})
    client.post(f"{API}/payroll-periods/{period['id']}/finalize", json={})
    blocked = decide(client, pending["id"], "approve")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "period_locked"
    assert logs(client, employee["id"]) == [] and balance(client, employee["id"])["used_hours"] == "0.00"


def test_ledger_reversal_rules(client):
    employee = make_employee(client, "Ters Usta", "daily", 80000)
    entry = grant(client, employee["id"], 5, day="2026-01-01").json()
    reverse = client.post(f"{API}/leave-ledger/{entry['id']}/reverse")
    assert reverse.status_code == 201 and reverse.json()["entry_type"] == "reversal"
    assert reverse.json()["quantity_hours"] == "-40.00" and reverse.json()["entry_date"] == "2026-03-10"
    assert balance(client, employee["id"])["balance_hours"] == "0.00"
    assert client.post(f"{API}/leave-ledger/{entry['id']}/reverse").json()["error"]["code"] == "already_reversed"
    assert client.post(f"{API}/leave-ledger/{reverse.json()['id']}/reverse").json()["error"]["code"] == "cannot_reverse_reversal"
    early = client.post(f"{API}/leave-ledger/{grant(client, employee['id'], 1, day='2026-05-01').json()['id']}/reverse",
                        json={"entry_date": "2026-04-01"})
    assert early.status_code == 422 and early.json()["error"]["code"] == "invalid_reversal_date"

    # Kullanılmış hakkın terslenmesi bakiyeyi negatife düşürürse engellenir.
    base = grant(client, employee["id"], 3, day="2026-01-01").json()
    used = decide(client, request_leave(client, employee["id"], "2026-10-05", "2026-10-07").json()["id"], "approve")
    assert used.status_code == 200
    blocked = client.post(f"{API}/leave-ledger/{base['id']}/reverse")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "reversal_makes_negative"
    with SessionLocal() as session:
        use_entry = session.scalars(select(LeaveLedgerEntry).where(LeaveLedgerEntry.entry_type == "use")).first()
        use_id = use_entry.id
    system = client.post(f"{API}/leave-ledger/{use_id}/reverse")
    assert system.status_code == 409 and system.json()["error"]["code"] == "system_entry"
    assert client.post(f"{API}/leave-ledger/yok/reverse").status_code == 404


def test_validity_periods_use_fifo_and_expire(client):
    employee = make_employee(client, "Süreli Usta", "daily", 80000)
    grant(client, employee["id"], 5, day="2026-01-01", valid_to="2026-06-30")
    grant(client, employee["id"], 5, day="2026-01-01", valid_to="2026-12-31")
    feb = request_leave(client, employee["id"], "2026-02-02", "2026-02-04").json()  # 3 gün
    assert decide(client, feb["id"], "approve").status_code == 200
    spring = balance(client, employee["id"], as_of="2026-03-01")
    assert (spring["available_days"], spring["expired_hours"]) == ("7.00", "0.00")
    # Süresi önce dolan hak önce tüketildi: 2 gün (16 saat) kullanılmadan sona erdi.
    summer = balance(client, employee["id"], as_of="2026-07-01")
    assert (summer["expired_hours"], summer["available_hours"], summer["used_hours"]) == ("16.00", "40.00", "24.00")
    # Süresi dolmuş hakla yeni kullanım yapılamaz.
    late = request_leave(client, employee["id"], "2026-07-06", "2026-07-17").json()  # 10 iş günü
    blocked = decide(client, late["id"], "approve")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "insufficient_leave_balance"
    ok = request_leave(client, employee["id"], "2026-07-20", "2026-07-24").json()  # 5 iş günü = 40 saat
    assert decide(client, ok["id"], "approve").status_code == 200
    assert balance(client, employee["id"], as_of="2026-12-31")["available_hours"] == "0.00"


def test_entitlement_suggestion_and_missing_log_report(client):
    senior = make_employee(client, "Kıdemli Usta", employment_start_date="2010-03-15")
    fresh = make_employee(client, "Yeni Usta", employment_start_date="2026-06-01")
    plain = make_employee(client, "Tarihsiz Usta")
    assert client.get(f"{API}/employees/{senior['id']}/leave-entitlement", params={"year": 2026}).json()["suggested_days"] == 26
    mid = make_employee(client, "Orta Usta", employment_start_date="2020-01-10")
    assert client.get(f"{API}/employees/{mid['id']}/leave-entitlement", params={"year": 2026}).json()["suggested_days"] == 20
    young = make_employee(client, "Genç Usta", employment_start_date="2024-01-10")
    assert client.get(f"{API}/employees/{young['id']}/leave-entitlement", params={"year": 2026}).json()["suggested_days"] == 14
    assert client.get(f"{API}/employees/{fresh['id']}/leave-entitlement", params={"year": 2026}).json()["suggested_days"] == 0
    assert client.get(f"{API}/employees/{plain['id']}/leave-entitlement", params={"year": 2026}).json()["suggested_days"] is None

    # Onaylı izin ama puantajı sonradan kaybolmuşsa uyumsuzluk raporlanır.
    grant(client, plain["id"], 5)
    approved = decide(client, request_leave(client, plain["id"], "2026-10-05", "2026-10-06").json()["id"], "approve").json()
    with SessionLocal() as session:
        victim = session.get(WorkLog, approved["work_log_ids"][0])
        victim.status = RecordStatus.CANCELLED
        session.commit()
    report = client.get(f"{API}/attendance/check", params={"date_from": "2026-10-05", "date_to": "2026-10-06", "employee_id": plain["id"]}).json()
    codes = {(i["code"], i["date"]) for i in report["employees"][0]["issues"]}
    assert any(code == "approved_leave_without_log" for code, _ in codes)
