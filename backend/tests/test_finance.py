from __future__ import annotations

import sqlite3
from contextlib import closing

from helpers import make_employee

from ks_yonetim.backup import backup_manager

URL = "/api/v1/employee-finance/movements"


def move(client, employee_id, kind, amount, key, day="2026-10-10", **extra):
    payload = {
        "employee_id": employee_id,
        "movement_type": kind,
        "amount_kurus": amount,
        "movement_date": day,
        "idempotency_key": key,
        **extra,
    }
    return client.post(URL, json=payload)


def summary(client, employee_id, as_of="2026-12-31"):
    response = client.get(
        f"/api/v1/employees/{employee_id}/financial-summary", params={"as_of": as_of}
    )
    assert response.status_code == 200, response.text
    return response.json()


def finalized_october(client, employee_id=None, **inputs):
    """Aylık 3.100.000 TL'lik personel için Ekim dönemini kesinleştirir."""
    period = client.post(
        "/api/v1/payroll-periods",
        json={"period_start": "2026-10-01", "period_end": "2026-10-31", "title": "Ekim"},
    ).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate", json=inputs)
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/finalize").status_code == 200
    return period


def test_company_and_employee_debts_are_separate_and_debt_payments_do_not_touch_salary(client):
    employee = make_employee(client, "Usta", "monthly", 3100000)
    period = client.post(
        "/api/v1/payroll-periods",
        json={"period_start": "2026-10-01", "period_end": "2026-10-31"},
    ).json()
    assert move(client, employee["id"], "advance", 500000, "adv-key-0001", "2026-10-02").status_code == 201
    debt = move(
        client, employee["id"], "employee_debt", 200000, "debt-key-0001", "2026-10-03",
        due_date="2026-10-20",
    )
    assert debt.status_code == 201 and debt.json()["direction"] == "employee_owes_company"
    client.post(
        f"/api/v1/payroll-periods/{period['id']}/calculate",
        json={"auto_advance_deduction": False},
    )
    client.post(f"/api/v1/payroll-periods/{period['id']}/finalize")

    before = summary(client, employee["id"])
    assert before["company_owes_employee_kurus"] == 3100000
    assert before["unpaid_payroll_kurus"] == 3100000
    assert before["employee_owes_company_kurus"] == 700000
    assert before["active_advance_kurus"] == 500000
    assert before["employee_debt_kurus"] == 200000
    assert before["overdue_employee_debt_kurus"] == 200000
    assert before["overdue_company_debt_kurus"] == 3100000

    paid = move(client, employee["id"], "employee_debt_payment", 150000, "debtpay-0001", "2026-11-01")
    assert paid.status_code == 201
    after = summary(client, employee["id"])
    assert after["company_owes_employee_kurus"] == 3100000  # maaş borcu değişmedi
    assert after["employee_owes_company_kurus"] == 550000
    assert after["employee_debt_kurus"] == 50000 and after["active_advance_kurus"] == 500000

    too_much = move(client, employee["id"], "employee_debt_payment", 60000, "debtpay-0002", "2026-11-02")
    assert too_much.status_code == 409
    assert too_much.json()["error"]["details"] == {"remaining_kurus": 50000}


