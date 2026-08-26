"""
QA test plan as pytest — the researcher validation checklist, without a browser.

Recovered from the pre-rewrite suite. The items covering the standalone /player
page and the old evaluations module are omitted: those features no longer exist,
and marker amendment is covered by tests/test_api_sessions.py. What remains is
the part the current server still owes the protocol:

  researcher usability scenario, post-TTS latency publication, the
  latency_validation scenario, and latency columns in the session CSV.

It does not open a browser or call a live LLM.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["OVARP_TESTING"] = "1"

import pytest

from src.core.config import OVARPConfig, config_manager
from src.core.orchestrator import DialogOrchestrator
from src.core.scenario_runner import ScenarioRunner
from src.core.telemetry import TelemetryLogger
from src.providers.base import BaseLLMProvider, BaseSTTProvider, BaseTTSProvider

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "static" / "index.html"
SDK_JS = ROOT / "src" / "static" / "sdk" / "OVARP-client.js"
SCENARIOS_DIR = ROOT / "scenarios"


def _reset_scenarios():
    runner = ScenarioRunner()
    runner._scenarios = {}
    runner._active_scenario = None
    runner._current_step_index = -1
    return runner


class TestPlanResearcherScenario:
    """PR item 3: Study Session can load and walk researcher_usability."""
    def test_researcher_usability_yaml_walks_all_facilitator_steps(self):
        runner = _reset_scenarios()
        try:
            loaded = runner.load_scenarios_from_dir(str(SCENARIOS_DIR))
            assert "researcher_usability" in loaded
            step = runner.start("researcher_usability")
            ids = [step.id]
            while True:
                nxt = runner.advance()
                if nxt is None:
                    break
                ids.append(nxt.id)
            assert ids[0] == "briefing"
            assert ids[-1] == "evaluation"
            markers = [s.auto_marker for s in loaded["researcher_usability"].steps]
            assert "researcher_woz_control" in markers
            assert not runner.is_active
        finally:
            _reset_scenarios()


class TestPlanLatencyAfterTts:
    """PR item 5: TTS/total latency is published after audio, not only on llm_reply."""
    def test_console_listens_for_the_final_latency_event(self):
        index = INDEX_HTML.read_text(encoding="utf-8")
        sdk = SDK_JS.read_text(encoding="utf-8")
        assert "onLatency" in sdk
        assert 'data.command === "latency"' in sdk
        assert "updatePlaygroundLatency" in index
        assert "onLatency" in index

    @pytest.mark.asyncio
    async def test_pipeline_broadcasts_latency_only_after_tts_stage(self):
        mock_stt = MagicMock(spec=BaseSTTProvider)
        mock_llm = MagicMock(spec=BaseLLMProvider)
        mock_llm.generate_response_with_actions = AsyncMock(return_value=("Hi", {}))
        mock_llm.model = "test-model"
        mock_tts = MagicMock(spec=BaseTTSProvider)
        orch = DialogOrchestrator(
            stt_provider=mock_stt,
            llm_providers={"test_llm": mock_llm},
            tts_providers={"test_llm": mock_tts},
            default_llm="test_llm",
            default_tts="test_llm",
        )
        orch.tts_enabled = False

        prev = config_manager._config
        config_manager._config = OVARPConfig(
            experiment={"name": "t", "description": "d", "version": "1"},
            devices=[{"id": "web_panel_01", "name": "Player", "type": "web"}],
            agents=[{"id": "agent_alpha", "name": "Alpha"}],
            custom_commands={},
        )
        mock_router = MagicMock()
        mock_router.route_command = AsyncMock()
        mock_tel = MagicMock()
        try:
            with patch("src.core.orchestrator.router", mock_router), patch(
                "src.core.orchestrator.telemetry", mock_tel
            ):
                await orch.process_text_interaction("hello", "web_panel_01", "agent_alpha")
        finally:
            config_manager._config = prev

        mock_tel.log_latency.assert_called_once()
        lat = mock_tel.log_latency.call_args[0][0]
        assert "tts_ms" in lat
        assert "total_ms" in lat
        cmds = [call.args[0] for call in mock_router.route_command.await_args_list]
        assert cmds[0].command == "llm_reply"
        latency_cmds = [c for c in cmds if c.command == "latency"]
        assert len(latency_cmds) == 1
        assert latency_cmds[0].subcommand["tts_ms"] == lat["tts_ms"]
        assert latency_cmds[0].subcommand["total_ms"] == lat["total_ms"]


class TestPlanLatencyValidation:
    """PR item 6: latency_validation protocol + session CSV latency columns."""
    def test_latency_validation_yaml_covers_text_mic_and_woz(self):
        runner = _reset_scenarios()
        try:
            loaded = runner.load_scenarios_from_dir(str(SCENARIOS_DIR))
            assert "latency_validation" in loaded
            markers = [s.auto_marker for s in loaded["latency_validation"].steps]
            assert "latency_setup" in markers
            assert "latency_turn_text" in markers
            assert "latency_turn_mic" in markers
            assert "latency_woz_direct" in markers
            assert "latency_debrief" in markers
            step = runner.start("latency_validation")
            ids = [step.id]
            while True:
                nxt = runner.advance()
                if nxt is None:
                    break
                ids.append(nxt.id)
            assert ids[0] == "setup"
            assert ids[-1] == "debrief"
        finally:
            _reset_scenarios()

    def test_session_csv_includes_latency_event_columns(self, tmp_path):
        logger = TelemetryLogger.__new__(TelemetryLogger)
        logger.log_dir = tmp_path
        logger.session_id = "qa"
        logger.jsonl_path = tmp_path / "session_qa.jsonl"
        logger.console_logger = MagicMock()
        logger.jsonl_path.write_text(
            json.dumps({
                "timestamp": "t0",
                "event": "latency",
                "stt_ms": 11,
                "llm_ms": 22,
                "tts_ms": 33,
                "total_ms": 66,
            })
            + "\n",
            encoding="utf-8",
        )
        csv_path = logger.export_to_csv()
        text = csv_path.read_text(encoding="utf-8")
        assert "event_type" in text
        assert "stt_ms" in text
        assert "tts_ms" in text
        assert "total_ms" in text
        assert "latency" in text
        assert "66" in text
