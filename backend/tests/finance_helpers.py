from __future__ import annotations

API = "/api/v1"


def make_supplier(client, name="Tedarikçi A"):
    response = client.post(f"{API}/suppliers", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def make_material(client, name="MDF", tracking="exact"):
    response = client.post(
        f"{API}/materials", json={"name": name, "default_unit": "levha", "tracking_mode": tracking}
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_purchase(client, supplier, material, project_id, total, key, state="received", **extra):
    payload = {
        "supplier_id": supplier["id"],
        "material_id": material["id"],
        "project_id": project_id,
        "purchase_date": "2026-01-05",
        "total_kurus": total,
        "idempotency_key": key,
        "lifecycle_state": state,
        **extra,
    }
    response = client.post(f"{API}/purchases", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def receipt(client, purchase_id, day, amount, key, **extra):
    return client.post(
        f"{API}/purchases/{purchase_id}/receipts",
        json={"receipt_date": day, "amount_kurus": amount, "idempotency_key": key, **extra},
    )


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


def schedule(client, customer_id, title, amount, due, **extra):
    response = client.post(
        f"{API}/receivable-schedules",
        json={
            "customer_id": customer_id,
            "title": title,
            "amount_kurus": amount,
            "due_date": due,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def allocate(client, collection_id, schedule_id, amount, key, **extra):
    return client.post(
        f"{API}/customer-payment-allocations",
        json={
            "collection_id": collection_id,
            "receivable_schedule_id": schedule_id,
            "amount_kurus": amount,
            "idempotency_key": key,
            **extra,
        },
    )
