from __future__ import annotations

from decimal import Decimal

from finance_helpers import make_material, make_purchase, make_supplier, receipt
from helpers import make_project
from sqlalchemy import func, select

from ks_yonetim.database import SessionLocal
from ks_yonetim.models import Purchase, PurchaseReceipt, RecordStatus

API = "/api/v1"


def supplier_balance(client, supplier):
    return client.get(f"{API}/suppliers/{supplier['id']}/balance").json()["remaining_kurus"]


def material_quantity(client, material):
    value = client.get(f"{API}/materials/{material['id']}/balance").json()["estimated_quantity"]
    return None if value is None else Decimal(value)


def assert_cache_matches_receipts():
    """received_kurus her zaman aktif fişlerin toplamıdır."""
    with SessionLocal() as session:
        for purchase in session.scalars(select(Purchase)):
            total = session.scalar(
                select(func.coalesce(func.sum(PurchaseReceipt.amount_kurus), 0)).where(
                    PurchaseReceipt.purchase_id == purchase.id,
                    PurchaseReceipt.status == RecordStatus.ACTIVE,
                )
            )
            assert purchase.received_kurus == total, purchase.id


def setup(client, total=300_000, quantity="30.000", tracking="exact"):
    project = make_project(client)
    supplier, material = make_supplier(client), make_material(client, tracking=tracking)
    purchase = make_purchase(
        client, supplier, material, project["id"], total, "pur-rcpt-0001", state="planned",
        quantity=quantity, unit="levha",
    )
    return project, supplier, material, purchase


def test_two_partial_receipts_complete_and_drive_balance_cost_and_ranges(client):
    project, supplier, material, purchase = setup(client)
    pid = project["id"]
    first = receipt(client, purchase["id"], "2026-01-10", 100_000, "teslim-000001", quantity="10.000")
    assert first.status_code == 201
    purchase_now = client.get(f"{API}/purchases").json()[0]
    assert purchase_now["lifecycle_state"] == "partially_received"
    assert purchase_now["received_kurus"] == 100_000
    second = receipt(client, purchase["id"], "2026-02-15", 120_000, "teslim-000002", quantity="12.000")
    assert second.status_code == 201

    assert supplier_balance(client, supplier) == 220_000
    assert material_quantity(client, material) == 22  # teslim anında hareket yazıldı
    profit = client.get(f"{API}/projects/{pid}/profitability").json()
    material_row = {c["category"]: c for c in profit["categories"]}["material"]
    assert (material_row["actual_kurus"], material_row["commitment_kurus"]) == (220_000, 80_000)

    # Dönemsel maliyet: her teslim kendi tarihiyle girer.
    def cost(**params):
        return client.get(f"{API}/projects/{pid}/cost-summary", params=params).json()["purchase_kurus"]

    assert cost() == 220_000
    assert cost(date_to="2026-01-31") == 100_000
    assert cost(date_from="2026-02-01") == 120_000
    assert cost(date_from="2026-01-11", date_to="2026-02-14") == 0

    drill = client.get(f"{API}/projects/{pid}/cost-drilldown").json()
    sources = {c["category"]: c for c in drill["categories"]}["material"]["actual_sources"]
    assert [(s["date"], s["amount_kurus"]) for s in sources] == [
        ("2026-01-10", 100_000), ("2026-02-15", 120_000)
    ]
    assert {s["source_id"] for s in sources} == {first.json()["id"], second.json()["id"]}

    # Tedarikçi ekstresi, yaşlandırma ve alış raporu teslim tarihlerini esas alır.
    statement = client.get(f"{API}/suppliers/{supplier['id']}/statement").json()
    assert [(r["date"], r["increase_kurus"], r["balance_kurus"]) for r in statement["rows"]] == [
        ("2026-01-10", 100_000, 100_000), ("2026-02-15", 120_000, 220_000)
    ]
    january = client.get(
        f"{API}/suppliers/{supplier['id']}/statement", params={"date_to": "2026-01-31"}
    ).json()
    assert january["closing_balance_kurus"] == 100_000
    aging_jan = client.get(
        f"{API}/suppliers/{supplier['id']}/aging", params={"as_of": "2026-01-31"}
    ).json()
    aging_mar = client.get(
        f"{API}/suppliers/{supplier['id']}/aging", params={"as_of": "2026-03-01"}
    ).json()
    assert (aging_jan["total_open_kurus"], aging_mar["total_open_kurus"]) == (100_000, 220_000)
    report = client.get(
        f"{API}/reports/purchases", params={"date_from": "2026-02-01", "date_to": "2026-02-28"}
    ).json()
    assert report["purchase_total_kurus"] == 120_000
    assert report["by_supplier"][0]["purchase_count"] == 1
    assert report["by_material"][0]["quantity"] == "12.000"
    whole = client.get(f"{API}/reports/purchases").json()
    assert whole["purchase_total_kurus"] == 220_000
    assert whole["by_supplier"][0]["purchase_count"] == 1  # iki teslim tek satın alma
    assert {m["month"]: m["total_kurus"] for m in whole["by_month"]} == {
        "2026-01": 100_000, "2026-02": 120_000
    }

    # Tamamlama ve aşım.
    over = receipt(client, purchase["id"], "2026-03-01", 80_001, "teslim-000003")
    assert over.status_code == 409 and over.json()["error"]["code"] == "receipt_exceeds_total"
    assert over.json()["error"]["details"]["remaining_kurus"] == 80_000
    assert receipt(client, purchase["id"], "2026-03-01", 80_000, "teslim-000004", quantity="8.000").status_code == 201
    done = client.get(f"{API}/purchases").json()[0]
    assert done["lifecycle_state"] == "received" and done["received_kurus"] == 300_000
    assert client.get(f"{API}/projects/{pid}/profitability").json()["commitment_kurus"] == 0
    assert_cache_matches_receipts()


