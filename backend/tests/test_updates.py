from __future__ import annotations


def create_records(client):
    supplier = client.post("/api/v1/suppliers", json={"name": "Eski Firma"}).json()
    other_supplier = client.post("/api/v1/suppliers", json={"name": "Diğer Firma"}).json()
    material = client.post(
        "/api/v1/materials",
        json={"name": "Eski Malzeme", "default_unit": "adet", "tracking_mode": "exact"},
    ).json()
    project = client.post(
        "/api/v1/projects", json={"name": "Eski Proje", "customer_name": "Eski Müşteri"}
    ).json()
    return supplier, other_supplier, material, project


def test_supplier_can_be_updated_and_duplicate_name_is_rejected(client):
    supplier, other, _, _ = create_records(client)
    updated = client.patch(
        f"/api/v1/suppliers/{supplier['id']}",
        json={"name": "Yeni Firma", "phone": "0555 000 00 00", "note": "Güncellendi"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Yeni Firma"
    assert updated.json()["phone"] == "0555 000 00 00"

    duplicate = client.patch(
        f"/api/v1/suppliers/{supplier['id']}", json={"name": other["name"]}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_supplier"


def test_material_tracking_and_note_can_be_updated(client):
    _, _, material, _ = create_records(client)
    updated = client.patch(
        f"/api/v1/materials/{material['id']}",
        json={"default_unit": "kg", "tracking_mode": "estimated", "note": "Yaklaşık sayım"},
    )
    assert updated.status_code == 200
    assert updated.json()["default_unit"] == "kg"
    assert updated.json()["tracking_mode"] == "estimated"


def test_project_state_and_nullable_budget_can_be_updated(client):
    _, _, _, project = create_records(client)
    with_budget = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"budget_kurus": 2500000, "project_state": "completed"},
    )
    assert with_budget.status_code == 200
    assert with_budget.json()["budget_kurus"] == 2500000
    assert with_budget.json()["project_state"] == "completed"

    cleared = client.patch(
        f"/api/v1/projects/{project['id']}", json={"budget_kurus": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["budget_kurus"] is None


def test_empty_or_null_required_updates_are_rejected(client):
    supplier, _, material, project = create_records(client)
    assert client.patch(f"/api/v1/suppliers/{supplier['id']}", json={}).status_code == 422
    assert (
        client.patch(f"/api/v1/materials/{material['id']}", json={"name": None}).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/projects/{project['id']}", json={"project_state": "unknown"}
        ).status_code
        == 422
    )


def test_purchase_note_due_date_and_project_can_be_corrected(client):
    supplier, _, material, project = create_records(client)
    purchase = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "project_id": project["id"],
            "purchase_date": "2026-10-26",
            "due_date": "2026-11-15",
            "total_kurus": 100000,
            "paid_kurus": 25000,
            "description": "İlk açıklama",
            "idempotency_key": "purchase-update-0001",
        },
    ).json()

    updated = client.patch(
        f"/api/v1/purchases/{purchase['id']}",
        json={
            "project_id": None,
            "due_date": "2026-12-01",
            "description": "Düzeltilmiş açıklama",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["project_id"] is None
    assert updated.json()["due_date"] == "2026-12-01"
    assert updated.json()["description"] == "Düzeltilmiş açıklama"
    assert updated.json()["total_kurus"] == 100000
    assert updated.json()["paid_kurus"] == 25000

    invalid_due = client.patch(
        f"/api/v1/purchases/{purchase['id']}", json={"due_date": "2026-10-25"}
    )
    assert invalid_due.status_code == 422
    assert invalid_due.json()["error"]["code"] == "invalid_due_date"


def test_purchase_update_rejects_empty_body_and_missing_project(client):
    supplier, _, material, _ = create_records(client)
    purchase = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "purchase_date": "2026-10-26",
            "total_kurus": 100000,
            "idempotency_key": "purchase-update-0002",
        },
    ).json()
    assert client.patch(f"/api/v1/purchases/{purchase['id']}", json={}).status_code == 422
    missing = client.patch(
        f"/api/v1/purchases/{purchase['id']}",
        json={"project_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404
