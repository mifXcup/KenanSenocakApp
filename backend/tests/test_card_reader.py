from __future__ import annotations

import pytest
from helpers import make_employee

from ks_yonetim import card_reader

URL = "https://script.google.com/macros/s/AKfycbxTEST/exec"


def event(event_id, uid, at, direction=None, device="kapi-1"):
    body = {"event_id": event_id, "card_uid": uid, "event_at": at, "device_id": device}
    if direction:
        body["direction"] = direction
    return body


def enable(client):
    response = client.put(
        "/api/v1/card-reader/settings",
        json={"web_app_url": URL, "secret": "gizli-anahtar", "enabled": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_settings_are_off_by_default_and_validate_url(client):
    settings = client.get("/api/v1/card-reader/settings").json()
    assert settings["enabled"] is False and settings["has_secret"] is False
    incomplete = client.put("/api/v1/card-reader/settings", json={"enabled": True})
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "card_reader_incomplete"
    for bad in (
        "http://script.google.com/macros/s/x/exec",
        "https://example.com/macros/s/x/exec",
        "https://script.google.com/other",
    ):
        response = client.put("/api/v1/card-reader/settings", json={"web_app_url": bad})
        assert response.status_code == 422, bad
    saved = enable(client)
    assert saved["enabled"] is True and saved["has_secret"] is True
    assert "secret" not in saved and "gizli-anahtar" not in str(saved)


def test_events_are_idempotent_deduplicated_and_unknown_cards_resolve_later(client):
    employee = make_employee(client)
    assigned = client.put(
        "/api/v1/card-reader/cards", json={"employee_id": employee["id"], "card_uid": "04:a1:b2:c3"}
    )
    assert assigned.status_code == 200 and assigned.json()["card_uid"] == "04A1B2C3"
    batch = {
        "events": [
            event("e1", "04A1B2C3", "2026-03-09T08:00:00+03:00"),
            event("e2", "04a1b2c3", "2026-03-09T08:00:20+03:00"),
            event("e3", "FFEE0011", "2026-03-09T08:05:00+03:00"),
            {"event_id": "bad", "card_uid": "XYZ", "event_at": "2026-03-09T08:00:00+03:00"},
        ]
    }
    first = client.post("/api/v1/card-reader/events/import", json=batch).json()
    assert (first["created"], first["duplicates"], first["unknown_card"]) == (2, 1, 1)
    assert len(first["invalid"]) == 1
    again = client.post("/api/v1/card-reader/events/import", json=batch).json()
    assert again["created"] == 0 and again["skipped_existing"] == 3

    unknown = client.get("/api/v1/card-reader/events?unknown_only=true").json()
    assert [item["card_uid"] for item in unknown] == ["FFEE0011"]
    other = make_employee(client, name="Mehmet Usta")
    client.put("/api/v1/card-reader/cards", json={"employee_id": other["id"], "card_uid": "ffee0011"})
    assert client.get("/api/v1/card-reader/events?unknown_only=true").json() == []

    conflict = client.put(
        "/api/v1/card-reader/cards", json={"employee_id": other["id"], "card_uid": "04A1B2C3"}
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "card_in_use"


def test_review_proposes_hours_and_approval_creates_work_log_once(client):
    employee = make_employee(client)
    client.put("/api/v1/card-reader/cards", json={"employee_id": employee["id"], "card_uid": "0A0B0C0D"})
    client.put("/api/v1/card-reader/settings", json={"break_minutes": 60})
    client.post(
        "/api/v1/card-reader/events/import",
        json={
            "events": [
                event("a1", "0A0B0C0D", "2026-03-09T08:02:00+03:00"),
                event("a2", "0A0B0C0D", "2026-03-09T18:31:00+03:00"),
                event("b1", "0A0B0C0D", "2026-03-10T08:00:00+03:00"),
            ]
        },
    )
    review = client.get("/api/v1/card-reader/review").json()
    by_date = {day["work_date"]: day for day in review["days"]}
    nine = by_date["2026-03-09"]
    assert nine["event_count"] == 2 and nine["needs_manual"] is False
    # 10 sa 29 dk - 60 dk mola = 9,48 sa -> çeyreğe yuvarla 9,5: 8 normal + 1,5 fazla mesai
    assert (nine["proposed_normal_hours"], nine["proposed_overtime_hours"]) == (8.0, 1.5)
    assert by_date["2026-03-10"]["needs_manual"] is True

    approval = client.post(
        "/api/v1/card-reader/review/approve",
        json={"items": [{"employee_id": employee["id"], "work_date": "2026-03-09", "normal_hours": "8", "overtime_hours": "1.5"}]},
    ).json()
    assert approval["approved"] == 1, approval
    logs = client.get("/api/v1/work-logs").json()
    assert len(logs) == 1 and logs[0]["work_date"] == "2026-03-09"
    processed = client.get("/api/v1/card-reader/events?state=processed").json()
    assert {item["event_key"] for item in processed} == {"a1", "a2"}
    assert all(item["work_log_id"] == logs[0]["id"] for item in processed)

    retry = client.post(
        "/api/v1/card-reader/review/approve",
        json={"items": [{"employee_id": employee["id"], "work_date": "2026-03-09", "normal_hours": "8"}]},
    ).json()
    assert retry["approved"] == 0 and retry["results"][0]["ok"] is False
    assert len(client.get("/api/v1/work-logs").json()) == 1

    left = client.get("/api/v1/card-reader/review").json()["days"]
    assert [day["work_date"] for day in left] == ["2026-03-10"]
    ignored = client.post(f"/api/v1/card-reader/events/{by_date['2026-03-10']['event_ids'][0]}/ignore")
    assert ignored.status_code == 200 and ignored.json()["state"] == "ignored"
    assert client.get("/api/v1/card-reader/review").json()["days"] == []


def test_sync_reads_new_rows_with_cursor_and_records_errors(client, monkeypatch):
    employee = make_employee(client)
    client.put("/api/v1/card-reader/cards", json={"employee_id": employee["id"], "card_uid": "AABBCCDD"})
    assert client.post("/api/v1/card-reader/sync").status_code == 409  # kapalı

    enable(client)
    calls = []

    def fake_fetch(url, secret, cursor, limit=card_reader.PAGE_SIZE):
        calls.append((url, secret, cursor))
        if cursor == "0":
            return {"events": [event("r2", "AABBCCDD", "2026-03-09T08:00:00+03:00")], "next_cursor": "2"}
        return {"events": [], "next_cursor": cursor}

    monkeypatch.setattr(card_reader, "fetch_sheet_events", fake_fetch)
    result = client.post("/api/v1/card-reader/sync").json()
    assert result["created"] == 1
    assert client.post("/api/v1/card-reader/sync").json()["created"] == 0
    assert [call[2] for call in calls] == ["0", "2"]
    settings = client.get("/api/v1/card-reader/settings").json()
    assert settings["cursor"] == "2" and settings["last_sync_at"] and settings["last_error"] is None

    def failing_fetch(*_args, **_kwargs):
        raise card_reader.CardReaderError("Google Sheet'e ulaşılamadı: zaman aşımı")

    monkeypatch.setattr(card_reader, "fetch_sheet_events", failing_fetch)
    failed = client.post("/api/v1/card-reader/sync")
    assert failed.status_code == 502
    assert "zaman aşımı" in client.get("/api/v1/card-reader/settings").json()["last_error"]

    # URL değişince imleç sıfırlanır
    client.put("/api/v1/card-reader/settings", json={"web_app_url": URL.replace("TEST", "YENI")})
    assert client.get("/api/v1/card-reader/settings").json()["cursor"] == "0"


def test_fetch_rejects_malformed_apps_script_answers(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.body

    for body in (b"<html>login</html>", b'{"error":"bad secret"}', b'{"rows":[]}'):
        monkeypatch.setattr(card_reader.urllib.request, "urlopen", lambda *_a, _b=body, **_k: FakeResponse(_b))
        with pytest.raises(card_reader.CardReaderError):
            card_reader.fetch_sheet_events(URL, "s", "0")