def test_payroll_deducts_advances_and_inputs_then_pays_partially_with_overpayment(client):
    employee = make_employee(client, "Usta", "monthly", 3100000)
    period = client.post(
        "/api/v1/payroll-periods",
        json={"period_start": "2026-10-01", "period_end": "2026-10-31"},
    ).json()
    pid = period["id"]
    move(client, employee["id"], "advance", 500000, "adv-key-0001", "2026-10-10")
    move(client, employee["id"], "advance", 100000, "adv-key-0002", "2026-11-05")  # dönem dışı
    assert move(client, employee["id"], "bonus", 100000, "bonus-key-01", payroll_period_id=pid).status_code == 201
    assert move(client, employee["id"], "additional_earning", 20000, "addl-key-01", payroll_period_id=pid).status_code == 201
    assert move(client, employee["id"], "salary_deduction", 50000, "ded-key-001", payroll_period_id=pid).status_code == 201
    no_period = move(client, employee["id"], "bonus", 1000, "bonus-key-02")
    assert no_period.status_code == 422

    client.post(f"/api/v1/payroll-periods/{pid}/calculate")
    entry = client.get(f"/api/v1/payroll-periods/{pid}/entries").json()[0]
    assert entry["bonus_kurus"] == 100000 and entry["additional_earning_kurus"] == 20000
    assert entry["deduction_kurus"] == 50000
    assert entry["advance_deduction_kurus"] == 500000  # yalnız dönem sonuna kadarki avans
    assert entry["gross_earning_kurus"] == 3220000
    assert entry["net_due_kurus"] == 3220000 - 50000 - 500000

    # Kesinleşmeden ödeme yapılamaz.
    early = move(client, employee["id"], "payroll_payment", 1000, "pay-key-0000", payroll_period_id=pid)
    assert early.status_code == 409 and early.json()["error"]["code"] == "period_not_finalized"
    client.post(f"/api/v1/payroll-periods/{pid}/finalize")
    net = 2670000

    state = summary(client, employee["id"], "2026-11-30")
    assert state["unpaid_payroll_kurus"] == net
    assert state["active_advance_kurus"] == 100000  # 500.000 mahsup edildi, 100.000 sonraki avans kaldı

    partial = move(client, employee["id"], "payroll_payment", 1000000, "pay-key-0001", "2026-11-01", payroll_period_id=pid)
    assert partial.status_code == 201
    entry = client.get(f"/api/v1/payroll-periods/{pid}/entries").json()[0]
    assert (entry["paid_kurus"], entry["remaining_kurus"]) == (1000000, net - 1000000)

    final = move(client, employee["id"], "payroll_payment", 2000000, "pay-key-0002", "2026-11-02", payroll_period_id=pid)
    body = final.json()
    assert body["amount_kurus"] == net - 1000000 and body["overpayment_movement_id"]
    entry = client.get(f"/api/v1/payroll-periods/{pid}/entries").json()[0]
    assert (entry["paid_kurus"], entry["remaining_kurus"]) == (net, 0)
    over = next(m for m in client.get(URL).json() if m["id"] == body["overpayment_movement_id"])
    assert (over["movement_type"], over["amount_kurus"]) == ("advance", 2000000 - (net - 1000000))
    final_state = summary(client, employee["id"], "2026-11-30")
    assert final_state["unpaid_payroll_kurus"] == 0
    assert final_state["active_advance_kurus"] == 100000 + over["amount_kurus"]

    # Dönem kesinleşince girdi eklenemez/terslenemez; düzeltme hareketi kullanılır.
    locked = move(client, employee["id"], "bonus", 5000, "bonus-key-03", payroll_period_id=pid)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "period_locked"
    correction = move(
        client, employee["id"], "correction", 30000, "corr-key-001", "2026-11-10",
        direction="company_owes_employee", payroll_period_id=pid,
    )
    assert correction.status_code == 201
    entry = client.get(f"/api/v1/payroll-periods/{pid}/entries").json()[0]
    assert entry["net_due_kurus"] == net and entry["remaining_kurus"] == 30000
    assert client.post(f"/api/v1/payroll-periods/{pid}/close").status_code == 409
    closed = client.post(f"/api/v1/payroll-periods/{pid}/close", json={"allow_unpaid": True})
    assert closed.json()["state"] == "closed"
    after_close = move(client, employee["id"], "payroll_payment", 100, "pay-key-0003", payroll_period_id=pid)
    assert after_close.status_code == 409


def test_idempotency_reversal_rules_and_audit(client):
    employee = make_employee(client, "Usta")
    first = move(client, employee["id"], "advance", 100000, "same-key-0001")
    again = move(client, employee["id"], "advance", 100000, "same-key-0001")
    assert first.json()["id"] == again.json()["id"]
    assert len(client.get(URL).json()) == 1
    other = make_employee(client, "Başka")
    assert move(client, other["id"], "advance", 100000, "same-key-0001").status_code == 409
    assert move(client, employee["id"], "advance", 0, "bad-amount-01").status_code == 422
    assert move(client, employee["id"], "payroll_accrual", 5, "system-key-01").status_code == 422
    assert move(client, employee["id"], "advance", 5, "wrong-dir-001", direction="company_owes_employee").status_code == 422

    original = first.json()
    reversed_once = client.post(f"{URL}/{original['id']}/reverse")
    assert reversed_once.status_code == 200
    reversal = reversed_once.json()
    assert reversal["movement_type"] == "reversal" and reversal["reversed_movement_id"] == original["id"]
    assert reversal["direction"] == "company_owes_employee"
    twice = client.post(f"{URL}/{original['id']}/reverse")
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "already_reversed"
    assert client.post(f"{URL}/{reversal['id']}/reverse").status_code == 409
    assert summary(client, employee["id"])["active_advance_kurus"] == 0

    listed = {m["id"]: m for m in client.get(URL).json()}
    assert listed[original["id"]]["amount_kurus"] == 100000  # orijinal değişmedi
    assert listed[original["id"]]["voided"] is True and listed[original["id"]]["status"] == "active"
    assert client.get(URL, params={"include_reversals": "false"}).json().__len__() == 1

    with closing(sqlite3.connect(backup_manager.database_path)) as connection:
        actions = {
            row[0]
            for row in connection.execute(
                "SELECT action FROM audit_logs WHERE entity_type='employee_financial_movement'"
            )
        }
    assert {"created", "reversed"} <= actions


