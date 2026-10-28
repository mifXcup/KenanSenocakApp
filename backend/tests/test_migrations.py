from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from legacy_db import build_v020_database

from ks_yonetim import migrate
from ks_yonetim.backup import backup_manager
from ks_yonetim.database import Base, build_engine


def query(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def test_clean_database_upgrades_to_head_and_matches_models(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    result = migrate.upgrade_database(engine)
    assert result["previous"] is None
    assert result["current"] == migrate.head_revision()
    assert result["backup_id"] is None
    assert migrate.current_revision(engine) == migrate.head_revision()

    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_v020_database_upgrades_without_data_loss(tmp_path):
    db_path = tmp_path / "legacy.db"
    build_v020_database(db_path)
    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    tables = (
        "suppliers",
        "purchases",
        "payments",
        "employees",
        "work_logs",
        "employee_payments",
        "project_expenses",
    )
    before = {t: query(db_path, f"SELECT COUNT(*) FROM {t}")[0][0] for t in tables}

    result = migrate.upgrade_database(engine)

    assert result["previous"] == "b4d2e3f5a6c7"
    assert result["current"] == migrate.head_revision()
    for table, count in before.items():
        assert query(db_path, f"SELECT COUNT(*) FROM {table}")[0][0] >= count
    # Eski değerler değişmeden korunur.
    assert query(db_path, "SELECT daily_rate_kurus, name FROM employees WHERE id='emp-1'") == [
        (80000, "Eski Usta")
    ]
    assert query(db_path, "SELECT amount_kurus, hours FROM work_logs WHERE id='wl-2'") == [
        (45000, 4)
    ]
    # Günlük ücret yeni ücret modeline taşındı.
    assert query(
        db_path,
        "SELECT wage_type, current_rate_kurus, employment_state FROM employees WHERE id='emp-1'",
    ) == [("daily", 80000, "active")]
    rates = query(
        db_path,
        "SELECT employee_id, effective_from, effective_to, wage_type, rate_kurus "
        "FROM employee_wage_rates",
    )
    assert rates == [("emp-1", "2026-09-10", None, "daily", 80000)]
    # Eski çalışma kayıtları: süre normal saate taşınır; formülle üretilemeyen tutar manuel sayılır.
    assert query(
        db_path,
        "SELECT id, work_status, normal_hours, overtime_hours, calculated_amount_kurus, "
        "manual_amount_kurus FROM work_logs ORDER BY id",
    ) == [
        ("wl-1", "worked", 8, 0, 80000, None),
        ("wl-2", "worked", 4, 0, 45000, 45000),
    ]
    # Eski personel ödemeleri deftere aynı kimlikle taşınır; eski tablo korunur.
    assert query(
        db_path,
        "SELECT id, movement_type, direction, amount_kurus, source FROM employee_financial_movements "
        "WHERE reversed_movement_id IS NULL ORDER BY id",
    ) == [
        ("ep-1", "advance", "employee_owes_company", 30000, "legacy"),
        ("ep-2", "payroll_payment", "company_owes_employee", 20000, "legacy"),
        ("ep-3", "advance", "employee_owes_company", 5000, "legacy"),
    ]
    assert query(
        db_path,
        "SELECT movement_type, reversed_movement_id FROM employee_financial_movements "
        "WHERE reversed_movement_id IS NOT NULL",
    ) == [("reversal", "ep-3")]
    assert query(db_path, "SELECT COUNT(*) FROM employee_payments") == [(3,)]
    # Yükseltmeden önce doğrulanabilir yedek alındı ve eski şemayı taşıyor.
    backup = next(item for item in backup_manager.list() if item.backup_id == result["backup_id"])
    assert backup.kind == "pre_migration"
    backup_manager.verify(backup.backup_id)
    # İkinci çalıştırma güvenli ve yedeksizdir.
    again = migrate.upgrade_database(engine)
    assert again["backup_id"] is None
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_failed_migration_restores_live_data(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-fail.db"
    build_v020_database(db_path)
    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    original_upgrade = migrate.command.upgrade

    def half_applied(config, revision):
        original_upgrade(config, "c5e3f4a6b7d8")
        config.attributes["connection"].exec_driver_sql("UPDATE employees SET name = 'BOZULDU'")
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(migrate.command, "upgrade", half_applied)
    with pytest.raises(migrate.MigrationError) as raised:
        migrate.upgrade_database(engine)
    assert raised.value.backup_id
    assert "başarısız" in str(raised.value)

    names = {row[0] for row in query(db_path, "SELECT name FROM employees")}
    assert names == {"Eski Usta", "Ücretsiz Kayıt"}
    columns = {row[1] for row in query(db_path, "PRAGMA table_info(employees)")}
    assert "wage_type" not in columns
    assert query(db_path, "PRAGMA integrity_check") == [("ok",)]
    engine.dispose()


def test_v020_projects_link_to_normalized_customers_and_purchases_default_to_received(tmp_path):
    db_path = tmp_path / "legacy-customers.db"
    build_v020_database(db_path)
    stamp = "2026-10-21 08:00:00.000000"
    with closing(sqlite3.connect(db_path)) as connection:
        for project_id, name, customer, created in (
            ("proj-2", "Proje İki", "  İPEK   Hanım ", "2026-10-21 08:00:01.000000"),
            ("proj-3", "Proje Üç", "ipek hanım", "2026-10-21 08:00:02.000000"),
            ("proj-4", "Proje Dört", "IPEK Hanım", "2026-10-21 08:00:03.000000"),
        ):
            connection.execute(
                "INSERT INTO projects (id, name, customer_name, project_state, status, created_at, "
                "updated_at) VALUES (?, ?, ?, 'active', 'ACTIVE', ?, ?)",
                (project_id, name, customer, created, stamp),
            )
        connection.execute(
            "INSERT INTO purchases (id, supplier_id, material_id, project_id, purchase_date, "
            "total_kurus, idempotency_key, status, created_at, updated_at) VALUES "
            "('pur-2', 'sup-1', 'mat-1', 'proj-1', '2026-09-03', 70000, 'legacy-purchase-0002', "
            f"'CANCELLED', '{stamp}', '{stamp}')"
        )
        connection.commit()

    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    result = migrate.upgrade_database(engine)
    assert result["current"] == migrate.head_revision()

    customers = set(query(db_path, "SELECT name, normalized_name FROM customers"))
    assert customers == {
        ("IPEK Hanım", "ıpek hanım"),  # Türkçe I -> ı: farklı müşteri
        ("Müşteri", "müşteri"),
        ("İPEK Hanım", "ipek hanım"),  # ilk görülen yazım, boşluklar sadeleşmiş
    }
    links = dict(
        query(
            db_path,
            "SELECT p.id, c.normalized_name FROM projects p JOIN customers c ON c.id = p.customer_id",
        )
    )
    assert links == {
        "proj-1": "müşteri",
        "proj-2": "ipek hanım",
        "proj-3": "ipek hanım",
        "proj-4": "ıpek hanım",
    }
    # Orijinal müşteri metni hiç değişmez.
    assert query(db_path, "SELECT customer_name FROM projects WHERE id IN ('proj-2','proj-3')") == [
        ("  İPEK   Hanım ",),
        ("ipek hanım",),
    ]
    assert query(
        db_path, "SELECT id, lifecycle_state, received_kurus FROM purchases ORDER BY id"
    ) == [("pur-1", "received", 200000), ("pur-2", "cancelled", 0)]

    again = migrate.upgrade_database(engine)
    assert again["backup_id"] is None
    assert query(db_path, "SELECT COUNT(*) FROM customers") == [(3,)]
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_create_all_database_is_recognised_at_the_new_head(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'created.db').as_posix()}")
    Base.metadata.create_all(bind=engine)
    result = migrate.upgrade_database(engine)
    assert result["legacy_stamp"] is False
    assert migrate.current_revision(engine) == migrate.head_revision()
    assert result["backup_id"] is None
    engine.dispose()


def test_alembic_has_a_single_head():
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(migrate.alembic_config()).get_heads()
    assert heads == [migrate.head_revision()]


def test_v030_database_upgrades_without_data_loss(tmp_path):
    from alembic import command

    db_path = tmp_path / "v030.db"
    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    config = migrate.alembic_config()
    migrate._run(config, engine, lambda cfg: command.upgrade(cfg, "fb1db398215f"))
    stamp = "2026-10-27 09:00:00.000000"
    with engine.begin() as connection:
        statements = [
            (
                "INSERT INTO suppliers (id, name, status, created_at, updated_at) VALUES "
                f"('s1', 'Firma', 'ACTIVE', '{stamp}', '{stamp}')"
            ),
            (
                "INSERT INTO materials (id, name, default_unit, tracking_mode, status, created_at, "
                f"updated_at) VALUES ('m1', 'Malzeme', 'adet', 'EXACT', 'ACTIVE', '{stamp}', '{stamp}')"
            ),
            (
                "INSERT INTO projects (id, name, customer_name, project_state, status, created_at, "
                "updated_at) VALUES ('p1', 'Proje', 'Ahmet  Yılmaz', 'active', 'ACTIVE', "
                f"'{stamp}', '{stamp}')"
            ),
            (
                "INSERT INTO purchases (id, supplier_id, material_id, project_id, purchase_date, "
                "total_kurus, idempotency_key, status, created_at, updated_at) VALUES "
                "('pu1', 's1', 'm1', 'p1', '2026-10-01', 120000, 'v030-purchase-0001', 'ACTIVE', "
                f"'{stamp}', '{stamp}')"
            ),
            (
                "INSERT INTO payments (id, supplier_id, purchase_id, payment_date, amount_kurus, "
                "idempotency_key, status, created_at, updated_at) VALUES "
                "('pa1', 's1', 'pu1', '2026-10-02', 20000, 'v030-payment-0001', 'ACTIVE', "
                f"'{stamp}', '{stamp}')"
            ),
        ]
        for sql in statements:
            connection.exec_driver_sql(sql)

    result = migrate.upgrade_database(engine)
    assert result["previous"] == "fb1db398215f"
    assert result["current"] == migrate.head_revision()
    backup = next(item for item in backup_manager.list() if item.backup_id == result["backup_id"])
    assert backup.kind == "pre_migration"
    backup_manager.verify(backup.backup_id)

    assert query(db_path, "SELECT total_kurus, received_kurus, lifecycle_state FROM purchases") == [
        (120000, 120000, "received")
    ]
    assert query(db_path, "SELECT amount_kurus FROM payments") == [(20000,)]
    assert query(db_path, "SELECT customer_name FROM projects") == [("Ahmet  Yılmaz",)]
    assert query(
        db_path,
        "SELECT c.name FROM projects p JOIN customers c ON c.id = p.customer_id",
    ) == [("Ahmet Yılmaz",)]
    assert query(db_path, "PRAGMA integrity_check") == [("ok",)]
    assert query(db_path, "PRAGMA foreign_key_check") == []
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_19b18b8_schema_upgrades_with_receipt_and_allocation_backfill(tmp_path):
    from alembic import command

    db_path = tmp_path / "b1.db"
    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    config = migrate.alembic_config()
    migrate._run(config, engine, lambda cfg: command.upgrade(cfg, "c1a7e9d2b3f4"))
    stamp = "2026-10-27 09:00:00.000000"
    audit_cols = f"'{stamp}', '{stamp}'"
    statements = [
        f"INSERT INTO suppliers (id, name, status, created_at, updated_at) VALUES ('s1', 'Firma', 'ACTIVE', {audit_cols})",
        (
            "INSERT INTO materials (id, name, default_unit, tracking_mode, status, created_at, updated_at) "
            f"VALUES ('m1', 'Malzeme', 'adet', 'EXACT', 'ACTIVE', {audit_cols})"
        ),
        (
            "INSERT INTO customers (id, name, normalized_name, status, created_at, updated_at) "
            f"VALUES ('c1', 'Müşteri', 'müşteri', 'ACTIVE', {audit_cols})"
        ),
        (
            "INSERT INTO projects (id, name, customer_name, customer_id, project_state, status, created_at, "
            f"updated_at) VALUES ('p1', 'Proje', 'Müşteri', 'c1', 'active', 'ACTIVE', {audit_cols})"
        ),
        # Teslim alınmış, planlı ve iptal edilmiş satın almalar (c1a7e9d2b3f4 şemasında).
        (
            "INSERT INTO purchases (id, supplier_id, material_id, project_id, purchase_date, quantity, "
            "total_kurus, idempotency_key, status, lifecycle_state, received_kurus, created_at, updated_at) "
            f"VALUES ('pu1', 's1', 'm1', 'p1', '2026-10-01', 12.000, 120000, 'b1-purchase-0001', 'ACTIVE', 'received', 120000, {audit_cols})"
        ),
        (
            "INSERT INTO purchases (id, supplier_id, material_id, project_id, purchase_date, total_kurus, "
            "idempotency_key, status, lifecycle_state, received_kurus, created_at, updated_at) "
            f"VALUES ('pu2', 's1', 'm1', 'p1', '2026-10-02', 50000, 'b1-purchase-0002', 'ACTIVE', 'planned', 0, {audit_cols})"
        ),
        (
            "INSERT INTO purchases (id, supplier_id, material_id, project_id, purchase_date, total_kurus, "
            "idempotency_key, status, lifecycle_state, received_kurus, created_at, updated_at) "
            f"VALUES ('pu3', 's1', 'm1', 'p1', '2026-10-03', 70000, 'b1-purchase-0003', 'CANCELLED', 'cancelled', 0, {audit_cols})"
        ),
        (
            "INSERT INTO material_movements (id, material_id, project_id, purchase_id, movement_date, "
            "movement_type, quantity, unit, amount_kurus, confidence, status, created_at, updated_at) "
            f"VALUES ('mm1', 'm1', 'p1', 'pu1', '2026-10-01', 'PURCHASE', 12.000, 'adet', 120000, 'EXACT', 'ACTIVE', {audit_cols})"
        ),
        (
            "INSERT INTO receivable_schedules (id, customer_id, project_id, title, amount_kurus, status, "
            f"created_at, updated_at) VALUES ('rs1', 'c1', 'p1', 'Plan', 50000, 'ACTIVE', {audit_cols})"
        ),
        # Plana bağlı tahsilat, terslenmiş tahsilat ve onun ters satırı.
        (
            "INSERT INTO customer_financial_movements (id, customer_id, project_id, receivable_schedule_id, "
            "movement_date, movement_type, direction, amount_kurus, idempotency_key, source, status, "
            f"created_at, updated_at) VALUES ('cm1', 'c1', 'p1', 'rs1', '2026-10-05', 'collection', 'receivable_decrease', 30000, 'b1-collect-0001', 'manual', 'ACTIVE', {audit_cols})"
        ),
        (
            "INSERT INTO customer_financial_movements (id, customer_id, project_id, receivable_schedule_id, "
            "movement_date, movement_type, direction, amount_kurus, idempotency_key, source, status, "
            f"created_at, updated_at) VALUES ('cm2', 'c1', 'p1', 'rs1', '2026-10-06', 'collection', 'receivable_decrease', 10000, 'b1-collect-0002', 'manual', 'ACTIVE', {audit_cols})"
        ),
        (
            "INSERT INTO customer_financial_movements (id, customer_id, project_id, receivable_schedule_id, "
            "movement_date, movement_type, direction, amount_kurus, idempotency_key, reversed_movement_id, "
            "source, status, created_at, updated_at) VALUES ('cm3', 'c1', 'p1', 'rs1', '2026-10-06', "
            f"'reversal', 'receivable_increase', 10000, 'reverse:cm2-0001', 'cm2', 'system', 'ACTIVE', {audit_cols})"
        ),
    ]
    with engine.begin() as connection:
        for sql in statements:
            connection.exec_driver_sql(sql)

    result = migrate.upgrade_database(engine)
    assert result["previous"] == "c1a7e9d2b3f4"
    assert result["current"] == migrate.head_revision()
    backup = next(item for item in backup_manager.list() if item.backup_id == result["backup_id"])
    backup_manager.verify(backup.backup_id)

    # Teslim alınmış satın alma tek başlangıç fişine dönüşür; planlı ve iptal edilmişler fiş almaz.
    receipts = query(
        db_path,
        "SELECT purchase_id, receipt_date, amount_kurus, quantity, status FROM purchase_receipts",
    )
    assert receipts == [("pu1", "2026-10-01", 120000, 12, "ACTIVE")]
    assert query(
        db_path, "SELECT p.id, p.received_kurus FROM purchases p ORDER BY p.id"
    ) == [("pu1", 120000), ("pu2", 0), ("pu3", 0)]
    linked = query(
        db_path,
        "SELECT m.id FROM material_movements m JOIN purchase_receipts r ON r.id = m.purchase_receipt_id",
    )
    assert linked == [("mm1",)]

    # Plana bağlı tahsilatlar dağıtıma dönüşür; terslenmiş olan iptal durumunda gelir.
    allocations = query(
        db_path,
        "SELECT collection_id, receivable_schedule_id, amount_kurus, status, customer_id "
        "FROM customer_payment_allocations ORDER BY collection_id",
    )
    assert allocations == [
        ("cm1", "rs1", 30000, "ACTIVE", "c1"),
        ("cm2", "rs1", 10000, "CANCELLED", "c1"),
    ]
    assert query(db_path, "SELECT COUNT(*) FROM project_cost_forecasts") == [(0,)]
    assert query(db_path, "PRAGMA integrity_check") == [("ok",)]
    assert query(db_path, "PRAGMA foreign_key_check") == []

    again = migrate.upgrade_database(engine)
    assert again["backup_id"] is None
    assert query(db_path, "SELECT COUNT(*) FROM purchase_receipts") == [(1,)]
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_b2_migration_reports_and_resolves_duplicate_work_logs_without_deleting(tmp_path):
    from alembic import command

    db_path = tmp_path / "dup.db"
    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    config = migrate.alembic_config()
    migrate._run(config, engine, lambda cfg: command.upgrade(cfg, "d2b8f6a1c4e7"))
    stamp = "2026-10-27 09:00:00.000000"

    def work_log(log_id, employee, day, status, amount, created, hours=8):
        return (
            "INSERT INTO work_logs (id, employee_id, work_date, hours, amount_kurus, status, "
            "created_at, updated_at) VALUES "
            f"('{log_id}', '{employee}', '{day}', {hours}, {amount}, '{status}', '{created}', '{created}')"
        )

    statements = [
        (
            "INSERT INTO employees (id, name, status, created_at, updated_at) VALUES "
            f"('e1', 'Mükerrer Usta', 'ACTIVE', '{stamp}', '{stamp}')"
        ),
        (
            "INSERT INTO employees (id, name, status, created_at, updated_at) VALUES "
            f"('e2', 'Tekil Usta', 'ACTIVE', '{stamp}', '{stamp}')"
        ),
        # 5 Ekim: iki aktif + bir iptal edilmiş; en eski aktif korunmalı.
        work_log("wl1", "e1", "2026-10-05", "ACTIVE", 80000, "2026-10-05 08:00:00.000000"),
        work_log("wl2", "e1", "2026-10-05", "ACTIVE", 50000, "2026-10-05 09:00:00.000000", 5),
        work_log("wl3", "e1", "2026-10-05", "CANCELLED", 99999, "2026-10-05 07:00:00.000000"),
        work_log("wl4", "e2", "2026-10-06", "ACTIVE", 70000, "2026-10-06 08:00:00.000000"),
        # 7 Ekim: üç aktif kayıt, kesinleşmiş döneme düşüyor.
        work_log("wl5", "e1", "2026-10-07", "ACTIVE", 80000, "2026-10-07 08:00:00.000000"),
        work_log("wl6", "e1", "2026-10-07", "ACTIVE", 40000, "2026-10-07 09:00:00.000000", 4),
        work_log("wl7", "e1", "2026-10-07", "ACTIVE", 20000, "2026-10-07 10:00:00.000000", 2),
        (
            "INSERT INTO payroll_periods (id, period_start, period_end, title, state, status, "
            f"created_at, updated_at) VALUES ('pp1', '2026-10-07', '2026-10-10', 'Kilitli', "
            f"'finalized', 'ACTIVE', '{stamp}', '{stamp}')"
        ),
    ]
    with engine.begin() as connection:
        for sql in statements:
            connection.exec_driver_sql(sql)

    result = migrate.upgrade_database(engine)
    assert result["previous"] == "d2b8f6a1c4e7" and result["current"] == migrate.head_revision()
    backup = next(item for item in backup_manager.list() if item.backup_id == result["backup_id"])
    backup_manager.verify(backup.backup_id)

    # Hiçbir kayıt silinmedi; aynı gün için yalnız en eski aktif kayıt aktif kaldı.
    assert query(db_path, "SELECT COUNT(*) FROM work_logs") == [(7,)]
    assert query(
        db_path, "SELECT id, status FROM work_logs WHERE status = 'ACTIVE' ORDER BY id"
    ) == [("wl1", "ACTIVE"), ("wl4", "ACTIVE"), ("wl5", "ACTIVE")]
    assert query(
        db_path, "SELECT id, status FROM work_logs WHERE id IN ('wl2','wl3','wl6','wl7') ORDER BY id"
    ) == [("wl2", "CANCELLED"), ("wl3", "CANCELLED"), ("wl6", "CANCELLED"), ("wl7", "CANCELLED")]
    notes = query(db_path, "SELECT note FROM work_logs WHERE id = 'wl2'")
    assert "korunan: wl1" in notes[0][0]
    assert query(db_path, "SELECT note FROM work_logs WHERE id = 'wl3'") == [(None,)]  # zaten iptal

    reports = query(
        db_path,
        "SELECT work_date, kept_work_log_id, cancelled_work_log_id, kept_amount_kurus, "
        "cancelled_amount_kurus, in_locked_period, resolution FROM work_log_duplicate_reports "
        "ORDER BY cancelled_work_log_id",
    )
    assert reports == [
        ("2026-10-05", "wl1", "wl2", 80000, 50000, 0, "cancelled_newer_duplicate"),
        ("2026-10-07", "wl5", "wl6", 80000, 40000, 1, "cancelled_newer_duplicate"),
        ("2026-10-07", "wl5", "wl7", 80000, 20000, 1, "cancelled_newer_duplicate"),
    ]
    assert query(
        db_path,
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'cancelled_duplicate' AND actor = 'migration'",
    ) == [(3,)]

    # Veritabanı artık ikinci aktif kaydı reddeder; iptal edilmiş kayıt serbesttir.
    with closing(sqlite3.connect(db_path)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO work_logs (id, employee_id, work_date, hours, amount_kurus, status, "
                "created_at, updated_at) VALUES ('x1', 'e1', '2026-10-05', 8, 1, 'ACTIVE', "
                "'2026-10-28 08:00:00', '2026-10-28 08:00:00')"
            )
        connection.execute(
            "INSERT INTO work_logs (id, employee_id, work_date, hours, amount_kurus, status, "
            "created_at, updated_at) VALUES ('x2', 'e1', '2026-10-05', 8, 1, 'CANCELLED', "
            "'2026-10-28 08:00:00', '2026-10-28 08:00:00')"
        )

    assert {row[0] for row in query(db_path, "SELECT code FROM leave_types")} == {
        "annual", "sick", "other_paid", "unpaid", "excused"
    }
    assert query(db_path, "SELECT salary_day, email FROM employees WHERE id = 'e1'") == [(None, None)]
    assert query(db_path, "SELECT source, leave_request_id FROM work_logs WHERE id = 'wl1'") == [
        ("manual", None)
    ]
    assert query(db_path, "PRAGMA integrity_check") == [("ok",)]
    assert query(db_path, "PRAGMA foreign_key_check") == []

    again = migrate.upgrade_database(engine)
    assert again["backup_id"] is None
    assert query(db_path, "SELECT COUNT(*) FROM work_log_duplicate_reports") == [(3,)]
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_b2_schema_upgrades_to_head_with_calendar_tables(tmp_path):
    from alembic import command

    db_path = tmp_path / "b2.db"
    engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    config = migrate.alembic_config()
    migrate._run(config, engine, lambda cfg: command.upgrade(cfg, "e3c9a7b5d1f2"))
    stamp = "2026-10-27 09:00:00.000000"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO projects (id, name, customer_name, project_state, status, created_at, "
            f"updated_at) VALUES ('p1', 'Proje', 'Müşteri', 'active', 'ACTIVE', '{stamp}', '{stamp}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO project_tasks (id, project_id, title, due_date, task_state, status, "
            f"created_at, updated_at) VALUES ('t1', 'p1', 'İş', '2026-11-01', 'todo', 'ACTIVE', '{stamp}', '{stamp}')"
        )

    result = migrate.upgrade_database(engine)
    assert result["previous"] == "e3c9a7b5d1f2" and result["current"] == migrate.head_revision()
    tables = {row[0] for row in query(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "calendar_manual_events", "calendar_event_occurrences",
        "calendar_reminder_preferences", "notification_deliveries",
    } <= tables
    # Takvim kaynak kayıtları kopyalanmaz: yalnız manuel olay/tercih/teslim tabloları vardır.
    assert query(db_path, "SELECT COUNT(*) FROM calendar_manual_events") == [(0,)]
    assert query(db_path, "SELECT title FROM project_tasks") == [("İş",)]
    assert query(db_path, "PRAGMA foreign_key_check") == []
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], diff
    engine.dispose()


def test_every_intermediate_revision_upgrades_to_head_without_metadata_drift(tmp_path):
    """B1, B1.1, B2, B3 ve tüm eski revizyonlardan boş şemayla head'e yükseltme."""
    from alembic import command
    from alembic.script import ScriptDirectory

    config = migrate.alembic_config()
    revisions = [r.revision for r in ScriptDirectory.from_config(config).walk_revisions()]
    assert len(revisions) >= 12
    for revision in revisions:
        db_path = tmp_path / f"rev-{revision}.db"
        engine = build_engine(f"sqlite:///{db_path.as_posix()}")
        migrate._run(config, engine, lambda cfg, rev=revision: command.upgrade(cfg, rev))
        assert migrate.current_revision(engine) == revision
        result = migrate.upgrade_database(engine)
        assert result["current"] == migrate.head_revision(), revision
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert diff == [], (revision, diff)
        assert query(db_path, "PRAGMA foreign_key_check") == []
        engine.dispose()
