"""
Tests for OVARP usability evaluations (SUS, UEQ-S, qualitative).

Author: Alexander Barquero Elizondo, Ph.D. - UCR, ECCI/CITIC
License: MIT
"""

import os

os.environ["OVARP_TESTING"] = "1"

from fastapi.testclient import TestClient

from src.core.evaluations import score_sus, score_ueq_s
from src.main import app


class TestScoringHelpers:
    def test_sus_standard_example(self):
        # Odd items 4, even items 2 -> each contributes 3 -> 30 * 2.5 = 75
        items = [4, 2, 4, 2, 4, 2, 4, 2, 4, 2]
        assert score_sus(items) == 75.0

    def test_sus_perfect_score(self):
        items = [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]
        assert score_sus(items) == 100.0

    def test_sus_rejects_wrong_length(self):
        try:
            score_sus([3] * 9)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "10" in str(exc)

    def test_ueq_s_means(self):
        items = [2, 1, 2, 1, 1, 2, 0, 1]
        scores = score_ueq_s(items)
        assert scores["pragmatic"] == 1.5
        assert scores["hedonic"] == 1.0
        assert scores["overall"] == 1.25


class TestEvaluationAPI:
    def test_post_and_get_evaluation(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.evaluations.EVAL_DIR", tmp_path)

        client = TestClient(app)
        payload = {
            "participant_id": "P01",
            "sus": [4, 2, 4, 2, 4, 2, 4, 2, 4, 2],
            "ueq": [2, 1, 2, 1, 1, 2, 0, 1],
            "qualitative": {
                "would_use": "yes",
                "for_what": "XR empathy studies",
                "improve": "onboarding",
                "likes": "profiles",
                "dislikes": "default tab",
            },
        }
        post = client.post("/api/evaluations/ovarp", json=payload)
        assert post.status_code == 200
        data = post.json()
        assert data["status"] == "ok"
        assert data["sus_score"] == 75.0
        assert data["ueq_pragmatic"] == 1.5
        assert data["participant_id"] == "P01"
        assert (tmp_path / "evaluations.jsonl").exists()

        listed = client.get("/api/evaluations/ovarp")
        assert listed.status_code == 200
        body = listed.json()
        assert body["count"] >= 1
        assert body["evaluations"][-1]["id"] == data["id"]

    def test_post_rejects_short_sus(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.evaluations.EVAL_DIR", tmp_path)
        client = TestClient(app)
        resp = client.post(
            "/api/evaluations/ovarp",
            json={"sus": [3] * 9, "ueq": [0] * 8},
        )
        assert resp.status_code == 422
