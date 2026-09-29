"""
Open Virtual Agent Research Platform (OVARP) — Turn Reporting Tests

Two things a turn must not do quietly: under-report how long the participant
waited, and drop a sentence of speech without saying so.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ["OVARP_TESTING"] = "1"

from src.core.orchestrator import DialogOrchestrator


@pytest.fixture
def orchestrator():
    """An orchestrator whose LLM answers instantly and whose TTS is off."""
    llm = MagicMock()
    llm.generate_response_with_actions = AsyncMock(return_value=("hola", {}))
    orch = DialogOrchestrator(
        stt_providers={"gemini": MagicMock()},
        llm_providers={"gemini": llm},
        tts_providers={"gemini": MagicMock()},
        default_llm="gemini", default_tts="gemini", default_stt="gemini",
    )
    orch.tts_enabled = False
    return orch


class TestTotalLatencyIncludesTranscription:
    """The clock starts after STT, so stt_ms has to be added back in.

    A voice turn otherwise reports a total that omits the seconds the
    participant spent being transcribed — the wait they actually felt.
    """

    def _latency(self, orchestrator, monkeypatch, stt_ms):
        published = {}

        async def capture(cmd):
            if cmd.command == "latency":
                published.update(cmd.subcommand)

        monkeypatch.setattr("src.core.orchestrator.router.route_command", capture)
        monkeypatch.setattr("src.core.orchestrator.telemetry", MagicMock())
        asyncio.run(orchestrator.process_text_interaction(
            "hola", "all", "agent_alpha", stt_ms=stt_ms))
        return published

    def test_transcription_time_is_part_of_the_total(self, orchestrator, monkeypatch):
        latency = self._latency(orchestrator, monkeypatch, stt_ms=2000)

        assert latency["stt_ms"] == 2000
        assert latency["total_ms"] >= 2000

    def test_a_typed_turn_reports_no_transcription(self, orchestrator, monkeypatch):
        latency = self._latency(orchestrator, monkeypatch, stt_ms=0)

        assert latency["stt_ms"] == 0

    def test_the_same_turn_reports_a_larger_total_with_stt(self, orchestrator, monkeypatch):
        without = self._latency(orchestrator, monkeypatch, stt_ms=0)["total_ms"]
        with_stt = self._latency(orchestrator, monkeypatch, stt_ms=3000)["total_ms"]

        assert with_stt - without >= 2900


class TestFailedSentenceIsAnnounced:
    """A sentence whose synthesis fails used to be logged and dropped.

    The reply text is already on screen at that point, so the silence reads as
    the agent mumbling rather than as a failure anyone can act on.
    """

    def test_a_failing_sentence_reports_a_pipeline_error(self, orchestrator, monkeypatch):
        provider = MagicMock()

        async def explode(_text):
            raise RuntimeError("quota exhausted")
            yield b""          # pragma: no cover - makes this an async generator

        provider.synthesize_stream = explode
        monkeypatch.setattr(orchestrator, "_resolve_tts", lambda _a: (provider, None))

        reported = []
        monkeypatch.setattr(
            orchestrator, "_report_pipeline_error",
            AsyncMock(side_effect=lambda *a, **k: reported.append(a)),
        )

        chunks = asyncio.run(orchestrator._synthesize_sentence(
            "una frase", "agent_alpha", asyncio.Semaphore(1)))

        assert chunks == []
        assert reported, "a dropped sentence must be announced, not just logged"
        assert reported[0][0] == "tts"
