"""
Tests for the connection details the console advertises to clients.

A hosted web client is served over HTTPS and the browser refuses to open a ws://
socket from it, so the endpoint must report the scheme the request actually
arrived on rather than assuming plain ws://.
"""

import os

import pytest

os.environ["OVARP_TESTING"] = "1"

from fastapi.testclient import TestClient

import src.main as main_module


@pytest.fixture
def client():
    return TestClient(main_module.app)


class TestServerInfo:
    def test_plain_http_reports_ws(self, client):
        data = client.get("/api/server/info").json()

        assert data["public_ws_url"].startswith("ws://")
        assert data["is_secure"] is False

    def test_tunnel_reports_wss(self, client):
        """cloudflared terminates TLS and forwards the original scheme."""
        data = client.get("/api/server/info", headers={
            "x-forwarded-proto": "https",
            "host": "random-words.trycloudflare.com",
        }).json()

        assert data["public_ws_url"] == "wss://random-words.trycloudflare.com"
        assert data["is_secure"] is True
        assert data["ws_url_template"].startswith("wss://")

    def test_lan_url_stays_plain_for_native_builds(self, client):
        """A native XR build is not bound by the browser's mixed-content rule."""
        data = client.get("/api/server/info", headers={
            "x-forwarded-proto": "https",
            "host": "random-words.trycloudflare.com",
        }).json()

        assert data["lan_ws_url"].startswith("ws://")
        assert data["lan_ip"] in data["lan_ws_url"]

    def test_client_url_is_exposed(self, client):
        assert "client_url" in client.get("/api/server/info").json()