def test_reversing_a_payment_restores_remaining_and_system_rows_are_protected(client):
    employee = make_employee(client, "Usta", "monthly", 3100000)
    period = finalized_october(client)
    pid = period["id"]
    payment = move(client, employee["id"], "payroll_payment", 1000000, "pay-key-0001", "2026-11-01", payroll_period_id=pid).json()
    assert client.get(f"/api/v1/payroll-periods/{pid}/entries").json()[0]["remaining_kurus"] == 2100000
    assert client.post(f"{URL}/{payment['id']}/reverse").status_code == 200
    entry = client.get(f"/api/v1/payroll-periods/{pid}/entries").json()[0]
    assert (entry["paid_kurus"], entry["remaining_kurus"]) == (0, 3100000)

    accrual = next(m for m in client.get(URL).json() if m["movement_type"] == "payroll_accrual")
    assert accrual["amount_kurus"] == 3100000 and accrual["due_date"] == "2026-10-31"
    blocked = client.post(f"{URL}/{accrual['id']}/reverse")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "system_movement"


def test_opening_balances_stay_apart_from_payroll_and_statement_and_aging(client):
    employee = make_employee(client, "Usta", "monthly", 3100000)
    move(client, employee["id"], "opening_balance", 400000, "open-co-0001", "2026-01-01",
         direction="company_owes_employee", due_date="2026-02-01")
    move(client, employee["id"], "opening_balance", 150000, "open-eo-0001", "2026-01-01",
         direction="employee_owes_company", due_date="2026-09-15")
    move(client, employee["id"], "advance", 70000, "adv-key-0001", "2026-10-05")
    finalized_october(client, auto_advance_deduction=False)

    state = summary(client, employee["id"], "2026-11-15")
    assert state["unpaid_payroll_kurus"] == 3100000
    assert state["company_owes_employee_kurus"] == 3100000 + 400000
    assert state["opening_and_correction_company_kurus"] == 400000
    assert state["employee_owes_company_kurus"] == 220000
    assert state["overdue_employee_debt_kurus"] == 150000  # vadesi 61 gün önce

    # Dönemsiz maaş ödemesi yalnız açılış/düzeltme havuzunu kapatır.
    paid = move(client, employee["id"], "payroll_payment", 100000, "pay-open-001", "2026-11-01")
    assert paid.status_code == 201
    state = summary(client, employee["id"], "2026-11-15")
    assert state["unpaid_payroll_kurus"] == 3100000
    assert state["opening_and_correction_company_kurus"] == 300000

    aging = client.get(
        f"/api/v1/employees/{employee['id']}/debt-aging", params={"as_of": "2026-11-15"}
    ).json()
    co = {b["bucket"]: b["amount_kurus"] for b in aging["company_owes_employee"]}
    eo = {b["bucket"]: b["amount_kurus"] for b in aging["employee_owes_company"]}
    assert co["1_30"] == 3100000 and co["90_plus"] == 300000
    assert eo["61_90"] == 150000 and eo["no_due_date"] == 70000
    assert set(co) == {"not_due", "1_30", "31_60", "61_90", "90_plus", "no_due_date"}

    statement = client.get(f"/api/v1/employees/{employee['id']}/statement").json()
    assert statement["line_count"] == len(statement["lines"])
    closing_ = statement["totals"]
    assert closing_["closing_company_owes_kurus"] == 3100000 + 300000
    assert closing_["closing_employee_owes_kurus"] == 220000
    assert statement["lines"][0]["movement_type"] == "opening_balance"
    ranged = client.get(
        f"/api/v1/employees/{employee['id']}/statement", params={"date_from": "2026-10-01"}
    ).json()
    assert ranged["lines"][0]["running_employee_owes_kurus"] >= 150000  # önceki bakiye taşınır


def test_legacy_employee_payment_endpoints_use_the_ledger(client):
    employee = make_employee(client, "Usta")
    advance = client.post(
        "/api/v1/employee-payments",
        json={"employee_id": employee["id"], "payment_date": "2026-10-05",
              "amount_kurus": 25000, "payment_type": "advance"},
    )
    assert advance.status_code == 201 and advance.json()["payment_type"] == "advance"
    listed = client.get("/api/v1/employee-payments").json()
    assert [(p["amount_kurus"], p["status"]) for p in listed] == [(25000, "active")]
    assert summary(client, employee["id"])["active_advance_kurus"] == 25000
    reverse = client.post(f"/api/v1/employee-payments/{advance.json()['id']}/reverse")
    assert reverse.json()["status"] == "reversed"
    assert client.get("/api/v1/employee-payments").json()[0]["status"] == "reversed"
    assert summary(client, employee["id"])["active_advance_kurus"] == 0
