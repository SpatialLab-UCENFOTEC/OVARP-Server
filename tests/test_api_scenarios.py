"""
Integration tests for the Scenario Runner REST API endpoints.

Covers:
    GET  /api/scenarios
    POST /api/scenarios/load
    POST /api/scenarios/advance
    GET  /api/scenarios/status
    POST /api/scenarios/stop
"""

import os
import pytest
import yaml

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.scenario_runner import ScenarioRunner


@pytest.fixture
def scenario_dir(tmp_path):
    """Create a temp directory with a test scenario YAML."""
    scenario_data = {
        "id": "api_test_scenario",
        "name": "API Test Scenario",
        "description": "Used for integration testing",
        "steps": [
            {"id": "step1", "instruction": "Welcome the participant."},
            {"id": "step2", "instruction": "Begin the task.", "auto_marker": "task_start"},
            {"id": "step3", "instruction": "Wrap up.", "action": {"emotions": "happy"}},
        ],
    }
    yaml_file = tmp_path / "api_test.yaml"
    with open(yaml_file, "w") as f:
        yaml.dump(scenario_data, f)
    return str(tmp_path)


@pytest.fixture(autouse=True)
def setup_app(monkeypatch, scenario_dir):
    """Inject a ScenarioRunner preloaded with test data into main module."""
    runner = ScenarioRunner()
    runner._scenarios = {}
    runner._active_scenario = None
    runner._current_step_index = -1
    runner.load_scenarios_from_dir(scenario_dir)

    mock_session_mgr = MagicMock()
    mock_session_mgr.add_marker = MagicMock()
    mock_router = MagicMock()
    mock_router.route_command = AsyncMock()
    mock_config_manager = MagicMock()
    mock_config_manager.config.conditions = {}

    monkeypatch.setattr(main_module, "scenario_runner", runner, raising=False)
    monkeypatch.setattr(main_module, "session_manager", mock_session_mgr, raising=False)
    monkeypatch.setattr(main_module, "telemetry", MagicMock(), raising=False)
    monkeypatch.setattr(main_module, "orchestrator", MagicMock(), raising=False)
    monkeypatch.setattr(main_module, "config_manager", mock_config_manager, raising=False)
    monkeypatch.setattr(main_module, "router", mock_router, raising=False)

    yield {"runner": runner}


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestListScenarios:
    def test_list_scenarios(self, client):
        resp = client.get("/api/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert "scenarios" in data
        assert len(data["scenarios"]) == 1
        assert data["scenarios"][0]["id"] == "api_test_scenario"
        assert data["scenarios"][0]["step_count"] == 3


class TestScenarioLifecycle:
    def test_load_scenario(self, client):
        resp = client.post("/api/scenarios/load", json={"scenario_id": "api_test_scenario"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["active"] is True
        assert data["current_step"] == 1
        assert data["step"]["id"] == "step1"

    def test_load_unknown_scenario(self, client):
        resp = client.post("/api/scenarios/load", json={"scenario_id": "nonexistent"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_advance_scenario(self, client, setup_app):
        setup_app["runner"].start("api_test_scenario")
        resp = client.post("/api/scenarios/advance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["current_step"] == 2
        assert data["step"]["id"] == "step2"

    def test_advance_past_end(self, client, setup_app):
        runner = setup_app["runner"]
        runner.start("api_test_scenario")
        runner.advance()  # step2
        runner.advance()  # step3
        resp = client.post("/api/scenarios/advance")  # past end
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["active"] is False

    def test_advance_without_start(self, client):
        resp = client.post("/api/scenarios/advance")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestScenarioStatus:
    def test_status_inactive(self, client):
        resp = client.get("/api/scenarios/status")
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_status_active(self, client, setup_app):
        setup_app["runner"].start("api_test_scenario")
        resp = client.get("/api/scenarios/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["progress_pct"] == 33


class TestScenarioStop:
    def test_stop_active_scenario(self, client, setup_app):
        setup_app["runner"].start("api_test_scenario")
        resp = client.post("/api/scenarios/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["active"] is False

    def test_stop_when_inactive(self, client):
        resp = client.post("/api/scenarios/stop")
        assert resp.status_code == 200
        assert resp.json()["active"] is False
