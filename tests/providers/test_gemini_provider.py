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


@pytest.mark.asyncio
async def test_gemini_tts_provider(mock_gemini_client):
    """Test Gemini TTS via generate_content AUDIO modality."""
    mock_response = MagicMock()
    mock_candidate = MagicMock()
    mock_content = MagicMock()
    mock_part = MagicMock()
    mock_inline = MagicMock()
    mock_inline.data = b"fake_gemini_audio" * 500
    mock_inline.mime_type = "audio/L16;codec=pcm;rate=24000"
    mock_part.inline_data = mock_inline
    mock_content.parts = [mock_part]
    mock_candidate.content = mock_content
    mock_response.candidates = [mock_candidate]
    
    mock_gemini_client.models.generate_content = MagicMock(return_value=mock_response)

    provider = GeminiTTSProvider()
    
    stream = provider.synthesize_stream("Hello Gemini Audio")
    
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) > 0
    assert mock_gemini_client.models.generate_content.called
