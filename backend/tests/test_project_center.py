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


def test_project_hub_records_notes_tasks_specs_and_visits(client):
    project = create_project(client)
    project_id = project["id"]

    records = (
        ("notes", {"content": "Tezgah taşı numunesi geldi.", "pinned": True}),
        ("tasks", {"title": "Elektrik planını bekle", "task_state": "waiting", "waiting_on": "Elektrikçi", "due_date": "2026-11-01"}),
        ("colors", {"label": "Mutfak kapağı", "color_code": "RAL 1019", "material": "Mat lake"}),
        ("measurements", {"space_name": "Mutfak", "label": "Tezgah duvarı", "value": "324", "unit": "cm", "measured_on": "2026-10-27"}),
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
    assert data["measurements"][0]["value"] == "324"
    assert data["visits"][0]["purpose"] == "Son ölçü kontrolü"

    completed = client.patch(f"/api/v1/project-tasks/{created['tasks']['id']}", json={"task_state": "done"})
    assert completed.status_code == 200
    assert completed.json()["task_state"] == "done"
