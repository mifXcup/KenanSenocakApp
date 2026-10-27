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
