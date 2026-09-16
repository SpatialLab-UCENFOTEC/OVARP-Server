"""
Integration tests for the Session Management REST API endpoints.

Covers:
    GET  /api/session/status
    POST /api/session/start
    POST /api/session/pause
    POST /api/session/resume
    POST /api/session/end
    POST /api/session/marker
"""

import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.runtime import runtime
from src.core.session_manager import SessionManager


@pytest.fixture(autouse=True)
def setup_app(monkeypatch):
    """Inject a fresh SessionManager and mock telemetry into main module."""
    fresh_mgr = SessionManager()
    fresh_mgr._session = None

    monkeypatch.setattr(runtime, "session_manager", fresh_mgr, raising=False)
    monkeypatch.setattr(runtime, "telemetry", MagicMock(), raising=False)

    yield {"mgr": fresh_mgr}


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestSessionStatus:
    def test_status_no_session(self, client):
        resp = client.get("/api/session/status")
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_status_active_session(self, client, setup_app):
        setup_app["mgr"].start_session("P001")
        resp = client.get("/api/session/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["participant_id"] == "P001"


class TestSessionLifecycle:
    def test_start_session(self, client):
        resp = client.post("/api/session/start", json={"participant_id": "P100"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["participant_id"] == "P100"
        assert data["status"] == "active"

    def test_pause_session(self, client, setup_app):
        setup_app["mgr"].start_session("P101")
        resp = client.post("/api/session/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    def test_resume_session(self, client, setup_app):
        setup_app["mgr"].start_session("P102")
        setup_app["mgr"].pause_session()
        resp = client.post("/api/session/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_end_session(self, client, setup_app):
        setup_app["mgr"].start_session("P103")
        resp = client.post("/api/session/end")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "session" in data

    def test_end_without_start(self, client):
        resp = client.post("/api/session/end")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_pause_without_start(self, client):
        resp = client.post("/api/session/pause")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_resume_without_pause(self, client):
        resp = client.post("/api/session/resume")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestSessionMarkers:
    def test_add_marker(self, client, setup_app):
        setup_app["mgr"].start_session("P200")
        resp = client.post("/api/session/marker", json={
            "label": "task_start",
            "metadata": {"phase": 1},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["marker"]["label"] == "task_start"
        assert data["marker"]["metadata"] == {"phase": 1}

    def test_add_marker_without_metadata(self, client, setup_app):
        setup_app["mgr"].start_session("P201")
        resp = client.post("/api/session/marker", json={"label": "simple_event"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_add_marker_without_session(self, client):
        resp = client.post("/api/session/marker", json={"label": "should_fail"})
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestMarkerEditing:
    """Correcting a marker must leave an auditable trail in the session log."""

    @pytest.fixture
    def marker_id(self, client):
        client.post("/api/session/start", json={"participant_id": "P_EDIT"})
        resp = client.post("/api/session/marker", json={"label": "task_startd"})
        return resp.json()["marker"]["id"]

    def test_amend_label_and_notes(self, client, marker_id, setup_app):
        resp = client.patch(f"/api/session/marker/{marker_id}",
                            json={"label": "task_started", "notes": "dudo al inicio"})

        assert resp.status_code == 200
        marker = resp.json()["marker"]
        assert marker["label"] == "task_started"
        assert marker["notes"] == "dudo al inicio"
        assert marker["amended"] is True

    def test_amendment_is_logged_with_the_previous_value(self, client, marker_id):
        client.patch(f"/api/session/marker/{marker_id}", json={"label": "task_started"})

        runtime.telemetry.log_marker_amendment.assert_called_once()
        args = runtime.telemetry.log_marker_amendment.call_args[0]
        assert args[0] == marker_id
        assert args[1] == {"label": "task_startd"}
        assert args[2] == {"label": "task_started"}

    def test_no_op_amendment_is_not_logged(self, client, marker_id):
        resp = client.patch(f"/api/session/marker/{marker_id}", json={"label": "task_startd"})

        assert resp.json()["amended"] is False
        runtime.telemetry.log_marker_amendment.assert_not_called()

    def test_delete_marker(self, client, marker_id):
        resp = client.delete(f"/api/session/marker/{marker_id}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert client.get("/api/session/status").json()["marker_count"] == 0
        runtime.telemetry.log_marker_deleted.assert_called_once()

    def test_unknown_marker_returns_error(self, client, marker_id):
        assert "error" in client.patch("/api/session/marker/nope", json={"label": "x"}).json()
        assert "error" in client.delete("/api/session/marker/nope").json()


class TestMarkerCategory:
    """Markers carry a category so the export can group them."""

    def test_marker_stores_its_category(self, client):
        client.post("/api/session/start", json={"participant_id": "P10"})

        resp = client.post(
            "/api/session/marker",
            json={"label": "headset_slipped", "category": "Technical Issue"},
        )

        assert resp.json()["marker"]["category"] == "Technical Issue"

    def test_category_can_be_amended(self, client):
        client.post("/api/session/start", json={"participant_id": "P11"})
        marker_id = client.post(
            "/api/session/marker", json={"label": "odd_reply"}
        ).json()["marker"]["id"]

        resp = client.patch(
            f"/api/session/marker/{marker_id}", json={"category": "Agent Error"}
        )

        assert resp.json()["marker"]["category"] == "Agent Error"
        assert resp.json()["marker"]["amended"] is True


class TestSessionCsvExport:
    """GET /api/session/export/csv hands a researcher a flat table."""

    def test_export_contains_the_header_and_markers(self, client):
        client.post("/api/session/start", json={"participant_id": "P12"})
        client.post(
            "/api/session/marker",
            json={"label": "task_started", "category": "Protocol", "notes": "after consent"},
        )

        resp = client.get("/api/session/export/csv")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        lines = resp.text.strip().splitlines()
        assert lines[0].startswith("Timestamp_ISO,Unix_Timestamp,Session_ID")
        assert "SESSION_START" in lines[1]
        assert "Protocol" in lines[2]
        assert "after consent" in lines[2]

    def test_export_falls_back_to_the_label_without_a_category(self, client):
        client.post("/api/session/start", json={"participant_id": "P13"})
        client.post("/api/session/marker", json={"label": "uncategorised"})

        assert "uncategorised" in client.get("/api/session/export/csv").text

    def test_export_without_a_session_still_returns_a_table(self, client):
        resp = client.get("/api/session/export/csv")

        assert resp.status_code == 200
        assert "NO_ACTIVE_SESSION" in resp.text

    def test_amended_markers_are_flagged_in_the_export(self, client):
        client.post("/api/session/start", json={"participant_id": "P14"})
        marker_id = client.post(
            "/api/session/marker", json={"label": "typo"}
        ).json()["marker"]["id"]
        client.patch(f"/api/session/marker/{marker_id}", json={"label": "fixed"})

        rows = client.get("/api/session/export/csv").text.strip().splitlines()

        assert rows[2].endswith(",yes")
