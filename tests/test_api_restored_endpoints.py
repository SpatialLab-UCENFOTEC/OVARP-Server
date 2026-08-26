"""
Endpoints recovered after 612f22c dropped them along with the console rewrite.

Profile duplication, marker preset authoring and scenario creation were removed
with no replacement — unlike the evaluations module or the PUT marker route,
which were genuinely superseded. They come back with typed request models,
which the originals lacked.
"""

import os

os.environ["OVARP_TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient

import src.main as main_module
from src.core.runtime import runtime


@pytest.fixture
def client():
    return TestClient(main_module.app)


class TestProfileDuplication:
    def test_duplicate_copies_the_source_and_renames_it(self, client, tmp_path):
        runtime.profile_manager.create_profile(
            {"id": "src_persona", "name": "Source", "identity": {"role": "therapist"}},
            persist=False,
        )
        try:
            body = client.post(
                "/api/profiles/src_persona/duplicate",
                json={"new_id": "copy_persona", "new_name": "Copy"},
            ).json()

            assert body["status"] == "ok"
            assert body["profile"]["id"] == "copy_persona"
            assert body["profile"]["name"] == "Copy"
            assert body["profile"]["identity"]["role"] == "therapist"
        finally:
            runtime.profile_manager.delete_profile("copy_persona")
            runtime.profile_manager.delete_profile("src_persona")

    def test_default_name_marks_it_as_a_copy(self, client):
        runtime.profile_manager.create_profile(
            {"id": "src2", "name": "Original"}, persist=False
        )
        try:
            body = client.post("/api/profiles/src2/duplicate", json={"new_id": "copy2"}).json()

            assert body["profile"]["name"] == "Original (copy)"
        finally:
            runtime.profile_manager.delete_profile("copy2")
            runtime.profile_manager.delete_profile("src2")

    def test_unknown_source_reports_an_error(self, client):
        body = client.post("/api/profiles/nope/duplicate", json={"new_id": "x"}).json()

        assert "error" in body

    def test_new_id_is_required(self, client):
        assert client.post("/api/profiles/whatever/duplicate", json={}).status_code == 422


class TestMarkerPresets:
    def test_preset_is_added_then_updated_in_place(self, client):
        config = runtime.config_manager.config
        before = list(config.event_markers or [])
        try:
            added = client.post(
                "/api/session/markers/presets",
                json={"id": "qa_probe", "label": "Probe", "color": "#ff0000"},
            ).json()
            assert any(p["id"] == "qa_probe" for p in added["presets"])

            updated = client.post(
                "/api/session/markers/presets",
                json={"id": "qa_probe", "label": "Probe v2"},
            ).json()

            matching = [p for p in updated["presets"] if p["id"] == "qa_probe"]
            assert len(matching) == 1
            assert matching[0]["label"] == "Probe v2"
        finally:
            config.event_markers = before

    def test_label_is_required(self, client):
        resp = client.post("/api/session/markers/presets", json={"id": "no_label"})

        assert resp.status_code == 422


class TestScenarioCreation:
    def test_created_scenario_is_persisted_and_listed(self, client, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        body = client.post(
            "/api/scenarios",
            json={
                "id": "qa_created",
                "name": "QA Created",
                "description": "d",
                "steps": [
                    {"id": "one", "instruction": "Greet", "auto_marker": "greeted"},
                    {"id": "two", "instruction": "Close"},
                ],
            },
        ).json()

        assert body["status"] == "ok"
        assert body["scenario"]["steps"][0]["auto_marker"] == "greeted"
        assert (tmp_path / "scenarios" / "qa_created.yaml").exists()
        assert any(s["id"] == "qa_created" for s in body["scenarios"])

    def test_steps_need_an_instruction(self, client):
        resp = client.post(
            "/api/scenarios",
            json={"id": "bad", "name": "Bad", "steps": [{"id": "one"}]},
        )

        assert resp.status_code == 422


class TestConnectedClients:
    def test_endpoint_is_registered(self, client):
        assert client.get("/api/clients").status_code == 200
