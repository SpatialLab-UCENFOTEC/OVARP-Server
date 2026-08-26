"""
Open Virtual Agent Research Platform (OVARP) — Telemetry Logger

Handles structured logging of all interactions for experimental
reproducibility. Events are recorded in JSONL format with high-precision
timestamps and can be exported to CSV for analysis in SPSS, R, or
similar statistical software.

Now supports session-aware logging: when an experiment session is active,
every log entry includes participant_id and session_id. Event markers
are logged as distinct entries for post-hoc analysis.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
import json
import csv
import time
from datetime import datetime
import structlog
from pathlib import Path

from src.core.schemas import BaseCommand

class TelemetryLogger:
    """
    Handles structured logging of all interactions for experimental reproducibility.
    Logs are saved in JSONL format, and can be exported to CSV.
    Session-aware: injects participant_id and session_id when a session is active.
    """
    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = Path("data/sessions")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.log_dir / f"session_{self.session_id}.jsonl"

        # Configure structlog to output to file
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer()
            ],
            logger_factory=structlog.WriteLoggerFactory(
                file=open(self.jsonl_path, "a", encoding="utf-8")
            )
        )
        self.file_logger = structlog.get_logger()

        # Keep a console logger separate so we don't spam JSON to the stdout
        self.console_logger = structlog.get_logger("console")
        self.console_logger.info("Telemetry Session Started", session_id=self.session_id, file=str(self.jsonl_path))

    def _get_session_context(self) -> dict:
        """Returns session metadata to inject into every log entry, if a session is active."""
        # Import here to avoid circular imports (session_manager imports nothing from telemetry)
        from src.core.session_manager import session_manager

        if session_manager.is_active and session_manager.session:
            return {
                "experiment_session_id": session_manager.session.session_id,
                "participant_id": session_manager.session.participant_id,
                "session_status": session_manager.session.status,
            }
        return {}

    def log_interaction(self, command: BaseCommand):
        """Append a Command directly to the session logs with an atomic timestamp."""
        ctx = self._get_session_context()
        self.file_logger.info(
            event="interaction",
            host_timestamp=time.time(),
            sender=command.sender,
            target_device=command.target_device,
            target_agent=command.target_agent,
            command_type=command.command_type,
            command=command.command,
            subcommand=command.subcommand,
            **ctx
        )

    def log_marker(self, label: str, metadata: dict = None):
        """Log an event marker as a distinct telemetry entry."""
        ctx = self._get_session_context()
        self.file_logger.info(
            event="marker",
            host_timestamp=time.time(),
            label=label,
            marker_metadata=metadata,
            **ctx
        )

    def log_marker_amendment(self, marker_id: str, before: dict, after: dict):
        """Record a marker correction without rewriting what was originally logged.

        The session JSONL is append-only, so the first ``marker`` entry stays as
        captured and this adds the diff on top. The pair is what makes an edited
        marker auditable rather than just changed.
        """
        ctx = self._get_session_context()
        self.file_logger.info(
            event="marker_amended",
            host_timestamp=time.time(),
            marker_id=marker_id,
            amended_from=before,
            amended_to=after,
            **ctx
        )

    def log_marker_deleted(self, marker_id: str, label: str):
        """Record that a marker was retracted, keeping the original entry intact."""
        ctx = self._get_session_context()
        self.file_logger.info(
            event="marker_deleted",
            host_timestamp=time.time(),
            marker_id=marker_id,
            label=label,
            **ctx
        )

    def log_survey_response(self, survey_id: str, participant_id: str,
                            answers: dict, score: dict):
        """Record a completed questionnaire alongside the interaction log.

        Keeping responses in the same JSONL as the session means the scores line
        up with the markers and latencies for that participant without a join.
        """
        ctx = self._get_session_context()
        ctx["participant_id"] = participant_id or ctx.get("participant_id", "")
        self.file_logger.info(
            event="survey_response",
            host_timestamp=time.time(),
            survey_id=survey_id,
            survey_answers=answers,
            survey_score=score,
            **ctx
        )

    def log_latency(self, latency: dict):
        """Log pipeline latency metrics."""
        ctx = self._get_session_context()
        self.file_logger.info(
            event="latency",
            host_timestamp=time.time(),
            **latency,
            **ctx
        )

    def log_xr_telemetry(self, device_id: str, frames: list[dict]):
        """Log batched XR telemetry frames (head/hand/gaze tracking)."""
        ctx = self._get_session_context()
        for frame in frames:
            self.file_logger.info(
                event="xr_telemetry",
                host_timestamp=time.time(),
                device_id=device_id,
                **frame,
                **ctx
            )

    def log_session_event(self, event_type: str, details: dict = None):
        """Log session lifecycle events (start, pause, resume, end)."""
        ctx = self._get_session_context()
        self.file_logger.info(
            event="session",
            host_timestamp=time.time(),
            session_event=event_type,
            details=details or {},
            **ctx
        )

    def export_to_csv(self) -> Path:
        """Parses the current session JSONL and flattens it to CSV for statistical analysis software like SPSS/R."""
        csv_path = self.log_dir / f"session_{self.session_id}.csv"

        try:
            with open(self.jsonl_path, 'r', encoding="utf-8") as f_in, \
                 open(csv_path, 'w', newline='', encoding="utf-8") as f_out:

                writer = csv.writer(f_out)
                # Write header with session columns
                writer.writerow([
                    "iso_time", "host_timestamp", "event_type",
                    "participant_id", "experiment_session_id",
                    "sender", "target_device", "target_agent",
                    "command_type", "command", "subcommand_json",
                    "marker_label", "marker_metadata",
                    "marker_id", "marker_amended_from", "marker_amended_to",
                    "survey_id", "survey_score", "survey_answers",
                    "stt_ms", "llm_ms", "tts_ms", "total_ms"
                ])

                for line in f_in:
                    if not line.strip(): continue
                    data = json.loads(line)
                    event_type = data.get("event", "")

                    writer.writerow([
                        data.get("timestamp", ""),
                        data.get("host_timestamp", ""),
                        event_type,
                        data.get("participant_id", ""),
                        data.get("experiment_session_id", ""),
                        data.get("sender", ""),
                        data.get("target_device", ""),
                        data.get("target_agent", ""),
                        data.get("command_type", ""),
                        data.get("command", ""),
                        json.dumps(data.get("subcommand", {})),
                        data.get("label", ""),
                        json.dumps(data.get("marker_metadata", {})),
                        data.get("marker_id", ""),
                        json.dumps(data.get("amended_from", {})) if data.get("amended_from") else "",
                        json.dumps(data.get("amended_to", {})) if data.get("amended_to") else "",
                        data.get("survey_id", ""),
                        json.dumps(data.get("survey_score", {})) if data.get("survey_score") else "",
                        json.dumps(data.get("survey_answers", {})) if data.get("survey_answers") else "",
                        data.get("stt_ms", ""),
                        data.get("llm_ms", ""),
                        data.get("tts_ms", ""),
                        data.get("total_ms", ""),
                    ])

            self.console_logger.info("Telemetry Exported successfully", csv_file=str(csv_path))
            return csv_path
        except Exception as e:
            self.console_logger.error("Failed to export telemetry to CSV", error=str(e))
            return None

telemetry = TelemetryLogger()
