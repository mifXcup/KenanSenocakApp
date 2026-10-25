from __future__ import annotations

import base64
import io

from openpyxl import Workbook, load_workbook


def workbook_payload(headers, rows, file_name="aktarim.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    return {"file_name": file_name, "content_base64": base64.b64encode(stream.getvalue()).decode()}


def test_supplier_template_preview_commit_and_duplicate_skip(client):
    template = client.get("/api/v1/imports/templates/suppliers")
    assert template.status_code == 200
    decoded = base64.b64decode(template.json()["content_base64"])
    workbook = load_workbook(io.BytesIO(decoded), read_only=True)
    assert workbook.active["A1"].value == "Firma Adı*"

    payload = workbook_payload(
        ["Firma Adı*", "Telefon", "Not"],
        [["Akın Orman", "0555", "Ana tedarikçi"], ["Akın Orman", None, None]],
    )
    preview = client.post("/api/v1/imports/suppliers/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["duplicate_rows"] == 1

    committed = client.post("/api/v1/imports/suppliers/commit", json=payload)
    assert committed.status_code == 200
    assert committed.json()["created"] == 1
    assert committed.json()["backup_id"]
    assert len(client.get("/api/v1/suppliers").json()) == 1

    repeated = client.post("/api/v1/imports/suppliers/commit", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["created"] == 0
    assert repeated.json()["skipped_duplicates"] == 2


def test_material_import_rejects_invalid_rows_atomically(client):
    payload = workbook_payload(
        ["Malzeme Adı*", "Birim*", "Takip Türü*", "Not"],
        [["MDF 18mm", "levha", "yaklaşık", None], ["Hatalı", "adet", "bilinmeyen", None]],
    )
    preview = client.post("/api/v1/imports/materials/preview", json=payload).json()
    assert preview["valid_rows"] == 1
    assert preview["invalid_rows"] == 1
    commit = client.post("/api/v1/imports/materials/commit", json=payload)
    assert commit.status_code == 422
    assert commit.json()["error"]["code"] == "import_validation_failed"
    assert client.get("/api/v1/materials").json() == []


def test_opening_debt_import_and_xlsx_exports(client):
    client.post("/api/v1/suppliers", json={"name": "Borç Firması"})
    payload = workbook_payload(
        ["Firma Adı*", "Tutar (TL)*", "Tarih*", "Vade Tarihi", "Açıklama"],
        [["Borç Firması", "1.250,50", "26.10.2026", "15.11.2026", "Devir borcu"]],
    )
    committed = client.post("/api/v1/imports/opening-debts/commit", json=payload)
    assert committed.status_code == 200
    purchases = client.get("/api/v1/purchases").json()
    assert len(purchases) == 1
    assert purchases[0]["total_kurus"] == 125050
    assert purchases[0]["due_date"] == "2026-11-15"

    for kind in ("suppliers", "materials", "purchases", "project-costs"):
        response = client.get(f"/api/v1/exports/{kind}")
        assert response.status_code == 200
        raw = base64.b64decode(response.json()["content_base64"])
        assert raw.startswith(b"PK")


def test_workbook_size_type_and_unknown_supplier_are_rejected(client):
    wrong_type = {"file_name": "data.csv", "content_base64": base64.b64encode(b"a,b").decode()}
    assert client.post("/api/v1/imports/suppliers/preview", json=wrong_type).status_code == 422

    payload = workbook_payload(
        ["Firma Adı*", "Tutar (TL)*", "Tarih*"],
        [["Olmayan Firma", 100, "2026-10-26"]],
    )
    preview = client.post("/api/v1/imports/opening-debts/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["invalid_rows"] == 1
