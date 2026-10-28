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
