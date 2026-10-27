from __future__ import annotations

import base64
import io

from openpyxl import Workbook


def make_employee(client, name="Ahmet Usta", wage_type="daily", rate=80000, **extra):
    payload = {
        "name": name,
        "wage_type": wage_type,
        "current_rate_kurus": rate,
        "rate_effective_from": "2026-01-01",
        **extra,
    }
    response = client.post("/api/v1/employees", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_project(client, name="Villa Projesi", **extra):
    payload = {
        "name": name,
        "customer_name": "Müşteri",
        "budget_kurus": 2000000,
        "contract_amount_kurus": 3000000,
        **extra,
    }
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_site(client, project_id=None, name="Villa Şantiyesi"):
    response = client.post("/api/v1/sites", json={"name": name, "project_id": project_id})
    assert response.status_code == 201, response.text
    return response.json()


def log_work(client, employee_id, day, **extra):
    payload = {"employee_id": employee_id, "work_date": day, **extra}
    return client.post("/api/v1/work-logs", json=payload)


def workbook_payload(headers, rows, file_name="puantaj.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    return {
        "file_name": file_name,
        "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
    }
