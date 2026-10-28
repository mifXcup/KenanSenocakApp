from __future__ import annotations

from datetime import date

from finance_helpers import make_material, make_purchase, make_supplier, move, schedule
from helpers import log_work, make_employee, make_project

from ks_yonetim import clock

API = "/api/v1"
TODAY = date(2026, 3, 10)  # Salı (conftest iş tarihi)


def events(client, start="2026-03-01", end="2026-03-31", **params):
    response = client.get(f"{API}/calendar/events", params={"date_from": start, "date_to": end, **params})
    assert response.status_code == 200, response.text
    return response.json()["events"]


def by_type(client, event_type, start="2026-01-01", end="2026-12-31"):
    return events(client, start, end, event_type=event_type)


def set_today(monkeypatch, day):
    monkeypatch.setattr(clock, "business_today", lambda: day)


def add_task(client, project_id, title, due, state="todo"):
    response = client.post(f"{API}/projects/{project_id}/tasks", json={"title": title, "due_date": due, "task_state": state})
    assert response.status_code == 201, response.text
    return response.json()


def test_project_task_and_visit_events_with_state_transitions(client, monkeypatch):
    project = make_project(client, "Takvim Projesi")
    pid = project["id"]
    done = add_task(client, pid, "Bitmiş iş", "2026-03-05", "done")
    overdue = add_task(client, pid, "Geciken iş", "2026-03-05")
    now = add_task(client, pid, "Bugünkü iş", "2026-03-10")
    later = add_task(client, pid, "Gelecek iş", "2026-03-12")
    states = {e["source_id"]: e["state"] for e in by_type(client, "project_task")}
    assert states == {done["id"]: "completed", overdue["id"]: "overdue", now["id"]: "today", later["id"]: "upcoming"}
    sample = next(e for e in by_type(client, "project_task") if e["source_id"] == now["id"])
    assert sample["event_id"] == f"project_task:{now['id']}:2026-03-10"
    assert sample["project_id"] == pid and sample["source_route"]["entity"] == "project_task"
    assert sample["notification_defaults"] == {"enabled": True, "offsets_days": [1], "is_financial": False}
    assert sample["description"] == "Takvim Projesi – iş vadesi" and sample["all_day"] is True

    # upcoming -> today -> overdue, yalnız iş tarihi değişerek.
    set_today(monkeypatch, date(2026, 3, 11))
    assert {e["source_id"]: e["state"] for e in by_type(client, "project_task")}[later["id"]] == "upcoming"
    set_today(monkeypatch, date(2026, 3, 12))
    assert {e["source_id"]: e["state"] for e in by_type(client, "project_task")}[later["id"]] == "today"
    set_today(monkeypatch, date(2026, 3, 13))
    assert {e["source_id"]: e["state"] for e in by_type(client, "project_task")}[later["id"]] == "overdue"

    visits = {}
    for state, day in (("planned", "2026-03-14"), ("completed", "2026-03-04"), ("cancelled", "2026-03-20")):
        visits[state] = client.post(f"{API}/projects/{pid}/visits", json={"visit_date": day, "purpose": f"Ziyaret {state}", "visit_state": state}).json()["id"]
    set_today(monkeypatch, TODAY)
    got = {e["source_id"]: e for e in by_type(client, "project_visit")}
    assert got[visits["planned"]]["state"] == "upcoming" and got[visits["planned"]]["title"] == "Ziyaret: Ziyaret planned"
    assert got[visits["completed"]]["state"] == "completed" and got[visits["cancelled"]]["state"] == "cancelled"


def test_source_change_does_not_leave_duplicate_events(client):
    project = make_project(client)
    task = add_task(client, project["id"], "Taşınan iş", "2026-03-12")
    assert len(by_type(client, "project_task")) == 1
    client.patch(f"{API}/project-tasks/{task['id']}", json={"task_state": "done"})
    only = by_type(client, "project_task")
    assert len(only) == 1 and only[0]["state"] == "completed"
    # Alacak planının vadesi değişince eski vade olayı kalmaz.
    cid = project["customer_id"]
    plan = schedule(client, cid, "Plan", 50_000, "2026-03-20")
    assert [e["start_date"] for e in by_type(client, "receivable_due")] == ["2026-03-20"]
    client.patch(f"{API}/receivable-schedules/{plan['id']}", json={"due_date": "2026-03-25"})
    after = by_type(client, "receivable_due")
    assert [e["start_date"] for e in after] == ["2026-03-25"] and len(after) == 1
    assert after[0]["event_id"] == f"receivable_schedule:{plan['id']}:2026-03-25"


