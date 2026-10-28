from __future__ import annotations

from finance_helpers import make_material, make_purchase, make_supplier
from helpers import make_project

API = "/api/v1"


def setup(client):
    project = make_project(client)  # sözleşme 3.000.000, proje bütçesi 2.000.000
    pid = project["id"]
    for category, amount in (("material", 500_000), ("labor", 300_000)):
        client.post(
            f"{API}/projects/{pid}/budget-lines",
            json={"category": category, "title": category, "amount_kurus": amount},
        )
    supplier, material = make_supplier(client), make_material(client)
    make_purchase(client, supplier, material, pid, 100_000, "pur-fc-000001")
    return project


def put(client, pid, *items):
    return client.put(f"{API}/projects/{pid}/cost-forecasts", json={"items": list(items)})


def item(category, estimate, reason="Yönetici tahmini", day="2026-03-01"):
    return {
        "category": category,
        "remaining_estimate_kurus": estimate,
        "as_of_date": day,
        "reason": reason,
    }


def categories(client, pid):
    return {c["category"]: c for c in client.get(f"{API}/projects/{pid}/profitability").json()["categories"]}


def test_without_manual_forecast_auto_residual_is_used(client):
    pid = setup(client)["id"]
    material = categories(client, pid)["material"]
    assert material["forecast_source"] == "auto"
    assert material["remaining_estimate_kurus"] == 400_000 == material["auto_remaining_estimate_kurus"]
    listing = client.get(f"{API}/projects/{pid}/cost-forecasts").json()["forecasts"]
    assert {f["category"]: f["forecast_source"] for f in listing}["material"] == "auto"
    assert client.get(f"{API}/projects/{pid}/profitability").json()["manual_forecast_count"] == 0


def test_manual_forecast_above_budget_drives_forecast_cost_and_profit(client):
    pid = setup(client)["id"]
    before = client.get(f"{API}/projects/{pid}/profitability").json()
    response = put(client, pid, item("material", 700_000, "Fiyat artışı bekleniyor"))
    assert response.status_code == 200

    after = client.get(f"{API}/projects/{pid}/profitability").json()
    material = {c["category"]: c for c in after["categories"]}["material"]
    assert material["forecast_source"] == "manual"
    assert material["remaining_estimate_kurus"] == 700_000  # bütçeyi (500.000) aşabilir
    assert material["auto_remaining_estimate_kurus"] == 400_000
    assert material["forecast_kurus"] == 800_000 and material["variance_kurus"] == -300_000
    assert (material["forecast_revision_no"], material["forecast_reason"]) == (1, "Fiyat artışı bekleniyor")
    assert material["forecast_as_of_date"] == "2026-03-01"
    assert after["manual_forecast_count"] == 1
    assert after["forecast_cost_at_completion_kurus"] == before["forecast_cost_at_completion_kurus"] + 300_000
    assert after["estimated_profit_kurus"] == before["estimated_profit_kurus"] - 300_000


def test_manual_forecast_lower_than_auto_residual(client):
    pid = setup(client)["id"]
    assert put(client, pid, item("labor", 100_000, "İş büyük ölçüde bitti")).status_code == 200
    labor = categories(client, pid)["labor"]
    assert labor["auto_remaining_estimate_kurus"] == 300_000
    assert (labor["remaining_estimate_kurus"], labor["forecast_kurus"]) == (100_000, 100_000)
    assert labor["variance_kurus"] == 200_000
    # Manuel olmayan kategori otomatik kalır; 0 tahmin de geçerli bir manuel değerdir.
    assert categories(client, pid)["material"]["forecast_source"] == "auto"
    assert put(client, pid, item("labor", 0, "Tamamlandı")).status_code == 200
    assert categories(client, pid)["labor"]["forecast_source"] == "manual"
    assert categories(client, pid)["labor"]["remaining_estimate_kurus"] == 0


def test_forecast_requires_reason_and_valid_values(client):
    pid = setup(client)["id"]
    assert put(client, pid, {**item("material", 1), "reason": ""}).status_code == 422
    assert put(client, pid, {**item("material", 1), "reason": "ab"}).status_code == 422
    missing = {"category": "material", "remaining_estimate_kurus": 1, "as_of_date": "2026-03-01"}
    assert put(client, pid, missing).status_code == 422
    assert put(client, pid, item("material", -5)).status_code == 422
    assert put(client, pid, item("bilinmeyen", 5)).status_code == 422
    assert put(client, pid, item("material", 1), item("material", 2)).status_code == 422
    assert client.put(f"{API}/projects/{pid}/cost-forecasts", json={"items": []}).status_code == 422
    assert client.get(f"{API}/projects/{pid}/cost-forecasts/history").json()["revisions"] == []


