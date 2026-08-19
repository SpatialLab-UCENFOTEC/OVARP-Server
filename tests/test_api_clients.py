"""GET /api/clients — live WebSocket client ids for the WoZ console."""

import os

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.main as main_module


def test_list_clients_empty():
    transport = MagicMock()
    transport.connected_client_ids.return_value = []
    main_module.ws_transport = transport

    client = TestClient(main_module.app)
    resp = client.get("/api/clients")
    assert resp.status_code == 200
    data = resp.json()
    assert data["clients"] == []
    assert data["count"] == 0


def test_list_clients_returns_sorted_ids():
    transport = MagicMock()
    transport.connected_client_ids.return_value = ["headset_01", "woz_web_console"]
    main_module.ws_transport = transport

    client = TestClient(main_module.app)
    resp = client.get("/api/clients")
    assert resp.status_code == 200
    data = resp.json()
    assert data["clients"] == ["headset_01", "woz_web_console"]
    assert data["count"] == 2