def test_receipt_cancellation_is_soft_and_reverses_effects(client):
    project, supplier, material, purchase = setup(client)
    r1 = receipt(client, purchase["id"], "2026-01-10", 100_000, "teslim-000011", quantity="10.000").json()
    r2 = receipt(client, purchase["id"], "2026-02-15", 200_000, "teslim-000012", quantity="20.000").json()
    assert client.get(f"{API}/purchases").json()[0]["lifecycle_state"] == "received"
    assert material_quantity(client, material) == 30

    cancelled = client.post(f"{API}/purchase-receipts/{r2['id']}/cancel", json={"reason": "Yanlış sevkiyat"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"] == "Yanlış sevkiyat" and cancelled.json()["cancelled_at"]
    row = client.get(f"{API}/purchases").json()[0]
    assert row["lifecycle_state"] == "partially_received" and row["received_kurus"] == 100_000
    assert supplier_balance(client, supplier) == 100_000
    assert material_quantity(client, material) == 10
    assert client.get(f"{API}/projects/{project['id']}/cost-summary").json()["purchase_kurus"] == 100_000
    assert client.get(f"{API}/projects/{project['id']}/profitability").json()["commitment_kurus"] == 200_000
    again = client.post(f"{API}/purchase-receipts/{r2['id']}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "receipt_cancelled"

    # Fiziksel silme yok.
    assert [x["id"] for x in client.get(f"{API}/purchases/{purchase['id']}/receipts").json()] == [r1["id"]]
    everything = client.get(f"{API}/purchases/{purchase['id']}/receipts", params={"include_cancelled": True}).json()
    assert {x["id"] for x in everything} == {r1["id"], r2["id"]}

    # Aynı tutarla yeni teslim yeniden girilebilir.
    assert receipt(client, purchase["id"], "2026-02-20", 200_000, "teslim-000013", quantity="20.000").status_code == 201
    assert client.get(f"{API}/purchases").json()[0]["lifecycle_state"] == "received"

    client.post(f"{API}/purchase-receipts/{r1['id']}/cancel")
    third = client.get(f"{API}/purchases/{purchase['id']}/receipts").json()
    client.post(f"{API}/purchase-receipts/{third[0]['id']}/cancel")
    zero = client.get(f"{API}/purchases").json()[0]
    assert zero["received_kurus"] == 0 and zero["lifecycle_state"] == "ordered"
    assert supplier_balance(client, supplier) == 0
    assert_cache_matches_receipts()


def test_receipt_idempotency_and_validation(client):
    _, _, _, purchase = setup(client)
    first = receipt(client, purchase["id"], "2026-01-10", 50_000, "teslim-000021")
    again = receipt(client, purchase["id"], "2026-01-10", 50_000, "teslim-000021")
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert len(client.get(f"{API}/purchases/{purchase['id']}/receipts").json()) == 1
    conflict = receipt(client, purchase["id"], "2026-01-10", 60_000, "teslim-000021")
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    assert receipt(client, purchase["id"], "2026-01-10", 0, "teslim-000022").status_code == 422
    assert receipt(client, "yok-satin-alma", "2026-01-10", 10, "teslim-000023").status_code == 404


def test_tracking_modes_decide_whether_a_movement_is_written(client):
    project = make_project(client)
    supplier = make_supplier(client)
    exact = make_material(client, "Tam Takip", tracking="exact")
    value_only = make_material(client, "Yalnız Maliyet", tracking="value_only")
    p1 = make_purchase(client, supplier, exact, project["id"], 10_000, "pur-trk-00001", state="ordered")
    p2 = make_purchase(client, supplier, value_only, project["id"], 20_000, "pur-trk-00002", state="ordered")

    def movements(material):
        # Malzeme bakiyesi dışında hareket sayısı için doğrudan veritabanı.
        from ks_yonetim.models import MaterialMovement

        with SessionLocal() as session:
            return session.scalar(
                select(func.count(MaterialMovement.id)).where(
                    MaterialMovement.material_id == material["id"],
                    MaterialMovement.status == RecordStatus.ACTIVE,
                )
            )

    receipt(client, p1["id"], "2026-01-10", 10_000, "teslim-000031")  # miktarsız, tam takip
    assert movements(exact) == 0
    receipt(client, p2["id"], "2026-01-10", 20_000, "teslim-000032")  # miktarsız, yalnız maliyet
    assert movements(value_only) == 1
    assert material_quantity(client, value_only) is None
    assert supplier_balance(client, supplier) == 30_000


def test_lifecycle_endpoint_writes_receipts_with_dates(client):
    project, supplier, _, purchase = setup(client, total=200_000, quantity="20.000")
    path = f"{API}/purchases/{purchase['id']}/lifecycle"
    assert client.post(path, json={"state": "ordered"}).status_code == 200
    partial = client.post(
        path, json={"state": "partially_received", "received_kurus": 80_000, "receipt_date": "2026-01-12"}
    )
    assert partial.status_code == 200 and partial.json()["received_kurus"] == 80_000
    done = client.post(path, json={"state": "received", "receipt_date": "2026-02-02"})
    assert done.status_code == 200 and done.json()["lifecycle_state"] == "received"
    rows = client.get(f"{API}/purchases/{purchase['id']}/receipts").json()
    assert [(r["receipt_date"], r["amount_kurus"]) for r in rows] == [
        ("2026-01-12", 80_000), ("2026-02-02", 120_000)
    ]
    assert rows[1]["quantity"] == "20.000"  # kalan miktar son teslime yazılır
    assert supplier_balance(client, supplier) == 200_000
    # Tarih gönderilmezse sunucu iş tarihi (conftest: 2026-03-10) kullanılır.
    other = make_purchase(client, supplier, make_material(client, "Diğer"), project["id"], 50_000, "pur-rcpt-0002", state="ordered")
    client.post(f"{API}/purchases/{other['id']}/lifecycle", json={"state": "received"})
    assert client.get(f"{API}/purchases/{other['id']}/receipts").json()[0]["receipt_date"] == "2026-03-10"
    assert_cache_matches_receipts()


def test_new_received_purchase_gets_initial_receipt_and_cancel_cancels_receipts(client):
    project = make_project(client)
    supplier, material = make_supplier(client), make_material(client)
    made = make_purchase(client, supplier, material, project["id"], 90_000, "pur-init-0001", quantity="9.000", unit="levha")
    rows = client.get(f"{API}/purchases/{made['id']}/receipts").json()
    assert [(r["receipt_date"], r["amount_kurus"], r["quantity"]) for r in rows] == [
        ("2026-01-05", 90_000, "9.000")
    ]
    assert made["received_kurus"] == 90_000
    assert client.post(f"{API}/purchases/{made['id']}/cancel").status_code == 200
    with SessionLocal() as session:
        statuses = {r.status for r in session.scalars(select(PurchaseReceipt))}
    assert statuses == {RecordStatus.CANCELLED}
    assert supplier_balance(client, supplier) == 0
    assert_cache_matches_receipts()


def test_import_opening_debts_create_receipts(client):
    from helpers import workbook_payload

    supplier = make_supplier(client, "Açılış Firma")
    payload = workbook_payload(
        ["Firma Adı*", "Tutar (TL)*", "Tarih*", "Vade Tarihi", "Açıklama"],
        [[supplier["name"], "1.250,50", "02.01.2026", "02.02.2026", "Eski borç"]],
    )
    committed = client.post(f"{API}/imports/opening-debts/commit", json=payload)
    assert committed.status_code == 200, committed.text
    purchase = client.get(f"{API}/purchases").json()[0]
    assert purchase["received_kurus"] == 125_050 and purchase["lifecycle_state"] == "received"
    rows = client.get(f"{API}/purchases/{purchase['id']}/receipts").json()
    assert [(r["receipt_date"], r["amount_kurus"]) for r in rows] == [("2026-01-02", 125_050)]
    assert supplier_balance(client, supplier) == 125_050
    assert_cache_matches_receipts()
