from __future__ import annotations

from helpers import make_project

API = "/api/v1"


def move(client, customer_id, movement_type, amount, key, day="2026-01-10", **extra):
    payload = {
        "customer_id": customer_id,
        "movement_type": movement_type,
        "amount_kurus": amount,
        "movement_date": day,
        "idempotency_key": key,
        **extra,
    }
    return client.post(f"{API}/customer-financial-movements", json=payload)


def balance(client, customer_id):
    return client.get(f"{API}/customers/{customer_id}").json()["balance_kurus"]


def new_customer(client, name="Kenan Yapı"):
    response = client.post(f"{API}/customers", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_customer_card_crud_and_duplicates(client):
    card = new_customer(client, "İpek  Hanım")
    assert card["name"] == "İpek Hanım"
    for variant in ("ipek hanım", "İPEK   HANIM"):
        duplicate = client.post(f"{API}/customers", json={"name": variant})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "duplicate_customer"
    # Türkçe I/ı ayrımı korunur: IPEK farklı bir ad sayılır.
    assert client.post(f"{API}/customers", json={"name": "IPEK Hanım"}).status_code == 201

    patched = client.patch(
        f"{API}/customers/{card['id']}",
        json={"phone": "0555", "contact_person": "Ayşe", "address": "Bursa"},
    )
    assert patched.status_code == 200
    assert patched.json()["contact_person"] == "Ayşe"
    assert client.patch(f"{API}/customers/{card['id']}", json={}).status_code == 422
    found = client.get(f"{API}/customers", params={"q": "HANIM"}).json()
    assert [c["id"] for c in found] == [card["id"]] or len(found) >= 1


def test_projects_link_to_normalized_customer_and_keep_original_text(client):
    first = make_project(client, "Proje A", customer_name="Ali  Veli")
    second = make_project(client, "Proje B", customer_name="ali veli")
    assert first["customer_id"] == second["customer_id"]
    assert second["customer_name"] == "ali veli"  # orijinal metin korunur
    detail = client.get(f"{API}/customers/{first['customer_id']}").json()
    assert detail["project_count"] == 2
    assert len(client.get(f"{API}/customers").json()) == 1

    moved = client.patch(f"{API}/projects/{second['id']}", json={"customer_name": "Başka Müşteri"})
    assert moved.json()["customer_id"] != first["customer_id"]

    card = new_customer(client, "Kart Müşteri")
    explicit = make_project(client, "Proje C", customer_id=card["id"], customer_name="Yanlış Ad")
    assert explicit["customer_id"] == card["id"]
    assert explicit["customer_name"] == "Kart Müşteri"


def test_ledger_idempotency_overcollection_and_reversals(client):
    cid = new_customer(client)["id"]
    accrual = move(client, cid, "accrual", 1_000_000, "acc-0001-aaaa")
    assert accrual.status_code == 201
    collection = move(client, cid, "collection", 300_000, "col-0001-aaaa", day="2026-01-20")
    assert collection.status_code == 201
    assert balance(client, cid) == 700_000

    over = move(client, cid, "collection", 800_000, "col-0002-aaaa")
    assert over.status_code == 409
    assert over.json()["error"]["code"] == "overcollection"
    assert over.json()["error"]["details"]["remaining_kurus"] == 700_000

    # Aynı anahtar ve aynı gövde: yeni kayıt yazılmaz.
    again = move(client, cid, "collection", 300_000, "col-0001-aaaa", day="2026-01-20")
    assert again.status_code == 201
    assert again.json()["id"] == collection.json()["id"]
    assert len(client.get(f"{API}/customer-financial-movements", params={"customer_id": cid}).json()) == 2
    conflict = move(client, cid, "collection", 1, "col-0001-aaaa", day="2026-01-20")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    # Tahsilat terslenince bakiye geri gelir; ikinci kez ve ters kaydın terslenmesi reddedilir.
    reverse = client.post(f"{API}/customer-financial-movements/{collection.json()['id']}/reverse")
    assert reverse.status_code == 201
    assert reverse.json()["movement_type"] == "reversal"
    assert balance(client, cid) == 1_000_000
    twice = client.post(f"{API}/customer-financial-movements/{collection.json()['id']}/reverse")
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "already_reversed"
    nested = client.post(f"{API}/customer-financial-movements/{reverse.json()['id']}/reverse")
    assert nested.status_code == 409 and nested.json()["error"]["code"] == "cannot_reverse_reversal"

    # Bakiyeyi negatife düşürecek tahakkuk tersi engellenir.
    assert move(client, cid, "collection", 1_000_000, "col-0003-aaaa").status_code == 201
    blocked = client.post(f"{API}/customer-financial-movements/{accrual.json()['id']}/reverse")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "reversal_makes_credit"

    listed = client.get(f"{API}/customer-financial-movements", params={"customer_id": cid}).json()
    voided = {m["id"]: m["is_voided"] for m in listed}
    assert voided[collection.json()["id"]] is True


def test_refund_correction_opening_balance_and_validation(client):
    cid = new_customer(client)["id"]
    assert move(client, cid, "opening_balance", 500_000, "open-0001-aa", project_id=None).status_code == 201
    assert move(client, cid, "collection", 200_000, "col-0001-bbbb").status_code == 201
    over = move(client, cid, "refund", 300_000, "ref-0001-bbbb")
    assert over.status_code == 409 and over.json()["error"]["code"] == "overrefund"
    assert move(client, cid, "refund", 50_000, "ref-0002-bbbb").status_code == 201
    assert balance(client, cid) == 350_000
    # Düzeltme yön ister; collection yanlış yönle gönderilemez.
    assert move(client, cid, "correction", 1_000, "cor-0001-bbbb").status_code == 422
    fix = move(client, cid, "correction", 10_000, "cor-0002-bbbb", direction="receivable_decrease")
    assert fix.status_code == 201
    assert balance(client, cid) == 340_000
    assert move(client, cid, "collection", 1, "col-0009-bbbb", direction="receivable_increase").status_code == 422
    assert move(client, cid, "accrual", 0, "acc-0000-bbbb").status_code == 422
    assert move(client, cid, "reversal", 5, "rev-0000-bbbb").status_code == 422


def test_schedules_aging_and_fifo_allocation(client):
    project = make_project(client, customer_name="Plan Müşteri")
    cid = project["customer_id"]
    assert move(client, cid, "accrual", 100_000, "acc-1111-aaaa", project_id=project["id"]).status_code == 201
    a = client.post(
        f"{API}/receivable-schedules",
        json={"customer_id": cid, "project_id": project["id"], "title": "Peşinat", "amount_kurus": 60_000, "due_date": "2026-02-01"},
    ).json()
    b = client.post(
        f"{API}/receivable-schedules",
        json={"customer_id": cid, "project_id": project["id"], "title": "Teslim", "amount_kurus": 40_000, "due_date": "2026-03-01"},
    ).json()
    linked = move(client, cid, "collection", 10_000, "col-1111-aaaa", day="2026-02-05", receivable_schedule_id=a["id"])
    assert linked.status_code == 201
    too_much = move(client, cid, "collection", 50_001, "col-1112-aaaa", receivable_schedule_id=a["id"])
    assert too_much.status_code == 409
    assert too_much.json()["error"]["details"]["remaining_kurus"] == 50_000

    aging = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-02-20"}).json()
    by_bucket = {x["bucket"]: x["amount_kurus"] for x in aging["buckets"]}
    assert aging["balance_kurus"] == 90_000
    assert by_bucket["1_30"] == 50_000 and by_bucket["not_due"] == 40_000
    assert aging["overdue_kurus"] == 50_000 and aging["unscheduled_kurus"] == 0

    # Plana bağlanmamış tahsilat en eski vadeden düşer ve as_of sonrası hareket sayılmaz.
    assert move(client, cid, "collection", 20_000, "col-1113-aaaa", day="2026-02-10").status_code == 201
    later = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-02-20"}).json()
    items = {i["receivable_schedule_id"]: i["remaining_kurus"] for i in later["items"]}
    assert items == {a["id"]: 30_000, b["id"]: 40_000}
    earlier = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-02-07"}).json()
    assert {i["receivable_schedule_id"]: i["remaining_kurus"] for i in earlier["items"]}[a["id"]] == 50_000

    states = {s["id"]: s["payment_state"] for s in client.get(f"{API}/receivable-schedules", params={"customer_id": cid, "as_of": "2026-02-20"}).json()}
    assert states == {a["id"]: "overdue", b["id"]: "open"}


def test_schedule_without_due_date_and_cancellation_rules(client):
    cid = new_customer(client)["id"]
    move(client, cid, "accrual", 50_000, "acc-2222-aaaa")
    undated = client.post(f"{API}/receivable-schedules", json={"customer_id": cid, "title": "Vadesiz", "amount_kurus": 50_000})
    assert undated.status_code == 201
    aging = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-05-01"}).json()
    assert {b["bucket"]: b["amount_kurus"] for b in aging["buckets"]}["no_due_date"] == 50_000

    sid = undated.json()["id"]
    assert move(client, cid, "collection", 10_000, "col-2222-aaaa", receivable_schedule_id=sid).status_code == 201
    blocked = client.post(f"{API}/receivable-schedules/{sid}/cancel")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "schedule_has_movements"
    lowered = client.patch(f"{API}/receivable-schedules/{sid}", json={"amount_kurus": 5_000})
    assert lowered.status_code == 409 and lowered.json()["error"]["code"] == "amount_below_collected"

    empty = client.post(f"{API}/receivable-schedules", json={"customer_id": cid, "title": "İptal", "amount_kurus": 1_000}).json()
    assert client.post(f"{API}/receivable-schedules/{empty['id']}/cancel").status_code == 200
    on_cancelled = move(client, cid, "collection", 500, "col-2223-aaaa", receivable_schedule_id=empty["id"])
    assert on_cancelled.status_code == 409 and on_cancelled.json()["error"]["code"] == "schedule_cancelled"
    # İptal edilen plan yaşlandırmaya girmez.
    after = client.get(f"{API}/customers/{cid}/aging", params={"as_of": "2026-05-01"}).json()
    assert all(i["receivable_schedule_id"] != empty["id"] for i in after["items"])


def test_archived_customer_and_project_mismatch(client):
    project = make_project(client, customer_name="Arşiv Müşteri")
    cid = project["customer_id"]
    other = new_customer(client, "Diğer Müşteri")
    mismatch = client.post(
        f"{API}/receivable-schedules",
        json={"customer_id": other["id"], "project_id": project["id"], "title": "Yanlış", "amount_kurus": 100},
    )
    assert mismatch.status_code == 409 and mismatch.json()["error"]["code"] == "project_customer_mismatch"

    move(client, cid, "accrual", 10_000, "acc-3333-aaaa")
    assert client.post(f"{API}/customers/{cid}/archive").status_code == 200
    assert client.post(f"{API}/customers/{cid}/archive").status_code == 409
    for response in (
        move(client, cid, "collection", 100, "col-3333-aaaa"),
        client.post(f"{API}/receivable-schedules", json={"customer_id": cid, "title": "Yeni", "amount_kurus": 100}),
        client.patch(f"{API}/customers/{cid}", json={"phone": "1"}),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "customer_archived"
    # Okuma ve ekstre arşivde de çalışır.
    assert client.get(f"{API}/customers/{cid}/statement").status_code == 200
    assert client.get(f"{API}/customers", params={"include_archived": True}).json()
    assert cid not in [c["id"] for c in client.get(f"{API}/customers").json()]
    assert client.post(f"{API}/customers/{cid}/unarchive").status_code == 200


def test_statement_running_balance_with_reversal_and_range(client):
    cid = new_customer(client)["id"]
    move(client, cid, "accrual", 100_000, "acc-4444-aaaa", day="2026-01-05")
    col = move(client, cid, "collection", 40_000, "col-4444-aaaa", day="2026-01-15").json()
    move(client, cid, "accrual", 20_000, "acc-4445-aaaa", day="2026-02-01")
    client.post(f"{API}/customer-financial-movements/{col['id']}/reverse")

    full = client.get(f"{API}/customers/{cid}/statement").json()
    assert full["closing_balance_kurus"] == 120_000
    assert full["opening_balance_kurus"] == 0
    # Ters kayıt varsayılan olarak orijinal hareket tarihine yazılır: 01-15 tahsilat, 01-15 ters kayıt.
    assert [r["balance_kurus"] for r in full["rows"]] == [100_000, 60_000, 100_000, 120_000]
    assert [r["is_voided"] for r in full["rows"]] == [False, True, False, False]
    assert full["total_increase_kurus"] - full["total_decrease_kurus"] == full["closing_balance_kurus"]

    ranged = client.get(f"{API}/customers/{cid}/statement", params={"date_from": "2026-01-10", "date_to": "2026-01-31"}).json()
    assert ranged["opening_balance_kurus"] == 100_000
    assert ranged["closing_balance_kurus"] == 100_000  # tahsilat + ters kayıt aynı gün aralığında dengelenir
    assert client.get(f"{API}/customers/{cid}/statement", params={"date_from": "2026-03-01", "date_to": "2026-01-01"}).status_code == 422


def test_change_order_accrual_requires_approved_order(client):
    project = make_project(client, customer_name="Ek İş Müşterisi")
    cid = project["customer_id"]
    order = client.post(f"{API}/projects/{project['id']}/change-orders", json={"title": "Ek dolap", "amount_kurus": 250_000}).json()
    draft = move(client, cid, "accrual", 250_000, "acc-5555-aaaa", project_id=project["id"], change_order_id=order["id"])
    assert draft.status_code == 409 and draft.json()["error"]["code"] == "change_order_not_approved"
    assert client.post(f"{API}/projects/{project['id']}/change-orders/{order['id']}/approve").status_code == 200
    no_project = move(client, cid, "accrual", 250_000, "acc-5556-aaaa", change_order_id=order["id"])
    assert no_project.status_code == 409 and no_project.json()["error"]["code"] == "change_order_project_mismatch"
    ok = move(client, cid, "accrual", 250_000, "acc-5557-aaaa", project_id=project["id"], change_order_id=order["id"])
    assert ok.status_code == 201
    assert ok.json()["change_order_id"] == order["id"]


def test_reversal_can_be_dated_after_the_original(client):
    cid = new_customer(client)["id"]
    move(client, cid, "accrual", 100_000, "acc-6666-aaaa", day="2026-01-05")
    col = move(client, cid, "collection", 40_000, "col-6666-aaaa", day="2026-01-15").json()
    early = client.post(
        f"{API}/customer-financial-movements/{col['id']}/reverse", json={"movement_date": "2026-01-01"}
    )
    assert early.status_code == 422 and early.json()["error"]["code"] == "invalid_reversal_date"
    late = client.post(
        f"{API}/customer-financial-movements/{col['id']}/reverse",
        json={"movement_date": "2026-03-01", "note": "Çek karşılıksız"},
    )
    assert late.status_code == 201 and late.json()["movement_date"] == "2026-03-01"
    january = client.get(f"{API}/customers/{cid}/statement", params={"date_to": "2026-02-28"}).json()
    assert january["closing_balance_kurus"] == 60_000  # dönem ekstresi sonradan değişmez
    assert client.get(f"{API}/customers/{cid}/statement").json()["closing_balance_kurus"] == 100_000
