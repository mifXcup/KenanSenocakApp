"""Upgrade a populated v0.3.0 database using the packaged sidecar."""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from alembic import command
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
from ks_yonetim import migrate


def main() -> None:
    executable = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/dist/ks-core/ks-core.exe").resolve()
    with tempfile.TemporaryDirectory(prefix="ks-v030-smoke-") as folder:
        db = Path(folder) / "kenan-senocak.db"
        engine = create_engine(f"sqlite:///{db.as_posix()}")
        migrate._run(migrate.alembic_config(), engine, lambda cfg: command.upgrade(cfg, "fb1db398215f"))
        stamp = "2026-10-27 09:00:00.000000"
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO suppliers (id,name,status,created_at,updated_at) VALUES (?,?,?,?,?)", ("s1", "Firma", "ACTIVE", stamp, stamp))
            conn.exec_driver_sql("INSERT INTO materials (id,name,default_unit,tracking_mode,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", ("m1", "Malzeme", "adet", "EXACT", "ACTIVE", stamp, stamp))
            conn.exec_driver_sql("INSERT INTO projects (id,name,customer_name,project_state,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", ("p1", "Proje", "Ahmet  Yılmaz", "active", "ACTIVE", stamp, stamp))
            conn.exec_driver_sql("INSERT INTO purchases (id,supplier_id,material_id,project_id,purchase_date,total_kurus,idempotency_key,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", ("pu1", "s1", "m1", "p1", "2026-10-01", 120000, "v030-purchase-0001", "ACTIVE", stamp, stamp))
            conn.exec_driver_sql("INSERT INTO payments (id,supplier_id,purchase_id,payment_date,amount_kurus,idempotency_key,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", ("pa1", "s1", "pu1", "2026-10-02", 20000, "v030-payment-0001", "ACTIVE", stamp, stamp))
        engine.dispose()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        token = "smoke-" + "b" * 64
        process = subprocess.Popen([str(executable), "--host", "127.0.0.1", "--port", str(port)], cwd=executable.parent, env={**os.environ, "KS_DATA_DIR": folder, "KS_SIDECAR_TOKEN": token}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"X-KS-Sidecar-Token": token}, timeout=20) as client:
                for _ in range(90):
                    if process.poll() is not None:
                        raise RuntimeError(process.stderr.read().decode(errors="replace")[:2000])
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.3)
                else:
                    raise RuntimeError("Packaged sidecar health timeout")
                response = client.get("/api/v1/projects")
                assert response.status_code == 200, response.text
                assert any(item["id"] == "p1" for item in response.json())
            conn = sqlite3.connect(db)
            try:
                assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "f4d1b8c6e2a3"
                assert conn.execute("SELECT total_kurus,received_kurus,lifecycle_state FROM purchases").fetchone() == (120000, 120000, "received")
                assert conn.execute("SELECT amount_kurus FROM payments").fetchone() == (20000,)
                assert conn.execute("SELECT name FROM customers").fetchone()[0] == "Ahmet Yılmaz"
                assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            finally:
                conn.close()
            assert any(Path(folder, "backups").glob("*-pre_migration.db"))
            print("P0 PACKAGED V0.3.0 MIGRATION SMOKE PASSED")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
