"""
Integration tests for the Agent Profiles REST API endpoints.

Covers:
    GET  /api/profiles
    GET  /api/profiles/{profile_id}
    POST /api/profiles/apply
    POST /api/profiles/create
    GET  /api/agents/{agent_id}
"""

import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.profile_manager import ProfileManager, AgentProfile, ProfileVoice, ProfilePersonality


@pytest.fixture(autouse=True)
def setup_app(monkeypatch):
    """Inject mock orchestrator, profile_manager, telemetry, and router into main module."""
    mgr = ProfileManager.__new__(ProfileManager)
    mgr._profiles = {}

    # Seed test profiles
    mgr._profiles["researcher"] = AgentProfile(
        id="researcher",
        name="Research Assistant",
        personality=ProfilePersonality(system_prompt="You are a research assistant."),
        voice=ProfileVoice(provider="openai", voice_id="nova"),
        avatar="female_formal",
    )
    mgr._profiles["companion"] = AgentProfile(
        id="companion",
        name="Casual Companion",
        personality=ProfilePersonality(system_prompt="You are a friendly companion."),
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.apply_profile = MagicMock(return_value={
        "profile_id": "researcher",
        "system_prompt": "You are a research assistant.",
        "history": [],
        "voice_provider": "openai",
        "voice_id": "nova",
    })
    mock_orchestrator.get_agent_info = MagicMock(return_value={
        "agent_id": "agent_alpha",
        "profile_id": "researcher",
        "history_length": 0,
        "voice_provider": "openai",
        "voice_id": "nova",
        "has_custom_prompt": True,
    })

    mock_router = MagicMock()
    mock_router.route_command = AsyncMock()

    monkeypatch.setattr(main_module, "profile_manager", mgr, raising=False)
    monkeypatch.setattr(main_module, "orchestrator", mock_orchestrator, raising=False)
    monkeypatch.setattr(main_module, "router", mock_router, raising=False)
    monkeypatch.setattr(main_module, "telemetry", MagicMock(), raising=False)

    yield {"mgr": mgr, "orchestrator": mock_orchestrator}


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestListProfiles:
    def test_list_profiles_returns_seeded(self, client):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        ids = [p["id"] for p in data["profiles"]]
        assert "researcher" in ids
        assert "companion" in ids

    def test_list_profiles_count(self, client):
        resp = client.get("/api/profiles")
        assert len(resp.json()["profiles"]) == 2


class TestGetProfile:
    def test_get_existing_profile(self, client):
        resp = client.get("/api/profiles/researcher")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "researcher"
        assert data["name"] == "Research Assistant"
        assert data["avatar"] == "female_formal"

    def test_get_nonexistent_profile(self, client):
        resp = client.get("/api/profiles/nonexistent")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestApplyProfile:
    def test_apply_profile_to_all(self, client, setup_app):
        resp = client.post("/api/profiles/apply", json={
            "profile_id": "researcher",
            "agent_id": "all",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["profile_id"] == "researcher"
        assert data["profile_name"] == "Research Assistant"
        setup_app["orchestrator"].apply_profile.assert_called()

    def test_apply_profile_to_specific_agent(self, client, setup_app):
        resp = client.post("/api/profiles/apply", json={
            "profile_id": "companion",
            "agent_id": "agent_alpha",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["profile_name"] == "Casual Companion"

    def test_apply_nonexistent_profile(self, client):
        resp = client.post("/api/profiles/apply", json={
            "profile_id": "nonexistent",
        })
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestCreateProfile:
    def test_create_profile_at_runtime(self, client, setup_app):
        resp = client.post("/api/profiles/create", json={
            "id": "new_agent",
            "name": "Brand New Agent",
            "personality": {"system_prompt": "You are brand new."},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["profile"]["id"] == "new_agent"
        assert setup_app["mgr"].get_profile("new_agent") is not None

    def test_create_minimal_profile(self, client):
        resp = client.post("/api/profiles/create", json={
            "id": "minimal",
            "name": "Minimal",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestGetAgentState:
    def test_get_agent_state(self, client, setup_app):
        resp = client.get("/api/agents/agent_alpha")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent_alpha"
        setup_app["orchestrator"].get_agent_info.assert_called_with("agent_alpha")
