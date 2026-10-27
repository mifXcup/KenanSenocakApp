from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from helpers import log_work, make_employee

from ks_yonetim import __version__, migrate
from ks_yonetim.backup import backup_manager
from ks_yonetim.config import get_settings

STAFF_TABLES = (
    "employees",
    "employee_wage_rates",
    "work_logs",
    "payroll_periods",
    "payroll_entries",
    "employee_financial_movements",
    "ml_runs",
    "ml_predictions",
    "app_settings",
)


def counts():
    with closing(sqlite3.connect(backup_manager.database_path)) as connection:
        return {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in STAFF_TABLES}


def seed(client):
    employee = make_employee(
        client, "Yedek Personeli", "monthly", 3100000, rate_effective_from="2026-01-01"
    )
    log_work(client, employee["id"], "2026-10-05", work_status="absent")
    period = client.post(
        "/api/v1/payroll-periods", json={"period_start": "2026-10-01", "period_end": "2026-10-31"}
    ).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    assert client.post(f"/api/v1/payroll-periods/{period['id']}/finalize").status_code == 200
    client.post(
        "/api/v1/employee-finance/movements",
        json={"employee_id": employee["id"], "movement_type": "advance", "amount_kurus": 5000,
              "movement_date": "2026-11-01", "idempotency_key": "backup-adv-0001"},
    )
    client.put("/api/v1/settings/payroll", json={"overtime_multiplier_percent": 175})
    client.post("/api/v1/analytics/ml/run", json={"as_of": "2026-11-02"})
    return employee, period


def test_new_backups_carry_current_version_and_schema_revision(client):
    created = client.post("/api/v1/backups").json()
    assert created["app_version"] == __version__ == "0.3.0"
    assert created["schema_revision"] == migrate.head_revision()
    path = get_settings().data_dir / "backups" / created["backup_id"]
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["app_version"] == "0.3.0"
    assert metadata["schema_revision"] == migrate.head_revision()
    assert client.post(f"/api/v1/backups/{created['backup_id']}/verify").json()["app_version"] == "0.3.0"

    # Eski (sürüm 0.2.0) metadata dosyaları schema_revision olmadan da okunur.
    metadata.pop("schema_revision")
    metadata["app_version"] = "0.2.0"
    path.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
    old = next(b for b in backup_manager.list() if b.backup_id == created["backup_id"])
    assert old.app_version == "0.2.0" and old.schema_revision is None


def test_staff_payroll_and_ml_tables_survive_backup_restore_roundtrip(client):
    employee, _period = seed(client)
    before = counts()
    assert all(value > 0 for key, value in before.items() if key != "app_settings") and before["app_settings"] == 1

    backup = client.post("/api/v1/backups").json()
    assert client.post(f"/api/v1/backups/{backup['backup_id']}/verify").status_code == 200
    # Yedekten sonra veri değişir.
    make_employee(client, "Sonradan Eklenen", rate_effective_from="2026-11-01")
    client.post("/api/v1/analytics/ml/run", json={"as_of": "2026-11-03"})
    assert counts() != before

    restored = client.post(f"/api/v1/backups/{backup['backup_id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["pre_restore_backup"]["kind"] == "pre_restore"
    assert counts() == before

    # Geri yüklenen veritabanı çalışmaya devam eder: bakiyeler ve ayarlar aynıdır.
    summary = client.get(f"/api/v1/employees/{employee['id']}/financial-summary", params={"as_of": "2026-12-01"})
    assert summary.json()["active_advance_kurus"] == 5000
    assert summary.json()["unpaid_payroll_kurus"] == 3000000
    assert client.get("/api/v1/settings/payroll").json()["overtime_multiplier_percent"] == 175
    with closing(sqlite3.connect(backup_manager.database_path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_restoring_an_old_schema_backup_upgrades_on_next_start(client, tmp_path):
    """0.2.0 şemalı yedek geri yüklense bile açılışta veri kaybı olmadan head'e yükseltilir."""
    from legacy_db import build_v020_database

    from ks_yonetim.database import build_engine

    legacy = tmp_path / "restored-legacy.db"
    build_v020_database(legacy)
    engine = build_engine(f"sqlite:///{legacy.as_posix()}")
    result = migrate.upgrade_database(engine)
    assert result["previous"] == "b4d2e3f5a6c7" and result["backup_id"]
    pre = next(b for b in backup_manager.list() if b.backup_id == result["backup_id"])
    assert pre.kind == "pre_migration" and pre.app_version == __version__
    assert pre.schema_revision == "b4d2e3f5a6c7"  # eski veritabanı damgalanıp yedeklendi
    with closing(sqlite3.connect(legacy)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM employee_payments").fetchone()[0] == 3
        assert connection.execute("SELECT name FROM employees WHERE id='emp-1'").fetchone() == ("Eski Usta",)
    engine.dispose()
