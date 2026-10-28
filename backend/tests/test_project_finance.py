from __future__ import annotations

from helpers import log_work, make_employee, make_project

API = "/api/v1"


def make_supplier(client, name="Tedarikçi A"):
    response = client.post(f"{API}/suppliers", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def make_material(client, name="MDF"):
    response = client.post(
        f"{API}/materials", json={"name": name, "default_unit": "levha", "tracking_mode": "exact"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_purchase(client, supplier, material, project_id, total, key, state="received", **extra):
    payload = {
        "supplier_id": supplier["id"],
        "material_id": material["id"],
        "project_id": project_id,
        "purchase_date": "2026-02-01",
        "total_kurus": total,
        "idempotency_key": key,
        "lifecycle_state": state,
        **extra,
    }
    response = client.post(f"{API}/purchases", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def supplier_balance(client, supplier):
    return client.get(f"{API}/suppliers/{supplier['id']}/balance").json()["remaining_kurus"]


def test_budget_lines_keep_original_and_audit_revisions(client):
    project = make_project(client)
    base = f"{API}/projects/{project['id']}/budget-lines"
    material = client.post(base, json={"category": "material", "title": "MDF", "amount_kurus": 500_000})
    assert material.status_code == 201
    labor = client.post(base, json={"category": "labor", "title": "Montaj ekibi", "amount_kurus": 300_000}).json()
    line = material.json()

    no_reason = client.patch(f"{base}/{line['id']}", json={"amount_kurus": 650_000})
    assert no_reason.status_code == 422
    revised = client.patch(f"{base}/{line['id']}", json={"amount_kurus": 650_000, "reason": "Fiyat artışı"})
    assert revised.status_code == 200
    assert revised.json()["amount_kurus"] == 650_000
    assert revised.json()["original_amount_kurus"] == 500_000
    assert revised.json()["revision_no"] == 2
    # Aynı tutar yeni revizyon üretmez; yalnız başlık değişikliği gerekçe istemez.
    assert client.patch(f"{base}/{line['id']}", json={"title": "MDF 18mm"}).json()["revision_no"] == 2

    history = client.get(f"{base}/{line['id']}/revisions").json()
    assert [(r["revision_no"], r["previous_amount_kurus"], r["amount_kurus"]) for r in history] == [
        (1, None, 500_000),
        (2, 500_000, 650_000),
    ]
    assert history[1]["reason"] == "Fiyat artışı"

    listing = client.get(base).json()
    assert listing["original_total_kurus"] == 800_000
    assert listing["revised_total_kurus"] == 950_000

    assert client.post(f"{base}/{labor['id']}/cancel").status_code == 200
    assert client.post(f"{base}/{labor['id']}/cancel").status_code == 409
    cancelled = client.patch(f"{base}/{labor['id']}", json={"title": "Yeni"})
    assert cancelled.status_code == 409 and cancelled.json()["error"]["code"] == "budget_line_cancelled"
    assert [x["id"] for x in client.get(base).json()["lines"]] == [line["id"]]
    assert len(client.get(base, params={"include_cancelled": True}).json()["lines"]) == 2
    assert client.post(base, json={"category": "unknown", "title": "x1", "amount_kurus": 1}).status_code == 422


def test_change_order_state_machine_and_revised_contract(client):
    project = make_project(client)  # sözleşme 3.000.000
    base = f"{API}/projects/{project['id']}/change-orders"
    extra = client.post(base, json={"title": "Ek dolap", "amount_kurus": 400_000}).json()
    cut = client.post(base, json={"title": "Kapsam daraltma", "amount_kurus": -100_000}).json()
    waiting = client.post(base, json={"title": "Onay bekleyen", "amount_kurus": 50_000}).json()
    assert client.post(base, json={"title": "Sıfır", "amount_kurus": 0}).status_code == 422

    assert client.post(f"{base}/{extra['id']}/approve", json={"note": "Telefon onayı"}).status_code == 200
    assert client.post(f"{base}/{cut['id']}/approve").status_code == 200
    unapproved = client.get(base).json()
    assert unapproved["approved_total_kurus"] == 300_000
    assert unapproved["pending_total_kurus"] == 50_000
    assert unapproved["revised_contract_kurus"] == 3_300_000  # onaysız ek iş dahil değil

    assert client.post(f"{base}/{waiting['id']}/reject").status_code == 200
    again = client.post(f"{base}/{waiting['id']}/approve")
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    locked = client.patch(f"{base}/{extra['id']}", json={"amount_kurus": 1})
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "change_order_locked"
    assert client.post(f"{base}/{extra['id']}/approve").status_code == 409

    assert client.post(f"{base}/{extra['id']}/cancel").status_code == 200
    final = client.get(base).json()
    assert final["approved_total_kurus"] == -100_000
    assert final["revised_contract_kurus"] == 2_900_000
    draft = client.post(base, json={"title": "Taslak", "amount_kurus": 10_000}).json()
    assert client.patch(f"{base}/{draft['id']}", json={"amount_kurus": 20_000}).json()["amount_kurus"] == 20_000
    assert client.get(base, params={"state": "rejected"}).json()["change_orders"][0]["id"] == waiting["id"]


def test_approved_change_order_with_accrual_cannot_be_cancelled_until_reversed(client):
    project = make_project(client, customer_name="Ek İş Müşteri")
    base = f"{API}/projects/{project['id']}/change-orders"
    order = client.post(base, json={"title": "Ek iş", "amount_kurus": 100_000}).json()
    client.post(f"{base}/{order['id']}/approve")
    accrual = client.post(
        f"{API}/customer-financial-movements",
        json={
            "customer_id": project["customer_id"],
            "project_id": project["id"],
            "change_order_id": order["id"],
            "movement_type": "accrual",
            "amount_kurus": 100_000,
            "movement_date": "2026-03-01",
            "idempotency_key": "acc-co-000001",
        },
    ).json()
    blocked = client.post(f"{base}/{order['id']}/cancel")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "change_order_has_accruals"
    assert client.post(f"{API}/customer-financial-movements/{accrual['id']}/reverse").status_code == 201
    assert client.post(f"{base}/{order['id']}/cancel").status_code == 200


def test_purchase_lifecycle_controls_debt_and_cost(client):
    project = make_project(client)
    supplier, material = make_supplier(client), make_material(client)
    received = make_purchase(client, supplier, material, project["id"], 100_000, "pur-recv-0001")
    assert received["lifecycle_state"] == "received" and received["received_kurus"] == 100_000
    planned = make_purchase(client, supplier, material, project["id"], 200_000, "pur-plan-0001", state="planned")
    assert planned["received_kurus"] == 0 and planned["lifecycle_state"] == "planned"

    # Planlı satın alma borç ve maliyet doğurmaz; yalnız taahhüttür.
    assert supplier_balance(client, supplier) == 100_000
    assert client.get(f"{API}/dashboard/summary").json()["purchase_total_kurus"] == 100_000
    assert client.get(f"{API}/projects/{project['id']}/cost-summary").json()["purchase_kurus"] == 100_000
    assert client.get(f"{API}/projects/{project['id']}/profitability").json()["commitment_kurus"] == 200_000

    path = f"{API}/purchases/{planned['id']}/lifecycle"
    assert client.post(path, json={"state": "ordered"}).status_code == 200
    backwards = client.post(path, json={"state": "received"})  # ordered -> received serbesttir
    assert backwards.status_code == 200
    backwards_again = client.post(path, json={"state": "ordered"})
    assert backwards_again.status_code == 409
    assert backwards_again.json()["error"]["code"] == "invalid_transition"


def test_partial_receipt_and_advance_payment_on_ordered_purchase(client):
    project = make_project(client)
    supplier, material = make_supplier(client), make_material(client)
    order = make_purchase(
        client, supplier, material, project["id"], 200_000, "pur-part-0001", state="ordered", paid_kurus=30_000
    )
    # Teslim edilmemiş siparişe yapılan ön ödeme tedarikçi avansıdır.
    assert supplier_balance(client, supplier) == -30_000
    aging = client.get(f"{API}/suppliers/{supplier['id']}/aging", params={"as_of": "2026-03-01"}).json()
    assert aging["credit_kurus"] == 30_000 and aging["total_open_kurus"] == 0

    path = f"{API}/purchases/{order['id']}/lifecycle"
    for bad in (200_000, 250_000):
        response = client.post(path, json={"state": "partially_received", "received_kurus": bad})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_received_amount"
    assert client.post(path, json={"state": "partially_received"}).status_code == 422
    assert client.post(path, json={"state": "received", "received_kurus": 5}).status_code == 422

    partial = client.post(path, json={"state": "partially_received", "received_kurus": 80_000})
    assert partial.status_code == 200 and partial.json()["received_kurus"] == 80_000
    assert supplier_balance(client, supplier) == 50_000
    profit = client.get(f"{API}/projects/{project['id']}/profitability").json()
    assert profit["commitment_kurus"] == 120_000
    smaller = client.post(path, json={"state": "partially_received", "received_kurus": 80_000})
    assert smaller.status_code == 422

    full = client.post(path, json={"state": "received"})
    assert full.status_code == 200 and full.json()["received_kurus"] == 200_000
    assert supplier_balance(client, supplier) == 170_000
    cancel = client.post(path, json={"state": "cancelled"})
    assert cancel.status_code == 409 and cancel.json()["error"]["code"] == "purchase_has_payments"


def test_cancelled_lifecycle_and_purchase_without_payments(client):
    supplier, material = make_supplier(client), make_material(client)
    planned = make_purchase(client, supplier, material, None, 50_000, "pur-canc-0001", state="planned")
    cancelled = client.post(f"{API}/purchases/{planned['id']}/lifecycle", json={"state": "cancelled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["lifecycle_state"] == "cancelled" and cancelled.json()["status"] == "cancelled"
    again = client.post(f"{API}/purchases/{planned['id']}/lifecycle", json={"state": "ordered"})
    assert again.status_code == 404  # iptal edilmiş satın alma aktif değildir


def test_profitability_and_drilldown_are_consistent(client):
    project = make_project(client)  # sözleşme 3.000.000, proje bütçesi 2.000.000
    pid = project["id"]
    budgets = f"{API}/projects/{pid}/budget-lines"
    for category, amount in (("material", 500_000), ("labor", 300_000), ("shipping", 50_000)):
        client.post(budgets, json={"category": category, "title": category.title(), "amount_kurus": amount})
    order = client.post(f"{API}/projects/{pid}/change-orders", json={"title": "Ek", "amount_kurus": 200_000}).json()
    client.post(f"{API}/projects/{pid}/change-orders/{order['id']}/approve")

    supplier, material = make_supplier(client), make_material(client)
    received = make_purchase(client, supplier, material, pid, 400_000, "pur-prof-0001")
    planned = make_purchase(client, supplier, material, pid, 150_000, "pur-prof-0002", state="planned")
    employee = make_employee(client)
    labor_log = log_work(client, employee["id"], "2026-02-02", project_id=pid, normal_hours="8").json()
    labor = labor_log["amount_kurus"]
    assert labor > 0
    expenses = {}
    for category, amount in (("shipping", 20_000), ("subcontract", 30_000)):
        expenses[category] = client.post(
            f"{API}/project-expenses",
            json={"project_id": pid, "expense_date": "2026-02-03", "category": category, "amount_kurus": amount},
        ).json()

    result = client.get(f"{API}/projects/{pid}/profitability").json()
    by_category = {c["category"]: c for c in result["categories"]}
    assert result["revised_contract_kurus"] == 3_200_000
    assert result["budget_source"] == "budget_lines"
    assert result["original_budget_kurus"] == 850_000

    material_row = by_category["material"]
    assert (material_row["actual_kurus"], material_row["commitment_kurus"]) == (400_000, 150_000)
    assert material_row["remaining_estimate_kurus"] == 0  # bütçe aşıldı; negatif tahmin yok
    assert material_row["forecast_kurus"] == 550_000 and material_row["variance_kurus"] == -50_000
    assert by_category["labor"]["remaining_estimate_kurus"] == 300_000 - labor
    assert by_category["shipping"]["remaining_estimate_kurus"] == 30_000
    assert by_category["subcontractor"]["budget_kurus"] is None
    assert by_category["subcontractor"]["actual_kurus"] == 30_000

    actual = 400_000 + labor + 20_000 + 30_000
    remaining = (300_000 - labor) + 30_000
    assert result["actual_cost_kurus"] == actual
    assert result["commitment_kurus"] == 150_000
    assert result["remaining_estimate_kurus"] == remaining
    forecast = actual + 150_000 + remaining
    assert result["forecast_cost_at_completion_kurus"] == forecast
    assert result["estimated_profit_kurus"] == 3_200_000 - forecast
    assert result["estimated_margin_percent"] == round((3_200_000 - forecast) / 3_200_000 * 100, 2)
    assert result["budget_variance_kurus"] == 850_000 - forecast
    assert result["current_profit_kurus"] == 3_200_000 - actual

    # Maliyet özetiyle aynı gerçekleşen toplam (taşeron dahil).
    summary = client.get(f"{API}/projects/{pid}/cost-summary").json()
    assert summary["total_cost_kurus"] == actual and summary["subcontract_kurus"] == 30_000

    drill = client.get(f"{API}/projects/{pid}/cost-drilldown").json()
    assert drill["actual_total_kurus"] == actual and drill["commitment_total_kurus"] == 150_000
    cats = {c["category"]: c for c in drill["categories"]}
    for name, row in by_category.items():
        assert sum(s["amount_kurus"] for s in cats[name]["actual_sources"]) == row["actual_kurus"]
        assert sum(s["amount_kurus"] for s in cats[name]["commitment_sources"]) == row["commitment_kurus"]
    material_sources = cats["material"]["actual_sources"]
    assert [s["purchase_id"] for s in material_sources] == [received["id"]]
    assert material_sources[0]["source_type"] == "purchase_receipt"
    assert [s["source_id"] for s in cats["material"]["commitment_sources"]] == [planned["id"]]
    assert [s["source_id"] for s in cats["labor"]["actual_sources"]] == [labor_log["id"]]
    assert [s["source_id"] for s in cats["shipping"]["actual_sources"]] == [expenses["shipping"]["id"]]
    assert cats["subcontractor"]["actual_sources"][0]["source_type"] == "project_expense"
    only = client.get(f"{API}/projects/{pid}/cost-drilldown", params={"category": "labor"}).json()
    assert [c["category"] for c in only["categories"]] == ["labor"]
    assert client.get(f"{API}/projects/{pid}/cost-drilldown", params={"category": "x"}).status_code == 422


def test_profitability_falls_back_to_project_budget_and_handles_missing_contract(client):
    project = make_project(client, contract_amount_kurus=None, budget_kurus=1_000_000)
    supplier, material = make_supplier(client), make_material(client)
    make_purchase(client, supplier, material, project["id"], 300_000, "pur-fall-0001")
    make_purchase(client, supplier, material, project["id"], 100_000, "pur-fall-0002", state="ordered")
    result = client.get(f"{API}/projects/{project['id']}/profitability").json()
    assert result["budget_source"] == "project_budget"
    assert result["revised_contract_kurus"] is None and result["estimated_profit_kurus"] is None
    assert result["estimated_margin_percent"] is None
    assert result["remaining_estimate_kurus"] == 600_000
    assert result["forecast_cost_at_completion_kurus"] == 1_000_000

    bare = make_project(client, name="Bütçesiz Proje", contract_amount_kurus=None, budget_kurus=None)
    empty = client.get(f"{API}/projects/{bare['id']}/profitability").json()
    assert empty["budget_source"] == "none" and empty["forecast_cost_at_completion_kurus"] == 0
    assert empty["revised_budget_kurus"] is None and empty["budget_variance_kurus"] is None
    assert client.get(f"{API}/projects/yok/profitability").status_code == 404


def test_supplier_statement_aging_and_payment_reversal(client):
    supplier, material = make_supplier(client), make_material(client)
    purchase = make_purchase(
        client, supplier, material, None, 100_000, "pur-stmt-0001", due_date="2026-02-15"
    )
    pay = client.post(
        f"{API}/payments",
        json={
            "supplier_id": supplier["id"],
            "purchase_id": purchase["id"],
            "payment_date": "2026-02-10",
            "amount_kurus": 40_000,
            "idempotency_key": "pay-stmt-0001",
        },
    ).json()
    # Kısmi ödeme sonrası kalan 60.000; vade geçince yaşlandırmaya girer.
    aging = client.get(f"{API}/suppliers/{supplier['id']}/aging", params={"as_of": "2026-03-01"}).json()
    assert aging["total_open_kurus"] == 60_000 and aging["overdue_kurus"] == 60_000
    assert {b["key"]: b["amount_kurus"] for b in aging["buckets"]}["d1_30"] == 60_000
    assert aging["items"][0]["purchase_id"] == purchase["id"]

    reversed_payment = client.post(f"{API}/payments/{pay['id']}/reverse")
    assert reversed_payment.status_code == 200
    again = client.post(f"{API}/payments/{pay['id']}/reverse")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_reversed"
    assert client.post(f"{API}/payments/yok-000/reverse").status_code == 404

    statement = client.get(f"{API}/suppliers/{supplier['id']}/statement").json()
    assert [r["row_type"] for r in statement["rows"]] == ["purchase_receipt", "payment", "payment_reversal"]
    assert statement["closing_balance_kurus"] == 100_000
    assert statement["closing_balance_kurus"] == supplier_balance(client, supplier)
    assert statement["total_increase_kurus"] - statement["total_decrease_kurus"] == 100_000

    ranged = client.get(
        f"{API}/suppliers/{supplier['id']}/statement", params={"date_from": "2026-02-05", "date_to": "2026-02-09"}
    ).json()
    assert ranged["opening_balance_kurus"] == 100_000 and ranged["rows"] == []
    assert client.get(
        f"{API}/suppliers/{supplier['id']}/statement", params={"date_from": "2026-03-01", "date_to": "2026-01-01"}
    ).status_code == 422
