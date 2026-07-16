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
