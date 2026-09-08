import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.core.orchestrator import DialogOrchestrator
from src.core.schemas import BaseCommand
from src.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider
from src.core.profile_manager import AgentProfile, ProfilePersonality, ProfileVoice

@pytest.fixture
def mock_stt():
    stt = MagicMock(spec=BaseSTTProvider)
    stt.transcribe = AsyncMock(return_value="Hello bot")
    return stt

@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=BaseLLMProvider)
    llm.generate_response_with_actions = AsyncMock(return_value=("Hi user", {"actions": "wave"}))
    llm.model = "test-llm-model"
    return llm

@pytest.fixture
def mock_tts():
    tts = MagicMock(spec=BaseTTSProvider)
    
    async def fake_stream(_):
        yield b"audio_chunk_1"
        yield b"audio_chunk_2"
        
    tts.synthesize_stream = fake_stream
    return tts

@pytest.fixture
def orchestrator(mock_stt, mock_llm, mock_tts):
    return DialogOrchestrator(
        stt_provider=mock_stt,
        llm_providers={"test_llm": mock_llm},
        tts_providers={"test_llm": mock_tts},
        default_llm="test_llm"
    )

@pytest.mark.asyncio
async def test_process_audio_interaction_pipeline(orchestrator, mock_stt, mock_llm, mocker):
    """Test the full pipeline: Audio in -> STT -> LLM -> TTS out"""
    # Mock the router so we don't actually send ZMQ messages
    mock_router = mocker.patch("src.core.orchestrator.router")
    mock_router.route_command = AsyncMock()

    await orchestrator.process_audio_interaction(
        audio_bytes=b"fake_wav_data",
        target_device="vr_headset",
        target_agent="agent_alpha"
    )

    # 1. Ensure STT was called with the bytes
    mock_stt.transcribe.assert_called_once_with(b"fake_wav_data")

    # 2. Ensure LLM was called with the transcribed text "Hello bot"
    mock_llm.generate_response_with_actions.assert_called_once()
    llm_args = mock_llm.generate_response_with_actions.call_args[1]
    assert llm_args["prompt"] == "Hello bot"

    # 3. Ensure the router received the resulting commands
    # user_transcript, llm_reply, execute_state, 2x tts_chunk, tts_complete, then final latency
    assert mock_router.route_command.call_count == 7

    commands_sent = [call_args[0][0] for call_args in mock_router.route_command.call_args_list]

    assert commands_sent[0].command == "user_transcript"
    assert commands_sent[0].subcommand["text"] == "Hello bot"

    assert commands_sent[1].command == "llm_reply"
    assert commands_sent[1].subcommand["text"] == "Hi user"

    assert commands_sent[2].command == "execute_state"
    assert commands_sent[2].subcommand["actions"] == "wave"

    assert commands_sent[3].command == "tts_chunk"
    assert commands_sent[4].command == "tts_chunk"
    
    assert commands_sent[5].command == "tts_complete"
    assert commands_sent[6].command == "latency"
    assert "total_ms" in commands_sent[6].subcommand


@pytest.fixture
def mock_gemini_stream_llm():
    """Stand-in for GeminiLLMProvider's streaming-only interface (stream_reply +
    extract_actions). Deliberately NOT spec'd to BaseLLMProvider, which is exactly
    why the orchestrator's hasattr(self.llm, "stream_reply") gate is Gemini-only:
    a plain BaseLLMProvider mock (see mock_llm above) doesn't have this attribute."""
    llm = MagicMock()
    llm.model = "gemini-test-model"

    async def fake_stream_reply(prompt, system_prompt=None, history=None):
        for piece in ["Hi ", "there"]:
            yield piece

    llm.stream_reply = fake_stream_reply
    llm.extract_actions = AsyncMock(return_value={"actions": "wave"})
    return llm


