"""
Open Virtual Agent Research Platform (OVARP) — API Key Store Tests

Covers the console's runtime credential management: status badges, in-memory
updates, encrypted persistence, clearing, and the explicit reveal.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import pytest
from fastapi.testclient import TestClient

from src.core import key_store
from src.main import app

client = TestClient(app)

SECRET = "test-secret-for-key-store"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the store at a scratch file and start from a clean environment."""
    monkeypatch.setattr(key_store, "KEY_STORE_FILE", tmp_path / "provider_keys.yaml")
    for name in key_store.TRACKED_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OVARP_SECRET_KEY", raising=False)
    yield


class TestKeyStatus:
    """GET /api/keys/status reports where each credential lives."""

    def test_unconfigured_key_reports_not_configured(self):
        resp = client.get("/api/keys/status")

        assert resp.status_code == 200
        status = resp.json()["keys"]["OPENAI_API_KEY"]
        assert status["is_set"] is False
        assert status["storage_state"] == "unconfigured"
        assert status["badge"] == "[NOT CONFIGURED]"

    def test_env_only_key_reports_memory_only(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-dotenv-1234")

        status = client.get("/api/keys/status").json()["keys"]["OPENAI_API_KEY"]

        assert status["is_set"] is True
        assert status["storage_state"] == "memory_only"
        assert status["persisted"] is False

    def test_status_masks_the_credential(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "abcd12345678wxyz")

        status = client.get("/api/keys/status").json()["keys"]["GEMINI_API_KEY"]

        assert status["masked_key"] == "abcd...wxyz"

    def test_every_tracked_key_is_listed(self):
        keys = client.get("/api/keys/status").json()["keys"]

        assert set(keys) == set(key_store.TRACKED_KEYS)


class TestKeyUpdate:
    """POST /api/keys/update applies a credential to the running server."""

    def test_update_without_persist_stays_in_memory(self):
        resp = client.post(
            "/api/keys/update",
            json={"provider": "openai", "api_key": "sk-live-abcdefgh"},
        )

        assert resp.status_code == 200
        assert key_store.read_key("OPENAI_API_KEY") == "sk-live-abcdefgh"
        assert resp.json()["keys"]["OPENAI_API_KEY"]["storage_state"] == "memory_only"
        assert not key_store.KEY_STORE_FILE.exists()

    def test_provider_alias_resolves_to_the_env_var(self):
        client.post("/api/keys/update", json={"provider": "gemini", "api_key": "g-123"})

        assert key_store.read_key("GEMINI_API_KEY") == "g-123"

    def test_batch_update_sets_several_keys(self):
        client.post(
            "/api/keys/update",
            json={"keys": {"openai": "sk-one", "elevenlabs": "el-two"}},
        )

        assert key_store.read_key("OPENAI_API_KEY") == "sk-one"
        assert key_store.read_key("ELEVENLABS_API_KEY") == "el-two"

    def test_empty_key_clears_the_credential(self):
        client.post("/api/keys/update", json={"provider": "openai", "api_key": "sk-x"})

        client.post("/api/keys/update", json={"provider": "openai", "api_key": ""})

        assert key_store.read_key("OPENAI_API_KEY") == ""

    def test_update_with_no_key_is_rejected(self):
        resp = client.post("/api/keys/update", json={})

        assert resp.status_code == 400

    def test_update_resets_the_cached_provider_client(self, monkeypatch):
        from src.providers.openai_provider import OpenAIClientSingleton

        reset = []
        monkeypatch.setattr(
            OpenAIClientSingleton, "reset_client",
            classmethod(lambda cls: reset.append(True)),
        )

        client.post("/api/keys/update", json={"provider": "openai", "api_key": "sk-new"})

        assert reset, "a changed key must invalidate the cached SDK client"


class TestKeyPersistence:
    """Saved credentials survive a restart and are encrypted when a secret is set."""

    def test_persisted_key_is_written_to_the_store(self):
        client.post(
            "/api/keys/update",
            json={"provider": "openai", "api_key": "sk-persisted", "persist": True},
        )

        assert key_store.KEY_STORE_FILE.exists()
        assert client.get("/api/keys/status").json()[
            "keys"]["OPENAI_API_KEY"]["persisted"] is True

    def test_persisted_key_is_ciphertext_when_a_secret_is_set(self, monkeypatch):
        monkeypatch.setenv("OVARP_SECRET_KEY", SECRET)

        client.post(
            "/api/keys/update",
            json={"provider": "openai", "api_key": "sk-secret-value", "persist": True},
        )

        on_disk = key_store.KEY_STORE_FILE.read_text(encoding="utf-8")
        assert "sk-secret-value" not in on_disk
        assert "enc:" in on_disk

    def test_encrypted_key_reports_the_encrypted_badge(self, monkeypatch):
        monkeypatch.setenv("OVARP_SECRET_KEY", SECRET)
        client.post(
            "/api/keys/update",
            json={"provider": "gemini", "api_key": "g-secret", "persist": True},
        )

        status = client.get("/api/keys/status").json()["keys"]["GEMINI_API_KEY"]

        assert status["storage_state"] == "encrypted"
        assert status["encrypted"] is True

    def test_key_without_a_secret_is_stored_in_plain_text(self):
        client.post(
            "/api/keys/update",
            json={"provider": "gemini", "api_key": "g-plain", "persist": True},
        )

        status = client.get("/api/keys/status").json()["keys"]["GEMINI_API_KEY"]

        assert status["storage_state"] == "plaintext"

    def test_stored_key_is_restored_on_boot(self, monkeypatch):
        monkeypatch.setenv("OVARP_SECRET_KEY", SECRET)
        client.post(
            "/api/keys/update",
            json={"provider": "openai", "api_key": "sk-restored", "persist": True},
        )
        monkeypatch.delenv("OPENAI_API_KEY")

        key_store.load_stored_keys()

        assert key_store.read_key("OPENAI_API_KEY") == "sk-restored"

    def test_clearing_a_key_removes_it_from_the_store(self):
        client.post(
            "/api/keys/update",
            json={"provider": "openai", "api_key": "sk-temp", "persist": True},
        )

        client.post(
            "/api/keys/update",
            json={"provider": "openai", "api_key": "", "persist": True},
        )

        status = client.get("/api/keys/status").json()["keys"]["OPENAI_API_KEY"]
        assert status["persisted"] is False
        assert status["storage_state"] == "unconfigured"

    def test_persist_endpoint_saves_what_is_in_memory(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-in-memory")

        resp = client.post("/api/keys/persist", json={})

        assert resp.status_code == 200
        assert resp.json()["keys"]["OPENAI_API_KEY"]["persisted"] is True

    def test_persist_with_nothing_to_save_is_rejected(self):
        resp = client.post("/api/keys/persist", json={})

        assert resp.status_code == 400


class TestKeyReveal:
    """The raw credential leaves the server only on an explicit request."""

    def test_reveal_returns_the_full_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-full-value-here")

        resp = client.post("/api/keys/reveal", json={"key_name": "openai"})

        assert resp.status_code == 200
        assert resp.json()["api_key"] == "sk-full-value-here"

    def test_reveal_rejects_an_unknown_key(self):
        resp = client.post("/api/keys/reveal", json={"key_name": "AWS_SECRET"})

        assert resp.status_code == 404

    def test_status_never_carries_the_raw_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak-1234")

        body = client.get("/api/keys/status").text

        assert "sk-must-not-leak-1234" not in body
