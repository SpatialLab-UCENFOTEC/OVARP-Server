"""
Open Virtual Agent Research Platform (OVARP) — Session Manager

Manages experiment sessions with participant tracking, lifecycle control
(start/pause/resume/end), and real-time event markers for annotation.
Designed for research protocols where reproducibility and precise timing
are critical.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import time
import uuid
import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

std_log = logging.getLogger("OVARP.session")


class EventMarker(BaseModel):
    """A timestamped annotation created by the researcher during an experiment."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8], description="Unique marker identifier")
    timestamp: float = Field(description="High-precision Unix timestamp")
    iso_time: str = Field(description="Human-readable ISO timestamp")
    label: str = Field(description="Short label, e.g. 'task_started', 'participant_discomfort'")
    category: Optional[str] = Field(default=None, description="Marker category, e.g. 'Technical Issue'")
    notes: Optional[str] = Field(default=None, description="Researcher notes")
    metadata: Optional[dict] = Field(default=None, description="Optional extra data")


class ExperimentSession(BaseModel):
    """Represents a single experiment session with one participant."""
    session_id: str = Field(description="Auto-generated unique session ID")
    participant_id: str = Field(description="Researcher-assigned participant identifier")
    started_at: str = Field(description="ISO timestamp of session start")
    started_at_unix: float = Field(description="Unix timestamp of session start")
    ended_at: Optional[str] = Field(default=None, description="ISO timestamp of session end")
    status: str = Field(default="active", description="active | paused | completed")
    markers: list[EventMarker] = Field(default_factory=list)
    pause_accumulator: float = Field(default=0.0, description="Total paused time in seconds")
    paused_at: Optional[float] = Field(default=None, description="When the current pause started")


class SessionManager:
    """
    Singleton that manages the active experiment session.
    Only one session can be active at a time.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._session = None
        return cls._instance

    @property
    def session(self) -> Optional[ExperimentSession]:
        return self._session

    @property
    def is_active(self) -> bool:
        return self._session is not None and self._session.status in ("active", "paused")

    def start_session(self, participant_id: str) -> ExperimentSession:
        """Start a new experiment session. Ends any existing session first."""
        if self.is_active:
            self.end_session()

        now = datetime.now()
        session = ExperimentSession(
            session_id=uuid.uuid4().hex[:12],
            participant_id=participant_id,
            started_at=now.isoformat(),
            started_at_unix=time.time(),
        )
        self._session = session
        std_log.info(f"🧪 Session STARTED | participant={participant_id} | session_id={session.session_id}")
        return session

    def pause_session(self) -> ExperimentSession:
        """Pause the active session."""
        if not self._session or self._session.status != "active":
            raise ValueError("No active session to pause")

        self._session.status = "paused"
        self._session.paused_at = time.time()
        std_log.info(f"⏸️ Session PAUSED | session_id={self._session.session_id}")
        return self._session

    def resume_session(self) -> ExperimentSession:
        """Resume a paused session."""
        if not self._session or self._session.status != "paused":
            raise ValueError("No paused session to resume")

        # Accumulate the paused duration
        if self._session.paused_at:
            self._session.pause_accumulator += time.time() - self._session.paused_at
            self._session.paused_at = None

        self._session.status = "active"
        std_log.info(f"▶️ Session RESUMED | session_id={self._session.session_id}")
        return self._session

    def end_session(self) -> ExperimentSession:
        """End the active session and return the final session data."""
        if not self._session:
            raise ValueError("No session to end")

        # If paused, accumulate remaining pause time
        if self._session.paused_at:
            self._session.pause_accumulator += time.time() - self._session.paused_at
            self._session.paused_at = None

        self._session.status = "completed"
        self._session.ended_at = datetime.now().isoformat()
        std_log.info(
            f"⏹️ Session ENDED | session_id={self._session.session_id} "
            f"| participant={self._session.participant_id} "
            f"| markers={len(self._session.markers)}"
        )

        completed = self._session
        self._session = None
        return completed

    def add_marker(self, label: str, metadata: dict = None, category: str = None, notes: str = None) -> EventMarker:
        """Add an event marker to the active session and log it to telemetry."""
        if not self._session or self._session.status == "completed":
            raise ValueError("No active session for markers")

        now = datetime.now()
        marker = EventMarker(
            timestamp=time.time(),
            iso_time=now.isoformat(),
            label=label,
            category=category,
            notes=notes,
            metadata=metadata,
        )
        self._session.markers.append(marker)
        std_log.info(f"📌 MARKER | label=\"{label}\" | category=\"{category}\" | session={self._session.session_id}")
        return marker

    def update_marker(
        self,
        marker_id: str,
        category: Optional[str] = None,
        notes: Optional[str] = None,
        label: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> EventMarker:
        """Update an existing event marker in the active session."""
        if not self._session or self._session.status == "completed":
            raise ValueError("No active session for marker update")

        target_marker = None
        for m in self._session.markers:
            if m.id == marker_id:
                target_marker = m
                break

        if not target_marker and marker_id.isdigit():
            idx = int(marker_id)
            if 0 <= idx < len(self._session.markers):
                target_marker = self._session.markers[idx]

        if not target_marker:
            raise ValueError(f"Marker '{marker_id}' not found in active session")

        if label is not None:
            target_marker.label = label
        if category is not None:
            target_marker.category = category
        if notes is not None:
            target_marker.notes = notes
        if metadata is not None:
            target_marker.metadata = metadata

        std_log.info(f"📌 MARKER UPDATED | id={target_marker.id} | category=\"{target_marker.category}\"")
        return target_marker

    def get_elapsed_seconds(self) -> float:
        """Returns the active (non-paused) elapsed time in seconds."""
        if not self._session:
            return 0.0

        total = time.time() - self._session.started_at_unix
        paused = self._session.pause_accumulator
        if self._session.paused_at:
            paused += time.time() - self._session.paused_at
        return total - paused

    def get_status(self) -> dict:
        """Returns a summary of the current session state for the API."""
        if not self._session:
            return {"active": False}

        return {
            "active": True,
            "session_id": self._session.session_id,
            "participant_id": self._session.participant_id,
            "status": self._session.status,
            "started_at": self._session.started_at,
            "elapsed_seconds": round(self.get_elapsed_seconds(), 1),
            "marker_count": len(self._session.markers),
            "markers": [m.model_dump() for m in self._session.markers],
        }


# Global accessor
session_manager = SessionManager()
