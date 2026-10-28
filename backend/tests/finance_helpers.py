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


def build_portfolio(client):
    """Tüm B4 raporlarını besleyen ortak senaryo (iş tarihi 2026-03-10)."""
    from helpers import log_work, make_employee, make_project

    ids: dict = {}
    s1, s2 = make_supplier(client, "Birinci Tedarikçi"), make_supplier(client, "İkinci Tedarikçi")
    material = make_material(client, "MDF Levha")
    project = make_project(client, "Villa Projesi", customer_name="Güneş İnşaat")
    other = make_project(client, "Daire Projesi", customer_name="Güneş İnşaat", contract_amount_kurus=1_000_000)
    pid, cid = project["id"], project["customer_id"]
    ids.update(project=project, other=other, customer_id=cid, supplier=s1, supplier2=s2, material=material)

    client.post(
        f"{API}/projects/{pid}/budget-lines",
        json={"category": "material", "title": "MDF", "amount_kurus": 100_000},
    )
    order = client.post(f"{API}/projects/{pid}/change-orders", json={"title": "Ek dolap", "amount_kurus": 100_000}).json()
    client.post(f"{API}/projects/{pid}/change-orders/{order['id']}/approve")
    ids["change_order"] = order

    ids["pu1"] = make_purchase(
        client, s1, material, pid, 150_000, "pur-b4-000001", quantity="10.000", unit="levha",
        purchase_date="2026-02-01", due_date="2026-03-15",
    )
    ids["pu2"] = make_purchase(
        client, s1, material, pid, 60_000, "pur-b4-000002", state="planned", purchase_date="2026-02-05",
        due_date="2026-03-20",
    )
    pu3 = make_purchase(
        client, s1, material, pid, 90_000, "pur-b4-000003", state="ordered", quantity="9.000", unit="levha",
        purchase_date="2026-02-08",
    )
    ids["pu3"] = pu3
    for index, (day, qty) in enumerate((("2026-02-10", "3.000"), ("2026-03-02", "3.000"), ("2026-03-05", "4.000"))):
        assert receipt(client, pu3["id"], day, 30_000, f"teslim-b4-00000{index}", quantity=qty).status_code == 201
    ids["pu4"] = make_purchase(client, s2, material, None, 80_000, "pur-b4-000004", purchase_date="2026-02-20")
    client.post(
        f"{API}/payments",
        json={"supplier_id": s1["id"], "purchase_id": ids["pu1"]["id"], "payment_date": "2026-02-10",
              "amount_kurus": 50_000, "idempotency_key": "pay-b4-0000001"},
    )

    worker = make_employee(client, "Ahmet Usta", "daily", 80000)
    ids["worker"] = worker
    for day in ("2026-02-02", "2026-02-03"):
        log_work(client, worker["id"], day, project_id=pid)
    client.post(
        f"{API}/project-expenses",
        json={"project_id": pid, "expense_date": "2026-02-15", "category": "rework", "amount_kurus": 20_000},
    )
    client.post(
        f"{API}/project-expenses",
        json={"project_id": pid, "expense_date": "2026-02-16", "category": "shipping", "amount_kurus": 10_000},
    )
    client.post(
        f"{API}/material-movements",
        json={"material_id": material["id"], "project_id": pid, "movement_date": "2026-02-18",
              "movement_type": "waste", "quantity": "1.000", "unit": "levha", "confidence": "estimated",
              "amount_kurus": 5_000},
    )

    move(client, cid, "accrual", 400_000, "tahakkuk-b4-0001", day="2026-02-01", project_id=pid)
    plan_a = schedule(client, cid, "Teslim tahsilatı", 250_000, "2026-03-20", project_id=pid)
    plan_b = schedule(client, cid, "Peşinat", 150_000, "2026-03-01", project_id=pid)
    move(client, cid, "collection", 100_000, "tahsilat-b4-001", day="2026-02-20", project_id=pid,
         receivable_schedule_id=plan_b["id"])
    unlinked = move(client, cid, "collection", 30_000, "tahsilat-b4-002", day="2026-02-25").json()
    ids.update(plan_a=plan_a, plan_b=plan_b, unlinked_collection=unlinked)

    client.put(f"{API}/settings/attendance", json={"default_salary_day": 5})
    period = client.post(f"{API}/payroll-periods", json={"period_start": "2026-02-01", "period_end": "2026-02-28"}).json()
    client.post(f"{API}/payroll-periods/{period['id']}/calculate", json={})
    client.post(f"{API}/payroll-periods/{period['id']}/finalize", json={})
    ids["period"] = period
    return ids