def test_receivable_schedule_events_amounts_and_states(client, monkeypatch):
    project = make_project(client, customer_name="Takvim Müşteri")
    cid = project["customer_id"]
    move(client, cid, "accrual", 100_000, "tahakkuk-cal-01", day="2026-03-01", project_id=project["id"])
    plan = schedule(client, cid, "Peşinat", 100_000, "2026-03-20", project_id=project["id"])
    event = by_type(client, "receivable_due")[0]
    assert (event["amount_kurus"], event["state"], event["customer_id"], event["project_id"]) == (
        100_000, "upcoming", cid, project["id"]
    )
    assert event["notification_defaults"]["offsets_days"] == [0, 1] and event["notification_defaults"]["is_financial"] is True

    move(client, cid, "collection", 30_000, "tahsilat-cal-01", day="2026-03-05", receivable_schedule_id=plan["id"])
    partial = by_type(client, "receivable_due")[0]
    assert partial["amount_kurus"] == 70_000 and partial["planned_amount_kurus"] == 100_000

    set_today(monkeypatch, date(2026, 3, 25))
    assert by_type(client, "receivable_due")[0]["state"] == "overdue"
    set_today(monkeypatch, TODAY)
    move(client, cid, "collection", 70_000, "tahsilat-cal-02", day="2026-03-06", receivable_schedule_id=plan["id"])
    paid = by_type(client, "receivable_due")[0]
    assert (paid["state"], paid["amount_kurus"]) == ("completed", 100_000)

    cancelled = schedule(client, cid, "İptal plan", 10_000, "2026-03-22")
    client.post(f"{API}/receivable-schedules/{cancelled['id']}/cancel")
    undated = client.post(f"{API}/receivable-schedules", json={"customer_id": cid, "title": "Vadesiz", "amount_kurus": 5_000})
    assert undated.status_code == 201
    assert [e["source_id"] for e in by_type(client, "receivable_due")] == [plan["id"]]


def test_supplier_payable_events(client, monkeypatch):
    supplier, material = make_supplier(client), make_material(client)
    purchase = make_purchase(client, supplier, material, None, 200_000, "pur-cal-0001", due_date="2026-03-15")
    planned = make_purchase(client, supplier, material, None, 90_000, "pur-cal-0002", state="planned", due_date="2026-03-16")
    no_due = make_purchase(client, supplier, material, None, 10_000, "pur-cal-0003")
    got = by_type(client, "supplier_payable")
    assert [e["source_id"] for e in got] == [purchase["id"]]  # planlı borç sayılmaz, vadesiz yok
    assert (got[0]["amount_kurus"], got[0]["state"], got[0]["supplier_id"]) == (200_000, "upcoming", supplier["id"])
    assert planned["id"] != no_due["id"]

    client.post(f"{API}/payments", json={"supplier_id": supplier["id"], "purchase_id": purchase["id"], "payment_date": "2026-03-08", "amount_kurus": 50_000, "idempotency_key": "pay-cal-00001"})
    assert by_type(client, "supplier_payable")[0]["amount_kurus"] == 150_000
    set_today(monkeypatch, date(2026, 3, 20))
    assert by_type(client, "supplier_payable")[0]["state"] == "overdue"
    set_today(monkeypatch, TODAY)
    client.post(f"{API}/payments", json={"supplier_id": supplier["id"], "purchase_id": purchase["id"], "payment_date": "2026-03-09", "amount_kurus": 150_000, "idempotency_key": "pay-cal-00002"})
    paid = by_type(client, "supplier_payable")[0]
    assert (paid["state"], paid["amount_kurus"]) == ("completed", 200_000)


