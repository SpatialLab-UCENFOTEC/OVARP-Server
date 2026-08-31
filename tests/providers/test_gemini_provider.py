import pytest
from unittest.mock import AsyncMock, MagicMock
from src.providers.gemini_provider import GeminiLLMProvider, GeminiTTSProvider
import json

@pytest.fixture
def mock_gemini_client(mocker):
    """Mocks the genai.Client returned by the singleton"""
    mock_client = MagicMock()
    
    # Mock LLM
    mock_llm_response = MagicMock()
    mock_fc = MagicMock()
    mock_fc.name = "update_agent_state"
    mock_fc.args = {
        "emotions": "sad",
        "actions": "nod",
        "spoken_response": "I am a Gemini test."
    }
    mock_part = MagicMock()
    mock_part.function_call = mock_fc
    mock_part.text = ""
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_candidate = MagicMock()
    mock_candidate.content = mock_content
    mock_llm_response.candidates = [mock_candidate]
    mock_llm_response.text = ""
    
    mock_client.models.generate_content_stream = MagicMock()
    # Mock generator returning single chunk
    def mock_generate_content(*args, **kwargs):
        yield mock_llm_response
        
    mock_client.models.generate_content = MagicMock(return_value=mock_llm_response)

    # Patch the singleton
    mocker.patch("src.providers.gemini_provider.GeminiClientSingleton.get_client", return_value=mock_client)
    return mock_client

@pytest.mark.asyncio
async def test_gemini_llm_provider_formatting(mock_gemini_client, mock_config):
    """Test that the Gemini provider correctly formats its prompt instructing JSON output."""
    provider = GeminiLLMProvider()
    
    spoken_text, actions = await provider.generate_response_with_actions(
        prompt="Hello Gemini",
        system_prompt="System",
        history=[{"role": "user", "content": "hi"}]
    )
    
    assert spoken_text == "I am a Gemini test."
    assert actions["emotions"] == "sad"
    
    # Verify api was called
    mock_gemini_client.models.generate_content.assert_called_once()
    
    call_kwargs = mock_gemini_client.models.generate_content.call_args[1]
    
    # Verify the contents array was properly structured
    contents = call_kwargs["contents"]
    assert len(contents) == 2 # History (1 turn) + Current Prompt (1 turn)
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"][0]["text"] == "hi"
    assert contents[1]["role"] == "user" # The latest prompt
    assert "Hello Gemini" in contents[1]["parts"][0]["text"]
    
    # Ensure system_instruction was properly populated
    config_kwarg = call_kwargs["config"]
    assert config_kwarg.system_instruction == "System"


def _make_text_stream_chunk(text: str):
    chunk = MagicMock()
    chunk.text = text
    return chunk


@pytest.mark.asyncio
async def test_gemini_stream_reply_yields_real_deltas(mock_gemini_client, mock_config):
    """stream_reply must NOT force the actions tool (that's what blocks real streaming,
    see gemini_provider.py) and must yield each delta as it arrives, not one lump."""
    stream_chunks = [_make_text_stream_chunk("Hello "), _make_text_stream_chunk("world")]
    mock_gemini_client.models.generate_content_stream = MagicMock(return_value=iter(stream_chunks))

    provider = GeminiLLMProvider()
    deltas = []
    async for delta in provider.stream_reply(
        prompt="Hi", system_prompt="Sys", history=[{"role": "user", "content": "hey"}]
    ):
        deltas.append(delta)

    assert deltas == ["Hello ", "world"]

    call_kwargs = mock_gemini_client.models.generate_content_stream.call_args[1]
    # The literal system_prompt plus the override that cancels any "always call the
    # function" instruction from config.yaml's condition prompts (see gemini_provider.py).
    assert call_kwargs["config"].system_instruction == "Sys" + GeminiLLMProvider._NO_FUNCTION_CALL_OVERRIDE
    assert call_kwargs["config"].tools is None  # no forced function call: unlocks real streaming

    contents = call_kwargs["contents"]
    assert len(contents) == 2
    assert contents[0]["parts"][0]["text"] == "hey"
    assert contents[1]["parts"][0]["text"] == "Hi"


