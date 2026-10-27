from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from helpers import log_work, make_employee
from sqlalchemy import event

from ks_yonetim.database import engine
from ks_yonetim.main import app
from ks_yonetim.sidecar import validate_runtime


def test_every_api_route_except_health_requires_the_sidecar_token(client):
    anonymous = TestClient(app)
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if path == "/api/v1/health":
            continue
        url = re.sub(r"\{[^}]+\}", "x", path)
        for method in operations:
            response = anonymous.request(
                method.upper(), url, json={} if method != "get" else None
            )
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked > 80
    assert anonymous.get("/api/v1/health").status_code == 200
    wrong = TestClient(app, headers={"X-KS-Sidecar-Token": "wrong"})
    assert wrong.get("/api/v1/employees").status_code == 401


def test_sidecar_refuses_non_loopback_hosts_and_short_tokens(monkeypatch):
    monkeypatch.setenv("KS_SIDECAR_TOKEN", "x" * 40)
    validate_runtime("127.0.0.1", 8765)
    for host in ("0.0.0.0", "192.168.1.5", "example.com", ""):
        with pytest.raises(SystemExit):
            validate_runtime(host, 8765)
    monkeypatch.setenv("KS_SIDECAR_TOKEN", "short")
    with pytest.raises(SystemExit):
        validate_runtime("127.0.0.1", 8765)


def test_no_user_supplied_file_paths_are_accepted(client):
    # Rapor/aktarım uçları dosya yolu değil yalnız base64 içerik alır; yolu andıran girdiler reddedilir.
    bad = client.post("/api/v1/work-logs/bulk-preview", json={"file_name": "../../x.csv", "content_base64": "YWJjZGVmZ2g="})
    assert bad.status_code == 422
    traversal = client.post("/api/v1/backups/..%2F..%2Fsecret.db/verify")
    assert traversal.status_code in {404, 409, 422}
    injected = client.get("/api/v1/employees", params={"q": "'; DROP TABLE employees; --"})
    assert injected.status_code == 200 and injected.json() == []
    assert client.get("/api/v1/employees").status_code == 200
    like = client.get("/api/v1/employees", params={"q": "%"})
    assert like.status_code == 200 and like.json() == []


class QueryCounter:
    def __init__(self):
        self.count = 0

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self._hit)
        return self

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._hit)

    def _hit(self, *args):
        self.count += 1


def test_list_endpoints_do_not_issue_per_row_queries(client):
    def populate(size: int, offset: int):
        for index in range(size):
            employee = make_employee(client, f"Usta {offset + index:03d}", "monthly", 3100000)
            log_work(client, employee["id"], "2026-10-05")
            client.post("/api/v1/employee-finance/movements", json={
                "employee_id": employee["id"], "movement_type": "advance", "amount_kurus": 100,
                "movement_date": "2026-10-02", "idempotency_key": f"nplus-adv-{offset + index:05d}"})

    def measure():
        period = None
        urls = ["/api/v1/employees", "/api/v1/work-logs", "/api/v1/employee-finance/movements",
                "/api/v1/reports/staff/unpaid-payroll", "/api/v1/reports/staff/employee-advances",
                "/api/v1/reports/staff/debt-aging", "/api/v1/reports/staff/project-labor"]
        counts = {}
        for url in urls:
            with QueryCounter() as counter:
                assert client.get(url).status_code == 200
            counts[url] = counter.count
        return counts, period

    populate(3, 0)
    period = client.post("/api/v1/payroll-periods", json={"period_start": "2026-10-01", "period_end": "2026-10-31"}).json()
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    small, _ = measure()
    with QueryCounter() as small_entries:
        client.get(f"/api/v1/payroll-periods/{period['id']}/entries")
    populate(20, 100)
    client.post(f"/api/v1/payroll-periods/{period['id']}/calculate")
    large, _ = measure()
    with QueryCounter() as large_entries:
        assert len(client.get(f"/api/v1/payroll-periods/{period['id']}/entries").json()) == 23
    assert large == small, (small, large)  # kayıt sayısı arttı, sorgu sayısı sabit
    assert large_entries.count == small_entries.count
