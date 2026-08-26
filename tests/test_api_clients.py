"""GET /api/clients — live WebSocket client ids for the WoZ console."""

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


def _transport(ids):
    transport = MagicMock()
    transport.connected_client_ids.return_value = ids
    return transport


def test_list_clients_empty(client, monkeypatch):
    monkeypatch.setattr(runtime_module.runtime, "ws_transport", _transport([]))

    data = client.get("/api/clients").json()

    assert data["clients"] == []
    assert data["count"] == 0


def test_list_clients_returns_sorted_ids(client, monkeypatch):
    monkeypatch.setattr(
        runtime_module.runtime, "ws_transport", _transport(["headset_01", "woz_web_console"])
    )

    data = client.get("/api/clients").json()

    assert data["clients"] == ["headset_01", "woz_web_console"]
    assert data["count"] == 2


def test_no_transport_is_not_an_error(client, monkeypatch):
    """Under OVARP_TESTING the transports are never started."""
    monkeypatch.setattr(runtime_module.runtime, "ws_transport", None)

    resp = client.get("/api/clients")

    assert resp.status_code == 200
    assert resp.json() == {"clients": [], "count": 0}
