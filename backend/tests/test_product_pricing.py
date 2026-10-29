from __future__ import annotations

from helpers import make_project


def _material(client, name="MDF", unit="levha"):
    response = client.post(
        "/api/v1/materials",
        json={"name": name, "default_unit": unit, "tracking_mode": "estimated"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _supplier(client):
    response = client.post("/api/v1/suppliers", json={"name": "Levha Tedarik"})
    assert response.status_code == 201, response.text
    return response.json()


def _product(client, project_id, **overrides):
    body = {
        "product_type": "Lake dolap",
        "quantity": "10",
        "unit": "m²",
        "finish": "Mat lake",
        "hardware_level": "standart",
        "complexity_percent": 100,
        "quote_date": "2026-01-10",
        "target_margin_percent": "25",
        "pricing_state": "draft",
        "factors": [],
    }
    body.update(overrides)
    response = client.post(f"/api/v1/projects/{project_id}/products", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_historical_quote_is_normalized_only_by_cost_share(client):
    old_project = make_project(client, name="Eski Mutfak")
    new_project = make_project(client, name="Yeni Mutfak")
    material = _material(client)
    supplier = _supplier(client)

    historical = _product(
        client,
        old_project["id"],
        quoted_total_kurus=15_000_000,
        pricing_state="offered",
        factors=[
            {
                "factor_key": "mdf",
                "label": "MDF levha",
                "material_id": material["id"],
                "share_percent": "30",
                "reference_unit_price_kurus": 130_000,
                "reference_date": "2026-01-10",
                "source": "manual",
            }
        ],
    )
    assert historical["factors"][0]["share_percent"] == 30

    purchase = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "purchase_date": "2026-03-01",
            "quantity": "1",
            "unit": "levha",
            "unit_price_kurus": 160_000,
            "idempotency_key": "pricing-current-mdf-001",
        },
    )
    assert purchase.status_code == 201, purchase.text

    target = _product(client, new_project["id"], quote_date="2026-03-10")
    response = client.post(
        f"/api/v1/project-products/{target['id']}/suggestions?as_of=2026-03-10"
    )
    assert response.status_code == 201, response.text
    suggestion = response.json()

    # 150.000 × (%70 sabit + %30 × 1600/1300) = 160.384,62 TL
    assert suggestion["suggested_mid_kurus"] == 16_038_462
    assert suggestion["confidence"] == "low"
    comparable = suggestion["explanation"]["comparables"][0]
    assert comparable["base_price_kurus"] == 15_000_000
    assert comparable["factors"][0]["change_percent"] == 23.08
    assert comparable["factors"][0]["current_source"] == "purchase"


def test_actual_cost_uses_target_margin_and_quantity(client):
    old_project = make_project(client, name="Eski Vestiyer")
    new_project = make_project(client, name="Yeni Vestiyer")
    _product(
        client,
        old_project["id"],
        product_type="Vestiyer",
        quantity="5",
        quoted_total_kurus=10_000_000,
        actual_cost_kurus=8_000_000,
        pricing_state="completed",
    )
    target = _product(
        client,
        new_project["id"],
        product_type="Vestiyer",
        quantity="10",
        target_margin_percent="25",
    )
    response = client.post(f"/api/v1/project-products/{target['id']}/suggestions")
    assert response.status_code == 201, response.text
    # 80.000 gerçek maliyet × 2 miktar × %25 hedef marj
    assert response.json()["suggested_mid_kurus"] == 20_000_000


def test_suggestion_requires_matching_history_and_factor_shares_are_guarded(client):
    project = make_project(client)
    target = _product(client, project["id"], product_type="TV ünitesi")
    response = client.post(f"/api/v1/project-products/{target['id']}/suggestions")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "pricing_history_insufficient"

    invalid = client.post(
        f"/api/v1/projects/{project['id']}/products",
        json={
            "product_type": "Mutfak",
            "quantity": "10",
            "unit": "m²",
            "quote_date": "2026-03-10",
            "factors": [
                {
                    "factor_key": "mdf",
                    "label": "MDF",
                    "share_percent": "70",
                    "reference_unit_price_kurus": 100,
                    "reference_date": "2026-01-01",
                },
                {
                    "factor_key": "labor",
                    "label": "İşçilik",
                    "share_percent": "40",
                    "reference_unit_price_kurus": 100,
                    "reference_date": "2026-01-01",
                },
            ],
        },
    )
    assert invalid.status_code == 422


def test_manual_index_and_learning_status(client):
    project = make_project(client)
    _product(client, project["id"], quoted_total_kurus=1_000_000)
    index = client.post(
        "/api/v1/pricing/indices",
        json={
            "factor_key": "labor",
            "label": "Atölye işçiliği",
            "recorded_on": "2026-03-10",
            "unit_price_kurus": 250_000,
            "note": "Günlük referans",
        },
    )
    assert index.status_code == 201, index.text

    status = client.get("/api/v1/pricing/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["ready"] is True
    assert body["priced_product_count"] == 1
    assert body["latest_manual_indices"][0]["factor_key"] == "labor"
