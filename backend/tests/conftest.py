from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DIR = Path(tempfile.mkdtemp(prefix="ks-yonetim-test-"))
os.environ["KS_DATA_DIR"] = str(TEST_DIR)
os.environ["KS_SIDECAR_TOKEN"] = "test-sidecar-token"

import pytest
from fastapi.testclient import TestClient

from ks_yonetim.database import Base, engine
from ks_yonetim.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app, headers={"X-KS-Sidecar-Token": "test-sidecar-token"}) as test_client:
        yield test_client
