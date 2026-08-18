"""GET /api/latency/last — latest pipeline timings for validation protocols."""

import os

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.main as main_module


def test_last_latency_empty_when_missing():
    main_module.orchestrator = None
    client = TestClient(main_module.app)
    resp = client.get("/api/latency/last")
    assert resp.status_code == 200
    assert resp.json()["latency"] == {}


def test_last_latency_returns_orchestrator_snapshot():
    orch = MagicMock()
    orch._last_latency = {"stt_ms": 12, "llm_ms": 340, "tts_ms": 210, "total_ms": 562}
    main_module.orchestrator = orch
    client = TestClient(main_module.app)
    resp = client.get("/api/latency/last")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["latency"]["total_ms"] == 562
    assert data["latency"]["llm_ms"] == 340
