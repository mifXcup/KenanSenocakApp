from __future__ import annotations


def create_basics(client):
    supplier = client.post("/api/v1/suppliers", json={"name": "Test Tedarikçi"}).json()
    material = client.post(
        "/api/v1/materials",
        json={"name": "Test MDF", "default_unit": "levha", "tracking_mode": "estimated"},
    ).json()
    project = client.post(
        "/api/v1/projects", json={"name": "Test Proje", "customer_name": "Test Müşteri"}
    ).json()
    return supplier, material, project


def test_purchase_payment_balance_and_idempotency(client):
    supplier, material, project = create_basics(client)
    payload = {
        "supplier_id": supplier["id"],
        "material_id": material["id"],
        "project_id": project["id"],
        "purchase_date": "2026-10-25",
        "quantity": "20",
        "unit": "levha",
        "unit_price_kurus": 160000,
        "paid_kurus": 2000000,
        "idempotency_key": "purchase-test-0001",
    }
    first = client.post("/api/v1/purchases", json=payload)
    assert first.status_code == 201
    assert first.json()["total_kurus"] == 3200000
    assert first.json()["remaining_kurus"] == 1200000
    duplicate = client.post("/api/v1/purchases", json=payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]

    payment = client.post(
        "/api/v1/payments",
        json={
            "supplier_id": supplier["id"],
            "purchase_id": first.json()["id"],
            "payment_date": "2026-10-26",
            "amount_kurus": 500000,
            "idempotency_key": "payment-test-0001",
        },
    )
    assert payment.status_code == 201
    balance = client.get(f"/api/v1/suppliers/{supplier['id']}/balance")
    assert balance.json()["remaining_kurus"] == 700000


def test_negative_estimated_stock_is_warning_not_block(client):
    _, material, project = create_basics(client)
    movement = client.post(
        "/api/v1/material-movements",
        json={
            "material_id": material["id"],
            "project_id": project["id"],
            "movement_date": "2026-10-25",
            "movement_type": "use",
            "quantity": "3.5",
            "unit": "levha",
            "confidence": "estimated",
        },
    )
    assert movement.status_code == 201
    balance = client.get(f"/api/v1/materials/{material['id']}/balance")
    assert balance.status_code == 200
    assert balance.json()["estimated_quantity"] == "-3.500"
    assert "sıfırın altında" in balance.json()["warning"]


def test_overpayment_is_rejected_and_token_is_required(client):
    supplier, material, _ = create_basics(client)
    purchase = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "purchase_date": "2026-10-25",
            "total_kurus": 10000,
            "idempotency_key": "purchase-test-0002",
        },
    ).json()
    response = client.post(
        "/api/v1/payments",
        json={
            "supplier_id": supplier["id"],
            "purchase_id": purchase["id"],
            "payment_date": "2026-10-25",
            "amount_kurus": 10001,
            "idempotency_key": "payment-test-0002",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "overpayment"

    from fastapi.testclient import TestClient

    from ks_yonetim.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/suppliers").status_code == 401
