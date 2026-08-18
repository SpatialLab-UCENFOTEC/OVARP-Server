import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.core.orchestrator import DialogOrchestrator
from src.core.schemas import BaseCommand
from src.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider

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
    # We expect 6 commands: user_transcript, llm_reply (text), execute_state (actions), 2x tts_chunk, 1x tts_complete
    assert mock_router.route_command.call_count == 6

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


def test_apply_profile_selects_llm_and_tts(orchestrator, mock_tts):
    from src.core.profile_manager import AgentProfile, ProfileVoice, ProfilePersonality

    orchestrator.llm_providers["openai"] = MagicMock(spec=BaseLLMProvider)
    orchestrator.tts_providers["openai"] = mock_tts
    profile = AgentProfile(
        id="pinned",
        name="Pinned",
        llm_provider="openai",
        voice=ProfileVoice(provider="openai", voice_id="nova"),
        personality=ProfilePersonality(system_prompt="You are pinned."),
    )
    orchestrator.apply_profile("agent_alpha", profile)
    info = orchestrator.get_agent_info("agent_alpha")
    assert orchestrator.active_llm_id == "openai"
    assert orchestrator.active_tts_id == "openai"
    assert mock_tts.voice == "nova"
    assert info["llm_provider"] == "openai"
    assert info["profile_id"] == "pinned"
    selection = orchestrator.get_runtime_selection()
    assert selection["llm"] == "openai"
    assert selection["tts"] == "openai"


@pytest.mark.asyncio
async def test_process_direct_tts_routes_to_selected_device(orchestrator):
    """Direct TTS captions must follow the WoZ target, not every headset."""
    from unittest.mock import patch
    from src.core.config import OVARPConfig, config_manager

    prev = config_manager._config
    config_manager._config = OVARPConfig(
        experiment={"name": "t", "description": "d", "version": "1"},
        devices=[{"id": "headset_01", "name": "Headset", "type": "xr"}],
        agents=[{"id": "agent_alpha", "name": "Alpha"}],
        custom_commands={},
    )
    orchestrator.tts_enabled = False
    mock_router = MagicMock()
    mock_router.route_command = AsyncMock()

    try:
        with patch("src.core.orchestrator.router", mock_router):
            await orchestrator.process_direct_tts(
                text="Hello headset",
                target_device="headset_01",
                target_agent="agent_alpha",
            )
    finally:
        config_manager._config = prev

    mock_router.route_command.assert_awaited_once()
    cmd = mock_router.route_command.await_args[0][0]
    assert cmd.command == "llm_reply"
    assert cmd.target_device == "headset_01"
    assert cmd.target_agent == "agent_alpha"
    assert cmd.subcommand["text"] == "Hello headset"
    assert cmd.subcommand["provider"] == "woz_direct"


@pytest.mark.asyncio
async def test_process_text_logs_and_broadcasts_final_latency(orchestrator):
    """After TTS (or skip), persist latency and notify clients with final tts/total."""
    from unittest.mock import patch
    from src.core.config import OVARPConfig, config_manager

    prev = config_manager._config
    config_manager._config = OVARPConfig(
        experiment={"name": "t", "description": "d", "version": "1"},
        devices=[{"id": "headset_01", "name": "Headset", "type": "xr"}],
        agents=[{"id": "agent_alpha", "name": "Alpha"}],
        custom_commands={},
    )
    orchestrator.tts_enabled = False
    mock_router = MagicMock()
    mock_router.route_command = AsyncMock()
    mock_tel = MagicMock()

    try:
        with patch("src.core.orchestrator.router", mock_router), \
             patch("src.core.orchestrator.telemetry", mock_tel):
            await orchestrator.process_text_interaction(
                "hello", "all", "agent_alpha"
            )
    finally:
        config_manager._config = prev

    mock_tel.log_latency.assert_called_once()
    lat = mock_tel.log_latency.call_args[0][0]
    assert lat["tts_ms"] == 0
    assert "llm_ms" in lat
    assert "total_ms" in lat
    cmds = [call.args[0] for call in mock_router.route_command.await_args_list]
    latency_cmds = [c for c in cmds if getattr(c, "command", None) == "latency"]
    assert len(latency_cmds) == 1
    assert latency_cmds[0].subcommand["total_ms"] == lat["total_ms"]