def test_payroll_due_events_use_derived_salary_day_and_remaining_debt(client):
    worker = make_employee(client, "Maaşlı Usta", "daily", 80000)
    for day in ("2026-02-02", "2026-02-03"):
        log_work(client, worker["id"], day)
    client.put(f"{API}/settings/attendance", json={"default_salary_day": 5})
    period = client.post(f"{API}/payroll-periods", json={"period_start": "2026-02-01", "period_end": "2026-02-28"}).json()
    client.post(f"{API}/payroll-periods/{period['id']}/calculate", json={})
    assert client.post(f"{API}/payroll-periods/{period['id']}/finalize", json={}).status_code == 200

    got = by_type(client, "payroll_due")
    assert len(got) == 1
    event = got[0]
    assert (event["start_date"], event["amount_kurus"], event["employee_id"]) == ("2026-03-05", 160_000, worker["id"])
    assert event["state"] == "overdue"  # vade 5 Mart, bugün 10 Mart
    assert event["payroll_period_id"] == period["id"]

    pay = client.post(
        f"{API}/employee-finance/movements",
        json={"employee_id": worker["id"], "payroll_period_id": period["id"], "movement_date": "2026-03-06",
              "movement_type": "payroll_payment", "amount_kurus": 100_000, "idempotency_key": "maas-ode-000001"},
    )
    assert pay.status_code == 201, pay.text
    assert by_type(client, "payroll_due")[0]["amount_kurus"] == 60_000  # kalan maaş borcu
    client.post(
        f"{API}/employee-finance/movements",
        json={"employee_id": worker["id"], "payroll_period_id": period["id"], "movement_date": "2026-03-07",
              "movement_type": "payroll_payment", "amount_kurus": 60_000, "idempotency_key": "maas-ode-000002"},
    )
    done = by_type(client, "payroll_due")[0]
    assert (done["state"], done["amount_kurus"]) == ("completed", 160_000)


def test_approved_leave_and_return_events(client):
    worker = make_employee(client, "İzinli Usta", "daily", 80000)

    def request(start, end, key):
        created = client.post(
            f"{API}/leave-requests",
            json={"employee_id": worker["id"], "leave_type_code": "other_paid", "start_date": start, "end_date": end, "idempotency_key": key},
        ).json()
        return created["id"]

    pending = request("2026-03-23", "2026-03-24", "izin-cal-000001")
    assert by_type(client, "leave") == []  # onaysız izin takvimde yok
    friday = request("2026-03-13", "2026-03-14", "izin-cal-000002")  # Cum–Cts
    assert client.post(f"{API}/leave-requests/{friday}/approve").status_code == 200
    got = {e["event_type"]: e for e in events(client, "2026-03-01", "2026-03-31", employee_id=worker["id"])}
    assert (got["leave"]["start_date"], got["leave"]["end_date"], got["leave"]["state"]) == ("2026-03-13", "2026-03-14", "upcoming")
    assert got["leave_return"]["start_date"] == "2026-03-16"  # Pazar atlanır, Pazartesi dönüş
    assert got["leave"]["title"] == "İzin: İzinli Usta"
    client.post(f"{API}/holidays", json={"holiday_date": "2026-03-16", "name": "Tatil"})
    assert by_type(client, "leave_return")[0]["start_date"] == "2026-03-17"  # tatil de atlanır
    client.post(f"{API}/leave-requests/{friday}/cancel")
    assert by_type(client, "leave") == [] and by_type(client, "leave_return") == []
    assert pending


def test_recurring_manual_events_including_month_end(client):
    def create(**body):
        response = client.post(f"{API}/calendar/manual-events", json={"title": "Tekrarlı olay", **body})
        assert response.status_code == 201, response.text
        return response.json()

    monthly = create(start_date="2026-01-31", repeat_rule="monthly")
    dates = [e["start_date"] for e in events(client, "2026-01-01", "2026-04-30", event_type="manual_event")]
    assert dates == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]
    assert [e["start_date"] for e in events(client, "2026-03-01", "2026-04-30", event_type="manual_event")] == ["2026-03-31", "2026-04-30"]
    leap = create(start_date="2028-01-31", repeat_rule="monthly", title="Artık yıl")
    leap_dates = [e["start_date"] for e in events(client, "2028-01-01", "2028-03-31", event_type="manual_event") if e["source_id"] == leap["id"]]
    assert leap_dates == ["2028-01-31", "2028-02-29", "2028-03-31"]
    client.post(f"{API}/calendar/manual-events/{monthly['id']}/cancel")
    client.post(f"{API}/calendar/manual-events/{leap['id']}/cancel")

    weekly = create(start_date="2026-03-02", repeat_rule="weekly", repeat_until="2026-03-23")
    assert [e["start_date"] for e in events(client, "2026-03-01", "2026-04-30", event_type="manual_event")] == [
        "2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"
    ]
    assert [e["start_date"] for e in events(client, "2026-03-10", "2026-03-20", event_type="manual_event")] == ["2026-03-16"]
    daily = create(start_date="2026-03-08", repeat_rule="daily", repeat_until="2026-03-10", title="Günlük")
    assert len([e for e in events(client, "2026-03-01", "2026-03-31", event_type="manual_event") if e["source_id"] == daily["id"]]) == 3
    # Sonsuz satır yazılmaz: yalnız olayın kendisi saklanır.
    assert len(client.get(f"{API}/calendar/manual-events").json()) == 2
    assert weekly["id"]
    one = create(start_date="2026-03-12", end_date="2026-03-14", title="Fuar", event_type="reminder")
    fair = next(e for e in events(client, "2026-03-01", "2026-03-31", event_type="reminder"))
    assert (fair["start_date"], fair["end_date"], fair["source_id"]) == ("2026-03-12", "2026-03-14", one["id"])


