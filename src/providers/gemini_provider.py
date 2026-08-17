"""
Open Virtual Agent Research Platform (OVARP) — Google Gemini Provider

Implements LLM and TTS providers using the Google ``genai`` SDK:
- ``GeminiLLMProvider``: Gemini chat completions with function calling for
  agent actions (emotions, gestures, gaze). Uses a shared singleton client.
- ``GeminiTTSProvider``: Text-to-speech synthesis using ``gemini-2.5-flash-tts``
  with configurable voice presets via the ``generate_content`` API.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
import asyncio
import base64
import json
import struct
import logging
from typing import AsyncGenerator, Dict, Any, Optional
from google import genai
from google.genai import types as genai_types
from structlog import get_logger

from src.providers.base import BaseLLMProvider, BaseTTSProvider
from src.core.config import config_manager

logger = get_logger()
std_log = logging.getLogger("OVARP.gemini")

class GeminiClientSingleton:
    """Manages the shared Gemini client instance."""
    _instance = None
    _client: genai.Client = None

    @classmethod
    def get_client(cls) -> genai.Client:
        if cls._client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                std_log.warning("⚠️ Gemini: GEMINI_API_KEY not found in environment. Provider will be disabled.")
                logger.warning("GEMINI_API_KEY environment variable not set.")
                return None
            
            try:
                cls._client = genai.Client(api_key=api_key)
                std_log.info(f"✅ Gemini: Client initialized successfully (key ends in ...{api_key[-4:]})")
            except ValueError as e:
                std_log.error(f"❌ Gemini: Failed to create client | {str(e)}")
                logger.error("Failed to create Gemini client", error=str(e))
                return None

        return cls._client

    @classmethod
    def reset_client(cls):
        """Drop the cached client so a new API key takes effect."""
        cls._client = None

class GeminiLLMProvider(BaseLLMProvider):
    """Google Gemini Language Model utilizing Native Tool Calling for configuration actions."""
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model = model_name

    @property
    def client(self):
        return GeminiClientSingleton.get_client()

    def _build_tools_schema(self) -> list:
        """Dynamically build Gemini Tool Schema from the config_manager."""
        config = config_manager.config
        
        properties = {}
        required = []

        # Iterate all custom defined commands from YAML config (ex: emotions, actions)
        for cat_name, category in config.custom_commands.items():
            properties[cat_name] = {
                "type": "STRING",
                "enum": category.values,
                "description": category.description
            }
            required.append(cat_name)

        # Add spoken_response as a required param so the LLM always provides text
        properties["spoken_response"] = {
            "type": "STRING",
            "description": "Your spoken reply to the user. This is what the agent will say out loud."
        }
        required.append("spoken_response")

        # Gemini expects the JSON Schema format to be slightly different (OpenAPI 3.0 subset)
        # We define a function declaration
        tool_schema = {
            "function_declarations": [
                {
                    "name": "update_agent_state",
                    "description": "Always call this function with your spoken reply and the agent's updated state.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": properties,
                        "required": required
                    }
                }
            ]
        }
        return [tool_schema]

    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        # Gemini Python SDK doesn't natively support AsyncGenerator out-of-the-box easily without workarounds
        # For the MVP we await the whole stream generation or loop through the blocking sync iterable
        
        config_kwargs = {}
        if system_prompt:
             config_kwargs["system_instruction"] = system_prompt

        response = self.client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(**config_kwargs)
        )
        
        # We yield as strings
        for chunk in response:
            if chunk.text:
                 yield chunk.text

    async def generate_response_with_actions(self, prompt: str, system_prompt: Optional[str] = None, history: Optional[list] = None) -> tuple[str, Dict[str, Any]]:
        """Non-streaming call that returns text and parallel tool arguments (JSON)."""
        if not self.client:
            std_log.error("❌ Gemini: Provider called but client is None (missing API key)")
            logger.error("Gemini Provider called but the client is not initialized (missing API key).")
            return "Server Error: Gemini Provider is unconfigured.", {}

        tools = self._build_tools_schema()
        
        config_kwargs = {
            "tools": tools,
            "temperature": 0.7,
        }
        if system_prompt:
             config_kwargs["system_instruction"] = system_prompt
        
        # Build multi-turn contents from history
        contents = []
        if history:
            for msg in history:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        
        std_log.info(f"🔄 Gemini: Calling API | model={self.model} | prompt=\"{prompt[:80]}\" | history_turns={len(contents)-1}")
             
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=genai.types.GenerateContentConfig(**config_kwargs)
            )
        except Exception as e:
            std_log.error(f"❌ Gemini: API call FAILED | {type(e).__name__}: {str(e)}")
            logger.error("Gemini API call failed", error=str(e))
            return f"API Error: {str(e)}", {}
        
        spoken_text = ""
        actions = {}
        
        # Manually iterate parts to handle mixed text + function_call responses
        # The SDK's response.text property can fail or return empty when function_calls are present
        try:
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        spoken_text += part.text
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        std_log.info(f"⚡ Gemini: Function call detected | name={fc.name} args={fc.args}")
                        if fc.name == "update_agent_state":
                            args = dict(fc.args)
                            # Extract spoken_response from function args if text is empty
                            if not spoken_text and "spoken_response" in args:
                                spoken_text = args.pop("spoken_response")
                            else:
                                args.pop("spoken_response", None)
                            actions = args
            else:
                # Fallback to simple .text if no candidates structure
                spoken_text = response.text or ""
        except Exception as e:
            std_log.warning(f"⚠️ Gemini: Error parsing response parts | {str(e)}")
            try:
                spoken_text = response.text or ""
            except Exception:
                pass
                    
        std_log.info(f"✅ Gemini: Response complete | text=\"{spoken_text[:80]}\" | actions={actions}")
        return spoken_text, actions


def _create_wav_header(sample_rate: int, num_channels: int, sample_width: int, data_size: int) -> bytes:
    """Generates a standard 44-byte WAV header for raw PCM data."""
    header = b'RIFF'
    header += struct.pack('<I', 36 + data_size)
    header += b'WAVE'
    header += b'fmt '
    header += struct.pack('<I', 16) # Subchunk1Size
    header += struct.pack('<H', 1)  # AudioFormat (1=PCM)
    header += struct.pack('<H', num_channels)
    header += struct.pack('<I', sample_rate)
    header += struct.pack('<I', sample_rate * num_channels * sample_width) # ByteRate
    header += struct.pack('<H', num_channels * sample_width) # BlockAlign
    header += struct.pack('<H', sample_width * 8) # BitsPerSample
    header += b'data'
    header += struct.pack('<I', data_size)
    return header

class GeminiTTSProvider(BaseTTSProvider):
    """Gemini TTS provider using the genai SDK with generate_content + AUDIO modality."""
    
    def __init__(self, model_name: str = "gemini-2.5-flash-preview-tts", voice: str = "Kore"):
        self.model = model_name
        self.voice = voice

    @property
    def client(self):
        return GeminiClientSingleton.get_client()
    
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not self.client:
            std_log.error("❌ Gemini TTS: Client not initialized (missing API key)")
            return
        
        std_log.info(f"🔊 Gemini TTS: Starting synthesis | model={self.model} voice={self.voice} text=\"{text[:60]}\"")
        
        try:
            # The preview TTS model can sometimes fail if the prompt isn't clearly
            # framed as a text-to-speech request. We wrap it slightly.
            tts_prompt = f"Repeat exactly this text as audio: {text}"
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=tts_prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=genai_types.SpeechConfig(
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name=self.voice
                            )
                        )
                    )
                )
            )
        except Exception as e:
            std_log.error(f"❌ Gemini TTS: API call failed | {type(e).__name__}: {str(e)}")
            return
        
        # Extract audio data from response
        try:
            audio_data = response.candidates[0].content.parts[0].inline_data
            audio_bytes = audio_data.data  # Raw audio bytes
            mime_type = audio_data.mime_type  # e.g. "audio/wav" or "audio/L16;codec=pcm;rate=24000"
            
            total_size = len(audio_bytes)
            std_log.info(f"✅ Gemini TTS: Audio received | size={total_size} bytes ({total_size//1024}KB) mime={mime_type}")
            
            # If it's pure L16 PCM without a RIFF header, we MUST prepend one so browsers can play it
            if mime_type.startswith("audio/L16") and not audio_bytes.startswith(b'RIFF'):
                # Default for Gemini L16 is 24kHz, mono, 16-bit
                wav_header = _create_wav_header(sample_rate=24000, num_channels=1, sample_width=2, data_size=total_size)
                yield wav_header
            
            # Yield in chunks for streaming over ZMQ/WS
            chunk_size = 32 * 1024  # 32KB chunks
            chunk_count = 0
            for i in range(0, total_size, chunk_size):
                chunk_count += 1
                yield audio_bytes[i:i + chunk_size]
            
            std_log.info(f"📤 Gemini TTS: Yielded {chunk_count} chunks to transport")
        except (IndexError, AttributeError) as e:
            std_log.error(f"❌ Gemini TTS: Failed to parse audio response | {type(e).__name__}: {str(e)}")

