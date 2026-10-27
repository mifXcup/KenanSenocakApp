"""Açılışta şema yükseltme: Alembic head'e çıkar, yükseltmeden önce yedek alır, hata olursa geri yükler."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Inspector, inspect, text

from .backup import BackupError, backup_manager


class MigrationError(RuntimeError):
    def __init__(self, message: str, backup_id: str | None = None):
        super().__init__(message)
        self.backup_id = backup_id


def migrations_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "migrations"
    return Path(__file__).resolve().parents[2] / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(migrations_dir()))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None
    return head


def _columns(inspector: Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


# create_all ile açılmış (alembic_version tablosu olmayan) veritabanlarının hangi revizyona denk
# geldiği tabloya/sütuna bakarak bulunur. En yeni revizyon en üstte durmalıdır.
BASELINE_MARKERS: list[tuple[str, Callable[[set[str], Inspector], bool]]] = [
    (
        "fb1db398215f",
        lambda tables, _i: "project_notes" in tables and "ml_runs" in tables,
    ),
    ("d6f4a7b8c9d0", lambda tables, _i: "project_notes" in tables),
    ("a9c7d8e0f1b2", lambda tables, _i: "ml_runs" in tables),
    ("f8b6c7d9e0a1", lambda tables, _i: "employee_financial_movements" in tables),
    ("e7a5b6c8d9f0", lambda tables, _i: "payroll_periods" in tables),
    ("d6f4a5b7c8e9", lambda tables, _i: "app_settings" in tables),
    ("c5e3f4a6b7d8", lambda tables, _i: "employee_wage_rates" in tables),
    ("b4d2e3f5a6c7", lambda tables, _i: "employees" in tables),
    (
        "a3c1d2e4f5b6",
        lambda tables, i: "purchases" in tables and "due_date" in _columns(i, "purchases"),
    ),
    ("1597ff061a94", lambda tables, _i: "suppliers" in tables),
]


def infer_baseline(inspector: Inspector) -> str | None:
    tables = set(inspector.get_table_names())
    for revision, matches in BASELINE_MARKERS:
        if matches(tables, inspector):
            return revision
    return None


def _run(config: Config, engine: Engine, action: Callable[[Config], None]) -> None:
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        action(config)


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _database_file(engine: Engine) -> Path | None:
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def _restore_live_database(engine: Engine, backup_id: str, live_path: Path) -> None:
    engine.dispose()
    backup_path = backup_manager.backup_dir / backup_id
    backup_manager._copy_database_online(backup_path, live_path)
    backup_manager._integrity_check(live_path)


def upgrade_database(engine: Engine) -> dict:
    """Veritabanını head'e getirir. Sonuç: önceki/yeni revizyon ve alınan yedek."""
    config = alembic_config()
    head = head_revision()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    user_tables = tables - {"alembic_version"}
    current = current_revision(engine) if "alembic_version" in tables else None
    previous = current

    if user_tables and current is None:
        baseline = infer_baseline(inspector)
        if baseline is None:
            # Tanınmayan eski/kısmi şema: eksik tabloları oluştur ve bilinen sütun düzeltmelerini uygula.
            from .database import Base

            Base.metadata.create_all(bind=engine)
            with engine.begin() as connection:
                if "purchases" in user_tables and "due_date" not in _columns(
                    inspect(connection), "purchases"
                ):
                    connection.execute(text("ALTER TABLE purchases ADD COLUMN due_date DATE"))
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_purchases_due_date "
                            "ON purchases (due_date)"
                        )
                    )
            _run(config, engine, lambda cfg: command.stamp(cfg, head))
            return {"previous": None, "current": head, "backup_id": None, "legacy_stamp": True}
        _run(config, engine, lambda cfg: command.stamp(cfg, baseline))
        current = previous = baseline

    backup_id: str | None = None
    if user_tables and current != head:
        live_path = _database_file(engine)
        if live_path is not None and live_path.is_file():
            try:
                backup_id = backup_manager.create("pre_migration", source_path=live_path).backup_id
            except BackupError as exc:
                raise MigrationError(
                    f"Yükseltmeden önce yedek alınamadı; veritabanına dokunulmadı: {exc.message}"
                ) from exc

    try:
        _run(config, engine, lambda cfg: command.upgrade(cfg, "head"))
    except Exception as exc:
        live_path = _database_file(engine)
        if backup_id is not None and live_path is not None:
            _restore_live_database(engine, backup_id, live_path)
            raise MigrationError(
                "Şema yükseltme başarısız oldu; canlı veri yükseltme öncesi yedekten geri yüklendi.",
                backup_id,
            ) from exc
        raise
    return {"previous": previous, "current": head, "backup_id": backup_id, "legacy_stamp": False}
