from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from . import __version__
from .config import get_settings
from .database import SessionLocal, engine
from .models import AuditLog

BACKUP_NAME_PATTERN = re.compile(
    r"^ks-\d{8}-\d{6}-\d{6}-(automatic|manual|pre_restore|pre_import)\.db$"
)
AUTOMATIC_RETENTION = 30


class BackupError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class BackupMetadata:
    backup_id: str
    kind: str
    created_at: str
    size_bytes: int
    sha256: str
    app_version: str
    integrity: str = "ok"


class BackupManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._in_progress = False
        self._last_error: str | None = None

    @property
    def backup_dir(self) -> Path:
        path = get_settings().data_dir / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_path(self) -> Path:
        database_url = make_url(get_settings().resolved_database_url)
        if database_url.drivername != "sqlite" or not database_url.database:
            raise BackupError(
                "unsupported_database",
                "Yedekleme yalnızca dosya tabanlı SQLite için kullanılabilir.",
            )
        return Path(database_url.database).resolve()

    def _safe_backup_path(self, backup_id: str) -> Path:
        if not BACKUP_NAME_PATTERN.fullmatch(backup_id) or Path(backup_id).name != backup_id:
            raise BackupError("invalid_backup_id", "Geçersiz yedek kimliği.")
        backup_root = self.backup_dir.resolve()
        candidate = (backup_root / backup_id).resolve()
        if candidate.parent != backup_root:
            raise BackupError("invalid_backup_id", "Yedek dizini dışına erişim reddedildi.")
        if not candidate.is_file():
            raise BackupError("backup_not_found", "Yedek bulunamadı.")
        return candidate

    @staticmethod
    def _metadata_path(backup_path: Path) -> Path:
        return backup_path.with_suffix(".json")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _integrity_check(path: Path) -> None:
        try:
            with closing(
                sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=15)
            ) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise BackupError(
                "backup_corrupt", "Yedek SQLite dosyası açılamadı veya bozuk."
            ) from exc
        if not result or result[0] != "ok":
            raise BackupError(
                "backup_corrupt",
                "Yedek bütünlük denetiminden geçemedi.",
                {"integrity_result": result[0] if result else "no_result"},
            )

    def _read_metadata(self, backup_path: Path) -> BackupMetadata:
        metadata_path = self._metadata_path(backup_path)
        if not metadata_path.is_file():
            raise BackupError("metadata_missing", "Yedek metadata dosyası bulunamadı.")
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            return BackupMetadata(**data)
        except (OSError, ValueError, TypeError) as exc:
            raise BackupError("metadata_invalid", "Yedek metadata dosyası geçersiz.") from exc

    def _write_event(self, action: str, details: dict) -> None:
        event_path = self.backup_dir / "backup-events.jsonl"
        event = {
            "created_at": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        }
        with event_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _try_write_event(self, action: str, details: dict) -> None:
        try:
            self._write_event(action, details)
        except OSError:
            pass

    def _audit_database(self, backup_id: str, action: str) -> None:
        try:
            with SessionLocal() as session:
                session.add(
                    AuditLog(
                        entity_type="backup",
                        entity_id=backup_id[:36],
                        action=action,
                        detail=json.dumps({"backup_id": backup_id}, ensure_ascii=False),
                    )
                )
                session.commit()
        except (SQLAlchemyError, sqlite3.Error, OSError) as exc:
            self._try_write_event(
                "database_audit_failed",
                {"backup_id": backup_id, "action": action, "error": type(exc).__name__},
            )

    def _copy_database_online(self, source_path: Path, destination_path: Path) -> None:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(
                sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True, timeout=15)
            ) as source,
            closing(sqlite3.connect(destination_path, timeout=15)) as destination,
        ):
            source.backup(destination, pages=256, sleep=0.01)
            destination.commit()

    def create(self, kind: str = "manual") -> BackupMetadata:
        if kind not in {"automatic", "manual", "pre_restore", "pre_import"}:
            raise BackupError("invalid_backup_kind", "Geçersiz yedek türü.")
        with self._lock:
            self._in_progress = True
            try:
                source_path = self.database_path
                if not source_path.is_file():
                    raise BackupError("database_missing", "Canlı veritabanı bulunamadı.")
                now = datetime.now(UTC)
                backup_id = f"ks-{now:%Y%m%d-%H%M%S-%f}-{kind}.db"
                final_path = self.backup_dir / backup_id
                temp_path = self.backup_dir / f".{backup_id}.tmp"
                metadata_path = self._metadata_path(final_path)
                metadata_temp = metadata_path.with_suffix(".json.tmp")
                try:
                    self._copy_database_online(source_path, temp_path)
                    self._integrity_check(temp_path)
                    metadata = BackupMetadata(
                        backup_id=backup_id,
                        kind=kind,
                        created_at=now.isoformat(),
                        size_bytes=temp_path.stat().st_size,
                        sha256=self._sha256(temp_path),
                        app_version=__version__,
                    )
                    metadata_temp.write_text(
                        json.dumps(asdict(metadata), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    with metadata_temp.open("r+b") as stream:
                        os.fsync(stream.fileno())
                    os.replace(temp_path, final_path)
                    os.replace(metadata_temp, metadata_path)
                finally:
                    temp_path.unlink(missing_ok=True)
                    metadata_temp.unlink(missing_ok=True)
                self._last_error = None
                self._write_event("backup_created", {"backup_id": backup_id, "kind": kind})
                self._audit_database(backup_id, "created")
                if kind == "automatic":
                    self._prune_automatic()
                return metadata
            except BackupError as exc:
                self._last_error = exc.message
                self._try_write_event("backup_failed", {"kind": kind, "code": exc.code})
                raise
            except (OSError, sqlite3.Error) as exc:
                wrapped = BackupError(
                    "backup_io_error", "Yedek oluşturulurken yerel dosya veya SQLite hatası oluştu."
                )
                self._last_error = wrapped.message
                self._try_write_event("backup_failed", {"kind": kind, "code": wrapped.code})
                raise wrapped from exc
            finally:
                self._in_progress = False

    def list(self) -> list[BackupMetadata]:
        results: list[BackupMetadata] = []
        for path in self.backup_dir.glob("ks-*.db"):
            if not BACKUP_NAME_PATTERN.fullmatch(path.name):
                continue
            try:
                results.append(self._read_metadata(path))
            except BackupError:
                continue
        return sorted(results, key=lambda item: item.created_at, reverse=True)

    def status(self) -> dict:
        backups = self.list()
        latest_automatic = next((item for item in backups if item.kind == "automatic"), None)
        latest_any = backups[0] if backups else None
        return {
            "healthy": self._last_error is None,
            "in_progress": self._in_progress,
            "last_error": self._last_error,
            "backup_count": len(backups),
            "latest_backup": asdict(latest_any) if latest_any else None,
            "latest_automatic": asdict(latest_automatic) if latest_automatic else None,
            "automatic_retention": AUTOMATIC_RETENTION,
        }

    def verify(self, backup_id: str) -> BackupMetadata:
        with self._lock:
            try:
                backup_path = self._safe_backup_path(backup_id)
                metadata = self._read_metadata(backup_path)
                actual_sha = self._sha256(backup_path)
                if actual_sha != metadata.sha256:
                    self._try_write_event(
                        "backup_verify_failed", {"backup_id": backup_id, "reason": "sha256"}
                    )
                    raise BackupError(
                        "backup_checksum_mismatch",
                        "Yedek dosyasının SHA-256 özeti uyuşmuyor.",
                    )
                if backup_path.stat().st_size != metadata.size_bytes:
                    raise BackupError(
                        "backup_size_mismatch", "Yedek dosyasının boyutu metadata ile uyuşmuyor."
                    )
                self._integrity_check(backup_path)
                self._try_write_event("backup_verified", {"backup_id": backup_id})
                return metadata
            except (OSError, sqlite3.Error) as exc:
                raise BackupError(
                    "backup_verify_io_error", "Yedek doğrulanırken yerel dosya hatası oluştu."
                ) from exc

    def restore(self, backup_id: str) -> tuple[BackupMetadata, BackupMetadata]:
        with self._lock:
            self._in_progress = True
            try:
                selected_path = self._safe_backup_path(backup_id)
                selected = self.verify(backup_id)
                pre_restore = self.create("pre_restore")
                live_path = self.database_path
                engine.dispose()
                try:
                    self._copy_database_online(selected_path, live_path)
                    self._integrity_check(live_path)
                except (BackupError, OSError, sqlite3.Error) as restore_error:
                    rollback_path = self._safe_backup_path(pre_restore.backup_id)
                    try:
                        self._copy_database_online(rollback_path, live_path)
                        self._integrity_check(live_path)
                    except (BackupError, OSError, sqlite3.Error) as rollback_error:
                        self._try_write_event(
                            "restore_rollback_failed",
                            {"backup_id": backup_id, "error": type(rollback_error).__name__},
                        )
                        raise BackupError(
                            "restore_rollback_failed",
                            "Geri yükleme ve emniyet yedeğine dönüş başarısız oldu. Uygulamayı kapatın.",
                        ) from rollback_error
                    self._try_write_event(
                        "restore_rolled_back",
                        {"backup_id": backup_id, "error": type(restore_error).__name__},
                    )
                    raise BackupError(
                        "restore_failed",
                        "Geri yükleme başarısız oldu; mevcut veritabanı emniyet yedeğinden geri alındı.",
                    ) from restore_error
                self._last_error = None
                self._write_event(
                    "backup_restored",
                    {"backup_id": backup_id, "pre_restore_backup_id": pre_restore.backup_id},
                )
                self._audit_database(backup_id, "restored")
                return selected, pre_restore
            except BackupError as exc:
                self._last_error = exc.message
                raise
            except (OSError, sqlite3.Error) as exc:
                wrapped = BackupError(
                    "restore_io_error",
                    "Geri yükleme sırasında yerel dosya veya SQLite hatası oluştu.",
                )
                self._last_error = wrapped.message
                raise wrapped from exc
            finally:
                self._in_progress = False

    def ensure_daily_automatic(self) -> BackupMetadata | None:
        today = datetime.now().astimezone().date()
        for metadata in self.list():
            if metadata.kind != "automatic":
                continue
            created = datetime.fromisoformat(metadata.created_at).astimezone().date()
            if created == today:
                return None
        return self.create("automatic")

    def _prune_automatic(self) -> None:
        automatic = [item for item in self.list() if item.kind == "automatic"]
        for metadata in automatic[AUTOMATIC_RETENTION:]:
            path = self._safe_backup_path(metadata.backup_id)
            self._metadata_path(path).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            self._write_event("backup_pruned", {"backup_id": metadata.backup_id})


backup_manager = BackupManager()
