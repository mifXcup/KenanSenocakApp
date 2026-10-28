from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

TEST_DIR = Path(tempfile.mkdtemp(prefix="ks-yonetim-test-"))
os.environ["KS_DATA_DIR"] = str(TEST_DIR)
os.environ["KS_SIDECAR_TOKEN"] = "test-sidecar-token"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ks_yonetim import clock
from ks_yonetim.database import Base, engine
from ks_yonetim.main import app


@pytest.fixture(autouse=True)
def clean_database():
    with engine.begin() as connection:
        # Öz-referanslı ters kayıt bağlantısı drop_all sırasında FK ihlali yapmasın.
        tables = inspect(connection)
        for ledger in ("employee_financial_movements", "customer_financial_movements"):
            if tables.has_table(ledger):
                connection.exec_driver_sql(f"UPDATE {ledger} SET reversed_movement_id = NULL")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


FIXED_TODAY = date(2026, 3, 10)


@pytest.fixture(autouse=True)
def fixed_business_today(monkeypatch):
    """Sunucu iş tarihi sabitlenir; hiçbir test sistem saatine bağlı kalmaz."""
    monkeypatch.setattr(clock, "business_today", lambda: FIXED_TODAY)
    return FIXED_TODAY


@pytest.fixture
def client():
    with TestClient(app, headers={"X-KS-Sidecar-Token": "test-sidecar-token"}) as test_client:
        yield test_client
