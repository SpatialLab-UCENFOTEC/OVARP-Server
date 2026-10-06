"""
Open Virtual Agent Research Platform (OVARP) — Session Routes

Participant session lifecycle (start / pause / resume / end) and the event
markers researchers use to annotate what happened and when.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import csv
import io
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.core import telemetry as telemetry_log
from src.core.runtime import runtime

router = APIRouter(prefix="/api/session", tags=["sessions"])

SESSION_CSV_HEADER = [
    "Timestamp_ISO", "Unix_Timestamp", "Session_ID", "Participant_ID",
    "Event_Type", "Category_or_Label", "Notes", "Amended",
]


class SessionStartRequest(BaseModel):
    participant_id: str


class MarkerRequest(BaseModel):
    label: str
    metadata: dict | None = None
    category: str | None = None
    notes: str | None = None


@router.get("/status")
async def get_session_status():
    """Returns the current experiment session state"""
    return runtime.session_manager.get_status()


@router.post("/start")
async def start_session(req: SessionStartRequest):
    """Start a new experiment session with a participant ID"""
    runtime.session_manager.start_session(req.participant_id)
    runtime.telemetry.log_session_event("started", {"participant_id": req.participant_id})
    return runtime.session_manager.get_status()


@router.post("/pause")
async def pause_session():
    """Pause the active experiment session"""
    try:
        runtime.session_manager.pause_session()
        runtime.telemetry.log_session_event("paused")
        return runtime.session_manager.get_status()
    except ValueError as e:
        return {"error": str(e)}


@router.post("/resume")
async def resume_session():
    """Resume a paused experiment session"""
    try:
        runtime.session_manager.resume_session()
        runtime.telemetry.log_session_event("resumed")
        return runtime.session_manager.get_status()
    except ValueError as e:
        return {"error": str(e)}


@router.post("/end")
async def end_session():
    """End the active session and return the final session data"""
    try:
        completed = runtime.session_manager.end_session()
        runtime.telemetry.log_session_event("ended", {
            "participant_id": completed.participant_id,
            "marker_count": len(completed.markers),
        })
        return {"status": "completed", "session": completed.model_dump()}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/marker")
async def add_marker(req: MarkerRequest):
    """Add an event marker to the active session"""
    try:
        marker = runtime.session_manager.add_marker(
            req.label, req.metadata, category=req.category, notes=req.notes
        )
        runtime.telemetry.log_marker(
            req.label, req.metadata, marker_id=marker.id,
            category=marker.category, notes=marker.notes,
        )
        return {"status": "ok", "marker": marker.model_dump()}
    except ValueError as e:
        # A marker the server refused used to come back as 200 with an error
        # body, so every client reported success and the moment was lost.
        raise HTTPException(status_code=409, detail=str(e)) from e


class MarkerAmendRequest(BaseModel):
    label: str | None = None
    notes: str | None = None
    category: str | None = None


@router.patch("/marker/{marker_id}")
async def amend_marker(marker_id: str, req: MarkerAmendRequest):
    """Correct a marker's label or attach notes after the fact.

    The timestamp is never touched and the amendment is appended to the session
    log, so the record still shows what was captured live.
    """
    try:
        marker, before = runtime.session_manager.amend_marker(
            marker_id, label=req.label, notes=req.notes, category=req.category
        )
    except ValueError as e:
        return {"error": str(e)}

    if before:
        runtime.telemetry.log_marker_amendment(
            marker_id,
            before,
            {k: getattr(marker, k) for k in before},
        )
    return {"status": "ok", "marker": marker.model_dump(), "amended": bool(before)}


@router.delete("/marker/{marker_id}")
async def delete_marker(marker_id: str):
    """Retract a marker that should not have been fired."""
    try:
        marker = runtime.session_manager.delete_marker(marker_id)
    except ValueError as e:
        return {"error": str(e)}

    runtime.telemetry.log_marker_deleted(marker_id, marker.label)
    return {"status": "ok", "deleted": marker.model_dump()}


@router.get("/markers/presets")
async def get_marker_presets():
    """Returns the pre-programmed event marker presets from config.yaml"""
    config = runtime.config_manager.config
    if config.event_markers:
        return {"presets": [m.model_dump() for m in config.event_markers]}
    return {"presets": []}


def _csv_response(output: io.StringIO, filename: str) -> Response:
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _csv_from_log(session_id: str) -> Response:
    """Rebuild a finished session's marker table from the telemetry log."""
    markers = telemetry_log.read_session_markers(session_id)
    if not markers:
        raise HTTPException(
            status_code=404,
            detail=f"No markers recorded for session '{session_id}'",
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(SESSION_CSV_HEADER)
    for marker in markers:
        writer.writerow([
            marker["iso_time"], marker["timestamp"], session_id,
            marker.get("participant_id", ""), "MARKER",
            marker.get("category") or marker.get("label", ""),
            marker.get("notes") or "", "yes" if marker.get("amended") else "",
        ])
    return _csv_response(output, f"ovarp_session_{session_id}.csv")


@router.get("/recorded")
async def list_recorded_sessions():
    """Sessions present in the telemetry log, newest first.

    The in-memory session is gone after a restart; this is what is still on
    disk, so a researcher can come back the next day and find their run.
    """
    return {"sessions": telemetry_log.list_recorded_sessions()}


@router.get("/export/csv")
async def export_session_csv(session_id: str = ""):
    """Download a session's markers as a flat CSV for analysis.

    With no ``session_id`` this exports the active session, or the last one to
    finish in this process. Pass an id and it is read back from the append-only
    telemetry log instead, which survives a restart.
    """
    if session_id:
        return _csv_from_log(session_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(SESSION_CSV_HEADER)

    session = runtime.session_manager.exportable_session()
    if session:
        writer.writerow([
            session.started_at, session.started_at_unix, session.session_id,
            session.participant_id, "SESSION_START", session.status.upper(),
            f"Status: {session.status}", "",
        ])
        for marker in session.markers:
            writer.writerow([
                marker.iso_time, marker.timestamp, session.session_id,
                session.participant_id, "MARKER", marker.category or marker.label,
                marker.notes or "", "yes" if marker.amended else "",
            ])
    else:
        writer.writerow([
            datetime.now().isoformat(), time.time(), "N/A", "N/A",
            "INFO", "NO_ACTIVE_SESSION", "No session markers recorded yet", "",
        ])

    return _csv_response(output, "ovarp_session_telemetry.csv")


class MarkerPresetRequest(BaseModel):
    id: str
    label: str
    description: str | None = None
    color: str = "#4f46e5"


@router.post("/markers/presets")
async def add_or_update_marker_preset(req: MarkerPresetRequest):
    """Add or update an event marker preset.

    Held in config memory only: a preset invented mid-study is a convenience for
    that session, not an edit to the experiment definition on disk.
    """
    from src.core.config import EventMarkerPreset

    preset = EventMarkerPreset(
        id=req.id, label=req.label, description=req.description, color=req.color
    )
    config = runtime.config_manager.config
    if config.event_markers is None:
        config.event_markers = []

    existing = next((i for i, m in enumerate(config.event_markers) if m.id == req.id), None)
    if existing is not None:
        config.event_markers[existing] = preset
    else:
        config.event_markers.append(preset)

    return {"status": "ok", "presets": [m.model_dump() for m in config.event_markers]}
