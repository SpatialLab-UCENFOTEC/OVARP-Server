"""GET /api/latency/last — latest pipeline timings for validation protocols."""

import os

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import src.main as main_module
from src.core import runtime as runtime_module


@pytest.fixture
def client():
    return TestClient(main_module.app)


def test_last_latency_empty_when_no_orchestrator(client, monkeypatch):
    monkeypatch.setattr(runtime_module.runtime, "orchestrator", None)

    resp = client.get("/api/latency/last")

    assert resp.status_code == 200
    assert resp.json()["latency"] == {}


def test_last_latency_empty_before_the_first_turn(client, monkeypatch):
    orch = MagicMock()
    orch._last_latency = {}
    monkeypatch.setattr(runtime_module.runtime, "orchestrator", orch)

    assert client.get("/api/latency/last").json()["latency"] == {}


def test_last_latency_returns_orchestrator_snapshot(client, monkeypatch):
    orch = MagicMock()
    orch._last_latency = {"stt_ms": 12, "llm_ms": 340, "tts_ms": 210, "total_ms": 562}
    monkeypatch.setattr(runtime_module.runtime, "orchestrator", orch)

    data = client.get("/api/latency/last").json()

    assert data["status"] == "ok"
    assert data["latency"]["total_ms"] == 562
    assert data["latency"]["tts_ms"] == 210
