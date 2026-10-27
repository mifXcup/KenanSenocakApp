from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import date, timedelta

from helpers import log_work, make_employee, make_project, make_site, workbook_payload

from ks_yonetim.backup import backup_manager

HEADERS = [
    "Personel*",
    "Tarih*",
    "Durum*",
    "Normal Saat",
    "Fazla Mesai Saat",
    "Proje",
    "Şantiye",
    "Manuel Tutar (TL)",
    "Not",
]


def test_status_rules_and_calculated_amounts(client):
    daily = make_employee(client, "Günlük Usta", "daily", 80000)
    hourly = make_employee(client, "Saatlik Usta", "hourly", 10000)
    monthly = make_employee(client, "Aylık Usta", "monthly", 3100000)

    full = log_work(client, daily["id"], "2026-10-05").json()
    assert (full["work_status"], full["normal_hours"], full["amount_kurus"]) == (
        "worked",
        "8.00",
        80000,
    )
    assert full["calculated_amount_kurus"] == 80000 and full["manual_amount_kurus"] is None

    half = log_work(client, daily["id"], "2026-10-06", work_status="half_day").json()
    assert (half["normal_hours"], half["amount_kurus"]) == ("4.00", 40000)

    overtime = log_work(
        client, daily["id"], "2026-10-07", work_status="overtime", overtime_hours="2"
    ).json()
    # 8 saat normal + 2 saat × (80000/8) × %150 = 80000 + 30000
    assert overtime["amount_kurus"] == 110000
    assert overtime["hours"] == "10.00"

    leave = log_work(client, daily["id"], "2026-10-08", work_status="paid_leave").json()
    assert leave["amount_kurus"] == 80000
    for status in ("unpaid_leave", "absent"):
        entry = log_work(client, daily["id"], "2026-10-09" if status == "absent" else "2026-10-10",
                         work_status=status).json()
        assert (entry["amount_kurus"], entry["normal_hours"], entry["overtime_hours"]) == (
            0,
            "0.00",
            "0.00",
        )

    hourly_log = log_work(client, hourly["id"], "2026-10-05", normal_hours="6.5").json()
    assert hourly_log["amount_kurus"] == 65000
    # Aylık: 31 günlük ay için günlük 3.100.000/31 = 100.000; 8 saatlik gün 100.000
    monthly_log = log_work(client, monthly["id"], "2026-10-05").json()
    assert monthly_log["amount_kurus"] == 100000

    bad = [
        {"work_status": "worked", "overtime_hours": "1"},
        {"work_status": "overtime"},
        {"work_status": "absent", "normal_hours": "4"},
        {"work_status": "half_day", "normal_hours": "9"},
        {"work_status": "worked", "normal_hours": "25"},
    ]
    for index, extra in enumerate(bad):
        response = log_work(client, hourly["id"], f"2026-11-{index + 1:02d}", **extra)
        assert response.status_code == 422, (extra, response.text)
        assert response.json()["error"]["code"] in {"invalid_hours", "validation_error"}


def test_manual_amount_overrides_and_legacy_fields(client):
    employee = make_employee(client)
    manual = log_work(client, employee["id"], "2026-10-05", manual_amount_kurus=55555).json()
    assert manual["amount_kurus"] == 55555
    assert manual["calculated_amount_kurus"] == 80000

    legacy = log_work(client, employee["id"], "2026-10-06", hours=4, amount_kurus=12345).json()
    assert legacy["manual_amount_kurus"] == 12345 and legacy["normal_hours"] == "4.00"

    conflict = log_work(client, employee["id"], "2026-10-07", hours=4, normal_hours=5)
    assert conflict.status_code == 422

    no_rate = client.post("/api/v1/employees", json={"name": "Ücretsiz"}).json()
    missing = log_work(client, no_rate["id"], "2026-10-05")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "missing_labor_rate"
    assert log_work(client, no_rate["id"], "2026-10-05", manual_amount_kurus=1000).status_code == 201


def test_cost_uses_rate_effective_on_work_date(client):
    employee = make_employee(client)
    url = f"/api/v1/employees/{employee['id']}/wage-rates"
    client.post(
        url, json={"effective_from": "2026-07-01", "wage_type": "daily", "rate_kurus": 100000}
    )
    old = log_work(client, employee["id"], "2026-06-15").json()
    new = log_work(client, employee["id"], "2026-07-15").json()
    assert (old["amount_kurus"], new["amount_kurus"]) == (80000, 100000)
    before_raise = log_work(client, employee["id"], "2025-12-31")
    assert before_raise.json()["error"]["code"] == "missing_labor_rate"
    # Ücret sonradan değişse de kayıtlı eski tutarlar değişmez.
    client.post(
        url, json={"effective_from": "2026-12-01", "wage_type": "daily", "rate_kurus": 200000}
    )
    stored = {i["work_date"]: i["amount_kurus"] for i in client.get("/api/v1/work-logs").json()}
    assert stored["2026-06-15"] == 80000 and stored["2026-07-15"] == 100000


