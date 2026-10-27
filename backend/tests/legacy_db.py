"""v0.2.0 şemasında (create_all ile açılmış) örnek veritabanı üretir."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).parent / "fixtures" / "schema_v020.sql"
STAMP = "2026-10-20 08:00:00.000000"

SEED = [
    "INSERT INTO suppliers (id, name, status, created_at, updated_at) VALUES "
    f"('sup-1', 'Eski Firma', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO materials (id, name, default_unit, tracking_mode, status, created_at, updated_at)"
    f" VALUES ('mat-1', 'Eski MDF', 'levha', 'EXACT', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO projects (id, name, customer_name, budget_kurus, contract_amount_kurus, "
    "project_state, status, created_at, updated_at) VALUES ('proj-1', 'Eski Proje', 'Müşteri', "
    f"5000000, 8000000, 'active', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO purchases (id, supplier_id, material_id, project_id, purchase_date, quantity, "
    "unit, unit_price_kurus, total_kurus, idempotency_key, status, created_at, updated_at) VALUES "
    "('pur-1', 'sup-1', 'mat-1', 'proj-1', '2026-09-01', 2.000, 'levha', 100000, 200000, "
    f"'legacy-purchase-0001', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO payments (id, supplier_id, purchase_id, payment_date, amount_kurus, "
    "idempotency_key, status, created_at, updated_at) VALUES ('pay-1', 'sup-1', 'pur-1', "
    f"'2026-09-02', 50000, 'legacy-payment-0001', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO employees (id, name, role, daily_rate_kurus, status, created_at, updated_at) "
    f"VALUES ('emp-1', 'Eski Usta', 'Montaj', 80000, 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO employees (id, name, status, created_at, updated_at) "
    f"VALUES ('emp-2', 'Ücretsiz Kayıt', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO sites (id, project_id, name, status, created_at, updated_at) VALUES "
    f"('site-1', 'proj-1', 'Eski Şantiye', 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO work_logs (id, employee_id, project_id, site_id, work_date, hours, amount_kurus, "
    "status, created_at, updated_at) VALUES ('wl-1', 'emp-1', 'proj-1', 'site-1', '2026-09-10', "
    f"8.00, 80000, 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO work_logs (id, employee_id, project_id, site_id, work_date, hours, amount_kurus, "
    "status, created_at, updated_at) VALUES ('wl-2', 'emp-1', 'proj-1', NULL, '2026-09-11', "
    f"4.00, 45000, 'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO employee_payments (id, employee_id, payment_date, amount_kurus, payment_type, "
    "status, created_at, updated_at) VALUES ('ep-1', 'emp-1', '2026-09-12', 30000, 'ADVANCE', "
    f"'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO employee_payments (id, employee_id, payment_date, amount_kurus, payment_type, "
    "status, created_at, updated_at) VALUES ('ep-2', 'emp-1', '2026-09-30', 20000, 'WAGE', "
    f"'ACTIVE', '{STAMP}', '{STAMP}')",
    "INSERT INTO employee_payments (id, employee_id, payment_date, amount_kurus, payment_type, "
    "status, created_at, updated_at) VALUES ('ep-3', 'emp-1', '2026-09-30', 5000, 'ADVANCE', "
    f"'REVERSED', '{STAMP}', '{STAMP}')",
    "INSERT INTO project_expenses (id, project_id, expense_date, category, amount_kurus, status, "
    "created_at, updated_at) VALUES ('pe-1', 'proj-1', '2026-09-15', 'SHIPPING', 15000, "
    f"'ACTIVE', '{STAMP}', '{STAMP}')",
]


def build_v020_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        for statement in SEED:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()
