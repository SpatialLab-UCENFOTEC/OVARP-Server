"""
QA test plan as pytest — the PR checklist, without a browser.

Maps 1:1 to:
  1. Player connects as web_panel_01
  2. WoZ commands target that device (Speak + gesture)
  3. researcher_usability scenario steps
  4. Evaluation tied to session + CSV export
  5. Latency is finalized after TTS and pushed to the UI
  6. latency_validation protocol + session CSV latency columns

These tests do not open Safari or call a live LLM. They lock the server
contracts so the manual checklist is not the only safety net.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["OVARP_TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.core.config import OVARPConfig, config_manager
from src.core.orchestrator import DialogOrchestrator
from src.core.scenario_runner import ScenarioRunner
from src.core.session_manager import SessionManager
from src.core.telemetry import TelemetryLogger
from src.providers.base import BaseLLMProvider, BaseSTTProvider, BaseTTSProvider

import src.main as main_module

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "static" / "index.html"
PLAYER_HTML = ROOT / "src" / "static" / "player.html"
SDK_JS = ROOT / "src" / "static" / "sdk" / "ovaf-client.js"
SCENARIOS_DIR = ROOT / "scenarios"


def _reset_scenarios():
    runner = ScenarioRunner()
    runner._scenarios = {}
    runner._active_scenario = None
    runner._current_step_index = -1
    return runner


class TestPlanPlayerPairing:
    def test_player_page_is_the_vr_stand_in(self):
        html = PLAYER_HTML.read_text(encoding="utf-8")
        assert "web_panel_01" in html
        assert "device-chip" in html
        assert "lat-total" in html
        assert "Mark event" in html
        assert "Copy pair info" in html
        assert "/ws/client/" in html
        assert "onLatency" in html

    def test_player_route_serves_that_page(self):
        client = TestClient(main_module.app)
        resp = client.get("/player")
        assert resp.status_code == 200
        assert "web_panel_01" in resp.text
        assert "OVARPClient" in resp.text

    def test_console_points_woz_at_the_player_device(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "web_panel_01" in html
        assert 'href="/player"' in html
        assert "target-device" in html


class TestPlanWozTargeting:
    def test_console_wires_speak_and_actions_to_selected_target(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "sendDirectTTS" in html
        assert "sendWozCommand" in html
        assert "direct_tts" in html
        assert "execute_state" in html
        assert "send-msg-btn" in html

    def test_sdk_does_not_hardcode_all_devices(self):
        sdk = SDK_JS.read_text(encoding="utf-8")
        assert "setTargets" in sdk
        assert "target_device: 'all'" not in sdk
        assert "targets.device || this.targetDevice" in sdk


class TestPlanResearcherScenario:
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


class TestPlanEvaluation:
    def test_console_has_facilitator_eval_controls(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "prefillEvalFromSession" in html
        assert "eval-session" in html
        assert "eval-scenario" in html
        assert "/api/evaluations/ovarp/export" in html
        assert "researcher_usability" in html

    def test_submit_evaluation_for_active_session_and_export_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.evaluations.EVAL_DIR", tmp_path)
        mgr = SessionManager()
        mgr._session = None
        monkeypatch.setattr(main_module, "session_manager", mgr, raising=False)
        monkeypatch.setattr(main_module, "telemetry", MagicMock(), raising=False)

        client = TestClient(main_module.app)
        started = client.post("/api/session/start", json={"participant_id": "P01"})
        assert started.status_code == 200
        status = client.get("/api/session/status").json()
        assert status["active"] is True
        assert status["participant_id"] == "P01"

        posted = client.post(
            "/api/evaluations/ovarp",
            json={
                "participant_id": status["participant_id"],
                "session_id": status["session_id"],
                "scenario_id": "researcher_usability",
                "role": "researcher",
                "sus": [4, 2, 4, 2, 4, 2, 4, 2, 4, 2],
                "ueq": [2, 1, 2, 1, 1, 2, 0, 1],
            },
        )
        assert posted.status_code == 200
        body = posted.json()
        assert body["session_id"] == status["session_id"]
        assert body["sus_score"] == 75.0

        exported = client.get("/api/evaluations/ovarp/export")
        assert exported.status_code == 200
        csv_text = exported.text
        assert "P01" in csv_text
        assert status["session_id"] in csv_text
        assert "researcher_usability" in csv_text


class TestPlanLatencyAfterTts:
    def test_console_and_player_listen_for_final_latency_event(self):
        index = INDEX_HTML.read_text(encoding="utf-8")
        player = PLAYER_HTML.read_text(encoding="utf-8")
        sdk = SDK_JS.read_text(encoding="utf-8")
        assert "onLatency" in sdk
        assert 'command === "latency"' in sdk
        assert "updatePlaygroundLatency" in index
        assert "onLatency" in index
        assert "onLatency" in player

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