@pytest.mark.asyncio
async def test_process_text_interaction_streams_gemini_reply(mock_stt, mock_gemini_stream_llm, mock_tts, mocker):
    """The Gemini-only streaming path: deltas go out as llm_reply_chunk in real time,
    the rest of the pipeline (execute_state, tts_chunk, tts_complete, latency) still
    happens. Actions (extract_actions) and TTS synthesis now run concurrently
    (OPA-335: gestures no longer block audio), so their relative order on the wire
    isn't guaranteed -- only that both complete before the final latency command."""
    orch = DialogOrchestrator(
        stt_provider=mock_stt,
        llm_providers={"gemini": mock_gemini_stream_llm},
        tts_providers={"gemini": mock_tts},
        default_llm="gemini",
        default_tts="gemini",
    )
    mock_router = mocker.patch("src.core.orchestrator.router")
    mock_router.route_command = AsyncMock()

    await orch.process_text_interaction("Hello bot", "all", "agent_alpha")

    commands_sent = [call_args[0][0] for call_args in mock_router.route_command.call_args_list]

    # First three and last are strictly ordered
    assert [c.command for c in commands_sent[:3]] == ["llm_reply_chunk", "llm_reply_chunk", "llm_reply"]
    assert commands_sent[-1].command == "latency"

    assert commands_sent[0].subcommand["text"] == "Hi "
    assert commands_sent[1].subcommand["text"] == "there"
    assert commands_sent[2].subcommand["text"] == "Hi there"
    assert commands_sent[2].subcommand["latency"]["llm_first_chunk_ms"] >= 0

    # The parallel actions + TTS commands land in between, order unconstrained
    middle = [c.command for c in commands_sent[3:-1]]
    assert sorted(middle) == sorted(["execute_state", "tts_chunk", "tts_chunk", "tts_complete"])

    execute_state_cmd = next(c for c in commands_sent if c.command == "execute_state")
    assert execute_state_cmd.subcommand == {"actions": "wave"}

    mock_gemini_stream_llm.extract_actions.assert_called_once()
    assert mock_gemini_stream_llm.extract_actions.call_args[0][0] == "Hi there"

    assert commands_sent[-1].subcommand["llm_first_chunk_ms"] >= 0
    assert commands_sent[-1].subcommand["tts_first_chunk_ms"] >= 0


@pytest.mark.asyncio
async def test_process_text_interaction_speaks_sentence_by_sentence(mock_stt, mocker):
    """OPA-335: each finished sentence is synthesized and sent to clients as soon as
    it's ready, instead of waiting for the whole reply -- two sentences means two
    separate synthesize_stream calls and two tts_chunk/tts_complete bursts, not one
    call on the full assembled text."""
    llm = MagicMock()
    llm.model = "gemini-test-model"

    async def fake_stream_reply(prompt, system_prompt=None, history=None):
        for piece in ["First sentence. ", "Second sentence."]:
            yield piece

    llm.stream_reply = fake_stream_reply
    llm.extract_actions = AsyncMock(return_value={})

    synth_calls = []
    tts = MagicMock(spec=BaseTTSProvider)

    async def fake_stream(text):
        synth_calls.append(text)
        yield b"audio_chunk"

    tts.synthesize_stream = fake_stream

    orch = DialogOrchestrator(
        stt_provider=mock_stt,
        llm_providers={"gemini": llm},
        tts_providers={"gemini": tts},
        default_llm="gemini",
        default_tts="gemini",
    )
    mock_router = mocker.patch("src.core.orchestrator.router")
    mock_router.route_command = AsyncMock()

    await orch.process_text_interaction("Hello bot", "all", "agent_alpha")

    assert synth_calls == ["First sentence.", "Second sentence."]

    commands_sent = [call_args[0][0] for call_args in mock_router.route_command.call_args_list]
    assert sum(1 for c in commands_sent if c.command == "tts_complete") == 2
    assert sum(1 for c in commands_sent if c.command == "tts_chunk") == 2

    latency_cmd = commands_sent[-1]
    assert latency_cmd.command == "latency"
    assert latency_cmd.subcommand["tts_first_chunk_ms"] >= 0


@pytest.mark.asyncio
async def test_history_management(orchestrator, mock_llm, mocker):
    """Test that the orchestrator properly trims conversation history to prevent context overflow"""
    mocker.patch("src.core.orchestrator.router") # Silence router

    # Intentionally lower the limit for testing
    orchestrator.MAX_HISTORY_TURNS = 4

    # Inject dummy conversation
    orchestrator.conversation_history = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"}
    ]

    await orchestrator.process_text_interaction("4", "all", "test")

    # History should now contain the new user prompt and the LLM reply ("Hi user" from fixture)
    # Total would be 5, but limit is 4, so the oldest ("1") should be dropped.
    assert len(orchestrator.conversation_history) == 4
    assert orchestrator.conversation_history[0]["content"] == "2"
    assert orchestrator.conversation_history[-1]["content"] == "Hi user"

def test_clear_history(orchestrator):
    """Test clearing conversation state"""
    orchestrator.conversation_history = [{"role": "user", "content": "hello"}]
    orchestrator.clear_history()
    assert len(orchestrator.conversation_history) == 0

def test_provider_hotswap(orchestrator, mock_llm):
    """Test dynamic switching of active LLM provider"""
    # Add a dummy second provider
    orchestrator.llm_providers["other_llm"] = MagicMock(spec=BaseLLMProvider)
    
    # Try valid swap
    success = orchestrator.set_active_llm("other_llm")
    assert success is True
    assert orchestrator.active_llm_id == "other_llm"
    assert orchestrator.llm == orchestrator.llm_providers["other_llm"]

    # Try invalid swap
    success2 = orchestrator.set_active_llm("non_existent_llm")
    assert success2 is False
    assert orchestrator.active_llm_id == "other_llm" # Should remain unchanged


# --- Per-agent voice resolution ---

