"""
Tests for questionnaire loading and scoring.

The scoring assertions use the published reference values for each instrument:
a wrong constant here would silently corrupt every result the platform reports.
"""

import pytest

from src.core.survey_manager import SurveyManager, score_survey


@pytest.fixture(scope="module")
def surveys():
    mgr = SurveyManager()
    mgr.load_surveys_from_dir("surveys")
    return mgr


class TestLoading:
    def test_shipped_instruments_load(self, surveys):
        assert {s["id"] for s in surveys.list_surveys()} >= {"sus", "ueq", "qualitative"}

    def test_sus_has_ten_items(self, surveys):
        assert len(surveys.get_survey("sus").items) == 10

    def test_ueq_scales_match_the_published_structure(self, surveys):
        counts = {}
        for item in surveys.get_survey("ueq").items:
            counts[item.scale] = counts.get(item.scale, 0) + 1

        assert counts == {
            "attractiveness": 6, "perspicuity": 4, "efficiency": 4,
            "dependability": 4, "stimulation": 4, "novelty": 4,
        }

    def test_every_item_is_answerable(self, surveys):
        """Each item must present either a statement or two poles."""
        for survey in ("sus", "ueq", "qualitative"):
            for item in surveys.get_survey(survey).items:
                assert item.text or (item.left and item.right), f"{survey}/{item.id}"


class TestSusScoring:
    def _answers(self, odd, even, surveys):
        items = surveys.get_survey("sus").items
        return {it.id: (odd if i % 2 else even) for i, it in enumerate(items, start=1)}

    def test_best_possible_is_100(self, surveys):
        """Agreeing with every positive item and rejecting every negative one."""
        answers = self._answers(odd=5, even=1, surveys=surveys)

        assert score_survey(surveys.get_survey("sus"), answers)["score"] == 100.0

    def test_worst_possible_is_zero(self, surveys):
        answers = self._answers(odd=1, even=5, surveys=surveys)

        assert score_survey(surveys.get_survey("sus"), answers)["score"] == 0.0

    def test_all_neutral_is_50(self, surveys):
        answers = self._answers(odd=3, even=3, surveys=surveys)

        assert score_survey(surveys.get_survey("sus"), answers)["score"] == 50.0

    def test_agreeing_with_everything_is_50_not_100(self, surveys):
        """Straight-lining 5s hits the negative items too — a known SUS property."""
        answers = self._answers(odd=5, even=5, surveys=surveys)

        assert score_survey(surveys.get_survey("sus"), answers)["score"] == 50.0

    def test_partial_response_has_no_score(self, surveys):
        result = score_survey(surveys.get_survey("sus"), {"sus_1": 5})

        assert result["score"] is None
        assert len(result["missing"]) == 9


class TestUeqScoring:
    def test_neutral_answers_score_zero(self, surveys):
        ueq = surveys.get_survey("ueq")
        answers = {item.id: 4 for item in ueq.items}

        result = score_survey(ueq, answers)

        assert result["overall"] == 0.0
        assert set(result["scales"].values()) == {0.0}

    def test_best_possible_is_plus_three(self, surveys):
        """The positive pole is on the right unless the item is reversed."""
        ueq = surveys.get_survey("ueq")
        answers = {item.id: (1 if item.reverse else 7) for item in ueq.items}

        result = score_survey(ueq, answers)

        assert result["overall"] == 3.0
        assert set(result["scales"].values()) == {3.0}

    def test_worst_possible_is_minus_three(self, surveys):
        ueq = surveys.get_survey("ueq")
        answers = {item.id: (7 if item.reverse else 1) for item in ueq.items}

        assert score_survey(ueq, answers)["overall"] == -3.0

    def test_reversed_items_are_flipped_before_averaging(self, surveys):
        """Straight-lining 7s must not read as a uniformly positive evaluation."""
        ueq = surveys.get_survey("ueq")
        answers = {item.id: 7 for item in ueq.items}

        result = score_survey(ueq, answers)

        assert result["overall"] == 0.0

    def test_reports_unanswered_items(self, surveys):
        ueq = surveys.get_survey("ueq")

        result = score_survey(ueq, {"ueq_1": 7})

        assert len(result["missing"]) == 25


class TestOpenSurvey:
    def test_open_questions_are_not_scored(self, surveys):
        result = score_survey(surveys.get_survey("qualitative"), {"q_would_use": "sí"})

        assert result == {}
