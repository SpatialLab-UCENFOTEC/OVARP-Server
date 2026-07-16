"""
Unit tests for the CustomLLMProvider and CustomTTSProvider.

These test the custom provider module that enables runtime registration
of any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, etc.).

Covers:
    - CustomLLMProvider tool-calling path
    - CustomLLMProvider fallback (no tool support)
    - CustomLLMProvider streaming
    - CustomTTSProvider chunked streaming
    - test_custom_endpoint health check function
"""

import os
import json
import pytest

os.environ["OVARP_TESTING"] = "1"

from unittest.mock import AsyncMock, MagicMock, patch
from src.providers.custom_provider import CustomLLMProvider, CustomTTSProvider
from src.providers.custom_provider import test_custom_endpoint as check_custom_endpoint


# --- CustomLLMProvider ---

@pytest.fixture
def mock_custom_llm_client():
    """Mocks the AsyncOpenAI client used by CustomLLMProvider."""
    mock_client = MagicMock()

    # Mock LLM response with tool calls
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = None
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "update_agent_state"
    mock_tool_call.function.arguments = json.dumps({
        "spoken_response": "Hello from custom LLM!",
        "emotions": "happy",
        "actions": "wave",
    })
    mock_msg.tool_calls = [mock_tool_call]
    mock_choice.message = mock_msg
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    return mock_client


@pytest.fixture
def custom_llm(mock_custom_llm_client):
    """Create a CustomLLMProvider with a mocked client."""
    provider = CustomLLMProvider(
        name="test-ollama",
        base_url="http://localhost:11434/v1",
        model="llama3",
        api_key="",
    )
    provider.client = mock_custom_llm_client
    return provider


@pytest.mark.asyncio
async def test_custom_llm_with_tools(custom_llm, mock_config):
    """Test tool-calling response parsing."""
    spoken, actions = await custom_llm.generate_response_with_actions(
        prompt="Hello",
        system_prompt="Be friendly.",
        history=[],
    )
    assert spoken == "Hello from custom LLM!"
    assert actions["emotions"] == "happy"
    assert actions["actions"] == "wave"


@pytest.mark.asyncio
async def test_custom_llm_fallback_no_tools(custom_llm, mock_custom_llm_client, mock_config):
    """Test fallback when tool calling raises an exception."""
    plain_response = MagicMock()
    plain_choice = MagicMock()
    plain_msg = MagicMock()
    plain_msg.content = "Fallback response."
    plain_choice.message = plain_msg
    plain_response.choices = [plain_choice]

    mock_custom_llm_client.chat.completions.create = AsyncMock(
        side_effect=[Exception("tools not supported"), plain_response]
    )

    spoken, actions = await custom_llm.generate_response_with_actions(
        prompt="Hello",
        system_prompt="Be friendly.",
    )
    assert spoken == "Fallback response."
    assert actions == {}


@pytest.mark.asyncio
async def test_custom_llm_streaming(custom_llm, mock_custom_llm_client):
    """Test streaming text generation."""
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Hello"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " world"

    async def fake_stream():
        yield mock_chunk1
        yield mock_chunk2

    mock_custom_llm_client.chat.completions.create = AsyncMock(return_value=fake_stream())

    chunks = []
    async for chunk in custom_llm.generate_response("Hello"):
        chunks.append(chunk)

    assert "Hello" in chunks
    assert " world" in chunks


# --- CustomTTSProvider ---

@pytest.fixture
def mock_custom_tts_client():
    """Mocks the AsyncOpenAI client used by CustomTTSProvider."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"fake_tts_audio_" * 7000  # ~100KB
    mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.fixture
def custom_tts(mock_custom_tts_client):
    provider = CustomTTSProvider(
        name="test-tts",
        base_url="http://localhost:8080/v1",
        model="tts-1",
        api_key="",
    )
    provider.client = mock_custom_tts_client
    return provider


@pytest.mark.asyncio
async def test_custom_tts_chunking(custom_tts, mock_custom_tts_client):
    """Test that TTS audio is properly chunked for streaming."""
    chunks = []
    async for chunk in custom_tts.synthesize_stream("Hello world"):
        chunks.append(chunk)

    assert len(chunks) > 1
    total = b"".join(chunks)
    assert total == mock_custom_tts_client.audio.speech.create.return_value.content


@pytest.mark.asyncio
async def test_custom_tts_api_call(custom_tts, mock_custom_tts_client):
    """Test that TTS calls the API with correct parameters."""
    async for _ in custom_tts.synthesize_stream("Test input"):
        pass

    mock_custom_tts_client.audio.speech.create.assert_called_once()
    call_kwargs = mock_custom_tts_client.audio.speech.create.call_args[1]
    assert call_kwargs["input"] == "Test input"
    assert call_kwargs["voice"] == "alloy"
    assert call_kwargs["response_format"] == "wav"


# --- test_custom_endpoint ---

@pytest.mark.asyncio
async def test_endpoint_checker_models_success():
    """Test the health checker when /v1/models succeeds."""
    mock_model = MagicMock()
    mock_model.id = "llama3"
    mock_models_list = MagicMock()
    mock_models_list.data = [mock_model]

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(return_value=mock_models_list)

    with patch("src.providers.custom_provider.AsyncOpenAI", return_value=mock_client):
        result = await check_custom_endpoint("http://localhost:11434/v1")
        assert result["ok"] is True
        assert "llama3" in result["detail"]


@pytest.mark.asyncio
async def test_endpoint_checker_models_fail_chat_success():
    """Test fallback to chat completions when /v1/models fails."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=Exception("Not found"))

    mock_chat_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Hi"
    mock_chat_resp.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_chat_resp)

    with patch("src.providers.custom_provider.AsyncOpenAI", return_value=mock_client):
        result = await check_custom_endpoint("http://localhost:11434/v1", model="llama3")
        assert result["ok"] is True
        assert "Hi" in result["detail"]


@pytest.mark.asyncio
async def test_endpoint_checker_all_fail():
    """Test when both /models and chat fail."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=Exception("fail"))
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("also fail"))

    with patch("src.providers.custom_provider.AsyncOpenAI", return_value=mock_client):
        result = await check_custom_endpoint("http://localhost:11434/v1", model="llama3")
        assert result["ok"] is False
