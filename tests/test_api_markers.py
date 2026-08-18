"""
Unit and Integration Tests for Event Markers (R4 Backend).

Tests EventMarker model, SessionManager marker reclassification and notes updates,
TelemetryLogger JSONL log updating, and PUT /api/session/markers/{marker_id} endpoint.

Author: Alexander Barquero Elizondo, Ph.D. - UCR, ECCI/CITIC
License: MIT
"""

import os
import pytest
from fastapi.testclient import TestClient

os.environ["OVARP_TESTING"] = "1"

from src.main import app
from src.core.session_manager import session_manager, EventMarker


class TestEventMarkerModel:
    def test_marker_creation_defaults(self):
        marker = EventMarker(timestamp=1000.0, iso_time="2026-08-07T12:00:00", label="task_start")
        assert marker.id is not None
        assert len(marker.id) == 8
        assert marker.category is None
        assert marker.notes is None

    def test_marker_creation_full(self):
        marker = EventMarker(
            id="m1234567",
            timestamp=1000.0,
            iso_time="2026-08-07T12:00:00",
            label="confused",
            category="Participant Issue",
            notes="Participant was unsure how to proceed",
            metadata={"step": 2}
        )
        assert marker.id == "m1234567"
        assert marker.category == "Participant Issue"
        assert marker.notes == "Participant was unsure how to proceed"
        assert marker.metadata == {"step": 2}


class TestSessionManagerMarkers:
    def test_add_and_update_marker_by_id(self):
        if session_manager.is_active:
            session_manager.end_session()

        session_manager.start_session("P_MARKER_01")
        m = session_manager.add_marker(label="initial_label", category="General", notes="Init note")
        assert m.category == "General"

        updated = session_manager.update_marker(
            marker_id=m.id,
            category="Technical Issue",
            notes="Updated note: Lag detected",
            label="reclassified_label"
        )
        assert updated.id == m.id
        assert updated.category == "Technical Issue"
        assert updated.notes == "Updated note: Lag detected"
        assert updated.label == "reclassified_label"

        session_manager.end_session()

    def test_update_marker_by_index(self):
        if session_manager.is_active:
            session_manager.end_session()

        session_manager.start_session("P_MARKER_02")
        session_manager.add_marker(label="first_marker")
        session_manager.add_marker(label="second_marker")

        # Update by index string "1"
        updated = session_manager.update_marker("1", category="User Error", notes="Pressed wrong button")
        assert updated.label == "second_marker"
        assert updated.category == "User Error"

        session_manager.end_session()

    def test_update_marker_error_no_session(self):
        if session_manager.is_active:
            session_manager.end_session()

        with pytest.raises(ValueError, match="No active session"):
            session_manager.update_marker("m_invalid", category="Issue")

    def test_update_marker_error_not_found(self):
        if session_manager.is_active:
            session_manager.end_session()

        session_manager.start_session("P_MARKER_03")
        with pytest.raises(ValueError, match="not found"):
            session_manager.update_marker("nonexistent_id", category="Issue")
        session_manager.end_session()


class TestMarkerAPIEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_put_marker_update_endpoint_success(self, client):
        if session_manager.is_active:
            session_manager.end_session()

        # Start session and add marker via API
        client.post("/api/session/start", json={"participant_id": "P_API_01"})
        add_resp = client.post("/api/session/marker", json={
            "label": "stuck",
            "category": "Confusion",
            "notes": "User froze"
        })
        assert add_resp.status_code == 200
        marker_id = add_resp.json()["marker"]["id"]

        # Update marker via PUT endpoint
        put_resp = client.put(f"/api/session/markers/{marker_id}", json={
            "category": "Technical Issue",
            "notes": "Reclassified: Controller disconnected",
            "label": "hardware_failure"
        })
        assert put_resp.status_code == 200
        data = put_resp.json()
        assert data["status"] == "ok"
        assert data["marker"]["category"] == "Technical Issue"
        assert data["marker"]["notes"] == "Reclassified: Controller disconnected"
        assert data["marker"]["label"] == "hardware_failure"

        client.post("/api/session/end")

    def test_put_marker_update_endpoint_no_session(self, client):
        if session_manager.is_active:
            session_manager.end_session()

        put_resp = client.put("/api/session/markers/marker_99", json={
            "category": "Issue"
        })
        assert put_resp.status_code == 400
        assert "error" in put_resp.json()
