from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from ks_yonetim.database import ensure_schema
from ks_yonetim.reports import aging_bucket


def create_basics(client):
    supplier = client.post("/api/v1/suppliers", json={"name": "Rapor Tedarikçi"}).json()
    material = client.post(
        "/api/v1/materials",
        json={"name": "Rapor MDF", "default_unit": "levha", "tracking_mode": "estimated"},
    ).json()
    project = client.post(
        "/api/v1/projects", json={"name": "Rapor Proje", "customer_name": "Rapor Müşteri"}
    ).json()
    return supplier, material, project


def add_purchase(client, supplier, material, key, day, total, due=None, paid=0, project=None):
    response = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "project_id": project["id"] if project else None,
            "purchase_date": day,
            "due_date": due,
            "total_kurus": total,
            "paid_kurus": paid,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_aging_bucket_boundaries():
    from datetime import date

    today = date(2026, 10, 25)
    assert aging_bucket(None, today) == ("no_due_date", None)
    assert aging_bucket(date(2026, 10, 25), today)[0] == "not_due"
    assert aging_bucket(date(2026, 10, 24), today)[0] == "d1_30"
    assert aging_bucket(date(2026, 9, 25), today)[0] == "d1_30"
    assert aging_bucket(date(2026, 9, 24), today)[0] == "d31_60"
    assert aging_bucket(date(2026, 8, 26), today)[0] == "d31_60"  # 60 gün
    assert aging_bucket(date(2026, 8, 25), today)[0] == "d61_90"  # 61 gün
    assert aging_bucket(date(2026, 7, 27), today)[0] == "d61_90"  # 90 gün
    assert aging_bucket(date(2026, 7, 26), today)[0] == "d90_plus"  # 91 gün


def test_due_date_cannot_precede_purchase(client):
    supplier, material, _ = create_basics(client)
    response = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "purchase_date": "2026-10-25",
            "due_date": "2026-10-20",
            "total_kurus": 1000,
            "idempotency_key": "purchase-due-bad1",
        },
    )
    assert response.status_code == 422


def test_debt_aging_buckets_payments_and_credit(client):
    supplier, material, _ = create_basics(client)
    other = client.post("/api/v1/suppliers", json={"name": "Avans Firması"}).json()
    # 100.000 vadesi geçmiş (40 gün), 20.000 kısmen ödenmiş; 50.000 vadesi gelmemiş
    add_purchase(
        client,
        supplier,
        material,
        "aging-test-0001",
        "2026-08-01",
        10000000,
        due="2026-09-15",
        paid=2000000,
    )
    add_purchase(
        client, supplier, material, "aging-test-0002", "2026-10-20", 5000000, due="2026-11-20"
    )
    add_purchase(client, supplier, material, "aging-test-0003", "2026-10-21", 300000)
    # Alışa bağlanmamış 30.000 ödeme en eski borçtan düşer
    client.post(
        "/api/v1/payments",
        json={
            "supplier_id": supplier["id"],
            "payment_date": "2026-10-22",
            "amount_kurus": 3000000,
            "idempotency_key": "payment-aging-0001",
        },
    )
    # Hiç alışı olmayan firmaya avans
    client.post(
        "/api/v1/payments",
        json={
            "supplier_id": other["id"],
            "payment_date": "2026-10-22",
            "amount_kurus": 700000,
            "idempotency_key": "payment-aging-0002",
        },
    )

    report = client.get("/api/v1/reports/debt-aging", params={"as_of": "2026-10-25"}).json()
    buckets = {b["key"]: b["amount_kurus"] for b in report["buckets"]}
    assert buckets["d31_60"] == 5000000  # 10M - 2M - 3M
    assert buckets["not_due"] == 5000000
    assert buckets["no_due_date"] == 300000
    assert report["total_open_kurus"] == 10300000
    assert report["overdue_kurus"] == 5000000
    assert report["credit_kurus"] == 700000
    first = next(s for s in report["suppliers"] if s["supplier_id"] == supplier["id"])
    assert first["total_open_kurus"] == 10300000
    assert first["overdue_kurus"] == 5000000
    overdue_item = next(i for i in report["items"] if i["bucket"] == "d31_60")
    assert overdue_item["days_overdue"] == 40


def test_aging_ignores_cancelled_and_reversed(client):
    supplier, material, _ = create_basics(client)
    purchase = add_purchase(
        client, supplier, material, "aging-test-0010", "2026-10-01", 100000, due="2026-10-10"
    )
    client.post(f"/api/v1/purchases/{purchase['id']}/cancel")
    report = client.get("/api/v1/reports/debt-aging", params={"as_of": "2026-10-25"}).json()
    assert report["total_open_kurus"] == 0


def test_purchase_report_date_filter_and_units(client):
    supplier, material, project = create_basics(client)
    for key, day, qty in (
        ("rep-test-0001", "2026-09-10", "10"),
        ("rep-test-0002", "2026-10-10", "5"),
    ):
        client.post(
            "/api/v1/purchases",
            json={
                "supplier_id": supplier["id"],
                "material_id": material["id"],
                "project_id": project["id"],
                "purchase_date": day,
                "quantity": qty,
                "unit": "levha",
                "unit_price_kurus": 100000,
                "paid_kurus": 100000,
                "idempotency_key": key,
            },
        )
    everything = client.get("/api/v1/reports/purchases").json()
    assert everything["purchase_count"] == 2
    assert everything["purchase_total_kurus"] == 1500000
    assert [m["month"] for m in everything["by_month"]] == ["2026-09", "2026-10"]

    october = client.get(
        "/api/v1/reports/purchases", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}
    ).json()
    assert october["purchase_count"] == 1
    assert october["purchase_total_kurus"] == 500000
    assert october["payment_total_kurus"] == 100000
    assert october["by_material"][0]["quantity"] == "5.000"
    assert october["by_material"][0]["unit"] == "levha"
    # Güncel borç dönem filtresinden bağımsız, tüm zamanlar
    assert october["by_supplier"][0]["current_debt_kurus"] == 1500000 - 200000

    bad = client.get(
        "/api/v1/reports/purchases", params={"date_from": "2026-11-01", "date_to": "2026-10-01"}
    )
    assert bad.status_code == 422


def test_ensure_schema_adds_due_date_to_old_database(tmp_path):
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as connection:
        connection.execute(text("CREATE TABLE purchases (id VARCHAR(36) PRIMARY KEY)"))
    ensure_schema(old)
    columns = {c["name"] for c in inspect(old).get_columns("purchases")}
    assert "due_date" in columns
    ensure_schema(old)  # tekrar çalıştırmak güvenli
