"""
Integration tests for the Event Marker Presets API endpoint.

Covers:
    GET  /api/session/markers/presets
"""

import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock, PropertyMock
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.config import config_manager, OVARPConfig, EventMarkerPreset


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestMarkerPresets:
    def test_get_presets_returns_configured_presets(self, client, mock_config, mocker):
        """Presets endpoint should return the event_markers from config."""
        # Inject presets into the mock config
        mock_config.event_markers = [
            EventMarkerPreset(id="task_started", label="Task Started", color="#28a745"),
            EventMarkerPreset(id="agent_error", label="Agent Error", description="The agent behaved unexpectedly", color="#fd7e14"),
        ]
        mocker.patch("src.core.config.ConfigManager.config", new_callable=PropertyMock, return_value=mock_config)

        resp = client.get("/api/session/markers/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        assert len(data["presets"]) == 2

        # Check first preset
        p0 = data["presets"][0]
        assert p0["id"] == "task_started"
        assert p0["label"] == "Task Started"
        assert p0["color"] == "#28a745"

        # Check second preset has description
        p1 = data["presets"][1]
        assert p1["id"] == "agent_error"
        assert p1["description"] == "The agent behaved unexpectedly"

    def test_get_presets_returns_empty_when_none_configured(self, client, mock_config, mocker):
        """Presets endpoint should return empty list when no event_markers in config."""
        mock_config.event_markers = None
        mocker.patch("src.core.config.ConfigManager.config", new_callable=PropertyMock, return_value=mock_config)

        resp = client.get("/api/session/markers/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["presets"] == []

    def test_get_presets_returns_empty_list_when_empty(self, client, mock_config, mocker):
        """Presets endpoint should return empty list when event_markers is an empty list."""
        mock_config.event_markers = []
        mocker.patch("src.core.config.ConfigManager.config", new_callable=PropertyMock, return_value=mock_config)

        resp = client.get("/api/session/markers/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["presets"] == []

    def test_preset_schema_includes_optional_fields(self, client, mock_config, mocker):
        """Presets should include all schema fields, with None for optional ones not set."""
        mock_config.event_markers = [
            EventMarkerPreset(id="minimal", label="Minimal Preset"),
        ]
        mocker.patch("src.core.config.ConfigManager.config", new_callable=PropertyMock, return_value=mock_config)

        resp = client.get("/api/session/markers/presets")
        assert resp.status_code == 200
        preset = resp.json()["presets"][0]
        assert preset["id"] == "minimal"
        assert preset["label"] == "Minimal Preset"
        assert preset["description"] is None
        assert preset["color"] is None
