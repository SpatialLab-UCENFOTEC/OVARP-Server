"""
Integration tests for the LLM Configuration REST API endpoints.

Covers:
    GET  /api/llm/config
    POST /api/llm/config
    POST /api/llm/tts
    GET  /api/tts/voices
    POST /api/tts/voice
    POST /api/llm/history/clear
    GET  /api/config
    GET  /api/export
"""

import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.runtime import runtime


@pytest.fixture(autouse=True)
def setup_app(monkeypatch):
    """Inject a mock orchestrator with LLM/TTS properties into main module."""
    mock_tts = MagicMock()
    mock_tts.voice = "alloy"

    mock_orchestrator = MagicMock()
    mock_orchestrator.active_llm_id = "openai"
    mock_orchestrator.llm_providers = {"openai": MagicMock(), "gemini": MagicMock()}
    mock_orchestrator.tts_providers = {"openai": mock_tts}
    mock_orchestrator.system_prompt = "Default system prompt."
    mock_orchestrator.tts_enabled = True
    mock_orchestrator.set_active_llm = MagicMock()
    mock_orchestrator.set_system_prompt = MagicMock()
    mock_orchestrator.clear_history = MagicMock()
    mock_orchestrator.set_tts_voice = MagicMock()
    mock_orchestrator.get_tts_config = MagicMock(return_value={
        "provider": "openai",
        "current_voice": "alloy",
        "voices": [
            {"id": "alloy", "label": "Alloy", "gender": "neutral"},
            {"id": "nova", "label": "Nova", "gender": "feminine"},
        ],
    })

    mock_telemetry = MagicMock()
    mock_telemetry.export_to_csv = MagicMock(return_value=None)

    monkeypatch.setattr(runtime, "orchestrator", mock_orchestrator, raising=False)
    monkeypatch.setattr(runtime, "telemetry", mock_telemetry, raising=False)

    yield {"orchestrator": mock_orchestrator, "telemetry": mock_telemetry}


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestGetLLMConfig:
    def test_get_llm_config(self, client):
        resp = client.get("/api/llm/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_provider"] == "openai"
        assert "openai" in data["available_providers"]
        assert data["system_prompt"] == "Default system prompt."
        assert data["tts_enabled"] is True


class TestSetLLMConfig:
    def test_set_provider(self, client, setup_app):
        resp = client.post("/api/llm/config", json={"provider_id": "gemini"})
        assert resp.status_code == 200
        setup_app["orchestrator"].set_active_llm.assert_called_with("gemini")

    def test_set_system_prompt(self, client, setup_app):
        resp = client.post("/api/llm/config", json={
            "system_prompt": "You are a pirate."
        })
        assert resp.status_code == 200
        setup_app["orchestrator"].set_system_prompt.assert_called_with("You are a pirate.", agent_id=None)

    def test_set_both(self, client, setup_app):
        resp = client.post("/api/llm/config", json={
            "provider_id": "gemini",
            "system_prompt": "Be concise.",
        })
        assert resp.status_code == 200
        setup_app["orchestrator"].set_active_llm.assert_called_with("gemini")
        setup_app["orchestrator"].set_system_prompt.assert_called_with("Be concise.", agent_id=None)


class TestTTSToggle:
    def test_toggle_tts(self, client):
        resp = client.post("/api/llm/tts")
        assert resp.status_code == 200
        assert "tts_enabled" in resp.json()


class TestTTSVoices:
    def test_get_voices(self, client):
        resp = client.get("/api/tts/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["current_voice"] == "alloy"
        assert len(data["voices"]) == 2

    def test_set_voice(self, client, setup_app):
        resp = client.post("/api/tts/voice", json={"voice_id": "nova"})
        assert resp.status_code == 200
        setup_app["orchestrator"].set_tts_voice.assert_called_with("nova")


class TestHistoryClear:
    def test_clear_history(self, client, setup_app):
        resp = client.post("/api/llm/history/clear")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        setup_app["orchestrator"].clear_history.assert_called_once()


class TestExport:
    def test_export_no_data(self, client):
        """When no CSV is generated, export returns error dict."""
        resp = client.get("/api/export")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestPromptTargeting:
    """The console's prompt box and an applied profile write to the same slot.

    Without a target the global default is edited; with one the agent's own
    prompt is, which is what a profile also sets. The response reports which
    agents a global edit will not reach so the console can say so.
    """

    def test_prompt_can_target_one_agent(self, client, setup_app):
        resp = client.post("/api/llm/config", json={
            "system_prompt": "Only for alpha.",
            "agent_id": "agent_alpha",
        })
        assert resp.status_code == 200
        setup_app["orchestrator"].set_system_prompt.assert_called_with(
            "Only for alpha.", agent_id="agent_alpha"
        )
        assert resp.json()["agent_id"] == "agent_alpha"

    def test_config_reports_agents_that_ignore_the_global_prompt(self, client, setup_app):
        setup_app["orchestrator"].get_agent_info = lambda aid: {
            "has_custom_prompt": aid == "agent_alpha",
            "profile_id": "therapist_male" if aid == "agent_alpha" else None,
        }

        overriding = client.get("/api/llm/config").json()["agents_overriding_global"]

        assert [a["agent_id"] for a in overriding] == ["agent_alpha"]
        assert overriding[0]["profile_id"] == "therapist_male"

    def test_no_profiles_means_nothing_overrides(self, client, setup_app):
        setup_app["orchestrator"].get_agent_info = lambda aid: {
            "has_custom_prompt": False, "profile_id": None
        }

        assert client.get("/api/llm/config").json()["agents_overriding_global"] == []


class TestSttProvider:
    """Transcription is swappable like the other two stages.

    It used to be fixed at construction, which tied the microphone to whichever
    vendor was wired in at boot even when LLM and TTS had been moved elsewhere.
    """

    @pytest.fixture(autouse=True)
    def stt_registry(self, setup_app):
        orchestrator = setup_app["orchestrator"]
        orchestrator.stt_providers = {"openai": MagicMock(), "gemini": MagicMock()}
        orchestrator.active_stt_id = "openai"

        def swap(provider_id):
            if provider_id not in orchestrator.stt_providers:
                return False
            orchestrator.active_stt_id = provider_id
            return True

        orchestrator.set_active_stt = MagicMock(side_effect=swap)
        return orchestrator

    def test_reports_the_active_provider(self, client):
        body = client.get("/api/stt/provider").json()

        assert body["provider"] == "openai"
        assert set(body["available"]) == {"openai", "gemini"}

    def test_can_switch_provider(self, client):
        resp = client.post("/api/stt/provider", json={"provider_id": "gemini"})

        assert resp.status_code == 200
        assert resp.json()["provider"] == "gemini"

    def test_unknown_provider_is_rejected(self, client, stt_registry):
        resp = client.post("/api/stt/provider", json={"provider_id": "nope"})

        assert "error" in resp.json()
        assert stt_registry.active_stt_id == "openai"

    def test_llm_config_exposes_stt_state(self, client):
        body = client.get("/api/llm/config").json()

        assert body["active_stt_provider"] == "openai"
        assert set(body["available_stt_providers"]) == {"openai", "gemini"}
