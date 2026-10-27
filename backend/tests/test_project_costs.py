from __future__ import annotations

from helpers import log_work, make_employee, make_project, make_site


def purchase(client, project_id, day, total, key):
    supplier = client.post("/api/v1/suppliers", json={"name": f"Firma {key}"}).json()
    material = client.post(
        "/api/v1/materials",
        json={"name": f"Malzeme {key}", "default_unit": "adet", "tracking_mode": "value_only"},
    ).json()
    response = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "project_id": project_id,
            "purchase_date": day,
            "total_kurus": total,
            "idempotency_key": f"cost-{key}-0001",
        },
    )
    assert response.status_code == 201, response.text


def test_cost_summary_uses_accrual_not_payroll_and_excludes_cancelled(client):
    project = make_project(client, budget_kurus=1000000, contract_amount_kurus=2000000)
    site = make_site(client, project["id"])
    other_site = make_site(client, project["id"], "İkinci Şantiye")
    ahmet = make_employee(client, "Ahmet", "daily", 80000)
    mehmet = make_employee(client, "Mehmet", "monthly", 3100000)
    log_work(client, ahmet["id"], "2026-10-05", project_id=project["id"], site_id=site["id"])
    november = log_work(
        client, ahmet["id"], "2026-11-05", project_id=project["id"], site_id=other_site["id"],
        work_status="overtime", overtime_hours="2",
    ).json()
    log_work(client, mehmet["id"], "2026-10-06", project_id=project["id"])
    log_work(client, mehmet["id"], "2026-10-07", project_id=project["id"], work_status="absent")
    purchase(client, project["id"], "2026-10-02", 150000, "a")
    client.post(
        "/api/v1/project-expenses",
        json={"project_id": project["id"], "site_id": site["id"], "expense_date": "2026-10-08",
              "category": "shipping", "amount_kurus": 20000},
    )
    expected_labor = 80000 + (80000 + 30000) + 100000 + 0

    summary = client.get(f"/api/v1/projects/{project['id']}/cost-summary").json()
    assert summary["labor_accrual_kurus"] == summary["labor_kurus"] == expected_labor
    assert summary["purchase_kurus"] == 150000 and summary["shipping_kurus"] == 20000
    assert summary["total_cost_kurus"] == expected_labor + 170000
    assert summary["budget_variance_kurus"] == 1000000 - summary["total_cost_kurus"]
    assert summary["profit_margin_percent"] == round(
        (2000000 - summary["total_cost_kurus"]) / 2000000 * 100, 2
    )

    # Maaş hesabı/kesinleştirme/ödeme proje işçilik maliyetini değiştirmez ve ikinci kez saymaz.
    period = client.post(
        "/api/v1/payroll-periods",
        json={"period_start": "2026-10-01", "period_end": "2026-10-31"},
    ).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    client.post(f"/api/v1/payroll-periods/{period['id']}/finalize")
    client.post(
        "/api/v1/employee-finance/movements",
        json={"employee_id": ahmet["id"], "movement_type": "payroll_payment", "amount_kurus": 80000,
              "movement_date": "2026-11-01", "payroll_period_id": period["id"],
              "idempotency_key": "cost-pay-0001"},
    )
    assert client.get(f"/api/v1/projects/{project['id']}/cost-summary").json() == summary

    ranged = client.get(
        f"/api/v1/projects/{project['id']}/cost-summary",
        params={"date_from": "2026-11-01", "date_to": "2026-11-30"},
    ).json()
    assert ranged["labor_accrual_kurus"] == 110000 and ranged["purchase_kurus"] == 0
    bad_range = client.get(
        f"/api/v1/projects/{project['id']}/cost-summary",
        params={"date_from": "2026-12-01", "date_to": "2026-11-01"},
    )
    assert bad_range.status_code == 422

    breakdown = client.get(f"/api/v1/projects/{project['id']}/labor-breakdown").json()
    assert breakdown["labor_accrual_kurus"] == expected_labor
    assert sum(r["amount_kurus"] for r in breakdown["by_employee"]) == expected_labor
    assert sum(r["amount_kurus"] for r in breakdown["by_month"]) == expected_labor
    assert sum(r["amount_kurus"] for r in breakdown["by_site"]) == expected_labor
    assert [r["month"] for r in breakdown["by_month"]] == ["2026-10", "2026-11"]
    assert {r["work_status"] for r in breakdown["by_status"]} == {"worked", "overtime", "absent"}
    assert breakdown["by_employee"][0]["employee_name"] == "Ahmet"

    site_summary = client.get(f"/api/v1/sites/{site['id']}/cost-summary").json()
    assert site_summary["labor_accrual_kurus"] == 80000
    assert site_summary["shipping_kurus"] == 20000 and site_summary["total_cost_kurus"] == 100000

    # İptal edilen çalışma maliyetten çıkar.
    assert client.post(f"/api/v1/work-logs/{november['id']}/cancel").status_code == 200
    after = client.get(f"/api/v1/projects/{project['id']}/cost-summary").json()
    assert after["labor_accrual_kurus"] == expected_labor - 110000
    other = client.get(f"/api/v1/sites/{other_site['id']}/cost-summary").json()
    assert other["labor_accrual_kurus"] == 0
    assert client.get("/api/v1/projects/nope/cost-summary").status_code == 404
    assert client.get("/api/v1/sites/nope/cost-summary").status_code == 404


def test_project_site_mismatch_is_rejected_on_work_logs_and_expenses(client):
    first = make_project(client)
    second = make_project(client, "Başka")
    site = make_site(client, first["id"])
    employee = make_employee(client)
    rejected = log_work(client, employee["id"], "2026-10-05", project_id=second["id"], site_id=site["id"])
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "site_project_mismatch"
    no_project = log_work(client, employee["id"], "2026-10-05", site_id=site["id"])
    assert no_project.status_code == 409
    expense = client.post(
        "/api/v1/project-expenses",
        json={"project_id": second["id"], "site_id": site["id"], "expense_date": "2026-10-05",
              "category": "site", "amount_kurus": 100},
    )
    assert expense.status_code == 409
