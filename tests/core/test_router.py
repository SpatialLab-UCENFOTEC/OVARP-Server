import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import json
import base64

from src.core.router import CommandRouter
from src.core.schemas import BaseCommand
from src.transport.base import BaseTransport

# Fixtures
@pytest.fixture
def mock_transport():
    transport = MagicMock(spec=BaseTransport)
    transport.send = AsyncMock()
    return transport

@pytest.fixture
def mock_orchestrator():
    orchestrator = MagicMock()
    orchestrator.process_audio_interaction = AsyncMock()
    orchestrator.process_text_interaction = AsyncMock()
    return orchestrator

@pytest.fixture
def router(mock_transport, mock_orchestrator):
    r = CommandRouter()
    r.add_transport(mock_transport)
    r.set_orchestrator(mock_orchestrator)
    return r

# Tests
@pytest.mark.asyncio
async def test_router_valid_dispatch_outbound(router, mock_transport):
    """Test that generic valid commands get dispatched to transports"""
    payload = {
        "sender": "woz_console",
        "target_device": "vr_headset",
        "target_agent": "agent_test",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {"actions": "wave"}
    }
    await router.handle_incoming_raw(json.dumps(payload))
    
    # Assert transport was called with the correct target and type
    assert mock_transport.send.call_count == 1
    call_args = mock_transport.send.call_args[0]
    assert call_args[0] == "vr_headset"  # target_device
    assert call_args[1] == "action"  # command_type
    
    # Assert payload was serialized properly
    sent_payload = json.loads(call_args[2])
    assert sent_payload["command"] == "execute_state"

@pytest.mark.asyncio
async def test_router_invalid_schema_ignored(router, mock_transport):
    """Test that invalid JSON schema doesn't crash the server and isn't routed"""
    bad_payload = {
        "sender": "vr_client",
        # Missing required fields like command_type
    }
    await router.handle_incoming_raw(json.dumps(bad_payload))
    
    assert mock_transport.send.call_count == 0

@pytest.mark.asyncio
async def test_router_audio_stt_routed_to_orchestrator(router, mock_orchestrator, mock_transport):
    """Test that audio chunks are sent to the orchestrator instead of being broadcasted back out"""
    audio_b64 = base64.b64encode(b"fake_audio_bytes").decode('utf-8')
    payload = {
        "sender": "mic_client",
        "target_device": "all",
        "target_agent": "agent_test",
        "command_type": "audio",
        "command": "stt_request",
        "subcommand": {"audio_base64": audio_b64}
    }
    
    await router.handle_incoming_raw(json.dumps(payload))
    
    # Wait a microsecond for the asyncio.create_task to fire
    await asyncio.sleep(0.01)
    
    assert mock_orchestrator.process_audio_interaction.call_count == 1
    call_kwargs = mock_orchestrator.process_audio_interaction.call_args[1]
    
    assert call_kwargs["audio_bytes"] == b"fake_audio_bytes"
    assert call_kwargs["target_device"] == "mic_client"  # Replies should go back to sender
    assert mock_transport.send.call_count == 0  # Should NOT broadcast raw audio


@pytest.mark.asyncio
async def test_router_text_llm_request_routed_to_orchestrator(router, mock_orchestrator, mock_transport):
    """Test that text messages intended for the LLM are routed properly to the orchestrator"""
    payload = {
        "sender": "web_chat",
        "target_device": "all",
        "target_agent": "agent_test",
        "command_type": "message",
        "command": "llm_request",
        "subcommand": {"text": "Hello world!"}
    }
    
    await router.handle_incoming_raw(json.dumps(payload))
    
    # Wait for asyncio.create_task to fire
    await asyncio.sleep(0.01)
    
    assert mock_orchestrator.process_text_interaction.call_count == 1
    call_kwargs = mock_orchestrator.process_text_interaction.call_args[1]
    
    assert call_kwargs["text"] == "Hello world!"
    assert call_kwargs["target_agent"] == "agent_test"
    assert mock_transport.send.call_count == 0 # Should NOT broadcast pure text request out without LLM processing
