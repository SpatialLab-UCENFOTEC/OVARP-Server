"""
Integration tests for the Custom Provider Registration REST API endpoints.

Covers:
    GET    /api/providers
    POST   /api/providers/register
    DELETE /api/providers/{name}
    POST   /api/providers/{name}/test
    POST   /api/providers/test
"""

import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

import src.main as main_module


@pytest.fixture(autouse=True)
def setup_app(monkeypatch, tmp_path):
    """Inject mock orchestrator and temporary custom_providers.yaml."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.llm_providers = {"openai": MagicMock(), "gemini": MagicMock()}
    mock_orchestrator.tts_providers = {"openai": MagicMock(), "gemini": MagicMock()}
    mock_orchestrator.active_llm_id = "openai"
    mock_orchestrator.register_provider = MagicMock()
    mock_orchestrator.unregister_provider = MagicMock(return_value=True)

    custom_file = tmp_path / "custom_providers.yaml"

    monkeypatch.setattr(main_module, "orchestrator", mock_orchestrator, raising=False)
    monkeypatch.setattr(main_module, "CUSTOM_PROVIDERS_FILE", custom_file, raising=False)
    monkeypatch.setattr(main_module, "_read_custom_registry", lambda: {}, raising=False)
    monkeypatch.setattr(main_module, "_save_custom_providers", lambda r: None, raising=False)

    yield {"orchestrator": mock_orchestrator}


@pytest.fixture
def client():
    return TestClient(main_module.app)


# --- Tests ---

class TestListProviders:
    def test_list_providers(self, client):
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "openai" in data["builtin"]
        assert "gemini" in data["builtin"]
        assert "available_llm" in data
        assert "available_tts" in data
        assert data["active_llm"] == "openai"


class TestRegisterProvider:
    def test_register_llm_provider(self, client, setup_app):
        resp = client.post("/api/providers/register", json={
            "name": "ollama-local",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
            "types": ["llm"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["name"] == "ollama-local"
        setup_app["orchestrator"].register_provider.assert_called()

    def test_register_llm_and_tts(self, client, setup_app):
        resp = client.post("/api/providers/register", json={
            "name": "local-ai",
            "base_url": "http://localhost:8080/v1",
            "model": "tts-1",
            "types": ["llm", "tts"],
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert setup_app["orchestrator"].register_provider.call_count >= 2

    def test_cannot_overwrite_builtin(self, client):
        resp = client.post("/api/providers/register", json={
            "name": "openai",
            "base_url": "http://evil.com",
            "model": "gpt-4",
            "types": ["llm"],
        })
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_register_with_api_key(self, client):
        resp = client.post("/api/providers/register", json={
            "name": "cloud-provider",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key-123",
            "model": "custom-model",
            "types": ["llm"],
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_name_normalization(self, client):
        resp = client.post("/api/providers/register", json={
            "name": "My Provider Name",
            "base_url": "http://localhost:8080/v1",
            "model": "model",
            "types": ["llm"],
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-provider-name"


class TestUnregisterProvider:
    def test_unregister_provider(self, client, setup_app):
        resp = client.delete("/api/providers/custom-llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        setup_app["orchestrator"].unregister_provider.assert_called_with("custom-llm")

    def test_unregister_nonexistent(self, client, setup_app):
        setup_app["orchestrator"].unregister_provider.return_value = False
        resp = client.delete("/api/providers/nonexistent")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestProviderConnectivity:
    def test_test_registered_provider_not_found(self, client):
        resp = client.post("/api/providers/nonexistent/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_test_arbitrary_endpoint(self, client, monkeypatch):
        """Test the generic endpoint tester (mocked to avoid real HTTP calls)."""
        monkeypatch.setattr(main_module, "test_custom_endpoint", AsyncMock(return_value={
            "ok": True,
            "detail": "Connected. Available models: llama3",
        }), raising=False)
        resp = client.post("/api/providers/test", json={
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
