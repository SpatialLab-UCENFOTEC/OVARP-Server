"""
Open Virtual Agent Research Platform (OVARP) — Google Gemini Provider

Implements LLM and TTS providers using the Google ``genai`` SDK:
- ``GeminiLLMProvider``: Gemini chat completions with function calling for
  agent actions (emotions, gestures, gaze). Uses a shared singleton client.
  ``stream_reply`` + ``extract_actions`` add real incremental text streaming
  (Gemini-only): forcing the actions tool call blocks streaming, so the spoken
  reply streams on its own and actions are classified in a lean follow-up call.
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
import threading
from typing import AsyncGenerator, Dict, Any, Optional
from google import genai
from google.genai import types as genai_types
from structlog import get_logger

from src.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider
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

class GeminiLLMProvider(BaseLLMProvider):
    """Google Gemini Language Model utilizing Native Tool Calling for configuration actions."""

    # Condition prompts (config.yaml) tell the model to "Always call the
    # update_agent_state function..."; stream_reply doesn't declare that tool, so this
    # cancels the instruction for the streaming call only. See stream_reply's docstring.
    _NO_FUNCTION_CALL_OVERRIDE = (
        "\nFor this reply, respond with plain spoken text only. Do not call any function or tool."
    )

    def __init__(self, model_name: str = None):
        # A dated id goes stale: gemini-2.5-flash is already refused for new
        # accounts. The rolling alias keeps working; the env var is the override.
        self.model = model_name or os.getenv("OVARP_GEMINI_LLM_MODEL", "gemini-flash-latest")
        self.client = GeminiClientSingleton.get_client()

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

    def _build_actions_only_tools_schema(self) -> list:
        """Same shape as ``_build_tools_schema`` but without ``spoken_response``:
        used by ``extract_actions`` to classify a reply that was already generated,
        instead of asking the model to write it again."""
        config = config_manager.config
        properties = {}
        required = []
        for cat_name, category in config.custom_commands.items():
            properties[cat_name] = {
                "type": "STRING",
                "enum": category.values,
                "description": category.description
            }
            required.append(cat_name)
        return [{
            "function_declarations": [
                {
                    "name": "update_agent_state",
                    "description": "Classify the agent's state (emotion/action) for the reply you just gave.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": properties,
                        "required": required
                    }
                }
            ]
        }]

    def _stream_text_sync_to_queue(self, contents: list, config_kwargs: dict, loop: asyncio.AbstractEventLoop,
                                    queue: "asyncio.Queue") -> None:
        """Runs in a worker thread so the blocking network iteration of
        ``generate_content_stream`` doesn't stall the asyncio event loop (which also
        has to keep serving other connected WS/ZMQ clients while this one streams).
        Pushes each text delta, then a sentinel or the exception, back via
        ``call_soon_threadsafe``."""
        SENTINEL = None
        try:
            stream = self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
            for chunk in stream:
                if chunk.text:
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.text)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    async def stream_reply(self, prompt: str, system_prompt: Optional[str] = None,
                            history: Optional[list] = None) -> AsyncGenerator[str, None]:
        """Real, incremental text streaming of the spoken reply.

        Deliberately does NOT force the ``update_agent_state`` tool call here: measured
        2026-08-31 against the live API that with ``tools`` set, ``generate_content_stream``
        buffers the whole function call and delivers it in a single chunk (no incremental
        text/args) -- the SDK's own ``partial_args``/``will_continue`` fields exist for this
        but raise "only supported in Gemini Enterprise Agent" on the plain API key we have.
        So actions can't ride along with a streamed reply; ``extract_actions`` below resolves
        them in a lean follow-up call once the full text is known.

        This project's condition prompts (config.yaml) instruct "Always call the
        update_agent_state function with your spoken reply..." -- measured live
        2026-08-31: with that instruction and no tool declared, Gemini tries to emit a
        function call anyway and returns FinishReason.MALFORMED_FUNCTION_CALL with empty
        text, silently producing an empty reply. ``_NO_FUNCTION_CALL_OVERRIDE`` cancels
        that instruction for this call only.
        """
        if not self.client:
            std_log.error("❌ Gemini: stream_reply called but client is None (missing API key)")
            return

        contents = []
        if history:
            for msg in history:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        config_kwargs = {"temperature": 0.7}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt + self._NO_FUNCTION_CALL_OVERRIDE

        std_log.info(f"🔄 Gemini: Streaming text call | model={self.model} | prompt=\"{prompt[:80]}\" | history_turns={len(contents)-1}")

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        worker = threading.Thread(
            target=self._stream_text_sync_to_queue,
            args=(contents, config_kwargs, loop, queue),
            daemon=True,
        )
        worker.start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                std_log.error(f"❌ Gemini: Streaming text call FAILED | {type(item).__name__}: {str(item)}")
                return
            yield item

    async def extract_actions(self, spoken_text: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Lean follow-up call: given a reply that was already generated (and already
        streamed to the client), classify the agent's state (emotion/action enums from
        config.yaml) without regenerating the text. Skipped entirely if no custom
        commands are configured, since there would be nothing to classify."""
        if not self.client or not spoken_text:
            return {}

        tools = self._build_actions_only_tools_schema()
        if not tools[0]["function_declarations"][0]["parameters"]["properties"]:
            return {}

        config_kwargs = {"tools": tools, "temperature": 0.3}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        classify_prompt = (
            f"You just replied with the following text to the user:\n\"{spoken_text}\"\n\n"
            "Call update_agent_state to classify your emotional/physical state for that reply. "
            "Do not repeat or alter the text."
        )

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=[{"role": "user", "parts": [{"text": classify_prompt}]}],
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as e:
            std_log.warning(f"⚠️ Gemini: extract_actions call failed | {type(e).__name__}: {str(e)}")
            return {}

        try:
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and fc.name == "update_agent_state":
                        return dict(fc.args)
        except Exception as e:
            std_log.warning(f"⚠️ Gemini: Error parsing extract_actions response | {str(e)}")
        return {}


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

