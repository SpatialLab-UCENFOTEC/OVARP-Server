"""
Tests for the SessionManager — session lifecycle and event markers.
"""

import time
import pytest
from src.core.session_manager import SessionManager, ExperimentSession, EventMarker


@pytest.fixture
def fresh_manager():
    """Provides a clean SessionManager for each test (resets singleton state)."""
    manager = SessionManager()
    # Reset singleton state so tests are independent
    manager._session = None
    return manager


def test_start_session(fresh_manager):
    """Starting a session creates an active session with the given participant ID."""
    session = fresh_manager.start_session("P001")
    assert session.participant_id == "P001"
    assert session.status == "active"
    assert fresh_manager.is_active


def test_pause_resume_session(fresh_manager):
    """Pausing and resuming changes the status correctly."""
    fresh_manager.start_session("P002")

    paused = fresh_manager.pause_session()
    assert paused.status == "paused"
    assert fresh_manager.is_active  # paused still counts as active

    resumed = fresh_manager.resume_session()
    assert resumed.status == "active"


def test_end_session(fresh_manager):
    """Ending a session sets status to completed and clears the active session."""
    fresh_manager.start_session("P003")
    completed = fresh_manager.end_session()

    assert completed.status == "completed"
    assert completed.ended_at is not None
    assert not fresh_manager.is_active


def test_add_marker(fresh_manager):
    """Markers are added to the active session with timestamps."""
    fresh_manager.start_session("P004")
    marker = fresh_manager.add_marker("task_started", {"phase": 1})

    assert marker.label == "task_started"
    assert marker.metadata == {"phase": 1}
    assert marker.timestamp > 0
    assert len(fresh_manager.session.markers) == 1


def test_multiple_markers(fresh_manager):
    """Multiple markers accumulate in the session."""
    fresh_manager.start_session("P005")
    fresh_manager.add_marker("intro_started")
    fresh_manager.add_marker("user_discomfort")
    fresh_manager.add_marker("task_completed")

    assert len(fresh_manager.session.markers) == 3
    labels = [m.label for m in fresh_manager.session.markers]
    assert labels == ["intro_started", "user_discomfort", "task_completed"]


def test_end_without_start_raises(fresh_manager):
    """Ending a session when none exists raises ValueError."""
    with pytest.raises(ValueError):
        fresh_manager.end_session()


def test_pause_without_start_raises(fresh_manager):
    """Pausing when no active session exists raises ValueError."""
    with pytest.raises(ValueError):
        fresh_manager.pause_session()


def test_marker_without_session_raises(fresh_manager):
    """Adding a marker without an active session raises ValueError."""
    with pytest.raises(ValueError):
        fresh_manager.add_marker("should_fail")


def test_get_status_active(fresh_manager):
    """get_status returns correct info for an active session."""
    fresh_manager.start_session("P006")
    fresh_manager.add_marker("test_marker")
    status = fresh_manager.get_status()

    assert status["active"] is True
    assert status["participant_id"] == "P006"
    assert status["status"] == "active"
    assert status["marker_count"] == 1


def test_get_status_no_session(fresh_manager):
    """get_status returns inactive when no session exists."""
    status = fresh_manager.get_status()
    assert status["active"] is False


def test_start_ends_existing_session(fresh_manager):
    """Starting a new session automatically ends the previous one."""
    fresh_manager.start_session("P007")
    fresh_manager.add_marker("old_marker")

    # Start a new session — should end the previous
    session = fresh_manager.start_session("P008")
    assert session.participant_id == "P008"
    assert len(session.markers) == 0  # fresh session has no markers
