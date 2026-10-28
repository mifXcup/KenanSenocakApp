from __future__ import annotations

from datetime import date

from finance_helpers import allocate, move, schedule
from helpers import make_project
from sqlalchemy import func, select

from ks_yonetim import clock
from ks_yonetim.database import SessionLocal
from ks_yonetim.models import AuditLog

API = "/api/v1"


def new_customer(client, name="Kenan Yapı"):
    response = client.post(f"{API}/customers", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def detail(client, cid):
    return client.get(f"{API}/customers/{cid}").json()


def schedule_states(client, cid, as_of="2026-03-01"):
    rows = client.get(
        f"{API}/receivable-schedules", params={"customer_id": cid, "as_of": as_of}
    ).json()
    return {r["title"]: (r["payment_state"], r["paid_kurus"], r["remaining_kurus"]) for r in rows}


def test_deposit_before_any_accrual_is_customer_credit(client):
    cid = new_customer(client)
    deposit = move(client, cid, "collection", 200_000, "kapora-000001")
    assert deposit.status_code == 201
    assert deposit.json()["allocated_kurus"] == 0 and deposit.json()["unallocated_kurus"] == 200_000

    summary = detail(client, cid)
    assert summary["receivable_kurus"] == 0
    assert summary["credit_kurus"] == 200_000
    assert summary["net_balance_kurus"] == -200_000 == summary["balance_kurus"]
    assert summary["unallocated_collection_kurus"] == 200_000

    aging = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-03-01"}).json()
    assert aging["advance_kurus"] == 200_000 and aging["overdue_kurus"] == 0
    assert aging["open_receivable_kurus"] == 0

    # Tahakkuk sonradan oluşunca avans otomatik mahsup olur.
    assert move(client, cid, "accrual", 500_000, "tahakkuk-00001", day="2026-02-01").status_code == 201
    after = detail(client, cid)
    assert (after["receivable_kurus"], after["credit_kurus"]) == (300_000, 0)
    stmt = client.get(f"{API}/customers/{cid}/statement").json()
    assert [r["balance_kurus"] for r in stmt["rows"]] == [-200_000, 300_000]
    assert stmt["closing_receivable_kurus"] == 300_000 and stmt["closing_credit_kurus"] == 0


def test_collection_above_open_receivable_is_accepted_and_overcollection_is_gone(client):
    cid = new_customer(client)
    move(client, cid, "accrual", 100_000, "tahakkuk-00002")
    over = move(client, cid, "collection", 150_000, "tahsilat-00002")
    assert over.status_code == 201
    summary = detail(client, cid)
    assert (summary["receivable_kurus"], summary["credit_kurus"]) == (0, 50_000)
    assert "overcollection" not in over.text

    # Fazla tahsilatın iadesi avansı kapatır; iade net tahsilatı aşamaz.
    assert move(client, cid, "refund", 160_000, "iade-0000002").status_code == 409
    assert move(client, cid, "refund", 50_000, "iade-0000003").status_code == 201
    final = detail(client, cid)
    assert (final["receivable_kurus"], final["credit_kurus"]) == (0, 0)


def test_collection_linked_to_small_schedule_keeps_remainder_unallocated(client):
    cid = new_customer(client)
    move(client, cid, "accrual", 100_000, "tahakkuk-00003")
    plan = schedule(client, cid, "Peşinat", 60_000, "2026-02-01")
    paid = move(
        client, cid, "collection", 90_000, "tahsilat-00003", receivable_schedule_id=plan["id"]
    )
    assert paid.status_code == 201
    assert paid.json()["allocated_kurus"] == 60_000 and paid.json()["unallocated_kurus"] == 30_000
    assert schedule_states(client, cid)["Peşinat"] == ("paid", 60_000, 0)
    assert detail(client, cid)["unallocated_collection_kurus"] == 30_000


def test_many_to_many_allocation_partial_and_remaining(client):
    cid = new_customer(client)
    first = schedule(client, cid, "Plan A", 60_000, "2026-02-01")
    second = schedule(client, cid, "Plan B", 40_000, "2026-03-01")
    c1 = move(client, cid, "collection", 80_000, "tahsilat-00004").json()
    c2 = move(client, cid, "collection", 30_000, "tahsilat-00005", day="2026-01-20").json()
    assert detail(client, cid)["unallocated_collection_kurus"] == 110_000

    # Bir tahsilat birden fazla plana, bir plan birden fazla tahsilata dağıtılır.
    assert allocate(client, c1["id"], first["id"], 50_000, "dagit-0000001").status_code == 201
    assert allocate(client, c1["id"], second["id"], 30_000, "dagit-0000002").status_code == 201
    assert allocate(client, c2["id"], first["id"], 10_000, "dagit-0000003").status_code == 201
    states = schedule_states(client, cid, as_of="2026-02-15")
    assert states["Plan A"] == ("paid", 60_000, 0)
    assert states["Plan B"] == ("partial", 30_000, 10_000)
    assert detail(client, cid)["unallocated_collection_kurus"] == 20_000

    listed = {c["id"]: c for c in client.get(f"{API}/customer-financial-movements").json()}
    assert listed[c1["id"]]["allocated_kurus"] == 80_000 and listed[c1["id"]]["unallocated_kurus"] == 0
    assert listed[c2["id"]]["unallocated_kurus"] == 20_000

    # Sınırlar: tahsilatın dağıtılmamış tutarı ve planın kalanı.
    too_big = allocate(client, c2["id"], second["id"], 25_000, "dagit-0000004")
    assert too_big.status_code == 409
    assert too_big.json()["error"]["code"] == "allocation_exceeds_collection"
    assert too_big.json()["error"]["details"]["unallocated_kurus"] == 20_000
    over_plan = allocate(client, c2["id"], first["id"], 1, "dagit-0000005")
    assert over_plan.status_code == 409
    assert over_plan.json()["error"]["code"] == "allocation_exceeds_schedule"
    assert allocate(client, c2["id"], second["id"], 10_000, "dagit-0000006").status_code == 201
    assert schedule_states(client, cid, as_of="2026-02-15")["Plan B"][0] == "paid"

    # Aynı anahtar aynı kaydı döner, farklı gövde çakışır.
    again = allocate(client, c1["id"], first["id"], 50_000, "dagit-0000001")
    assert again.status_code == 201
    conflict = allocate(client, c1["id"], first["id"], 1, "dagit-0000001")
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def test_allocation_cancel_is_soft_and_audited(client):
    cid = new_customer(client)
    plan = schedule(client, cid, "Plan", 50_000, "2026-02-01")
    col = move(client, cid, "collection", 50_000, "tahsilat-00006").json()
    alloc = allocate(client, col["id"], plan["id"], 50_000, "dagit-0000007").json()
    assert schedule_states(client, cid)["Plan"][0] == "paid"

    blocked = client.post(f"{API}/receivable-schedules/{plan['id']}/cancel")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "schedule_has_allocations"

    cancelled = client.post(
        f"{API}/customer-payment-allocations/{alloc['id']}/cancel", json={"reason": "Yanlış plan"}
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"] == "Yanlış plan"
    assert client.post(f"{API}/customer-payment-allocations/{alloc['id']}/cancel").status_code == 409
    assert schedule_states(client, cid, as_of="2026-01-01")["Plan"][0] == "open"
    assert detail(client, cid)["unallocated_collection_kurus"] == 50_000

    # Fiziksel silme yok: iptal edilen satır geçmişte durur.
    assert client.get(f"{API}/customer-payment-allocations", params={"customer_id": cid}).json() == []
    history = client.get(
        f"{API}/customer-payment-allocations", params={"customer_id": cid, "include_cancelled": True}
    ).json()
    assert [h["status"] for h in history] == ["cancelled"]
    with SessionLocal() as session:
        audited = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "customer_payment_allocation",
                AuditLog.entity_id == alloc["id"],
                AuditLog.action == "cancelled",
            )
        )
    assert audited == 1
    # İptalden sonra plan iptal edilebilir ve dağıtım yeniden yapılabilir.
    assert allocate(client, col["id"], plan["id"], 20_000, "dagit-0000008").status_code == 201


