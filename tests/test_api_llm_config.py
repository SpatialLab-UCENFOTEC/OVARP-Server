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

    monkeypatch.setattr(main_module, "orchestrator", mock_orchestrator, raising=False)
    monkeypatch.setattr(main_module, "telemetry", mock_telemetry, raising=False)

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
        setup_app["orchestrator"].set_system_prompt.assert_called_with("You are a pirate.")

    def test_set_both(self, client, setup_app):
        resp = client.post("/api/llm/config", json={
            "provider_id": "gemini",
            "system_prompt": "Be concise.",
        })
        assert resp.status_code == 200
        setup_app["orchestrator"].set_active_llm.assert_called_with("gemini")
        setup_app["orchestrator"].set_system_prompt.assert_called_with("Be concise.")


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
