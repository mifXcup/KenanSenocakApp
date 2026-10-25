from __future__ import annotations


def create_project(client):
    return client.post(
        "/api/v1/projects",
        json={
            "name": "Villa Projesi",
            "customer_name": "Müşteri",
            "budget_kurus": 2000000,
            "contract_amount_kurus": 3000000,
        },
    ).json()


def test_personnel_site_work_and_project_cost_flow(client):
    project = create_project(client)
    employee = client.post(
        "/api/v1/employees",
        json={"name": "Ahmet Usta", "role": "Montaj", "daily_rate_kurus": 80000},
    ).json()
    site = client.post(
        "/api/v1/sites",
        json={"name": "Villa Şantiyesi", "project_id": project["id"]},
    ).json()
    work = client.post(
        "/api/v1/work-logs",
        json={
            "employee_id": employee["id"],
            "project_id": project["id"],
            "site_id": site["id"],
            "work_date": "2026-10-26",
            "hours": "4",
        },
    )
    assert work.status_code == 201
    assert work.json()["amount_kurus"] == 40000

    expense = client.post(
        "/api/v1/project-expenses",
        json={
            "project_id": project["id"],
            "site_id": site["id"],
            "expense_date": "2026-10-26",
            "category": "shipping",
            "amount_kurus": 15000,
            "description": "Nakliye",
        },
    )
    assert expense.status_code == 201

    summary = client.get(f"/api/v1/projects/{project['id']}/cost-summary")
    assert summary.status_code == 200
    assert summary.json()["labor_kurus"] == 40000
    assert summary.json()["shipping_kurus"] == 15000
    assert summary.json()["total_cost_kurus"] == 55000
    assert summary.json()["budget_variance_kurus"] == 1945000
    assert summary.json()["estimated_profit_kurus"] == 2945000


def test_personnel_payment_reverse_and_missing_rate(client):
    employee = client.post("/api/v1/employees", json={"name": "Ücretsiz Tanım"}).json()
    missing_rate = client.post(
        "/api/v1/work-logs",
        json={"employee_id": employee["id"], "work_date": "2026-10-26", "hours": "8"},
    )
    assert missing_rate.status_code == 422
    assert missing_rate.json()["error"]["code"] == "missing_labor_rate"

    payment = client.post(
        "/api/v1/employee-payments",
        json={
            "employee_id": employee["id"],
            "payment_date": "2026-10-26",
            "amount_kurus": 50000,
            "payment_type": "advance",
        },
    ).json()
    reversed_payment = client.post(f"/api/v1/employee-payments/{payment['id']}/reverse")
    assert reversed_payment.status_code == 200
    assert reversed_payment.json()["status"] == "reversed"


def test_site_project_mismatch_is_rejected_and_cancelled_cost_is_removed(client):
    first = create_project(client)
    second = client.post(
        "/api/v1/projects", json={"name": "İkinci Proje", "customer_name": "Müşteri 2"}
    ).json()
    site = client.post(
        "/api/v1/sites", json={"name": "Birinci Şantiye", "project_id": first["id"]}
    ).json()
    mismatch = client.post(
        "/api/v1/project-expenses",
        json={
            "project_id": second["id"],
            "site_id": site["id"],
            "expense_date": "2026-10-26",
            "category": "site",
            "amount_kurus": 10000,
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "site_project_mismatch"

    expense = client.post(
        "/api/v1/project-expenses",
        json={
            "project_id": first["id"],
            "expense_date": "2026-10-26",
            "category": "other",
            "amount_kurus": 10000,
        },
    ).json()
    assert client.post(f"/api/v1/project-expenses/{expense['id']}/cancel").status_code == 200
    assert client.get(f"/api/v1/projects/{first['id']}/cost-summary").json()["other_kurus"] == 0
