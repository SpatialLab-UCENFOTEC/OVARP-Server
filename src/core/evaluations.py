"""
Open Virtual Agent Research Platform (OVARP) - Usability Evaluations

Stores researcher usability feedback about OVARP itself (not the agent):
System Usability Scale (SUS), UEQ-S, and qualitative questions.
Persists each submission as one JSONL line under data/evaluations/.

Author: Alexander Barquero Elizondo, Ph.D. - UCR, ECCI/CITIC
License: MIT
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

EVAL_DIR = Path("data/evaluations")
EVAL_FILE = "evaluations.jsonl"

evaluations_router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


def score_sus(items: list[int]) -> float:
    """Brooke (1996) SUS: odd items (r-1), even items (5-r), sum * 2.5 -> 0-100."""
    if len(items) != 10:
        raise ValueError("SUS requires 10 items")
    if any(r < 1 or r > 5 for r in items):
        raise ValueError("SUS items must be integers from 1 to 5")
    raw = 0
    for i, rating in enumerate(items):
        raw += (rating - 1) if i % 2 == 0 else (5 - rating)
    return round(raw * 2.5, 2)


def score_ueq_s(items: list[int]) -> dict:
    """UEQ-S: 8 items from -3 to +3. Pragmatic = mean 1-4, Hedonic = mean 5-8."""
    if len(items) != 8:
        raise ValueError("UEQ-S requires 8 items")
    if any(r < -3 or r > 3 for r in items):
        raise ValueError("UEQ-S items must be integers from -3 to 3")
    pragmatic = sum(items[:4]) / 4
    hedonic = sum(items[4:]) / 4
    return {
        "pragmatic": round(pragmatic, 2),
        "hedonic": round(hedonic, 2),
        "overall": round((pragmatic + hedonic) / 2, 2),
    }


def _eval_path() -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    return EVAL_DIR / EVAL_FILE


def save_evaluation(record: dict) -> Path:
    path = _eval_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def list_evaluations(limit: int = 50) -> list[dict]:
    path = EVAL_DIR / EVAL_FILE
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


class QualitativeFeedback(BaseModel):
    would_use: str = ""
    for_what: str = ""
    improve: str = ""
    likes: str = ""
    dislikes: str = ""


class EvaluationRequest(BaseModel):
    participant_id: Optional[str] = None
    session_id: Optional[str] = None
    scenario_id: Optional[str] = None
    role: Optional[str] = None
    sus: list[int] = Field(..., description="10 SUS Likert ratings (1-5)")
    ueq: list[int] = Field(..., description="8 UEQ-S ratings (-3 to 3)")
    qualitative: QualitativeFeedback = Field(default_factory=QualitativeFeedback)

    @field_validator("sus")
    @classmethod
    def validate_sus(cls, value: list[int]) -> list[int]:
        score_sus(value)
        return value

    @field_validator("ueq")
    @classmethod
    def validate_ueq(cls, value: list[int]) -> list[int]:
        score_ueq_s(value)
        return value


@evaluations_router.post("/ovarp")
async def submit_ovarp_evaluation(req: EvaluationRequest):
    """Save a usability evaluation of OVARP and return computed scores."""
    sus_score = score_sus(req.sus)
    ueq_scores = score_ueq_s(req.ueq)
    record = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "participant_id": req.participant_id or "",
        "session_id": req.session_id or "",
        "scenario_id": req.scenario_id or "",
        "role": req.role or "researcher",
        "sus": req.sus,
        "ueq": req.ueq,
        "qualitative": req.qualitative.model_dump(),
        "sus_score": sus_score,
        "ueq_pragmatic": ueq_scores["pragmatic"],
        "ueq_hedonic": ueq_scores["hedonic"],
        "ueq_overall": ueq_scores["overall"],
    }
    save_evaluation(record)
    return {"status": "ok", **record}


@evaluations_router.get("/ovarp")
async def list_ovarp_evaluations():
    """List stored OVARP usability evaluations (newest last)."""
    items = list_evaluations()
    return {"status": "ok", "count": len(items), "evaluations": items}


@evaluations_router.get("/ovarp/export")
async def export_ovarp_evaluations():
    """CSV download of stored researcher usability evaluations."""
    items = list_evaluations(limit=10000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "created_at", "participant_id", "session_id", "scenario_id", "role",
        "sus_score", "ueq_pragmatic", "ueq_hedonic", "ueq_overall",
        "would_use", "for_what", "improve", "likes", "dislikes",
    ])
    for row in items:
        qualitative = row.get("qualitative") or {}
        writer.writerow([
            row.get("id", ""),
            row.get("created_at", ""),
            row.get("participant_id", ""),
            row.get("session_id", ""),
            row.get("scenario_id", ""),
            row.get("role", ""),
            row.get("sus_score", ""),
            row.get("ueq_pragmatic", ""),
            row.get("ueq_hedonic", ""),
            row.get("ueq_overall", ""),
            qualitative.get("would_use", ""),
            qualitative.get("for_what", ""),
            qualitative.get("improve", ""),
            qualitative.get("likes", ""),
            qualitative.get("dislikes", ""),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ovarp_evaluations.csv"},
    )
