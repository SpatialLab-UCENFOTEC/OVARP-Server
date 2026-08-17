"""Tests for the standalone web player route."""

import os

os.environ["OVARP_TESTING"] = "1"

from fastapi.testclient import TestClient

from src.main import app


def test_player_route_serves_html():
    client = TestClient(app)
    response = client.get("/player")
    assert response.status_code == 200
    body = response.text
    assert "OVARP Player" in body
    assert "OVARPClient" in body
    assert "web_panel_01" in body
