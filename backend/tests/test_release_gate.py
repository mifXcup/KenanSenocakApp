from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from finance_helpers import allocate, build_portfolio, move, receipt
from helpers import log_work, make_employee
from sqlalchemy import func, select

from ks_yonetim.config import get_settings
from ks_yonetim.database import SessionLocal
from ks_yonetim.models import AuditLog

API = "/api/v1"


def snapshot(client, portfolio):
    cid = portfolio["customer_id"]
    with SessionLocal() as session:
        audits = session.scalar(select(func.count()).select_from(AuditLog))
    return {
        "customer": client.get(f"{API}/customers/{cid}").json(),
        "receipts": client.get(f"{API}/purchases/{portfolio['pu3']['id']}/receipts").json(),
        "manual_events": client.get(f"{API}/calendar/manual-events").json(),
        "profit": client.get(f"{API}/projects/{portfolio['project']['id']}/profitability").json(),
        "audits": audits,
    }


def test_backup_restore_round_trip_covers_all_package_tables(client):
    portfolio = build_portfolio(client)
    cid = portfolio["customer_id"]
    client.post(f"{API}/calendar/manual-events", json={"title": "Yedekteki olay", "start_date": "2026-03-12"})
    before = snapshot(client, portfolio)
    backup = client.post(f"{API}/backups").json()
    assert client.post(f"{API}/backups/{backup['backup_id']}/verify").status_code == 200

    # Yedekten sonra: tersleme, yeni olay, yeni teslim ve dağıtım.
    movement = move(client, cid, "collection", 5_000, "tahsilat-rg-0001", day="2026-03-09").json()
    client.post(f"{API}/customer-financial-movements/{movement['id']}/reverse")
    client.post(f"{API}/calendar/manual-events", json={"title": "Yedek sonrası olay", "start_date": "2026-03-13"})
    receipt(client, portfolio["pu3"]["id"], "2026-03-09", 1, "teslim-rg-000001")
    assert snapshot(client, portfolio)["audits"] > before["audits"]

    restored = client.post(f"{API}/backups/{backup['backup_id']}/restore")
    assert restored.status_code == 200 and restored.json()["restart_required"] is True
    after = snapshot(client, portfolio)
    assert after["customer"] == before["customer"]
    assert after["receipts"] == before["receipts"]
    assert [e["title"] for e in after["manual_events"]] == ["Yedekteki olay"]
    assert after["profit"] == before["profit"]
    # Denetim izi yedekle birlikte geri döndü: yedek sonrası hareketin kayıtları yok.
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == movement["id"])) == 0
    assert after["audits"] <= before["audits"] + 1  # geri yükleme kendi olay kaydını yazabilir

    # Yedek dosyası bu paketlerin tablolarını taşır.
    path = Path(get_settings().data_dir) / "backups" / backup["backup_id"]
    with closing(sqlite3.connect(path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert {
        "customers", "customer_financial_movements", "customer_payment_allocations", "purchase_receipts",
        "project_cost_forecasts", "leave_ledger_entries", "weekly_work_plans", "calendar_manual_events",
        "notification_deliveries", "work_log_duplicate_reports",
    } <= tables


def test_idempotency_is_stable_across_packages(client):
    portfolio = build_portfolio(client)
    cid = portfolio["customer_id"]
    first = move(client, cid, "collection", 7_000, "tahsilat-id-0001", day="2026-03-09").json()
    again = move(client, cid, "collection", 7_000, "tahsilat-id-0001", day="2026-03-09").json()
    assert first["id"] == again["id"]
    assert move(client, cid, "collection", 7_001, "tahsilat-id-0001", day="2026-03-09").json()["error"]["code"] == "idempotency_conflict"

    one = allocate(client, first["id"], portfolio["plan_a"]["id"], 3_000, "dagit-id-0000001").json()
    assert allocate(client, first["id"], portfolio["plan_a"]["id"], 3_000, "dagit-id-0000001").json()["id"] == one["id"]
    r1 = receipt(client, portfolio["pu3"]["id"], "2026-03-09", 1, "teslim-id-0000001")
    # Satın alma zaten tamamen teslim alınmış; aynı anahtar yine aynı kaydı döner, yenisi aşım nedeniyle reddedilir.
    assert r1.status_code == 409 and r1.json()["error"]["code"] == "receipt_exceeds_total"
    worker = make_employee(client, "Idempotent Usta", "daily", 80000, rate_effective_from="2026-03-01")
    body = {"entry_type": "grant", "quantity_days": "3", "entry_date": "2026-03-01", "idempotency_key": "hak-id-00000001"}
    a = client.post(f"{API}/employees/{worker['id']}/leave-ledger", json=body).json()
    b = client.post(f"{API}/employees/{worker['id']}/leave-ledger", json=body).json()
    assert a["id"] == b["id"]
    leave = {"employee_id": worker["id"], "leave_type_code": "annual", "start_date": "2026-03-11", "end_date": "2026-03-11", "idempotency_key": "izin-id-0000001"}
    assert client.post(f"{API}/leave-requests", json=leave).json()["id"] == client.post(f"{API}/leave-requests", json=leave).json()["id"]
    assert len(client.get(f"{API}/leave-requests", params={"employee_id": worker["id"]}).json()) == 1


def test_reversals_cancellations_and_audit_trail(client):
    portfolio = build_portfolio(client)
    cid = portfolio["customer_id"]
    movement = move(client, cid, "collection", 9_000, "tahsilat-rv-0001", day="2026-03-09",
                    receivable_schedule_id=portfolio["plan_a"]["id"]).json()
    reversal = client.post(f"{API}/customer-financial-movements/{movement['id']}/reverse")
    assert reversal.status_code == 201 and reversal.json()["movement_date"] == "2026-03-10"
    assert client.post(f"{API}/customer-financial-movements/{movement['id']}/reverse").json()["error"]["code"] == "already_reversed"
    assert client.post(f"{API}/customer-financial-movements/{reversal.json()['id']}/reverse").json()["error"]["code"] == "cannot_reverse_reversal"
    assert client.get(f"{API}/customer-payment-allocations", params={"collection_id": movement["id"]}).json() == []

    receipts = client.get(f"{API}/purchases/{portfolio['pu3']['id']}/receipts").json()
    cancelled = client.post(f"{API}/purchase-receipts/{receipts[0]['id']}/cancel", json={"reason": "Hatalı giriş"})
    assert cancelled.status_code == 200
    with SessionLocal() as session:
        actions = {
            (a.entity_type, a.action) for a in session.scalars(select(AuditLog))
        }
    assert {
        ("customer_movement", "reversed"), ("customer_payment_allocation", "cancelled"),
        ("purchase_receipt", "cancelled"), ("project_change_order", "approved"),
        ("customer_movement", "created"), ("purchase_receipt", "created"),
    } <= actions


def test_period_locks_cover_attendance_leave_and_wages(client):
    portfolio = build_portfolio(client)
    worker = portfolio["worker"]
    locked_log = log_work(client, worker["id"], "2026-02-20")
    assert locked_log.status_code == 409 and locked_log.json()["error"]["code"] == "period_locked"
    leave = client.post(
        f"{API}/leave-requests",
        json={"employee_id": worker["id"], "leave_type_code": "other_paid", "start_date": "2026-02-24",
              "end_date": "2026-02-24", "idempotency_key": "izin-lk-0000001"},
    )
    assert leave.status_code == 409 and leave.json()["error"]["code"] == "period_locked"
    rate = client.post(
        f"{API}/employees/{worker['id']}/wage-rates",
        json={"effective_from": "2026-02-15", "wage_type": "daily", "rate_kurus": 99999},
    )
    assert rate.status_code == 409 and rate.json()["error"]["code"] == "period_locked"
    assert client.post(f"{API}/work-logs/{client.get(f'{API}/work-logs', params={'employee_id': worker['id']}).json()[0]['id']}/cancel").json()["error"]["code"] == "period_locked"
    # Kilit dışı tarih serbesttir.
    assert log_work(client, worker["id"], "2026-03-04").status_code == 201
