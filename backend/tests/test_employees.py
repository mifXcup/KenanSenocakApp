from __future__ import annotations

from datetime import date

from ks_yonetim import clock


def make_employee(client, **overrides):
    payload = {"name": "Ahmet Usta", "wage_type": "daily", "current_rate_kurus": 80000}
    payload.update(overrides)
    response = client.post("/api/v1/employees", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_employee_with_new_wage_model_and_legacy_daily_rate(client):
    modern = make_employee(
        client,
        wage_type="monthly",
        current_rate_kurus=3000000,
        employment_start_date="2026-01-05",
        iban="tr33 0006 1005 1978 6457 8413 26",
        payment_note="Hafta sonu elden",
    )
    assert modern["wage_type"] == "monthly"
    assert modern["current_rate_kurus"] == 3000000
    assert modern["daily_rate_kurus"] is None
    assert modern["employment_state"] == "active"
    assert modern["iban"] == "TR330006100519786457841326"

    legacy = client.post("/api/v1/employees", json={"name": "Eski İstemci", "daily_rate_kurus": 90000})
    assert legacy.status_code == 201
    assert legacy.json()["wage_type"] == "daily"
    assert legacy.json()["current_rate_kurus"] == 90000
    assert legacy.json()["daily_rate_kurus"] == 90000

    rates = client.get(f"/api/v1/employees/{modern['id']}/wage-rates").json()
    assert len(rates) == 1
    assert rates[0]["effective_from"] == "2026-01-05"
    assert rates[0]["effective_to"] is None

    conflict = client.post(
        "/api/v1/employees",
        json={"name": "Çelişki", "wage_type": "hourly", "daily_rate_kurus": 1000},
    )
    assert conflict.status_code == 422


def test_employee_list_filters_patch_and_archive(client):
    first = make_employee(client, name="Birinci Usta")
    make_employee(client, name="İkinci Usta", employment_state="left")

    left = client.get("/api/v1/employees", params={"employment_state": "left"}).json()
    assert [item["name"] for item in left] == ["İkinci Usta"]
    found = client.get("/api/v1/employees", params={"q": "birinci"}).json()
    assert [item["id"] for item in found] == [first["id"]]
    assert client.get("/api/v1/employees", params={"limit": 1}).json().__len__() == 1

    patched = client.patch(
        f"/api/v1/employees/{first['id']}",
        json={"role": "Kalfa", "employment_end_date": None, "note": "Not"},
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "Kalfa"
    assert client.patch(f"/api/v1/employees/{first['id']}", json={}).status_code == 422
    assert (
        client.patch(f"/api/v1/employees/{first['id']}", json={"current_rate_kurus": 5}).status_code
        == 422
    )
    bad_dates = client.patch(
        f"/api/v1/employees/{first['id']}",
        json={"employment_start_date": "2026-05-01", "employment_end_date": "2026-04-01"},
    )
    assert bad_dates.status_code == 422

    archived = client.post(f"/api/v1/employees/{first['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["employment_state"] == "inactive"
    assert client.post(f"/api/v1/employees/{first['id']}/archive").status_code == 200
    listed = [item["id"] for item in client.get("/api/v1/employees").json()]
    assert first["id"] not in listed
    with_archived = client.get("/api/v1/employees", params={"include_archived": "true"}).json()
    assert first["id"] in [item["id"] for item in with_archived]
    assert client.patch(f"/api/v1/employees/{first['id']}", json={"note": "x"}).status_code == 409


def test_wage_rates_do_not_overlap_and_close_previous_period(client, monkeypatch):
    # "Güncel ücret" iş tarihine göre türetilir; test sistem saatine değil sabit tarihe bağlıdır.
    monkeypatch.setattr(clock, "business_today", lambda: date(2026, 10, 1))
    employee = make_employee(client, rate_effective_from="2026-01-01")
    url = f"/api/v1/employees/{employee['id']}/wage-rates"

    raise_rate = client.post(
        url,
        json={
            "effective_from": "2026-07-01",
            "wage_type": "daily",
            "rate_kurus": 100000,
            "reason": "Yıllık zam",
        },
    )
    assert raise_rate.status_code == 201
    rates = client.get(url).json()
    assert [(r["effective_from"], r["effective_to"], r["rate_kurus"]) for r in rates] == [
        ("2026-07-01", None, 100000),
        ("2026-01-01", "2026-06-30", 80000),
    ]

    overlap = client.post(
        url, json={"effective_from": "2026-03-01", "wage_type": "daily", "rate_kurus": 90000}
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "wage_rate_overlap"
    same_start = client.post(
        url, json={"effective_from": "2026-07-01", "wage_type": "hourly", "rate_kurus": 5000}
    )
    assert same_start.status_code == 409
    inside = client.post(
        url,
        json={
            "effective_from": "2026-08-01",
            "effective_to": "2026-08-31",
            "wage_type": "daily",
            "rate_kurus": 1,
        },
    )
    assert inside.status_code == 409
    backwards = client.post(
        url,
        json={
            "effective_from": "2026-09-10",
            "effective_to": "2026-09-01",
            "wage_type": "daily",
            "rate_kurus": 1,
        },
    )
    assert backwards.status_code == 422

    # Bugün için geçerli ücret kartta görünür; geçmiş dönem kaydı değişmedi.
    card = client.get("/api/v1/employees").json()[0]
    assert card["current_rate_kurus"] == 100000
    old = next(r for r in client.get(url).json() if r["effective_from"] == "2026-01-01")
    assert old["rate_kurus"] == 80000


def test_wage_rate_cancel_and_future_rate(client):
    employee = make_employee(client, rate_effective_from="2026-01-01")
    url = f"/api/v1/employees/{employee['id']}/wage-rates"
    future = client.post(
        url, json={"effective_from": "2099-01-01", "wage_type": "daily", "rate_kurus": 500000}
    ).json()
    # Gelecek tarihli ücret bugünkü kartı değiştirmez.
    assert client.get("/api/v1/employees").json()[0]["current_rate_kurus"] == 80000
    cancelled = client.post(f"{url}/{future['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.post(f"{url}/{future['id']}/cancel").status_code == 404
    # İptal edilen dönem tekrar kullanılabilir.
    again = client.post(
        url, json={"effective_from": "2099-01-01", "wage_type": "daily", "rate_kurus": 600000}
    )
    assert again.status_code == 201
