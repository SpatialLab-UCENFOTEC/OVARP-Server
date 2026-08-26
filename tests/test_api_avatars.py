"""
Tests for the avatar model listing the console builds its picker from.

The picker used to hardcode /models/default_avatar.vrm, a file that was never
committed, so every fresh clone opened on a 404 and a grey T-pose. The endpoint
reports what is actually on disk so the console can offer an upload instead.
"""

import os

import pytest

os.environ["OVARP_TESTING"] = "1"

from fastapi.testclient import TestClient

import src.main as main_module
from src.api.routers import system


@pytest.fixture
def client():
    return TestClient(main_module.app)


class TestAvatarListing:
    def test_empty_when_no_models_are_installed(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(system, "AVATAR_DIR", str(tmp_path))

        assert client.get("/api/avatars").json() == {"avatars": []}

    def test_missing_directory_is_not_an_error(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(system, "AVATAR_DIR", str(tmp_path / "absent"))

        resp = client.get("/api/avatars")

        assert resp.status_code == 200
        assert resp.json() == {"avatars": []}

    def test_lists_models_with_their_served_url(self, client, monkeypatch, tmp_path):
        (tmp_path / "beta.vrm").write_bytes(b"x")
        (tmp_path / "alpha.glb").write_bytes(b"x")
        (tmp_path / "notes.txt").write_text("ignored")
        monkeypatch.setattr(system, "AVATAR_DIR", str(tmp_path))

        avatars = client.get("/api/avatars").json()["avatars"]

        assert avatars == [
            {"name": "alpha.glb", "url": "/models/alpha.glb"},
            {"name": "beta.vrm", "url": "/models/beta.vrm"},
        ]

    def test_no_model_named_default_avatar_is_assumed(self):
        """The console must never fall back to a bundled file again."""
        index = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "src", "static", "index.html")
        with open(index, encoding="utf-8") as f:
            assert "default_avatar.vrm" not in f.read()