class GeminiSTTProvider(BaseSTTProvider):
    """Gemini transcription via generate_content with inline audio.

    Gemini has no dedicated transcription endpoint; audio goes in as an inline
    part alongside an instruction, and the reply is the transcript.
    """

    def __init__(self, model_name: str = None):
        self.model = model_name or os.getenv("OVARP_GEMINI_STT_MODEL", "gemini-flash-latest")
        self.client = GeminiClientSingleton.get_client()

    async def transcribe(self, audio_data: bytes) -> str:
        if not self.client:
            std_log.error("❌ Gemini STT: Client not initialized (missing API key)")
            return ""

        std_log.info(f"🎤 Gemini STT: Starting transcription | audio_size={len(audio_data)} bytes")
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=[
                    genai_types.Part.from_bytes(data=audio_data, mime_type="audio/wav"),
                    "Transcribe this audio verbatim. Reply with the transcript only, "
                    "with no preamble and no quotation marks. If there is no speech, reply "
                    "with nothing at all.",
                ],
            )
            text = (response.text or "").strip()
            std_log.info(f"✅ Gemini STT: Transcription complete | text=\"{text[:80]}\"")
            return text
        except Exception as e:
            std_log.error(f"❌ Gemini STT: Transcription failed | {type(e).__name__}: {str(e)}")
            logger.error("Gemini STT transcription failed", error=str(e))
            return ""


class GeminiTTSProvider(BaseTTSProvider):
    """Gemini TTS provider using the genai SDK with generate_content + AUDIO modality.

    Uses ``generate_content_stream`` instead of a single blocking ``generate_content``
    call: on the preview TTS models, the response is generated and transferred
    incrementally, so the full audio arrives measurably sooner than waiting for one
    blocking call to return everything at once (measured 2026-08-31, same input text,
    gemini-3.1-flash-tts-preview: 9.7s blocking vs 6.4s via the stream, first bytes at
    0.9s). We still buffer chunks server-side before forwarding, so the exact WAV
    ``data`` size is known upfront and the transport/wire format to the client is
    unchanged; only the retrieval from the Gemini API is faster.
    """

    def __init__(self, model_name: str = None, voice: str = "Kore"):
        self.model = model_name or os.getenv(
            "OVARP_GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview"
        )
        self.voice = voice
        self.client = GeminiClientSingleton.get_client()

    def _collect_stream(self, tts_prompt: str) -> tuple[bytes, Optional[str]]:
        """Runs synchronously in a worker thread: consumes the streaming response
        and returns the fully assembled audio bytes plus the mime type of the
        first audio part seen."""
        audio_bytes = bytearray()
        mime_type = None
        stream = self.client.models.generate_content_stream(
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
                ),
            ),
        )
        for chunk in stream:
            try:
                parts = chunk.candidates[0].content.parts
            except (AttributeError, IndexError, TypeError):
                continue
            if not parts:
                continue
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    audio_bytes.extend(inline.data)
                    if mime_type is None:
                        mime_type = inline.mime_type
        return bytes(audio_bytes), mime_type

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not self.client:
            std_log.error("❌ Gemini TTS: Client not initialized (missing API key)")
            return

        std_log.info(f"🔊 Gemini TTS: Starting synthesis | model={self.model} voice={self.voice} text=\"{text[:60]}\"")

        try:
            # The preview TTS model can sometimes fail if the prompt isn't clearly
            # framed as a text-to-speech request. We wrap it slightly.
            tts_prompt = f"Repeat exactly this text as audio: {text}"
            audio_bytes, mime_type = await asyncio.to_thread(self._collect_stream, tts_prompt)
        except Exception as e:
            std_log.error(f"❌ Gemini TTS: API call failed | {type(e).__name__}: {str(e)}")
            return

        if not audio_bytes or not mime_type:
            std_log.error("❌ Gemini TTS: Stream returned no audio data")
            return

        total_size = len(audio_bytes)
        std_log.info(f"✅ Gemini TTS: Audio received | size={total_size} bytes ({total_size//1024}KB) mime={mime_type}")

        # If it's pure L16 PCM without a RIFF header, we MUST prepend one so browsers
        # can play it. Mime casing has varied between model versions ("audio/L16" vs
        # "audio/l16"), so match case-insensitively.
        if mime_type.lower().startswith("audio/l16") and not audio_bytes.startswith(b'RIFF'):
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

