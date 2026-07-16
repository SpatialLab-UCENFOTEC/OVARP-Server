"""
Open Virtual Agent Research Platform (OVARP) — OpenAI Provider

Implements STT, LLM, and TTS providers using the OpenAI API:
- ``OpenAISTTProvider``: Whisper-based speech-to-text transcription.
- ``OpenAILLMProvider``: GPT chat completions with tool/function calling
  for agent actions (emotions, gestures, gaze).
- ``OpenAITTSProvider``: Text-to-speech synthesis using the ``tts-1`` model.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
import json
from typing import AsyncGenerator, Dict, Any, Optional
from openai import AsyncOpenAI
import logging
from structlog import get_logger

from src.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider
from src.core.config import config_manager

logger = get_logger()
std_log = logging.getLogger("OVARP.openai")

class OpenAIClientSingleton:
    """Manages the shared AsyncOpenAI client instance."""
    _instance = None
    _client: AsyncOpenAI = None

    @classmethod
    def get_client(cls) -> AsyncOpenAI:
        if cls._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY environment variable not set. OpenAI won't authenticate.")
                # We instantiate with a dummy key to prevent immediate pydantic validation crashes at boot,
                # though any actual API call will fail gracefully later.
                cls._client = AsyncOpenAI(api_key="sk-dummy")
            else:
                cls._client = AsyncOpenAI(api_key=api_key)
        return cls._client

class OpenAISTTProvider(BaseSTTProvider):
    """Whisper transcription provider."""
    def __init__(self, model_name: str = "whisper-1"):
        self.model = model_name
        self.client = OpenAIClientSingleton.get_client()

    async def transcribe(self, audio_data: bytes) -> str:
        # Note: OpenAI expects a named file or a tuple (filename, file_content)
        # Ideally, we receive WAV or similar encoded binary audio from the XR client
        try:
            std_log.info(f"🎤 STT: Starting transcription | audio_size={len(audio_data)} bytes")
            file_tuple = ("audio.wav", audio_data, "audio/wav")
            transcription = await self.client.audio.transcriptions.create(
                model=self.model,
                file=file_tuple,
                response_format="text"
            )
            std_log.info(f"✅ STT: Transcription complete | text=\"{str(transcription)[:80]}\"")
            return transcription
        except Exception as e:
            std_log.error(f"❌ STT: Transcription failed | {type(e).__name__}: {str(e)}")
            logger.error("STT transcription failed", error=str(e))
            return ""

class OpenAILLMProvider(BaseLLMProvider):
    """GPT-based Language Model using Tool Calling for dynamic configuration actions."""
    def __init__(self, model_name: str = "gpt-4o"):
        self.model = model_name
        self.client = OpenAIClientSingleton.get_client()

    def _build_tools_schema(self) -> list[Dict[str, Any]]:
        """Dynamically build OpenAI Tool Schema from the config_manager."""
        config = config_manager.config
        
        properties = {}
        required = []

        # Iterate all custom defined commands from YAML config (ex: emotions, actions)
        for cat_name, category in config.custom_commands.items():
            properties[cat_name] = {
                "type": "string",
                "enum": category.values,
                "description": category.description
            }
            # We enforce that the model always picks an action/emotion state
            required.append(cat_name)

        # Add spoken_response as a required param so the LLM always provides text
        properties["spoken_response"] = {
            "type": "string",
            "description": "Your spoken reply to the user. This is what the agent will say out loud."
        }
        required.append("spoken_response")

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "update_agent_state",
                    "description": "Always call this function with your spoken reply and the agent's updated state.",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            }
        ]
        return tools

    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def generate_response_with_actions(self, prompt: str, system_prompt: Optional[str] = None, history: Optional[list] = None) -> tuple[str, Dict[str, Any]]:
        """Non-streaming call that returns text and parallel tool arguments (JSON)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        # Include conversation history for multi-turn awareness
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        tools = self._build_tools_schema()

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="required"  # Force the model to always call update_agent_state
        )

        message = response.choices[0].message
        spoken_text = message.content or ""
        
        actions = {}
        if message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.function.name == "update_agent_state":
                    args = json.loads(tool_call.function.arguments)
                    # Extract spoken_response from function args if text content is empty
                    if not spoken_text and "spoken_response" in args:
                        spoken_text = args.pop("spoken_response")
                    else:
                        args.pop("spoken_response", None)
                    actions = args

        return spoken_text, actions

class OpenAITTSProvider(BaseTTSProvider):
    """OpenAI TTS streaming provider."""
    def __init__(self, model_name: str = "tts-1", voice: str = "alloy"):
        self.model = model_name
        self.voice = voice
        self.client = OpenAIClientSingleton.get_client()

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        std_log.info(f"🔊 TTS: Starting synthesis | model={self.model} voice={self.voice} text=\"{text[:60]}\"")
        audio_response = await self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="wav"  # WAV allows easier playback in Unity and browsers
        )
        
        # Read the full audio response (.content is sync-safe on the already-resolved response)
        # Note: iter_bytes() returns a SYNC iterator on AsyncOpenAI responses,
        # so 'async for' silently yields nothing. We read .content instead.
        audio_bytes = audio_response.content
        total_size = len(audio_bytes)
        std_log.info(f"✅ TTS: Audio received | size={total_size} bytes ({total_size//1024}KB)")
        
        # Yield in chunks for streaming over ZMQ/WS
        chunk_size = 32 * 1024  # 32KB chunks
        chunk_count = 0
        for i in range(0, total_size, chunk_size):
            chunk_count += 1
            yield audio_bytes[i:i + chunk_size]
        std_log.info(f"📤 TTS: Yielded {chunk_count} chunks to transport")
