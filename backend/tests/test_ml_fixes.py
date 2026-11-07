"""ML denetiminde bulunan veri seçimi hataları için regresyon testleri."""

from __future__ import annotations

from helpers import make_project
from test_product_pricing import _material, _product, _supplier

from ks_yonetim.textnorm import match_key


def _purchase(client, supplier_id, material_id, key, day, unit, price, **extra):
    body = {
        "supplier_id": supplier_id,
        "material_id": material_id,
        "purchase_date": day,
        "quantity": "1",
        "unit": unit,
        "unit_price_kurus": price,
        "idempotency_key": f"mlfix-{key}",
    }
    body.update(extra)
    response = client.post("/api/v1/purchases", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _suggest(client, product_id):
    response = client.post(f"/api/v1/project-products/{product_id}/suggestions?as_of=2026-03-10")
    assert response.status_code == 201, response.text
    return response.json()


def test_match_key_ignores_turkish_letter_case_and_accents():
    assert match_key("Lİtre") == match_key("LITRE") == match_key("litre") == match_key(" litre ")
    assert match_key("ÇİĞ Dolap") == match_key("çiğ  dolap") == match_key("CIG DOLAP")
    assert match_key("kg") != match_key("adet")
    assert match_key(None) == ""


def test_current_factor_price_ignores_other_units_and_unreceived_purchases(client):
    old = make_project(client, name="Eski")
    new = make_project(client, name="Yeni")
    material = _material(client)
    supplier = _supplier(client)
    _product(
        client, old["id"], quoted_total_kurus=15_000_000, pricing_state="offered",
        factors=[{"factor_key": "mdf", "label": "MDF", "material_id": material["id"], "share_percent": "30",
                  "reference_unit_price_kurus": 130_000, "reference_date": "2026-01-10", "source": "manual"}],
    )
    _purchase(client, supplier["id"], material["id"], "fx-levha", "2026-03-01", "levha", 160_000)
    target = _product(client, new["id"], quote_date="2026-03-10")
    assert _suggest(client, target["id"])["suggested_mid_kurus"] == 16_038_462

    # Aynı malzemeden kg biriminde ucuz alım ve teslim alınmamış pahalı planlı alım öneriyi değiştirmemeli.
    _purchase(client, supplier["id"], material["id"], "fx-kg", "2026-03-05", "kg", 5_000)
    _purchase(client, supplier["id"], material["id"], "fx-planned", "2026-03-06", "levha", 400_000, lifecycle_state="planned")
    assert _suggest(client, target["id"])["suggested_mid_kurus"] == 16_038_462


def test_candidates_exclude_rejected_draft_and_future_quotes(client):
    projects = [make_project(client, name=f"P{index}") for index in range(5)]
    _product(client, projects[0]["id"], quoted_total_kurus=10_000_000, pricing_state="offered")
    _product(client, projects[1]["id"], quoted_total_kurus=50_000_000, pricing_state="rejected", quote_date="2026-02-01")
    _product(client, projects[2]["id"], quoted_total_kurus=50_000_000, pricing_state="offered", quote_date="2026-09-01")
    _product(client, projects[3]["id"], quoted_total_kurus=50_000_000, pricing_state="draft", quote_date="2026-02-01")
    target = _product(client, projects[4]["id"], quote_date="2026-03-10")
    suggestion = _suggest(client, target["id"])
    assert suggestion["suggested_mid_kurus"] == 10_000_000
    assert len(suggestion["explanation"]["comparables"]) == 1


def test_zero_actual_cost_is_not_treated_as_real_cost(client):
    old = make_project(client, name="Eski")
    new = make_project(client, name="Yeni")
    _product(client, old["id"], quoted_total_kurus=10_000_000, actual_cost_kurus=0, pricing_state="completed")
    target = _product(client, new["id"], quote_date="2026-03-10")
    comparable = _suggest(client, target["id"])["explanation"]["comparables"][0]
    assert comparable["used_actual_cost"] is False
    assert comparable["normalized_price_kurus"] == 10_000_000


def test_product_type_and_unit_match_regardless_of_turkish_case(client):
    old = make_project(client, name="Eski")
    new = make_project(client, name="Yeni")
    _product(client, old["id"], product_type="ÇİĞ Dolap", unit="Mİ", quoted_total_kurus=8_000_000, pricing_state="offered")
    target = _product(client, new["id"], product_type="çiğ dolap", unit="mi", quote_date="2026-03-10")
    assert _suggest(client, target["id"])["suggested_mid_kurus"] == 8_000_000


def test_price_series_merges_turkish_unit_spellings(client):
    material = _material(client, name="Boya", unit="litre")
    supplier = _supplier(client)
    units = ["Lİtre", "litre", "LİTRE", "litre", "LITRE", "Litre"]
    for index, unit in enumerate(units):
        _purchase(client, supplier["id"], material["id"], f"boya-{index}", f"2026-02-{index + 1:02d}", unit, 100_000)
    insights = client.get("/api/v1/analytics/ml/insights?as_of=2026-03-10").json()
    assert len(insights["price_anomalies"]) == 1
    assert insights["price_anomalies"][0]["sample_count"] == 6


def test_price_insights_do_not_leak_purchases_after_as_of(client):
    material = _material(client, name="Vida", unit="kg")
    supplier = _supplier(client)
    for index in range(6):
        _purchase(client, supplier["id"], material["id"], f"vida-{index}", f"2026-02-{index + 1:02d}", "kg", 100_000)
    _purchase(client, supplier["id"], material["id"], "vida-future", "2026-06-01", "kg", 900_000)
    past = client.get("/api/v1/analytics/ml/insights?as_of=2026-03-10").json()["price_anomalies"]
    assert past[0]["latest_unit_price_kurus"] == 100_000 and past[0]["is_anomaly"] is False
    later = client.get("/api/v1/analytics/ml/insights?as_of=2026-07-01").json()["price_anomalies"]
    assert later[0]["latest_unit_price_kurus"] == 900_000 and later[0]["is_anomaly"] is True


def test_reorder_confidence_needs_enough_samples_and_flags_stalled_series(client):
    material = _material(client, name="Cıvata", unit="adet")
    stalled = _material(client, name="Eski Kol", unit="adet")
    supplier = _supplier(client)
    for index in range(6):
        _purchase(client, supplier["id"], material["id"], f"civ-{index}", f"2026-09-{index * 4 + 1:02d}", "adet", 1000)
    for index in range(4):
        _purchase(client, supplier["id"], stalled["id"], f"kol-{index}", f"2026-01-{index * 7 + 1:02d}", "adet", 1000)
    forecasts = {
        item["material_name"]: item
        for item in client.get("/api/v1/analytics/ml/insights?as_of=2026-10-01").json()["reorder_forecasts"]
    }
    assert forecasts["Cıvata"]["confidence"] == "high" and forecasts["Cıvata"]["stale"] is False
    old = forecasts["Eski Kol"]
    assert old["stale"] is True and old["confidence"] == "low" and old["confidence_score"] <= 0.2
    assert "kesilmiş olabilir" in old["explanation"]


def test_price_range_covers_real_spread_and_confidence_drops(client):
    projects = [make_project(client, name=f"Q{index}") for index in range(4)]
    for project, total in zip(projects, (10_000_000, 30_000_000, 90_000_000), strict=False):
        _product(client, project["id"], quoted_total_kurus=total, pricing_state="offered")
    target = _product(client, projects[3]["id"], quote_date="2026-03-10")
    suggestion = _suggest(client, target["id"])
    assert suggestion["suggested_mid_kurus"] == 30_000_000
    assert suggestion["suggested_low_kurus"] <= 10_000_000
    assert suggestion["suggested_high_kurus"] >= 90_000_000
    assert suggestion["confidence"] == "low"
    assert suggestion["explanation"]["dispersion_ratio"] == 9.0
    assert any("çok farklı" in warning for warning in suggestion["explanation"]["warnings"])


def test_fallback_prices_and_big_quantity_gaps_are_flagged(client):
    material = _material(client)
    projects = [make_project(client, name=f"F{index}") for index in range(4)]
    factors = [{"factor_key": "mdf", "label": "MDF", "material_id": material["id"], "share_percent": "40",
                "reference_unit_price_kurus": 130_000, "reference_date": "2026-01-10", "source": "manual"}]
    for project in projects[:3]:
        _product(client, project["id"], quoted_total_kurus=10_000_000, pricing_state="offered", factors=factors)
    target = _product(client, projects[3]["id"], quote_date="2026-03-10", quantity="100")
    suggestion = _suggest(client, target["id"])
    warnings = " ".join(suggestion["explanation"]["warnings"])
    assert "referans fiyat kullanıldı" in warnings and "Miktar farkı büyük" in warnings
    assert suggestion["confidence"] == "low"


def test_single_historical_outlier_does_not_shift_price_baseline(client):
    material = _material(client, name="Kulp", unit="adet")
    supplier = _supplier(client)
    prices = [100_000] * 4 + [100_000, 300_000, 100_000] + [100_000]
    for index, price in enumerate(prices):
        _purchase(client, supplier["id"], material["id"], f"kulp-{index}", f"2026-02-{index + 1:02d}", "adet", price)
    row = client.get("/api/v1/analytics/ml/insights?as_of=2026-03-10").json()["price_anomalies"][0]
    assert abs(row["expected_unit_price_kurus"] - 100_000) <= 1_000
    assert abs(row["deviation_percent"]) < 2
    assert row["is_anomaly"] is False


def _anomaly_series(client, name="Ray"):
    material = _material(client, name=name, unit="adet")
    supplier = _supplier(client)
    for index, price in enumerate([100_000, 101_000, 99_000, 100_500, 100_000, 400_000]):
        _purchase(client, supplier["id"], material["id"], f"{name}-{index}", f"2026-02-{index + 1:02d}", "adet", price)
    return material, supplier


def test_wrong_feedback_dismisses_signal_until_new_data_arrives(client):
    material, supplier = _anomaly_series(client)
    day = "?as_of=2026-03-10"
    row = client.get(f"/api/v1/analytics/ml/insights{day}").json()["price_anomalies"][0]
    assert row["is_anomaly"] is True and row["dismissed"] is False
    assert any(item["type"] == "price_anomaly" for item in client.get(f"/api/v1/analytics/savings{day}").json()["opportunities"])

    run = client.post("/api/v1/analytics/ml/run", json={"as_of": "2026-03-10", "models": ["price_anomaly"]}).json()
    prediction = client.get("/api/v1/analytics/ml/predictions", params={"run_id": run["runs"][0]["id"]}).json()[0]
    assert client.post(f"/api/v1/analytics/ml/predictions/{prediction['id']}/feedback", json={"feedback": "wrong"}).status_code == 200

    hidden = client.get(f"/api/v1/analytics/ml/insights{day}").json()["price_anomalies"][0]
    assert hidden["dismissed"] is True and hidden["user_feedback"] == "wrong" and hidden["is_anomaly"] is True
    savings = client.get(f"/api/v1/analytics/savings{day}").json()["opportunities"]
    assert not any(item["type"] == "price_anomaly" for item in savings)

    # Aynı gün yeniden çalıştırma geri bildirimi silmez ve satır çoğaltmaz.
    client.post("/api/v1/analytics/ml/run", json={"as_of": "2026-03-10", "models": ["price_anomaly"]})
    again = client.get("/api/v1/analytics/ml/predictions").json()
    assert len([p for p in again if p["prediction_type"] == "price_anomaly"]) == 1
    assert client.get(f"/api/v1/analytics/ml/insights{day}").json()["price_anomalies"][0]["dismissed"] is True

    # Yeni veri gelince sinyal yeniden değerlendirilir.
    _purchase(client, supplier["id"], material["id"], "Ray-new", "2026-03-09", "adet", 410_000)
    revived = client.get(f"/api/v1/analytics/ml/insights{day}").json()["price_anomalies"][0]
    assert revived["dismissed"] is False


def test_useful_feedback_does_not_dismiss(client):
    _anomaly_series(client, name="Menteşe")
    run = client.post("/api/v1/analytics/ml/run", json={"as_of": "2026-03-10", "models": ["price_anomaly"]}).json()
    prediction = client.get("/api/v1/analytics/ml/predictions", params={"run_id": run["runs"][0]["id"]}).json()[0]
    client.post(f"/api/v1/analytics/ml/predictions/{prediction['id']}/feedback", json={"feedback": "useful"})
    row = client.get("/api/v1/analytics/ml/insights?as_of=2026-03-10").json()["price_anomalies"][0]
    assert row["dismissed"] is False and row["user_feedback"] == "useful"


def test_savings_total_is_split_into_groups(client):
    _anomaly_series(client, name="Çekmece")
    body = client.get("/api/v1/analytics/savings?as_of=2026-03-10").json()
    assert body["by_group"]["saving"]["count"] >= 1
    assert sum(slot["estimated_impact_kurus"] for slot in body["by_group"].values()) == body["total_estimated_impact_kurus"]


def test_target_margin_is_margin_on_price_and_bounded(client):
    project = make_project(client, name="Marj")
    response = client.post(
        f"/api/v1/projects/{project['id']}/products",
        json={"product_type": "Dolap", "quantity": "1", "unit": "adet", "quote_date": "2026-03-10", "target_margin_percent": "100"},
    )
    assert response.status_code == 422
