import base64


def create_project(client):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Köşk Mutfak",
            "customer_name": "Örnek Müşteri",
            "accent_color": "#8A5A3A",
            "stage": "design",
            "progress_percent": 25,
            "next_step": "Renk onayını al",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_completed_historical_project_can_be_created(client):
    response = client.post("/api/v1/projects", json={
        "name": "Geçmiş mutfak projesi",
        "customer_name": "Örnek Müşteri",
        "project_state": "completed",
        "stage": "completed",
        "progress_percent": 100,
    })
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["project_state"] == "completed"
    assert project["stage"] == "completed"
    assert project["progress_percent"] == 100
    listed = client.get("/api/v1/projects")
    assert project["id"] in {item["id"] for item in listed.json()}


def test_project_contract_upload_and_download(client):
    pdf = b"%PDF-1.4\nexample contract"
    response = client.post("/api/v1/projects", json={
        "name": "Yeni Mutfak", "customer_name": "Örnek Müşteri",
        "contract_amount_kurus": 25000000,
        "contract_file": {"file_name": "sozlesme.pdf", "content_base64": base64.b64encode(pdf).decode()},
    })
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["contract_amount_kurus"] == 25000000
    assert project["budget_kurus"] is None
    project_id = project["id"]

    metadata = client.get(f"/api/v1/projects/{project_id}/contract")
    assert metadata.status_code == 200
    assert metadata.json()["file_name"] == "sozlesme.pdf"
    assert metadata.json()["size_bytes"] == len(pdf)
    downloaded = client.get(f"/api/v1/projects/{project_id}/contract/file")
    assert downloaded.status_code == 200
    assert downloaded.content == pdf
    assert downloaded.headers["content-type"] == "application/pdf"

    replacement = b"%PDF-1.7\nupdated contract"
    replaced = client.put(f"/api/v1/projects/{project_id}/contract", json={
        "file_name": "yeni.pdf", "content_base64": base64.b64encode(replacement).decode(),
    })
    assert replaced.status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/contract/file").content == replacement


def test_project_contract_rejects_invalid_file(client):
    project = create_project(client)
    project_id = project["id"]
    assert client.get(f"/api/v1/projects/{project_id}/contract").status_code == 404
    invalid = client.put(f"/api/v1/projects/{project_id}/contract", json={
        "file_name": "fake.pdf", "content_base64": base64.b64encode(b"not a PDF").decode(),
    })
    assert invalid.status_code == 422
    invalid_docx = client.put(f"/api/v1/projects/{project_id}/contract", json={
        "file_name": "fake.docx", "content_base64": base64.b64encode(b"PKnot a DOCX").decode(),
    })
    assert invalid_docx.status_code == 422
    assert client.get(f"/api/v1/projects/{project_id}/contract").status_code == 404


def test_foreign_agreed_price_keeps_original_and_tl_equivalent(client):
    response = client.post("/api/v1/projects", json={
        "name": "Dövizli Mutfak", "customer_name": "Örnek Müşteri",
        "contract_currency": "USD", "contract_foreign_amount_minor": 10050,
        "contract_fx_rate": "42.25",
    })
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["contract_currency"] == "USD"
    assert project["contract_foreign_amount_minor"] == 10050
    assert project["contract_amount_kurus"] == 424613
    profitability = client.get(f"/api/v1/projects/{project['id']}/profitability")
    assert profitability.status_code == 200
    assert profitability.json()["contract_amount_kurus"] == 424613
    updated = client.patch(f"/api/v1/projects/{project['id']}", json={
        "contract_currency": "TRY", "contract_amount_kurus": 500000,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["contract_foreign_amount_minor"] is None
    assert updated.json()["contract_fx_rate"] is None
    assert updated.json()["contract_amount_kurus"] == 500000


def test_foreign_agreed_price_requires_rate(client):
    response = client.post("/api/v1/projects", json={
        "name": "Dövizli Mutfak", "customer_name": "Örnek Müşteri",
        "contract_currency": "EUR", "contract_foreign_amount_minor": 10000,
    })
    assert response.status_code == 422


def test_project_hub_records_notes_tasks_colors_and_visits(client):
    project = create_project(client)
    project_id = project["id"]

    records = (
        ("notes", {"content": "Tezgah taşı numunesi geldi.", "pinned": True}),
        ("tasks", {"title": "Elektrik planını bekle", "task_state": "waiting", "waiting_on": "Elektrikçi", "due_date": "2026-11-01"}),
        ("colors", {"label": "Mutfak kapağı", "color_code": "RAL 1019", "material": "Mat lake"}),
        ("visits", {"visit_date": "2026-11-03", "purpose": "Son ölçü kontrolü"}),
    )
    created = {}
    for endpoint, payload in records:
        response = client.post(f"/api/v1/projects/{project_id}/{endpoint}", json=payload)
        assert response.status_code == 201, response.text
        created[endpoint] = response.json()

    hub = client.get(f"/api/v1/projects/{project_id}/hub")
    assert hub.status_code == 200, hub.text
    data = hub.json()
    assert data["project"]["next_step"] == "Renk onayını al"
    assert data["notes"][0]["pinned"] is True
    assert data["tasks"][0]["waiting_on"] == "Elektrikçi"
    assert data["colors"][0]["color_code"] == "RAL 1019"
    assert "measurements" not in data
    assert data["visits"][0]["purpose"] == "Son ölçü kontrolü"

    completed = client.patch(f"/api/v1/project-tasks/{created['tasks']['id']}", json={"task_state": "done"})
    assert completed.status_code == 200
    assert completed.json()["task_state"] == "done"


def test_project_measurement_entry_is_removed(client):
    project_id = create_project(client)["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/measurements",
        json={"space_name": "Mutfak", "label": "Tezgah duvarı", "value": "324", "unit": "cm", "measured_on": "2026-10-27"},
    )
    assert response.status_code == 404