def test_revision_history_and_returning_to_auto(client):
    pid = setup(client)["id"]
    put(client, pid, item("material", 700_000, "İlk tahmin", "2026-03-01"))
    put(client, pid, item("material", 450_000, "Tedarikçi indirimi", "2026-03-15"))
    history = client.get(f"{API}/projects/{pid}/cost-forecasts/history", params={"category": "material"}).json()
    revisions = history["revisions"]
    assert [(r["revision_no"], r["remaining_estimate_kurus"], r["is_current"]) for r in revisions] == [
        (1, 700_000, False), (2, 450_000, True)
    ]
    assert revisions[1]["reason"] == "Tedarikçi indirimi" and revisions[1]["as_of_date"] == "2026-03-15"
    assert categories(client, pid)["material"]["forecast_revision_no"] == 2

    cleared = put(client, pid, item("material", None, "Manuel tahmin kaldırıldı", "2026-04-01"))
    assert cleared.status_code == 200
    material = categories(client, pid)["material"]
    assert material["forecast_source"] == "auto" and material["remaining_estimate_kurus"] == 400_000
    revisions = client.get(f"{API}/projects/{pid}/cost-forecasts/history").json()["revisions"]
    assert [(r["revision_no"], r["forecast_source"], r["is_current"]) for r in revisions] == [
        (1, "manual", False), (2, "manual", False), (3, "auto", True)
    ]
    again = put(client, pid, item("material", None, "Yine kaldır"))
    assert again.status_code == 409 and again.json()["error"]["code"] == "no_manual_forecast"
    # Yeniden manuel tahmin revizyon numarasını sürdürür.
    put(client, pid, item("material", 123, "Yeniden tahmin"))
    assert categories(client, pid)["material"]["forecast_revision_no"] == 4


def test_batch_update_is_atomic(client):
    pid = setup(client)["id"]
    failed = put(client, pid, item("material", 1_000), item("labor", None, "Kaldırılacak yok"))
    assert failed.status_code == 409
    assert categories(client, pid)["material"]["forecast_source"] == "auto"
    assert client.get(f"{API}/projects/{pid}/cost-forecasts/history").json()["revisions"] == []
    ok = put(client, pid, item("material", 1_000), item("labor", 2_000))
    assert ok.status_code == 200
    assert {f["category"]: f["remaining_estimate_kurus"] for f in ok.json()["forecasts"]}["labor"] == 2_000


def test_profitability_and_drilldown_agree_on_forecast(client):
    pid = setup(client)["id"]
    put(client, pid, item("material", 700_000), item("shipping", 25_000, "Nakliye eklenecek"))
    profit = client.get(f"{API}/projects/{pid}/profitability").json()
    drill = client.get(f"{API}/projects/{pid}/cost-drilldown").json()
    by_profit = {c["category"]: c for c in profit["categories"]}
    for row in drill["categories"]:
        reference = by_profit[row["category"]]
        assert row["remaining_estimate_kurus"] == reference["remaining_estimate_kurus"]
        assert row["forecast_source"] == reference["forecast_source"]
        assert row["forecast_kurus"] == reference["forecast_kurus"]
        assert row["actual_kurus"] == reference["actual_kurus"]
    # Bütçesi olmayan kategoriye de manuel tahmin girilebilir.
    assert by_profit["shipping"]["budget_kurus"] is None
    assert by_profit["shipping"]["remaining_estimate_kurus"] == 25_000
    total = sum(r["forecast_kurus"] for r in drill["categories"])
    assert profit["forecast_cost_at_completion_kurus"] == total
    assert drill["actual_total_kurus"] == profit["actual_cost_kurus"]
    assert sum(r["remaining_estimate_kurus"] for r in drill["categories"]) == profit["remaining_estimate_kurus"]


def test_manual_forecast_with_project_level_budget_only(client):
    project = make_project(client, budget_kurus=1_000_000)
    pid = project["id"]
    supplier, material = make_supplier(client), make_material(client)
    make_purchase(client, supplier, material, pid, 300_000, "pur-fc-000002")
    auto = client.get(f"{API}/projects/{pid}/profitability").json()
    assert auto["budget_source"] == "project_budget" and auto["remaining_estimate_kurus"] == 700_000

    put(client, pid, item("labor", 200_000, "Montaj ekibi tahmini"))
    manual = client.get(f"{API}/projects/{pid}/profitability").json()
    # Manuel tahmin proje bütçesinden harcanmış sayılır; kalan genel artık buna göre azalır.
    assert manual["remaining_estimate_kurus"] == 700_000
    assert manual["forecast_cost_at_completion_kurus"] == 1_000_000
    put(client, pid, item("labor", 900_000, "Beklenenden büyük"))
    over = client.get(f"{API}/projects/{pid}/profitability").json()
    assert over["forecast_cost_at_completion_kurus"] == 300_000 + 900_000
    assert client.get(f"{API}/projects/yok/cost-forecasts").status_code == 404