def test_collection_reversal_cancels_active_allocations_atomically(client):
    cid = new_customer(client)
    plan_a = schedule(client, cid, "Plan A", 30_000, "2026-02-01")
    plan_b = schedule(client, cid, "Plan B", 30_000, "2026-03-01")
    col = move(client, cid, "collection", 50_000, "tahsilat-00007").json()
    assert allocate(client, col["id"], plan_a["id"], 30_000, "dagit-0000009").status_code == 201
    assert allocate(client, col["id"], plan_b["id"], 20_000, "dagit-0000010").status_code == 201

    reverse = client.post(f"{API}/customer-financial-movements/{col['id']}/reverse")
    assert reverse.status_code == 201
    states = schedule_states(client, cid, as_of="2026-01-01")
    assert states["Plan A"][0] == "open" and states["Plan B"][0] == "open"
    assert client.get(f"{API}/customer-payment-allocations", params={"customer_id": cid}).json() == []
    cancelled = client.get(
        f"{API}/customer-payment-allocations", params={"customer_id": cid, "include_cancelled": True}
    ).json()
    assert len(cancelled) == 2
    assert {c["cancel_reason"] for c in cancelled} == {"Tahsilat ters kaydı"}
    with SessionLocal() as session:
        events = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "customer_payment_allocation", AuditLog.action == "cancelled"
            )
        )
    assert events == 2
    # Terslenmiş tahsilat yeniden dağıtılamaz.
    again = allocate(client, col["id"], plan_a["id"], 1_000, "dagit-0000011")
    assert again.status_code == 409 and again.json()["error"]["code"] == "collection_reversed"
    assert detail(client, cid)["net_balance_kurus"] == 0