def _profile(voice_provider="auto", voice_id="nova", profile_id="p1"):
    return AgentProfile(
        id=profile_id,
        name=profile_id.title(),
        voice=ProfileVoice(provider=voice_provider, voice_id=voice_id),
        personality=ProfilePersonality(system_prompt="Be brief."),
    )


@pytest.mark.asyncio
async def test_profile_voice_is_used_for_synthesis(orchestrator, mocker):
    """A profile's voice must reach the provider, not just sit in _agent_state."""
    mock_router = mocker.patch("src.core.orchestrator.router")
    mock_router.route_command = AsyncMock()
    orchestrator.tts_providers["test_llm"].voice = "alloy"

    orchestrator.apply_profile("agent_alpha", _profile(voice_id="nova"))
    await orchestrator._dispatch_tts("hola", "vr_headset", "agent_alpha")

    assert orchestrator.tts_providers["test_llm"].voice == "nova"


@pytest.mark.asyncio
async def test_agent_without_profile_uses_global_voice(orchestrator, mocker):
    """Agents left on the defaults follow the console's voice picker."""
    mock_router = mocker.patch("src.core.orchestrator.router")
    mock_router.route_command = AsyncMock()

    orchestrator.set_tts_voice("shimmer")
    await orchestrator._dispatch_tts("hola", "vr_headset", "agent_beta")

    assert orchestrator.tts_providers["test_llm"].voice == "shimmer"


def test_global_voice_change_does_not_override_a_pinned_agent(orchestrator):
    """The picker moves the global voice; a profiled agent keeps its own."""
    orchestrator.apply_profile("agent_alpha", _profile(voice_id="nova"))

    orchestrator.set_tts_voice("shimmer")

    _, resolved = orchestrator._resolve_tts("agent_alpha")
    assert resolved == "nova"
    assert orchestrator.get_effective_voice("agent_alpha")["pinned_by_profile"] is True
    assert orchestrator.get_effective_voice("agent_beta")["pinned_by_profile"] is False


def test_set_tts_voice_can_target_one_agent(orchestrator):
    """Pinning a voice per agent does not disturb the global setting."""
    orchestrator.tts_providers["test_llm"].voice = "alloy"

    orchestrator.set_tts_voice("echo", agent_id="agent_alpha")

    assert orchestrator._resolve_tts("agent_alpha")[1] == "echo"
    assert orchestrator.tts_providers["test_llm"].voice == "alloy"


def test_clear_profile_returns_agent_to_globals(orchestrator):
    """Releasing an agent makes the global prompt and voice apply to it again."""
    orchestrator.set_system_prompt("global prompt")
    orchestrator.tts_providers["test_llm"].voice = "alloy"
    orchestrator.apply_profile("agent_alpha", _profile(voice_id="nova"))

    orchestrator.clear_profile("agent_alpha")

    info = orchestrator.get_agent_info("agent_alpha")
    assert info["has_custom_prompt"] is False
    assert info["profile_id"] is None
    assert orchestrator._resolve_tts("agent_alpha")[1] is None
    assert orchestrator.get_effective_voice("agent_alpha")["voice"] == "alloy"


# --- Swappable transcription ---

@pytest.fixture
def two_stt_orchestrator(mock_llm, mock_tts):
    first, second = MagicMock(spec=BaseSTTProvider), MagicMock(spec=BaseSTTProvider)
    first.transcribe = AsyncMock(return_value="from first")
    second.transcribe = AsyncMock(return_value="from second")
    orchestrator = DialogOrchestrator(
        stt_providers={"first": first, "second": second},
        llm_providers={"test_llm": mock_llm},
        tts_providers={"test_llm": mock_tts},
        default_llm="test_llm",
        default_stt="first",
    )
    return orchestrator, first, second


@pytest.mark.asyncio
async def test_active_stt_provider_does_the_transcription(two_stt_orchestrator):
    orchestrator, _, _ = two_stt_orchestrator

    assert await orchestrator.stt.transcribe(b"audio") == "from first"


@pytest.mark.asyncio
async def test_switching_stt_changes_who_transcribes(two_stt_orchestrator):
    orchestrator, _, _ = two_stt_orchestrator

    assert orchestrator.set_active_stt("second") is True
    assert await orchestrator.stt.transcribe(b"audio") == "from second"


def test_unknown_stt_provider_is_refused(two_stt_orchestrator):
    orchestrator, _, _ = two_stt_orchestrator

    assert orchestrator.set_active_stt("nope") is False
    assert orchestrator.active_stt_id == "first"


def test_single_stt_provider_still_accepted(mock_stt, mock_llm, mock_tts):
    """The original single-provider signature keeps working."""
    orchestrator = DialogOrchestrator(
        stt_provider=mock_stt,
        llm_providers={"test_llm": mock_llm},
        tts_providers={"test_llm": mock_tts},
        default_llm="test_llm",
    )

    assert orchestrator.stt is mock_stt
    assert orchestrator.active_stt_id == "openai"
