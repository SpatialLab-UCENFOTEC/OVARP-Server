"""
Open Virtual Agent Research Platform (OVARP) — Re-test Findings, 3 Oct 2026

Covers the three server findings the SpatialLab re-test still marked as failing.
Two of them were real through a path the earlier fix did not cover.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import json
import os

import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.core import telemetry as telemetry_log
from src.core.runtime import runtime
from src.core.survey_manager import SurveyManager
from src.main import app


@pytest.fixture(autouse=True)
def loaded_surveys(monkeypatch):
    """Testing mode skips the bootstrap, so the instruments are loaded here."""
    mgr = SurveyManager()
    mgr._surveys = {}
    mgr.load_surveys_from_dir("surveys")
    monkeypatch.setattr(runtime, "survey_manager", mgr, raising=False)
    monkeypatch.setattr(runtime, "telemetry", MagicMock(), raising=False)
    yield


@pytest.fixture
def client():
    return TestClient(app)


class TestProfileIdsAreValidatedAtTheBoundary:
    """H12. Scenarios rejected a path-like id; profiles did not.

    The write was blocked, so nothing escaped the directory, but the API
    answered 200 and the unpersistable profile stayed in the registry.
    """

    @pytest.mark.parametrize("bad_id", ["../../escaped", "a/b", "..", "with space", ""])
    def test_a_path_like_id_is_refused(self, client, bad_id):
        resp = client.post("/api/profiles/create", json={"id": bad_id, "name": "X"})

        assert resp.status_code == 422

    def test_a_refused_id_never_reaches_the_registry(self, client):
        client.post("/api/profiles/create", json={"id": "../../escaped", "name": "X"})

        listed = client.get("/api/profiles").json()["profiles"]
        assert not any("escaped" in p["id"] for p in listed)

    def test_a_duplicate_is_a_conflict_not_a_200(self, client, tmp_path, monkeypatch):
        from src.core.runtime import runtime
        monkeypatch.setattr(runtime.profile_manager, "_profiles_dir", tmp_path, raising=False)
        client.post("/api/profiles/create", json={"id": "dup_check", "name": "X"})

        resp = client.post("/api/profiles/create", json={"id": "dup_check", "name": "X"})

        assert resp.status_code == 409


class TestSurveyAnswersAreTypedAndBounded:
    """H15. Range was checked; type was not, so "99" was accepted as an answer."""

    def test_a_numeric_string_is_refused_on_a_scored_survey(self, client):
        resp = client.post("/api/surveys/response", json={
            "survey_id": "sus", "participant_id": "QA", "answers": {"sus_1": "99"},
        })

        assert resp.status_code == 422

    def test_free_text_is_refused_on_a_scored_survey(self, client):
        resp = client.post("/api/surveys/response", json={
            "survey_id": "sus", "participant_id": "QA", "answers": {"sus_1": "mucho"},
        })

        assert resp.status_code == 422

    def test_free_text_is_accepted_on_an_open_survey(self, client):
        """An open questionnaire is where prose belongs."""
        resp = client.post("/api/surveys/response", json={
            "survey_id": "qualitative", "participant_id": "QA",
            "answers": {"q_would_use": "Si, lo usaria para entrevistas"},
        })

        assert resp.status_code == 200

    def test_a_number_inside_the_scale_still_passes(self, client):
        resp = client.post("/api/surveys/response", json={
            "survey_id": "sus", "participant_id": "QA", "answers": {"sus_1": 3},
        })

        assert resp.status_code == 200


class TestMarkersOutliveTheProcess:
    """H16. The export read the in-memory session, which a restart empties."""

    def _log(self, tmp_path, entries):
        path = tmp_path / "session_test.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        return tmp_path

    def test_markers_are_read_back_from_the_log(self, tmp_path):
        self._log(tmp_path, [
            {"event": "marker", "marker_id": "m1", "label": "task_started",
             "marker_category": "Protocol", "marker_notes": "after consent",
             "experiment_session_id": "s1", "participant_id": "P1",
             "host_timestamp": 1.0, "timestamp": "2026-10-03T10:00:00Z"},
        ])

        markers = telemetry_log.read_session_markers("s1", log_dir=str(tmp_path))

        assert len(markers) == 1
        assert markers[0]["label"] == "task_started"
        assert markers[0]["category"] == "Protocol"
        assert markers[0]["participant_id"] == "P1"

    def test_an_amendment_is_applied_in_order(self, tmp_path):
        self._log(tmp_path, [
            {"event": "marker", "marker_id": "m1", "label": "typo",
             "experiment_session_id": "s1", "host_timestamp": 1.0, "timestamp": "t"},
            {"event": "marker_amended", "marker_id": "m1",
             "amended_from": {"label": "typo"}, "amended_to": {"label": "fixed"},
             "experiment_session_id": "s1", "host_timestamp": 2.0, "timestamp": "t"},
        ])

        markers = telemetry_log.read_session_markers("s1", log_dir=str(tmp_path))

        assert markers[0]["label"] == "fixed"
        assert markers[0]["amended"] is True

    def test_a_retracted_marker_is_left_out(self, tmp_path):
        self._log(tmp_path, [
            {"event": "marker", "marker_id": "m1", "label": "mistake",
             "experiment_session_id": "s1", "host_timestamp": 1.0, "timestamp": "t"},
            {"event": "marker_deleted", "marker_id": "m1",
             "experiment_session_id": "s1", "host_timestamp": 2.0, "timestamp": "t"},
        ])

        assert telemetry_log.read_session_markers("s1", log_dir=str(tmp_path)) == []

    def test_another_session_is_not_mixed_in(self, tmp_path):
        self._log(tmp_path, [
            {"event": "marker", "marker_id": "m1", "label": "mine",
             "experiment_session_id": "s1", "host_timestamp": 1.0, "timestamp": "t"},
            {"event": "marker", "marker_id": "m2", "label": "theirs",
             "experiment_session_id": "s2", "host_timestamp": 2.0, "timestamp": "t"},
        ])

        markers = telemetry_log.read_session_markers("s1", log_dir=str(tmp_path))

        assert [m["label"] for m in markers] == ["mine"]

    def test_an_unknown_session_exports_as_not_found(self, client):
        resp = client.get("/api/session/export/csv", params={"session_id": "nope_at_all"})

        assert resp.status_code == 404
