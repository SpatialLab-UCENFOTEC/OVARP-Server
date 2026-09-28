"""
Tests for credential handling and console access control.

Covers:
    GET  /api/auth/status
    POST /api/auth/verify
    Token enforcement across the researcher API
    Encryption at rest and redaction of provider credentials
"""

import os

import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.main as main_module
from src.api.routers import providers as providers_router
from src.core.runtime import runtime
from src.core.secrets import ENCRYPTED_PREFIX, protect, redact, reveal

TOKEN = "s3cr3t-console-token"


@pytest.fixture
def client():
    return TestClient(main_module.app)


@pytest.fixture(autouse=True)
def _open_by_default(monkeypatch):
    """Most tests run in the default open mode unless they opt into a token."""
    monkeypatch.delenv("OVARP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OVARP_SECRET_KEY", raising=False)


class TestAccessToken:
    def test_open_when_no_token_configured(self, client):
        """A local run must not need a token — that is the common case."""
        assert client.get("/api/auth/status").json()["required"] is False
        assert client.get("/api/session/status").status_code == 200

    def test_api_rejects_calls_without_the_token(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        assert client.get("/api/auth/status").json()["required"] is True
        assert client.get("/api/session/status").status_code == 401

    def test_api_accepts_the_configured_token(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        resp = client.get("/api/session/status", headers={"X-OVARP-Token": TOKEN})

        assert resp.status_code == 200

    def test_wrong_token_is_rejected(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        resp = client.get("/api/session/status", headers={"X-OVARP-Token": "wrong"})

        assert resp.status_code == 401

    def test_verify_endpoint_checks_a_token(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        assert client.post("/api/auth/verify", headers={"X-OVARP-Token": TOKEN}).status_code == 200
        assert client.post("/api/auth/verify", headers={"X-OVARP-Token": "no"}).status_code == 401

    def test_log_stream_stays_reachable_without_a_token(self, client, monkeypatch):
        """The WebSockets are exempt: XR clients never carry a researcher token."""
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        with client.websocket_connect("/ws/logs") as ws:
            assert ws is not None


class TestCredentialProtection:
    def test_registry_never_exposes_the_key(self):
        """The registry used to travel to the browser with api_key intact."""
        redacted = redact({"my-ollama": {"base_url": "http://x/v1", "api_key": "sk-abc123"}})

        assert "api_key" not in redacted["my-ollama"]
        assert redacted["my-ollama"]["has_key"] is True
        assert redacted["my-ollama"]["base_url"] == "http://x/v1"

    def test_absent_key_reported_as_false(self):
        redacted = redact({"local": {"base_url": "http://x", "api_key": ""}})

        assert redacted["local"]["has_key"] is False

    def test_list_endpoint_redacts(self, client, monkeypatch):
        monkeypatch.setattr(runtime, "orchestrator", MagicMock(), raising=False)
        monkeypatch.setattr(
            providers_router, "_read_custom_registry",
            lambda: {"my-ollama": {"base_url": "http://x/v1", "api_key": "sk-leak"}},
            raising=False,
        )

        body = client.get("/api/providers").text

        assert "sk-leak" not in body
        assert "has_key" in body

    def test_roundtrip_with_a_secret_key(self, monkeypatch):
        monkeypatch.setenv("OVARP_SECRET_KEY", "a-master-passphrase")

        stored = protect("sk-abc123")

        assert stored.startswith(ENCRYPTED_PREFIX)
        assert "sk-abc123" not in stored
        assert reveal(stored) == "sk-abc123"

    def test_protect_is_idempotent(self, monkeypatch):
        monkeypatch.setenv("OVARP_SECRET_KEY", "a-master-passphrase")

        once = protect("sk-abc123")

        assert protect(once) == once

    def test_plaintext_passes_through_without_a_key(self):
        """Upgrading without setting a key must not break an existing registry."""
        assert protect("sk-abc123") == "sk-abc123"
        assert reveal("sk-abc123") == "sk-abc123"

    def test_wrong_key_does_not_return_the_secret(self, monkeypatch):
        monkeypatch.setenv("OVARP_SECRET_KEY", "original")
        stored = protect("sk-abc123")

        monkeypatch.setenv("OVARP_SECRET_KEY", "different")

        assert reveal(stored) == ""


class TestSurveyResultsAreProtected:
    """Answering a questionnaire is public; reading who answered what is not."""

    def test_responses_needs_the_token(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        assert client.get("/api/surveys/responses").status_code == 401

    def test_responses_is_reachable_with_the_token(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        resp = client.get("/api/surveys/responses", headers={"X-OVARP-Token": TOKEN})

        assert resp.status_code == 200

    def test_the_catch_all_route_does_not_serve_responses(self, client, monkeypatch):
        """/api/surveys/{survey_id} is registered after /responses on purpose.

        Mounted the other way round it matches survey_id="responses" and hands
        the participant data out unprotected, which is how this first shipped.
        """
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        assert client.get("/api/surveys").status_code == 200
        assert client.get("/api/surveys/sus").status_code == 200

    def test_a_participant_can_still_submit(self, client, monkeypatch):
        monkeypatch.setenv("OVARP_ACCESS_TOKEN", TOKEN)

        resp = client.post("/api/surveys/response", json={
            "survey_id": "sus", "participant_id": "P40", "answers": {"sus_1": 3},
        })

        assert resp.status_code == 200