def test_aging_keeps_advance_apart_from_overdue(client):
    cid = new_customer(client)
    plan = schedule(client, cid, "Gecikmiş plan", 50_000, "2026-01-15")
    col = move(client, cid, "collection", 30_000, "tahsilat-00008", day="2026-01-05").json()
    assert allocate(client, col["id"], plan["id"], 30_000, "dagit-0000012").status_code == 201
    aging = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-03-01"}).json()
    assert aging["advance_kurus"] == 30_000  # tahakkuk edilmemiş, mahsup bekleyen avans
    assert aging["overdue_kurus"] == 20_000
    assert {b["bucket"]: b["amount_kurus"] for b in aging["buckets"]}["31_60"] == 20_000
    assert aging["open_receivable_kurus"] == 20_000


def test_allocation_requires_open_customer_and_matching_schedule(client):
    cid = new_customer(client, "Müşteri Bir")
    other = new_customer(client, "Müşteri İki")
    col = move(client, cid, "collection", 10_000, "tahsilat-00009").json()
    foreign = schedule(client, other, "Yabancı plan", 10_000, "2026-02-01")
    mismatch = allocate(client, col["id"], foreign["id"], 10_000, "dagit-0000013")
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "schedule_customer_mismatch"
    cancelled = schedule(client, cid, "İptal", 10_000, "2026-02-01")
    client.post(f"{API}/receivable-schedules/{cancelled['id']}/cancel")
    gone = allocate(client, col["id"], cancelled["id"], 10_000, "dagit-0000014")
    assert gone.status_code == 409 and gone.json()["error"]["code"] == "schedule_cancelled"
    accrual = move(client, cid, "accrual", 1_000, "tahakkuk-00004").json()
    wrong = allocate(client, accrual["id"], cancelled["id"], 10, "dagit-0000015")
    assert wrong.status_code == 404
    client.post(f"{API}/customers/{cid}/archive")
    ok_plan = schedule(client, other, "Diğer", 10_000, "2026-02-01")
    archived = allocate(client, col["id"], ok_plan["id"], 10, "dagit-0000016")
    assert archived.status_code == 409 and archived.json()["error"]["code"] == "customer_archived"


def test_reversal_date_defaults_to_business_today_and_is_injectable(client, monkeypatch):
    project = make_project(client, customer_name="Tarih Müşteri")
    cid = project["customer_id"]
    move(client, cid, "accrual", 100_000, "tahakkuk-00005", day="2026-01-05")
    col = move(client, cid, "collection", 40_000, "tahsilat-00010", day="2026-01-15").json()

    reversal = client.post(f"{API}/customer-financial-movements/{col['id']}/reverse").json()
    assert reversal["movement_date"] == "2026-03-10"  # conftest iş tarihi

    explicit = move(client, cid, "collection", 10_000, "tahsilat-00011", day="2026-01-20").json()
    sent = client.post(
        f"{API}/customer-financial-movements/{explicit['id']}/reverse",
        json={"movement_date": "2026-04-01"},
    ).json()
    assert sent["movement_date"] == "2026-04-01"

    early = move(client, cid, "collection", 5_000, "tahsilat-00012", day="2026-02-10").json()
    rejected = client.post(
        f"{API}/customer-financial-movements/{early['id']}/reverse", json={"movement_date": "2026-02-01"}
    )
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "invalid_reversal_date"

    # Zaman enjekte edilir; gelecek tarihli hareket için varsayılan hareketin kendi tarihidir.
    monkeypatch.setattr(clock, "business_today", lambda: date(2026, 6, 1))
    future = move(client, cid, "collection", 1_000, "tahsilat-00013", day="2026-07-01").json()
    later = client.post(f"{API}/customer-financial-movements/{future['id']}/reverse").json()
    assert later["movement_date"] == "2026-07-01"
    normal = move(client, cid, "collection", 2_000, "tahsilat-00014", day="2026-05-01").json()
    assert client.post(
        f"{API}/customer-financial-movements/{normal['id']}/reverse"
    ).json()["movement_date"] == "2026-06-01"


def test_past_statements_do_not_change_after_late_reversal(client):
    cid = new_customer(client)
    move(client, cid, "accrual", 100_000, "tahakkuk-00006", day="2026-01-05")
    col = move(client, cid, "collection", 40_000, "tahsilat-00015", day="2026-01-15").json()
    january = client.get(f"{API}/customers/{cid}/statement", params={"date_to": "2026-01-31"}).json()
    before = [(r["movement_id"], r["balance_kurus"]) for r in january["rows"]]
    assert january["closing_balance_kurus"] == 60_000

    client.post(f"{API}/customer-financial-movements/{col['id']}/reverse")  # iş tarihi 2026-03-10
    again = client.get(f"{API}/customers/{cid}/statement", params={"date_to": "2026-01-31"}).json()
    assert [(r["movement_id"], r["balance_kurus"]) for r in again["rows"]] == before
    assert again["closing_balance_kurus"] == 60_000
    full = client.get(f"{API}/customers/{cid}/statement").json()
    assert full["closing_balance_kurus"] == 100_000
    assert full["rows"][-1]["movement_date"] == "2026-03-10"
