"""
Integration tests for the Survey REST API.

Covers:
    GET  /api/surveys
    GET  /api/surveys/{id}
    POST /api/surveys/response
"""

import os

import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.main as main_module
from src.core.runtime import runtime
from src.core.survey_manager import SurveyManager


@pytest.fixture(autouse=True)
def setup_app(monkeypatch):
    mgr = SurveyManager()
    mgr._surveys = {}
    mgr.load_surveys_from_dir("surveys")
    monkeypatch.setattr(runtime, "survey_manager", mgr, raising=False)
    monkeypatch.setattr(runtime, "telemetry", MagicMock(), raising=False)
    session_mgr = MagicMock()
    session_mgr.get_status = MagicMock(return_value={"participant_id": "P_SESSION"})
    monkeypatch.setattr(runtime, "session_manager", session_mgr, raising=False)
    yield {"mgr": mgr}


@pytest.fixture
def client():
    return TestClient(main_module.app)


class TestSurveyListing:
    def test_lists_shipped_instruments(self, client):
        ids = {s["id"] for s in client.get("/api/surveys").json()["surveys"]}

        assert {"sus", "ueq", "qualitative"} <= ids

    def test_get_survey_returns_items(self, client):
        data = client.get("/api/surveys/sus").json()

        assert len(data["items"]) == 10
        assert data["scale"]["max"] == 5

    def test_unknown_survey_reports_error(self, client):
        assert "error" in client.get("/api/surveys/nope").json()


class TestLocalization:
    def test_spanish_replaces_item_text(self, client):
        data = client.get("/api/surveys/sus?lang=es").json()

        assert data["items"][0]["text"].startswith("Creo que me gustaría")
        assert data["scale"]["max_label"] == "Totalmente de acuerdo"

    def test_english_is_the_default(self, client):
        data = client.get("/api/surveys/sus").json()

        assert data["items"][0]["text"].startswith("I think that I would like")

    def test_bipolar_poles_are_translated(self, client):
        data = client.get("/api/surveys/ueq?lang=es").json()

        assert data["items"][0]["left"] == "molesto"
        assert data["items"][0]["right"] == "agradable"


class TestSubmitResponse:
    def _perfect_sus(self, client):
        items = client.get("/api/surveys/sus").json()["items"]
        return {it["id"]: (5 if i % 2 else 1) for i, it in enumerate(items, start=1)}

    def test_submitting_scores_the_response(self, client):
        resp = client.post("/api/surveys/response", json={
            "survey_id": "sus",
            "participant_id": "P001",
            "answers": self._perfect_sus(client),
        })

        assert resp.status_code == 200
        assert resp.json()["score"]["score"] == 100.0

    def test_response_is_written_to_telemetry(self, client):
        answers = self._perfect_sus(client)

        client.post("/api/surveys/response", json={
            "survey_id": "sus", "participant_id": "P001", "answers": answers,
        })

        runtime.telemetry.log_survey_response.assert_called_once()
        args = runtime.telemetry.log_survey_response.call_args[0]
        assert args[0] == "sus"
        assert args[1] == "P001"

    def test_participant_falls_back_to_the_active_session(self, client):
        """A participant answering on their phone will not type their own ID."""
        client.post("/api/surveys/response", json={
            "survey_id": "sus", "answers": self._perfect_sus(client),
        })

        assert runtime.telemetry.log_survey_response.call_args[0][1] == "P_SESSION"

    def test_open_answers_are_stored_without_a_score(self, client):
        resp = client.post("/api/surveys/response", json={
            "survey_id": "qualitative",
            "participant_id": "P001",
            "answers": {"q_would_use": "Sí, para terapia"},
        })

        assert resp.status_code == 200
        assert resp.json()["score"] == {}

    def test_unknown_survey_is_rejected(self, client):
        resp = client.post("/api/surveys/response", json={
            "survey_id": "nope", "answers": {},
        })

        assert "error" in resp.json()
        runtime.telemetry.log_survey_response.assert_not_called()
