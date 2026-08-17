"""
Unit and Integration Tests for Secure API Key Store (R6 Backend).

Tests in-memory key updates, provider singleton client resetting, visual storage badges
('[GUARDADO EN .ENV]' vs '[SOLO EN MEMORIA - NO GUARDADO]'), masked keys, and line-by-line
persistence to .env without corrupting existing comments or non-key lines.

Author: Alexander Barquero Elizondo, Ph.D. - UCR, ECCI/CITIC
License: MIT
"""

import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

os.environ["OVARP_TESTING"] = "1"

from src.main import app, _persist_to_env_file, _read_env_file_keys, _build_key_status_item
from src.providers.openai_provider import OpenAIClientSingleton
from src.providers.gemini_provider import GeminiClientSingleton


class TestAPIKeyHelpers:
    def test_key_masking_and_badges(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-testkey123456789")

        status = _build_key_status_item("OPENAI_API_KEY")
        assert status["is_set"] is True
        assert status["masked_key"] == "sk-p...6789"
        assert status["key_name"] == "OPENAI_API_KEY"

    def test_line_by_line_env_persistence(self, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        initial_content = (
            "# Existing environment configuration file\n"
            "SERVER_PORT=8000\n"
            "OPENAI_API_KEY=sk-old-key-value\n"
            "# End of config\n"
        )
        env_path.write_text(initial_content, encoding="utf-8")

        monkeypatch.setattr("src.main._get_env_file_path", lambda: env_path)

        _persist_to_env_file({
            "OPENAI_API_KEY": "sk-new-key-value",
            "GEMINI_API_KEY": "AIzaSyNewGeminiKey"
        })

        new_content = env_path.read_text(encoding="utf-8")
        assert "# Existing environment configuration file\n" in new_content
        assert "SERVER_PORT=8000\n" in new_content
        assert "OPENAI_API_KEY=sk-new-key-value\n" in new_content
        assert "GEMINI_API_KEY=AIzaSyNewGeminiKey\n" in new_content
        assert "# End of config\n" in new_content


class TestAPIKeyEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_get_keys_status(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-mock-key-1111")
        resp = client.get("/api/keys/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "keys" in data
        assert "OPENAI_API_KEY" in data["keys"]
        assert data["keys"]["OPENAI_API_KEY"]["is_set"] is True

    def test_post_keys_update_memory_only(self, client, monkeypatch):
        # Ensure singletons exist
        _ = OpenAIClientSingleton.get_client()
        _ = GeminiClientSingleton.get_client()

        payload = {
            "provider": "openai",
            "api_key": "sk-mem-test-key-9999",
            "persist": False
        }
        resp = client.post("/api/keys/update", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert os.environ["OPENAI_API_KEY"] == "sk-mem-test-key-9999"

        badge = data.get("badge") or data.get("storage_badge")
        assert badge == "[IN MEMORY ONLY]"

        # Check singleton reset
        assert OpenAIClientSingleton._client is None

    def test_post_keys_update_with_persist(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        env_path.write_text("# Test env\n", encoding="utf-8")
        monkeypatch.setattr("src.main._get_env_file_path", lambda: env_path)

        payload = {
            "provider": "gemini",
            "api_key": "AIzaSyTestKeyMemoryAndPersist",
            "persist": True
        }
        resp = client.post("/api/keys/update", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert os.environ["GEMINI_API_KEY"] == "AIzaSyTestKeyMemoryAndPersist"

        badge = data.get("badge") or data.get("storage_badge")
        assert badge == "[SAVED IN .ENV]"

        env_file_text = env_path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY=AIzaSyTestKeyMemoryAndPersist" in env_file_text

    def test_post_keys_persist_endpoint(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        env_path.write_text("# Test env\n", encoding="utf-8")
        monkeypatch.setattr("src.main._get_env_file_path", lambda: env_path)

        monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven_key_mock_val")

        payload = {
            "provider": "elevenlabs",
            "api_key": "eleven_key_mock_val"
        }
        resp = client.post("/api/keys/persist", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        badge = data.get("badge") or data.get("storage_badge")
        assert badge == "[SAVED IN .ENV]"

        env_file_text = env_path.read_text(encoding="utf-8")
        assert "ELEVENLABS_API_KEY=eleven_key_mock_val" in env_file_text