@pytest.mark.asyncio
async def test_gemini_stream_reply_swallows_stream_error(mock_gemini_client, mock_config):
    """A failed stream ends the generator instead of raising into the orchestrator's
    interaction loop (parity with generate_response_with_actions returning an error string)."""
    def _raise(*args, **kwargs):
        raise RuntimeError("network exploded")
    mock_gemini_client.models.generate_content_stream = MagicMock(side_effect=_raise)

    provider = GeminiLLMProvider()
    deltas = [d async for d in provider.stream_reply(prompt="Hi")]

    assert deltas == []


@pytest.mark.asyncio
async def test_gemini_extract_actions_classifies_generated_text(mock_gemini_client, mock_config):
    """extract_actions must NOT ask the model to restate spoken_response: only the
    configured action/emotion categories are in its tool schema."""
    mock_fc = MagicMock()
    mock_fc.name = "update_agent_state"
    mock_fc.args = {"emotions": "happy", "actions": "wave"}
    mock_part = MagicMock()
    mock_part.function_call = mock_fc
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_candidate = MagicMock()
    mock_candidate.content = mock_content
    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_gemini_client.models.generate_content = MagicMock(return_value=mock_response)

    provider = GeminiLLMProvider()
    actions = await provider.extract_actions("Hi there!", system_prompt="Sys")

    assert actions == {"emotions": "happy", "actions": "wave"}

    call_kwargs = mock_gemini_client.models.generate_content.call_args[1]
    properties = call_kwargs["config"].tools[0].function_declarations[0].parameters.properties
    assert "spoken_response" not in properties
    assert "emotions" in properties


@pytest.mark.asyncio
async def test_gemini_extract_actions_skips_empty_text(mock_gemini_client, mock_config):
    provider = GeminiLLMProvider()
    actions = await provider.extract_actions("", system_prompt="Sys")

    assert actions == {}
    mock_gemini_client.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_extract_actions_skips_when_no_custom_commands(
    mock_gemini_client, mock_config
):
    mock_config.custom_commands = {}
    provider = GeminiLLMProvider()
    actions = await provider.extract_actions("Hi there!", system_prompt="Sys")

    assert actions == {}
    mock_gemini_client.models.generate_content.assert_not_called()


def _make_tts_stream_chunk(data: bytes, mime_type: str):
    mock_part = MagicMock()
    mock_inline = MagicMock()
    mock_inline.data = data
    mock_inline.mime_type = mime_type
    mock_part.inline_data = mock_inline
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_candidate = MagicMock()
    mock_candidate.content = mock_content
    mock_chunk = MagicMock()
    mock_chunk.candidates = [mock_candidate]
    return mock_chunk


@pytest.mark.asyncio
async def test_gemini_tts_provider(mock_gemini_client):
    """Test Gemini TTS via generate_content_stream AUDIO modality (real incremental
    streaming, not a single blocking call — see gemini_provider.py for why)."""
    stream_chunks = [
        _make_tts_stream_chunk(b"fake_gemini_audio" * 250, "audio/l16;codec=pcm;rate=24000"),
        _make_tts_stream_chunk(b"fake_gemini_audio" * 250, "audio/l16;codec=pcm;rate=24000"),
    ]
    mock_gemini_client.models.generate_content_stream = MagicMock(return_value=iter(stream_chunks))

    provider = GeminiTTSProvider()

    stream = provider.synthesize_stream("Hello Gemini Audio")

    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) > 0
    assert chunks[0].startswith(b"RIFF")  # lower-case mime should still trigger the WAV header
    assert mock_gemini_client.models.generate_content_stream.called
