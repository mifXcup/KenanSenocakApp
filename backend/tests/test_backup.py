from __future__ import annotations

from pathlib import Path

from ks_yonetim.backup import backup_manager
from ks_yonetim.config import get_settings


def create_supplier(client, name: str) -> dict:
    response = client.post("/api/v1/suppliers", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_create_and_verify_backup(client):
    create_supplier(client, "Yedek Test Firması")

    created = client.post("/api/v1/backups")
    assert created.status_code == 201
    payload = created.json()
    assert payload["kind"] == "manual"
    assert len(payload["sha256"]) == 64

    verified = client.post(f"/api/v1/backups/{payload['backup_id']}/verify")
    assert verified.status_code == 200
    assert verified.json()["sha256"] == payload["sha256"]

    status = client.get("/api/v1/backups/status")
    assert status.status_code == 200
    assert status.json()["healthy"] is True
    assert status.json()["automatic_retention"] == 30


def test_corrupt_backup_is_rejected(client):
    created = client.post("/api/v1/backups").json()
    backup_path = get_settings().data_dir / "backups" / created["backup_id"]
    original = backup_path.read_bytes()
    backup_path.write_bytes(original[: max(1, len(original) // 2)])

    response = client.post(f"/api/v1/backups/{created['backup_id']}/verify")
    assert response.status_code == 409
    assert response.json()["error"]["code"] in {
        "backup_checksum_mismatch",
        "backup_size_mismatch",
        "backup_corrupt",
    }


def test_restore_roundtrip_creates_pre_restore_backup(client):
    create_supplier(client, "Geri Dönecek Firma")
    backup = client.post("/api/v1/backups").json()
    create_supplier(client, "Geri Yüklemede Silinecek Firma")

    restored = client.post(f"/api/v1/backups/{backup['backup_id']}/restore")
    assert restored.status_code == 200
    result = restored.json()
    assert result["restart_required"] is True
    assert result["restored_backup"]["backup_id"] == backup["backup_id"]
    assert result["pre_restore_backup"]["kind"] == "pre_restore"

    suppliers = client.get("/api/v1/suppliers").json()
    names = {supplier["name"] for supplier in suppliers}
    assert "Geri Dönecek Firma" in names
    assert "Geri Yüklemede Silinecek Firma" not in names

    backup_dir = Path(get_settings().data_dir) / "backups"
    assert (backup_dir / result["pre_restore_backup"]["backup_id"]).is_file()


def test_path_traversal_backup_id_is_rejected(client):
    response = client.post("/api/v1/backups/not-a-valid-backup.db/verify")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_backup_id"


def test_automatic_retention_keeps_30_and_preserves_manual(client):
    manual = client.post("/api/v1/backups").json()
    for _ in range(31):
        backup_manager.create("automatic")

    backups = backup_manager.list()
    automatic = [item for item in backups if item.kind == "automatic"]
    assert len(automatic) == 30
    assert any(item.backup_id == manual["backup_id"] for item in backups)
