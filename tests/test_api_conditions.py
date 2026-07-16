"""
Integration tests for the deprecated Conditions REST API endpoints.

These endpoints exist for backward compatibility with clients that used
the original condition-based API before profiles were introduced.

Covers:
    GET  /api/conditions
    POST /api/conditions/apply
"""

import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.profile_manager import ProfileManager, AgentProfile, ProfilePersonality


@pytest.fixture(autouse=True)
def setup_app(monkeypatch):
    """Inject ProfileManager with migrated conditions and mock orchestrator."""
    mgr = ProfileManager.__new__(ProfileManager)
    mgr._profiles = {}

    # Simulate migrated conditions
    mgr._profiles["condition_empathetic"] = AgentProfile(
        id="condition_empathetic",
        name="Empathetic (migrated)",
        personality=ProfilePersonality(
            system_prompt="Be warm, empathetic, and supportive.",
        ),
    )
    mgr._profiles["condition_neutral"] = AgentProfile(
        id="condition_neutral",
        name="Neutral (migrated)",
        personality=ProfilePersonality(
            system_prompt="Be neutral and factual.",
        ),
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.apply_profile = MagicMock()

    monkeypatch.setattr(main_module, "profile_manager", mgr, raising=False)
    monkeypatch.setattr(main_module, "orchestrator", mock_orchestrator, raising=False)
    monkeypatch.setattr(main_module, "telemetry", MagicMock(), raising=False)

    yield {"mgr": mgr, "orchestrator": mock_orchestrator}


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestGetConditions:
    def test_get_conditions_returns_profiles(self, client):
        resp = client.get("/api/conditions")
        assert resp.status_code == 200
        data = resp.json()
        assert "conditions" in data
        assert "condition_empathetic" in data["conditions"]
        assert "condition_neutral" in data["conditions"]


class TestApplyCondition:
    def test_apply_condition_with_prefix(self, client, setup_app):
        """Apply using the full 'condition_empathetic' ID."""
        resp = client.post("/api/conditions/apply", json={
            "condition_id": "condition_empathetic",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["profile_id"] == "condition_empathetic"
        assert "deprecated" in data
        setup_app["orchestrator"].apply_profile.assert_called()

    def test_apply_condition_without_prefix(self, client, setup_app):
        """Apply using just 'empathetic' — auto-resolves to 'condition_empathetic'."""
        resp = client.post("/api/conditions/apply", json={
            "condition_id": "empathetic",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["profile_id"] == "condition_empathetic"

    def test_apply_nonexistent_condition(self, client):
        resp = client.post("/api/conditions/apply", json={
            "condition_id": "nonexistent",
        })
        assert resp.status_code == 200
        assert "error" in resp.json()