def test_complete_postpone_and_cancel_occurrences(client, monkeypatch):
    series = client.post(
        f"{API}/calendar/manual-events",
        json={"title": "Haftalık kontrol", "start_date": "2026-03-02", "repeat_rule": "weekly", "amount_kurus": 5000},
    ).json()
    base = f"{API}/calendar/manual-events/{series['id']}"
    assert client.post(f"{base}/complete").status_code == 422  # tekrarlıda tarih zorunlu
    assert client.post(f"{base}/complete", json={"occurrence_date": "2026-03-03"}).json()["error"]["code"] == "not_an_occurrence"

    assert client.post(f"{base}/complete", json={"occurrence_date": "2026-03-02"}).status_code == 200
    again = client.post(f"{base}/complete", json={"occurrence_date": "2026-03-02"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "occurrence_closed"
    got = {e["event_id"]: e for e in events(client, "2026-03-01", "2026-03-31", event_type="manual_event")}
    assert got[f"manual_event:{series['id']}:2026-03-02"]["state"] == "completed"
    assert got[f"manual_event:{series['id']}:2026-03-09"]["state"] == "overdue"  # bugün 10 Mart
    assert got[f"manual_event:{series['id']}:2026-03-16"]["state"] == "upcoming"

    moved = client.post(f"{base}/postpone", json={"occurrence_date": "2026-03-16", "new_date": "2026-03-19"})
    assert moved.status_code == 200 and moved.json()["start_date"] == "2026-03-19"
    stale = client.post(f"{base}/postpone", json={"occurrence_date": "2026-03-16", "new_date": "2026-03-19"})
    assert stale.status_code == 422 and stale.json()["error"]["code"] == "invalid_postpone_date"
    after = {e["event_id"]: e for e in events(client, "2026-03-01", "2026-03-31", event_type="manual_event")}
    postponed = after[f"manual_event:{series['id']}:2026-03-16"]
    assert (postponed["start_date"], postponed["original_date"], postponed["amount_kurus"]) == ("2026-03-19", "2026-03-16", 5000)
    assert len([e for e in after.values() if e["original_date"] == "2026-03-16"]) == 1  # kopya yok
    # Yalnız yeni tarihi içeren aralıkta da görünür.
    assert [e["original_date"] for e in events(client, "2026-03-18", "2026-03-20", event_type="manual_event")] == ["2026-03-16"]
    assert client.post(f"{base}/postpone", json={"occurrence_date": "2026-03-16", "new_date": "2026-03-26"}).status_code == 200
    set_today(monkeypatch, date(2026, 3, 27))
    assert next(e for e in events(client, "2026-03-20", "2026-03-31", event_type="manual_event") if e["original_date"] == "2026-03-16")["state"] == "overdue"
    set_today(monkeypatch, TODAY)

    assert client.post(f"{base}/cancel", json={"occurrence_date": "2026-03-23"}).json()["scope"] == "occurrence"
    states = {e["start_date"]: e["state"] for e in events(client, "2026-03-20", "2026-03-31", event_type="manual_event")}
    assert states["2026-03-23"] == "cancelled" and states["2026-03-30"] == "upcoming"
    assert client.post(f"{base}/cancel").json()["scope"] == "series"
    assert events(client, "2026-03-01", "2026-03-31", event_type="manual_event") == []
    assert client.post(f"{base}/complete", json={"occurrence_date": "2026-03-30"}).json()["error"]["code"] == "event_cancelled"
    once = client.post(f"{API}/calendar/manual-events", json={"title": "Tek seferlik", "start_date": "2026-03-15"}).json()
    done = client.post(f"{API}/calendar/manual-events/{once['id']}/complete")
    assert done.status_code == 200 and done.json()["state"] == "completed"


def test_manual_event_validation_and_patch(client):
    base = {"title": "Doğrulama"}
    for bad in (
        {"start_date": "2026-03-10", "end_date": "2026-03-09"},
        {"start_date": "2026-03-10", "repeat_until": "2026-03-20"},
        {"start_date": "2026-03-10", "repeat_rule": "weekly", "repeat_until": "2026-03-01"},
        {"start_date": "2026-03-10", "start_time": "10:00"},
        {"start_date": "2026-03-10", "all_day": False, "start_time": "25:00"},
        {"start_date": "2026-03-10", "repeat_rule": "yearly"},
    ):
        assert client.post(f"{API}/calendar/manual-events", json={**base, **bad}).status_code == 422, bad
    assert client.post(f"{API}/calendar/manual-events", json={**base, "start_date": "2026-03-10", "project_id": "yok"}).status_code == 404
    timed = client.post(f"{API}/calendar/manual-events", json={**base, "start_date": "2026-03-10", "all_day": False, "start_time": "09:30"})
    assert timed.status_code == 201
    event = timed.json()
    patched = client.patch(f"{API}/calendar/manual-events/{event['id']}", json={"title": "Yeni başlık", "repeat_rule": "daily"})
    assert patched.status_code == 200 and patched.json()["repeat_rule"] == "daily"
    assert client.patch(f"{API}/calendar/manual-events/{event['id']}", json={}).status_code == 422
    bad_patch = client.patch(f"{API}/calendar/manual-events/{event['id']}", json={"repeat_until": "2026-03-01"})
    assert bad_patch.status_code == 422
    client.post(f"{API}/calendar/manual-events/{event['id']}/complete", json={"occurrence_date": "2026-03-10"})
    locked = client.patch(f"{API}/calendar/manual-events/{event['id']}", json={"repeat_rule": "weekly"})
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "event_has_history"
    assert client.patch(f"{API}/calendar/manual-events/{event['id']}", json={"title": "Hâlâ düzenlenebilir"}).status_code == 200
    assert client.get(f"{API}/calendar/manual-events/yok").status_code == 404
    shown = events(client, "2026-03-10", "2026-03-10", event_type="manual_event")
    assert shown[0]["start_time"] == "09:30" and shown[0]["all_day"] is False


def test_calendar_filters_and_range_validation(client):
    first, second = make_project(client, "Birinci Proje"), make_project(client, "İkinci Proje", customer_name="Başka")
    add_task(client, first["id"], "A işi", "2026-03-12")
    add_task(client, second["id"], "B işi", "2026-03-13", "done")
    worker = make_employee(client, "Filtre Usta")
    client.post(f"{API}/calendar/manual-events", json={"title": "Personel olayı", "start_date": "2026-03-14", "employee_id": worker["id"]})
    assert [e["title"] for e in events(client, project_id=first["id"])] == ["A işi"]
    assert [e["title"] for e in events(client, employee_id=worker["id"])] == ["Personel olayı"]
    assert [e["title"] for e in events(client, state="completed")] == ["B işi"]
    assert len(events(client, event_type="project_task")) == 2
    assert [e["start_date"] for e in events(client, "2026-03-13", "2026-03-13")] == ["2026-03-13"]
    assert client.get(f"{API}/calendar/events", params={"date_from": "2026-03-10", "date_to": "2026-03-01"}).json()["error"]["code"] == "invalid_range"
    assert client.get(f"{API}/calendar/events", params={"date_from": "2025-01-01", "date_to": "2026-12-31"}).json()["error"]["code"] == "range_too_large"
    assert client.get(f"{API}/calendar/events", params={"date_from": "2026-03-01", "date_to": "2026-03-02", "event_type": "bilinmeyen"}).status_code == 422


def test_today_groups_totals_and_recurring_manual_do_not_pile_up(client):
    project = make_project(client, customer_name="Bugün Müşteri")
    cid = project["customer_id"]
    add_task(client, project["id"], "Geciken iş", "2026-03-01")
    client.post(f"{API}/projects/{project['id']}/visits", json={"visit_date": "2026-03-10", "purpose": "Keşif"})
    move(client, cid, "accrual", 100_000, "tahakkuk-today-1", day="2026-03-01")
    schedule(client, cid, "Gecikmiş tahsilat", 40_000, "2026-03-05")
    schedule(client, cid, "Yaklaşan tahsilat", 25_000, "2026-03-14")
    schedule(client, cid, "Uzak tahsilat", 99_000, "2026-03-25")
    supplier, material = make_supplier(client), make_material(client)
    make_purchase(client, supplier, material, None, 70_000, "pur-today-0001", due_date="2026-03-10")
    client.post(f"{API}/calendar/manual-events", json={"title": "Günlük hatırlatma", "start_date": "2025-01-01", "repeat_rule": "daily", "event_type": "reminder"})
    client.post(f"{API}/calendar/manual-events", json={"title": "Eski tek seferlik", "start_date": "2026-01-15"})

    view = client.get(f"{API}/today").json()
    assert view["as_of"] == "2026-03-10"
    titles = lambda group: {e["title"] for e in view[group]["events"]}
    assert "Geciken iş" in titles("overdue") and "Eski tek seferlik" in titles("overdue")
    assert "Tahsilat vadesi: Bugün Müşteri – Gecikmiş tahsilat" in titles("overdue")
    assert {"Keşif"} <= {t.split(": ", 1)[-1] for t in titles("today")}
    assert any(t.startswith("Ödeme vadesi") for t in titles("today"))
    assert "Tahsilat vadesi: Bugün Müşteri – Yaklaşan tahsilat" in titles("next_7_days")
    assert not any("Uzak tahsilat" in t for g in ("overdue", "today", "next_7_days") for t in titles(g))
    # Tekrarlı günlük hatırlatma: geçmişten yığılmaz (son 7 gün + bugün + 7 gün ileri).
    reminders = [e for g in ("overdue", "today", "next_7_days") for e in view[g]["events"] if e["event_type"] == "reminder"]
    assert len(reminders) == 7 + 1 + 7
    assert view["overdue"]["receivable_kurus"] == 40_000 and view["today"]["payable_kurus"] == 70_000
    assert view["next_7_days"]["receivable_kurus"] == 25_000
    assert view["totals"]["amount_kurus"] == sum(view[g]["amount_kurus"] for g in ("overdue", "today", "next_7_days"))
    assert view["totals"]["count"] == sum(view[g]["count"] for g in ("overdue", "today", "next_7_days"))


def due(client):
    response = client.get(f"{API}/notifications/due")
    assert response.status_code == 200, response.text
    return response.json()["notifications"]


def test_notification_offsets_dedup_and_overdue_silence(client, monkeypatch):
    project = make_project(client, customer_name="Bildirim Müşteri")
    cid = project["customer_id"]
    task = add_task(client, project["id"], "Bildirimli iş", "2026-03-12")
    move(client, cid, "accrual", 100_000, "tahakkuk-bil-001", day="2026-03-01")
    plan = schedule(client, cid, "Bildirimli plan", 100_000, "2026-03-12")

    assert due(client) == []  # 10 Mart: henüz erken
    set_today(monkeypatch, date(2026, 3, 11))
    first = due(client)
    kinds = {(n["event"]["source_id"], n["offset_days"]) for n in first}
    assert kinds == {(task["id"], 1), (plan["id"], 1)}  # finansal ve diğer: bir gün önce
    key = next(n["delivery_key"] for n in first if n["event"]["source_id"] == plan["id"])
    assert key == f"receivable_schedule:{plan['id']}:2026-03-12|2026-03-12|1|windows"
    delivered = client.post(f"{API}/notifications/delivered", json={"delivery_key": key})
    assert delivered.status_code == 200 and delivered.json()["already_delivered"] is False
    again = client.post(f"{API}/notifications/delivered", json={"delivery_key": key})
    assert again.json()["already_delivered"] is True
    assert {n["delivery_key"] for n in due(client)} == {n["delivery_key"] for n in first} - {key}

    set_today(monkeypatch, date(2026, 3, 12))
    day_of = {(n["event"]["source_id"], n["offset_days"]) for n in due(client)}
    assert (plan["id"], 0) in day_of  # vade günü
    assert (plan["id"], 1) not in day_of  # teslim edilen tekrar gelmez
    assert (task["id"], 1) in day_of  # kaçırılan bir gün öncesi olay gününe kadar yakalanır
    assert (task["id"], 0) not in day_of  # görev yalnız bir gün önce bildirir

    # Gecikmiş olay yeni bildirim üretmez; her gün tekrarlanmaz.
    set_today(monkeypatch, date(2026, 3, 13))
    assert due(client) == []
    set_today(monkeypatch, date(2026, 3, 20))
    assert due(client) == []
    assert len(client.get(f"{API}/today").json()["overdue"]["events"]) >= 2


def test_notifications_skip_completed_and_respect_preferences(client, monkeypatch):
    project = make_project(client)
    done = add_task(client, project["id"], "Biten iş", "2026-03-11", "done")
    todo = add_task(client, project["id"], "Yapılacak iş", "2026-03-11")
    set_today(monkeypatch, date(2026, 3, 10))
    assert {n["event"]["source_id"] for n in due(client)} == {todo["id"]}
    assert done["id"] not in {n["event"]["source_id"] for n in due(client)}

    prefs = client.get(f"{API}/calendar/reminder-preferences").json()
    assert prefs["channels"] == ["windows"]
    by = {p["event_type"]: p for p in prefs["preferences"]}
    assert by["receivable_due"]["offsets_days"] == [0, 1] and by["project_task"]["offsets_days"] == [1]
    assert all(p["is_default"] for p in by.values())

    off = client.put(f"{API}/calendar/reminder-preferences", json={"items": [{"event_type": "project_task", "enabled": False, "offsets_days": [1]}]})
    assert off.status_code == 200
    assert due(client) == []
    custom = client.put(f"{API}/calendar/reminder-preferences", json={"items": [{"event_type": "project_task", "enabled": True, "offsets_days": [3, 1, 0]}]})
    assert {p["event_type"]: p for p in custom.json()["preferences"]}["project_task"]["offsets_days"] == [0, 1, 3]
    assert {n["offset_days"] for n in due(client)} == {1, 3}  # 3 gün öncesi için de vade yaklaştı
    assert next(e for e in events(client, "2026-03-11", "2026-03-11") if e["source_id"] == todo["id"])["notification_defaults"]["offsets_days"] == [0, 1, 3]
    for bad in (
        {"items": []},
        {"items": [{"event_type": "project_task", "enabled": True, "offsets_days": []}]},
        {"items": [{"event_type": "project_task", "enabled": True, "offsets_days": [1, 1]}]},
        {"items": [{"event_type": "project_task", "enabled": True, "offsets_days": [31]}]},
        {"items": [{"event_type": "bilinmeyen", "enabled": True, "offsets_days": [1]}]},
        {"items": [{"event_type": "reminder", "offsets_days": [1]}, {"event_type": "reminder", "offsets_days": [2]}]},
    ):
        assert client.put(f"{API}/calendar/reminder-preferences", json=bad).status_code == 422, bad


def test_delivery_endpoint_is_narrow_and_validated(client, monkeypatch):
    project = make_project(client)
    task = add_task(client, project["id"], "Teslim işi", "2026-03-11")
    set_today(monkeypatch, date(2026, 3, 10))
    key = due(client)[0]["delivery_key"]
    assert client.post(f"{API}/notifications/delivered", json={"delivery_key": "bozuk-anahtar-yok"}).json()["error"]["code"] == "invalid_delivery_key"
    assert client.post(f"{API}/notifications/delivered", json={"delivery_key": f"project_task:{task['id']}:2026-03-11|2026-03-11|1|sms"}).status_code == 422
    unknown = client.post(f"{API}/notifications/delivered", json={"delivery_key": "project_task:yok:2026-03-11|2026-03-11|1|windows"})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "event_not_found"
    wrong_offset = client.post(f"{API}/notifications/delivered", json={"delivery_key": f"project_task:{task['id']}:2026-03-11|2026-03-11|5|windows"})
    assert wrong_offset.status_code == 422 and wrong_offset.json()["error"]["code"] == "invalid_offset"
    assert client.post(f"{API}/notifications/delivered", json={"delivery_key": key}).status_code == 200
    assert due(client) == []
