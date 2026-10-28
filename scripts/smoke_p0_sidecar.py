"""Real packaged sidecar P0 smoke test using an isolated temporary data directory."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    executable = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/dist/ks-core/ks-core.exe").resolve()
    if not executable.is_file():
        raise RuntimeError(f"Sidecar not found: {executable}")
    with tempfile.TemporaryDirectory(prefix="ks-p0-smoke-") as folder:
        port = free_port()
        token = "smoke-" + "a" * 64
        env = {**os.environ, "KS_DATA_DIR": folder, "KS_SIDECAR_TOKEN": token}
        process = subprocess.Popen(
            [str(executable), "--host", "127.0.0.1", "--port", str(port)],
            cwd=executable.parent, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"X-KS-Sidecar-Token": token}, timeout=20) as client:
                for _ in range(90):
                    if process.poll() is not None:
                        raise RuntimeError(f"Sidecar exited: {process.stderr.read().decode(errors='replace')[:1000]}")
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.3)
                else:
                    raise RuntimeError("Sidecar health timeout")

                def call(method: str, path: str, body: dict | None = None, expected: int = 200):
                    response = client.request(method, "/api/v1" + path, json=body)
                    if response.status_code != expected:
                        raise AssertionError(f"{method} {path}: {response.status_code} {response.text[:1000]}")
                    return response.json() if "json" in response.headers.get("content-type", "") else response.content

                customer = call("POST", "/customers", {"name": "Smoke Müşteri"}, 201)
                project = call("POST", "/projects", {"name": "Smoke Proje", "customer_name": customer["name"], "contract_amount_kurus": 2_000_000, "budget_kurus": 1_000_000}, 201)
                pid, cid = project["id"], customer["id"]
                call("POST", f"/projects/{pid}/budget-lines", {"category": "material", "title": "Malzeme bütçesi", "amount_kurus": 600_000}, 201)
                order = call("POST", f"/projects/{pid}/change-orders", {"title": "Ek dolap", "amount_kurus": 100_000}, 201)
                call("POST", f"/projects/{pid}/change-orders/{order['id']}/approve", {})
                call("PUT", f"/projects/{pid}/cost-forecasts", {"items": [{"category": "material", "remaining_estimate_kurus": 120_000, "as_of_date": "2026-10-28", "reason": "Smoke tahmini"}]})
                supplier = call("POST", "/suppliers", {"name": "Smoke Tedarikçi"}, 201)
                material = call("POST", "/materials", {"name": "Smoke MDF", "default_unit": "levha", "tracking_mode": "estimated"}, 201)
                purchase = call("POST", "/purchases", {"supplier_id": supplier["id"], "material_id": material["id"], "project_id": pid, "purchase_date": "2026-10-28", "total_kurus": 400_000, "quantity": "4.000", "unit": "levha", "lifecycle_state": "planned", "idempotency_key": "smoke-purchase-0001"}, 201)
                call("POST", f"/purchases/{purchase['id']}/lifecycle", {"state": "ordered"})
                call("POST", f"/purchases/{purchase['id']}/receipts", {"receipt_date": "2026-10-28", "amount_kurus": 200_000, "quantity": "2.000", "idempotency_key": "smoke-receipt-0001"}, 201)
                call("POST", f"/purchases/{purchase['id']}/receipts", {"receipt_date": "2026-10-28", "amount_kurus": 200_000, "quantity": "2.000", "idempotency_key": "smoke-receipt-0002"}, 201)
                call("POST", "/payments", {"supplier_id": supplier["id"], "purchase_id": purchase["id"], "payment_date": "2026-10-28", "amount_kurus": 100_000, "idempotency_key": "smoke-payment-0001"}, 201)
                employee = call("POST", "/employees", {"name": "Smoke Usta", "wage_type": "daily", "current_rate_kurus": 80_000, "rate_effective_from": "2026-10-01", "employment_start_date": "2026-10-01"}, 201)
                call("POST", "/work-logs", {"employee_id": employee["id"], "project_id": pid, "work_date": "2026-10-27", "work_status": "worked", "normal_hours": 8}, 201)
                call("POST", f"/employees/{employee['id']}/leave-ledger", {"entry_type": "grant", "quantity_days": "2", "entry_date": "2026-10-01", "idempotency_key": "smoke-grant-0001"}, 201)
                leave = call("POST", "/leave-requests", {"employee_id": employee["id"], "leave_type_code": "annual", "start_date": "2026-10-29", "end_date": "2026-10-29", "idempotency_key": "smoke-leave-0001"}, 201)
                call("POST", f"/leave-requests/{leave['id']}/approve", {})
                period = call("POST", "/payroll-periods", {"period_start": "2026-10-01", "period_end": "2026-10-31"}, 201)
                call("POST", f"/payroll-periods/{period['id']}/calculate", {})
                call("POST", f"/payroll-periods/{period['id']}/finalize", {})
                schedule = call("POST", "/receivable-schedules", {"customer_id": cid, "project_id": pid, "title": "Kapora", "amount_kurus": 300_000, "due_date": "2026-10-29"}, 201)
                collection = call("POST", "/customer-financial-movements", {"customer_id": cid, "project_id": pid, "movement_date": "2026-10-28", "movement_type": "collection", "amount_kurus": 100_000, "idempotency_key": "smoke-collection-0001"}, 201)
                call("POST", "/customer-payment-allocations", {"collection_id": collection["id"], "receivable_schedule_id": schedule["id"], "amount_kurus": 100_000, "allocation_date": "2026-10-28", "idempotency_key": "smoke-allocation-0001"}, 201)
                profit = call("GET", f"/projects/{pid}/profitability")
                assert profit["actual_cost_kurus"] >= 400_000 and profit["collections"]["net_collected_kurus"] == 100_000
                assert call("GET", f"/projects/{pid}/cost-drilldown")["categories"]
                call("POST", "/calendar/manual-events", {"title": "Smoke ziyaret", "start_date": "2026-10-28"}, 201)
                assert call("GET", "/calendar/events?date_from=2026-10-28&date_to=2026-10-30")["count"] >= 1
                assert "today" in call("GET", "/today")
                due = call("GET", "/notifications/due")
                if due["notifications"]:
                    call("POST", "/notifications/delivered", {"delivery_key": due["notifications"][0]["delivery_key"]})
                assert call("GET", "/reports/finance/project-profitability")["row_count"] >= 1
                assert bytes(call("GET", "/reports/finance/project-profitability/export.xlsx")).startswith(b"PK")
                assert bytes(call("GET", "/reports/finance/project-profitability/export.pdf")).startswith(b"%PDF-")
                assert len(call("GET", "/analytics/ml/status")["models"]) == 6
                call("POST", "/analytics/ml/run", {})
                assert "opportunities" in call("GET", "/analytics/savings")
                backup = call("POST", "/backups", {}, 201)
                call("POST", "/calendar/manual-events", {"title": "After backup", "start_date": "2026-10-29"}, 201)
                call("POST", f"/backups/{backup['backup_id']}/restore", {})
                assert all(item["title"] != "After backup" for item in call("GET", "/calendar/manual-events"))
                print("P0 PACKAGED SIDECAR SMOKE PASSED")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
