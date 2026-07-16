import pytest
from unittest.mock import AsyncMock, MagicMock
from src.providers.openai_provider import OpenAISTTProvider, OpenAILLMProvider, OpenAITTSProvider
import json

@pytest.fixture
def mock_openai_client(mocker):
    """Mocks the AsyncOpenAI client returned by the singleton"""
    mock_client = MagicMock()
    
    # Mock STT
    mock_stt_response = MagicMock()
    mock_stt_response.text = "Testing STT"
    # The actual transcribe method returns just the string directly when response_format="text"
    mock_client.audio.transcriptions.create = AsyncMock(return_value="Testing STT")
    
    # Mock LLM (with tool calls)
    mock_llm_response = MagicMock()
    mock_choice = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = None # Typically empty when tool calls are used in our architecture
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "update_agent_state"
    mock_tool_call.function.arguments = json.dumps({
        "spoken_response": "I am a test.",
        "emotions": "happy",
        "actions": "wave"
    })
    mock_msg.tool_calls = [mock_tool_call]
    mock_choice.message = mock_msg
    mock_llm_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_llm_response)
    
    # Mock TTS
    mock_tts_response = MagicMock()
    mock_tts_response.content = b"fake_wav_audio_data_that_is_long_enough_to_chunk" * 1000 # Make it ~40KB
    mock_client.audio.speech.create = AsyncMock(return_value=mock_tts_response)

    # Patch the singleton
    mocker.patch("src.providers.openai_provider.OpenAIClientSingleton.get_client", return_value=mock_client)
    return mock_client

@pytest.mark.asyncio
async def test_openai_stt_provider(mock_openai_client):
    provider = OpenAISTTProvider()
    
    result = await provider.transcribe(b"fake_audio")
    assert result == "Testing STT"
    
    # Verify the API was called correctly
    mock_openai_client.audio.transcriptions.create.assert_called_once()
    call_kwargs = mock_openai_client.audio.transcriptions.create.call_args[1]
    assert call_kwargs["file"][1] == b"fake_audio"
    assert call_kwargs["response_format"] == "text"


@pytest.mark.asyncio
async def test_openai_llm_provider_tool_calling(mock_openai_client, mock_config):
    """Test that the LLM provider correctly parses tool calls from OpenAIs response into spoken text and action dicts."""
    provider = OpenAILLMProvider()
    
    spoken_text, actions = await provider.generate_response_with_actions(
        prompt="Hello",
        system_prompt="System",
        history=[]
    )
    
    assert spoken_text == "I am a test."
    assert actions["emotions"] == "happy"
    assert actions["actions"] == "wave"

    # Verify api was called
    mock_openai_client.chat.completions.create.assert_called_once()
    
    # Verify our custom dynamic tool schema was generated and passed
    call_kwargs = mock_openai_client.chat.completions.create.call_args[1]
    assert "tools" in call_kwargs
    tools = call_kwargs["tools"]
    assert len(tools) == 1
    func = tools[0]["function"]
    assert func["name"] == "update_agent_state"
    # Ensure properties match our config
    assert "emotions" in func["parameters"]["properties"]
    assert "spoken_response" in func["parameters"]["properties"]


@pytest.mark.asyncio
async def test_openai_tts_provider_chunking(mock_openai_client):
    """Test that the TTS provider correctly retrieves audio and generators chunks."""
    provider = OpenAITTSProvider()
    
    stream = provider.synthesize_stream("Hello")
    
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
        
    # verify we got chunks
    assert len(chunks) > 0
    # verify concatenation matches original
    assert b"".join(chunks) == mock_openai_client.audio.speech.create.return_value.content
