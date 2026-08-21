"""
Open Virtual Agent Research Platform (OVARP) — Survey Manager

Loads questionnaires from ``surveys/*.yaml`` and scores the responses. Adding a
questionnaire is a YAML file, the same way scenarios and profiles work; the
scoring rule is named in the file and resolved here.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

std_log = logging.getLogger("OVARP.surveys")


class SurveyItem(BaseModel):
    """One question. ``reverse`` marks items whose scale runs the other way.

    A Likert or open item carries a ``text`` statement; a bipolar item (UEQ)
    is defined by its two poles instead, so exactly one of the two forms must
    be present.
    """
    id: str
    text: str | None = None
    text_es: str | None = None
    # Bipolar instruments (UEQ) label both ends instead of using one statement
    left: str | None = None
    right: str | None = None
    left_es: str | None = None
    right_es: str | None = None
    scale: str | None = None       # Sub-scale this item contributes to
    reverse: bool = False

    @model_validator(mode="after")
    def _needs_a_statement_or_two_poles(self):
        if not self.text and not (self.left and self.right):
            raise ValueError(
                f"Item '{self.id}' needs either 'text' or both 'left' and 'right'"
            )
        return self


class SurveyScale(BaseModel):
    """The response range shown to the participant."""
    min: int = 1
    max: int = 5
    min_label: str | None = None
    max_label: str | None = None
    min_label_es: str | None = None
    max_label_es: str | None = None


class Survey(BaseModel):
    """A questionnaire: metadata, response scale, and either items or open questions."""
    id: str
    name: str
    description: str | None = None
    attribution: str | None = None
    kind: str = "likert"              # likert | bipolar | open
    scoring: str | None = None     # sus | ueq | none
    scale: SurveyScale = Field(default_factory=SurveyScale)
    items: list[SurveyItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_sus(survey: Survey, answers: dict[str, int]) -> dict:
    """Standard SUS scoring: 0-100 from ten 1-5 items, odd positive, even negative.

    Every item must be answered — a partial SUS has no defined score, so this
    reports the gap instead of quietly scoring the answered subset.
    """
    missing = [i.id for i in survey.items if i.id not in answers]
    if missing:
        return {"score": None, "missing": missing}

    total = 0
    for position, item in enumerate(survey.items, start=1):
        value = answers[item.id]
        # Odd items count up from the floor, even items count down from the ceiling
        total += (value - survey.scale.min) if position % 2 else (survey.scale.max - value)

    return {"score": round(total * 2.5, 1), "missing": []}


def score_ueq(survey: Survey, answers: dict[str, int]) -> dict:
    """UEQ scoring: per-scale means on the -3..+3 range the instrument reports in."""
    centre = (survey.scale.min + survey.scale.max) / 2
    per_scale: dict[str, list[float]] = {}

    for item in survey.items:
        if item.id not in answers or not item.scale:
            continue
        value = answers[item.id] - centre
        if item.reverse:
            value = -value
        per_scale.setdefault(item.scale, []).append(value)

    scores = {
        scale: round(sum(values) / len(values), 2)
        for scale, values in per_scale.items() if values
    }
    overall = round(sum(scores.values()) / len(scores), 2) if scores else None
    missing = [i.id for i in survey.items if i.id not in answers]
    return {"scales": scores, "overall": overall, "missing": missing}


SCORERS = {"sus": score_sus, "ueq": score_ueq}


def score_survey(survey: Survey, answers: dict) -> dict:
    """Apply the survey's declared scoring rule, if it has one."""
    scorer = SCORERS.get(survey.scoring or "")
    if scorer is None:
        return {}
    numeric = {k: v for k, v in answers.items() if isinstance(v, (int, float))}
    return scorer(survey, numeric)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SurveyManager:
    """Singleton registry of the questionnaires found in surveys/."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._surveys = {}
            cls._instance._responses = []
        return cls._instance

    def load_surveys_from_dir(self, directory: str | Path = "surveys") -> dict[str, Survey]:
        """Parse every YAML in the directory into a Survey."""
        path = Path(directory)
        if not path.exists():
            std_log.warning(f"⚠️ Surveys directory not found: {path}")
            return self._surveys

        for yaml_file in sorted(path.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    survey = Survey(**yaml.safe_load(f))
                self._surveys[survey.id] = survey
            except Exception as e:
                std_log.error(f"❌ Could not load survey {yaml_file.name}: {e}")

        std_log.info(f"📋 Loaded {len(self._surveys)} survey(s) from {path}")
        return self._surveys

    def list_surveys(self) -> list[dict]:
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "kind": s.kind,
                "scoring": s.scoring,
                "item_count": len(s.items),
            }
            for s in self._surveys.values()
        ]

    def get_survey(self, survey_id: str) -> Survey | None:
        return self._surveys.get(survey_id)


    def record_response(self, survey_id: str, participant_id: str,
                        answers: dict, score: dict) -> dict:
        """Keep a completed response in memory so the console can show it live.

        The authoritative copy is the session JSONL; this is the read model the
        researcher watches while the study is running.
        """
        known = self._surveys.get(survey_id)
        entry = {
            "survey_id": survey_id,
            "survey_name": known.name if known else survey_id,
            "participant_id": participant_id,
            "answers": answers,
            "score": score,
        }
        self._responses.append(entry)
        return entry

    def list_responses(self, participant_id: str = None) -> list[dict]:
        """Responses collected since the server started, newest first."""
        entries = self._responses
        if participant_id:
            entries = [r for r in entries if r["participant_id"] == participant_id]
        return list(reversed(entries))


survey_manager = SurveyManager()
