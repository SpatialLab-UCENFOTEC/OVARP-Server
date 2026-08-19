"""Telemetry CSV export includes latency columns for validation protocols."""

import json
import os
from unittest.mock import MagicMock

os.environ["OVARP_TESTING"] = "1"

from src.core.telemetry import TelemetryLogger


def test_export_csv_includes_latency_columns(tmp_path):
    logger = TelemetryLogger.__new__(TelemetryLogger)
    logger.log_dir = tmp_path
    logger.session_id = "testlat"
    logger.jsonl_path = tmp_path / "session_testlat.jsonl"
    logger.console_logger = MagicMock()
    logger.jsonl_path.write_text(
        json.dumps({
            "timestamp": "t0",
            "event": "latency",
            "stt_ms": 10,
            "llm_ms": 20,
            "tts_ms": 30,
            "total_ms": 60,
            "target_device": "web_panel_01",
        }) + "\n",
        encoding="utf-8",
    )
    csv_path = logger.export_to_csv()
    text = csv_path.read_text(encoding="utf-8")
    assert "stt_ms" in text
    assert "total_ms" in text
    assert "60" in text
    assert "latency" in text
