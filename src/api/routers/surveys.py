"""
Open Virtual Agent Research Platform (OVARP) — Survey Routes

Serves the questionnaires defined in ``surveys/*.yaml`` and records the
responses next to the session telemetry.

The participant-facing page and its submit endpoint are deliberately outside
the console token: a participant answering on their own phone has no token,
and the page carries no control over the experiment.

Reading the collected responses is not part of that bargain. It returns
participant ids and their answers, so it lives on ``results_router``, which
``main.py`` mounts behind the console token.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.runtime import runtime
from src.core.survey_manager import score_survey

router = APIRouter(prefix="/api/surveys", tags=["surveys"])

# Same prefix, mounted separately so the console token can cover it alone.
results_router = APIRouter(prefix="/api/surveys", tags=["surveys"])


class SurveyResponse(BaseModel):
    survey_id: str
    participant_id: str = ""
    answers: dict


def _localize(survey, lang: str) -> dict:
    """Render a survey in the requested language, falling back to English."""
    data = survey.model_dump()
    if lang != "es":
        return data

    for raw, item in zip(data["items"], survey.items):
        for field in ("text", "left", "right"):
            translated = getattr(item, f"{field}_es", None)
            if translated:
                raw[field] = translated
    for field in ("min_label", "max_label"):
        translated = getattr(survey.scale, f"{field}_es", None)
        if translated:
            data["scale"][field] = translated
    return data


def _out_of_scale(survey, answers: dict) -> list[str]:
    """Item ids whose numeric answer falls outside the survey's own scale.

    Unbounded values sail through the SUS formula and produce scores above 100,
    which would then be written to the session record as if they were real.
    """
    low, high = survey.scale.min, survey.scale.max
    return [
        item_id for item_id, value in answers.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and not (low <= value <= high)
    ]


@router.get("")
async def list_surveys():
    """List the available questionnaires."""
    return {"surveys": runtime.survey_manager.list_surveys()}


@results_router.get("/responses")
async def list_responses(participant_id: str = ""):
    """Responses collected since the server started, for the live results panel."""
    return {"responses": runtime.survey_manager.list_responses(participant_id or None)}


@router.get("/{survey_id}")
async def get_survey(survey_id: str, lang: str = "en"):
    """Full definition of one questionnaire, ready to render."""
    survey = runtime.survey_manager.get_survey(survey_id)
    if not survey:
        return {"error": f"Survey '{survey_id}' not found"}
    return _localize(survey, lang)


@router.post("/response")
async def submit_response(response: SurveyResponse):
    """Score a completed questionnaire and write it to the session log."""
    survey = runtime.survey_manager.get_survey(response.survey_id)
    if not survey:
        return {"error": f"Survey '{response.survey_id}' not found"}

    invalid = _out_of_scale(survey, response.answers)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Answers outside the {survey.scale.min}-{survey.scale.max} scale: {invalid}",
        )

    score = score_survey(survey, response.answers)
    participant = response.participant_id or runtime.session_manager.get_status().get(
        "participant_id", ""
    )
    runtime.telemetry.log_survey_response(
        response.survey_id, participant, response.answers, score
    )
    runtime.survey_manager.record_response(
        response.survey_id, participant, response.answers, score
    )
    return {"status": "ok", "survey_id": response.survey_id, "score": score}
