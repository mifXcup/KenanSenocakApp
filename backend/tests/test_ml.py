from __future__ import annotations


def test_ml_waits_for_enough_data(client):
    response = client.get("/api/v1/analytics/ml/insights", params={"as_of": "2026-10-26"})
    assert response.status_code == 200
    assert response.json()["status"]["ready"] is False
    assert response.json()["price_anomalies"] == []
    assert "yeterli" in response.json()["status"]["message"]


def test_local_models_detect_price_anomaly_reorder_and_project_risk(client):
    supplier = client.post("/api/v1/suppliers", json={"name": "Model Firması"}).json()
    material = client.post(
        "/api/v1/materials",
        json={"name": "Model MDF", "default_unit": "levha", "tracking_mode": "estimated"},
    ).json()
    project = client.post(
        "/api/v1/projects",
        json={"name": "Riskli Proje", "customer_name": "Müşteri", "budget_kurus": 60000},
    ).json()
    dates = ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"]
    prices = [10000, 10200, 10100, 9900, 20000]
    for index, (day, price) in enumerate(zip(dates, prices, strict=True)):
        response = client.post(
            "/api/v1/purchases",
            json={
                "supplier_id": supplier["id"],
                "material_id": material["id"],
                "project_id": project["id"],
                "purchase_date": day,
                "quantity": "1",
                "unit": "levha",
                "unit_price_kurus": price,
                "idempotency_key": f"ml-purchase-{index:04d}",
            },
        )
        assert response.status_code == 201

    insight = client.get(
        "/api/v1/analytics/ml/insights", params={"as_of": "2026-10-01"}
    ).json()
    assert insight["status"]["ready"] is True
    assert insight["status"]["material_series_ready"] == 1
    assert insight["status"]["reorder_series_ready"] == 1
    assert insight["status"]["project_series_ready"] == 1

    anomaly = insight["price_anomalies"][0]
    assert anomaly["material_id"] == material["id"]
    assert anomaly["is_anomaly"] is True
    assert anomaly["deviation_percent"] > 80

    reorder = insight["reorder_forecasts"][0]
    assert reorder["median_interval_days"] == 7
    assert reorder["next_expected_date"] == "2026-10-06"
    assert reorder["confidence"] == "medium"  # 4-5 kayıtla "yüksek" güven verilmez

    risk = insight["project_risks"][0]
    assert risk["project_id"] == project["id"]
    assert risk["current_cost_kurus"] == sum(prices)
    assert risk["risk_level"] == "high"