def test_overtime_multiplier_is_a_setting(client):
    employee = make_employee(client, rate=80000)
    assert client.get("/api/v1/settings/payroll").json() == {
        "overtime_multiplier_percent": 150,
        "standard_day_hours": 8,
    }
    changed = client.put("/api/v1/settings/payroll", json={"overtime_multiplier_percent": 200})
    assert changed.status_code == 200
    log = log_work(
        client, employee["id"], "2026-10-07", work_status="overtime", overtime_hours="1"
    ).json()
    assert log["amount_kurus"] == 80000 + 20000
    assert client.put("/api/v1/settings/payroll", json={}).status_code == 422
    assert (
        client.put("/api/v1/settings/payroll", json={"overtime_multiplier_percent": 50}).status_code
        == 422
    )


def test_duplicate_day_patch_cancel_and_project_cost(client):
    employee = make_employee(client)
    project = make_project(client)
    site = make_site(client, project["id"])
    first = log_work(
        client, employee["id"], "2026-10-05", project_id=project["id"], site_id=site["id"]
    ).json()
    duplicate = log_work(client, employee["id"], "2026-10-05")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_work_log"

    other_project = make_project(client, "Başka Proje")
    mismatch = log_work(
        client, employee["id"], "2026-10-06", project_id=other_project["id"], site_id=site["id"]
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "site_project_mismatch"

    patched = client.patch(
        f"/api/v1/work-logs/{first['id']}",
        json={"work_status": "overtime", "overtime_hours": "1", "note": "Düzeltme"},
    )
    assert patched.status_code == 200
    assert patched.json()["amount_kurus"] == 80000 + 15000
    cost = client.get(f"/api/v1/projects/{project['id']}/cost-summary").json()
    assert cost["labor_kurus"] == 95000

    second = log_work(client, employee["id"], "2026-10-06", project_id=project["id"]).json()
    move_to_taken = client.patch(
        f"/api/v1/work-logs/{second['id']}", json={"work_date": "2026-10-05"}
    )
    assert move_to_taken.status_code == 409
    assert client.patch(f"/api/v1/work-logs/{second['id']}", json={}).status_code == 422
    clear_manual = client.patch(
        f"/api/v1/work-logs/{second['id']}", json={"manual_amount_kurus": 1000}
    )
    assert clear_manual.json()["amount_kurus"] == 1000
    restored = client.patch(
        f"/api/v1/work-logs/{second['id']}", json={"manual_amount_kurus": None}
    )
    assert restored.json()["amount_kurus"] == 80000

    cancelled = client.post(f"/api/v1/work-logs/{first['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/work-logs/{first['id']}/cancel").status_code == 404
    cost = client.get(f"/api/v1/projects/{project['id']}/cost-summary").json()
    assert cost["labor_kurus"] == 80000
    # İptal edilen günün yerine yeni kayıt girilebilir.
    assert log_work(client, employee["id"], "2026-10-05").status_code == 201

    listed = client.get(
        "/api/v1/work-logs", params={"employee_id": employee["id"], "date_from": "2026-10-06"}
    ).json()
    assert [item["work_date"] for item in listed] == ["2026-10-06"]


def test_bulk_preview_reports_errors_duplicates_and_commit_is_atomic(client):
    ahmet = make_employee(client, "Ahmet Usta")
    make_employee(client, "Mehmet Usta", rate=60000)
    project = make_project(client)
    make_site(client, project["id"], "Villa Şantiyesi")
    log_work(client, ahmet["id"], "2026-10-05")  # veritabanında mevcut

    good = [
        ["Ahmet Usta", "2026-10-05", "worked", None, None, None, None, None, None],
        ["Ahmet Usta", "2026-10-06", "overtime", 8, 2, "Villa Projesi", "Villa Şantiyesi", None, "x"],
        ["Mehmet Usta", "07.10.2026", "yarım gün", None, None, None, None, None, None],
        ["Mehmet Usta", "2026-10-07", "worked", None, None, None, None, None, None],
        ["Mehmet Usta", "2026-10-08", "absent", None, None, None, None, None, None],
    ]
    preview = client.post("/api/v1/work-logs/bulk-preview", json=workbook_payload(HEADERS, good))
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"]) == (5, 3, 0)
    assert body["duplicate_rows"] == 2
    assert {item["row"] for item in body["duplicates"]} == {2, 5}
    assert body["total_labor_kurus"] == 110000 + 30000 + 0
    assert body["sample"][0]["employee_name"] == "Ahmet Usta"

    bad = good + [
        ["Bilinmeyen", "2026-10-09", "worked", None, None, None, None, None, None],
        ["Ahmet Usta", "2026-10-10", "worked", None, 1, None, None, None, None],
        ["Ahmet Usta", "gün değil", "worked", None, None, None, None, None, None],
        ["Ahmet Usta", "2026-10-12", "uçtu", None, None, None, None, None, None],
        ["Ahmet Usta", "2026-10-13", "worked", None, None, "Yok Proje", None, None, None],
    ]
    bad_preview = client.post("/api/v1/work-logs/bulk-preview", json=workbook_payload(HEADERS, bad)).json()
    assert bad_preview["invalid_rows"] == 5
    assert {issue["row"] for issue in bad_preview["issues"]} == {7, 8, 9, 10, 11}

    backups_before = len(backup_manager.list())
    before_count = len(client.get("/api/v1/work-logs", params={"limit": 500}).json())
    failed = client.post("/api/v1/work-logs/bulk-commit", json=workbook_payload(HEADERS, bad))
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "import_validation_failed"
    # Tek hatalı satır varsa hiçbir kayıt yazılmaz ve yedek de alınmaz.
    assert len(client.get("/api/v1/work-logs", params={"limit": 500}).json()) == before_count
    assert len(backup_manager.list()) == backups_before

    committed = client.post("/api/v1/work-logs/bulk-commit", json=workbook_payload(HEADERS, good))
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert (result["created"], result["skipped_duplicates"]) == (3, 2)
    backup = next(b for b in backup_manager.list() if b.backup_id == result["backup_id"])
    assert backup.kind == "pre_import"
    after = client.get("/api/v1/work-logs", params={"limit": 500}).json()
    assert len(after) == before_count + 3
    # Aynı dosya tekrar gönderilirse yeni satır olmaz.
    again = client.post("/api/v1/work-logs/bulk-commit", json=workbook_payload(HEADERS, good))
    assert again.status_code == 422 and again.json()["error"]["code"] == "nothing_to_import"


def test_bulk_import_limits_template_and_ambiguous_names(client):
    template = client.get("/api/v1/work-logs/import-template").json()
    assert template["file_name"].endswith(".xlsx")

    make_employee(client, "Aynı İsim")
    make_employee(client, "Aynı İsim", rate=50000)
    ambiguous = client.post(
        "/api/v1/work-logs/bulk-preview",
        json=workbook_payload(
            HEADERS, [["Aynı İsim", "2026-10-05", "worked", None, None, None, None, None, None]]
        ),
    ).json()
    assert ambiguous["invalid_rows"] == 1
    assert "birden fazla" in ambiguous["issues"][0]["message"]

    too_many = [["X", "2026-10-05", "worked"]] * 5001
    response = client.post(
        "/api/v1/work-logs/bulk-preview", json=workbook_payload(HEADERS[:3], too_many)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_rows"
    not_xlsx = client.post(
        "/api/v1/work-logs/bulk-preview",
        json={"file_name": "x.csv", "content_base64": "YWJjZGVmZ2g="},
    )
    assert not_xlsx.status_code == 422


def test_bulk_commit_of_5000_rows_is_reasonably_fast(client):
    employees = [make_employee(client, f"Usta {index:03d}", rate=70000) for index in range(50)]
    start = date(2026, 1, 1)
    rows = [
        [employee["name"], (start + timedelta(days=day)).isoformat(), "worked"]
        for employee in employees
        for day in range(100)
    ]
    assert len(rows) == 5000
    payload = workbook_payload(HEADERS[:3], rows)

    began = time.perf_counter()
    preview = client.post("/api/v1/work-logs/bulk-preview", json=payload).json()
    preview_seconds = time.perf_counter() - began
    assert preview["valid_rows"] == 5000 and preview["total_labor_kurus"] == 5000 * 70000

    began = time.perf_counter()
    result = client.post("/api/v1/work-logs/bulk-commit", json=payload)
    commit_seconds = time.perf_counter() - began
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 5000
    assert preview_seconds < 20 and commit_seconds < 30, (preview_seconds, commit_seconds)

    with closing(sqlite3.connect(backup_manager.database_path)) as connection:
        count = connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0]
        audits = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE entity_type='work_log' AND action='created'"
        ).fetchone()[0]
    assert count == 5000 and audits == 5000
