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
from src.core.session_manager import SessionManager


@pytest.fixture(autouse=True)
def setup_app(monkeypatch):
    """Inject a fresh SessionManager and mock telemetry into main module."""
    fresh_mgr = SessionManager()
    fresh_mgr._session = None

    monkeypatch.setattr(main_module, "session_manager", fresh_mgr, raising=False)
    monkeypatch.setattr(main_module, "telemetry", MagicMock(), raising=False)

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
