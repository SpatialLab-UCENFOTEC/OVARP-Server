"""
Open Virtual Agent Research Platform (OVARP) — Custom Provider

Generic provider implementations for any OpenAI-compatible API endpoint.
Lets users register Ollama, LM Studio, vLLM, LocalAI, or any custom
service that exposes an OpenAI-compatible ``/v1/chat/completions`` or
``/v1/audio/speech`` endpoint.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import json
import logging
from typing import AsyncGenerator, Dict, Any, Optional
from openai import AsyncOpenAI
from structlog import get_logger

from src.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider
from src.core.config import config_manager

logger = get_logger()
std_log = logging.getLogger("OVARP.custom")


class CustomLLMProvider(BaseLLMProvider):
    """
    OpenAI-compatible LLM provider with configurable base_url.

    Works with Ollama, LM Studio, vLLM, LocalAI, text-generation-webui,
    or any server that speaks the OpenAI chat completions protocol.
    Gracefully falls back to plain text when function calling is not
    supported by the remote model.
    """

    def __init__(self, name: str, base_url: str, model: str, api_key: str = ""):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Many local services don't need a key, but the SDK validates it isn't empty
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=api_key or "not-needed"
        )
        std_log.info(f"🔌 Custom LLM '{name}' registered | url={self.base_url} model={model}")

    def _build_tools_schema(self) -> list[Dict[str, Any]]:
        """Build the same tools schema the OpenAI provider uses."""
        config = config_manager.config

        properties = {}
        required = []

        for cat_name, category in config.custom_commands.items():
            properties[cat_name] = {
                "type": "string",
                "enum": category.values,
                "description": category.description
            }
            required.append(cat_name)

        properties["spoken_response"] = {
            "type": "string",
            "description": "Your spoken reply to the user. This is what the agent will say out loud."
        }
        required.append("spoken_response")

        return [{
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
        }]

    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            std_log.error(f"❌ Custom LLM '{self.name}': Streaming failed | {type(e).__name__}: {e}")
            yield f"[Error: {e}]"

    async def generate_response_with_actions(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[list] = None
    ) -> tuple[str, Dict[str, Any]]:
        """
        Tries function calling first. If the endpoint doesn't support it,
        falls back to a plain completion and returns empty actions.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        # Attempt 1: with function calling
        try:
            tools = self._build_tools_schema()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="required"
            )

            message = response.choices[0].message
            spoken_text = message.content or ""
            actions = {}

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "update_agent_state":
                        args = json.loads(tool_call.function.arguments)
                        if not spoken_text and "spoken_response" in args:
                            spoken_text = args.pop("spoken_response")
                        else:
                            args.pop("spoken_response", None)
                        actions = args

            std_log.info(f"✅ Custom LLM '{self.name}': Response (tools) | text=\"{spoken_text[:60]}\" actions={actions}")
            return spoken_text, actions

        except Exception as tool_err:
            std_log.warning(
                f"⚠️ Custom LLM '{self.name}': Function calling not supported, falling back to plain chat | {tool_err}"
            )

        # Attempt 2: plain completion without tools
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            spoken_text = response.choices[0].message.content or ""
            std_log.info(f"✅ Custom LLM '{self.name}': Response (plain) | text=\"{spoken_text[:60]}\"")
            return spoken_text, {}

        except Exception as e:
            std_log.error(f"❌ Custom LLM '{self.name}': Plain completion also failed | {type(e).__name__}: {e}")
            return f"Error from {self.name}: {e}", {}


class CustomTTSProvider(BaseTTSProvider):
    """
    OpenAI-compatible TTS provider with configurable base_url.

    Works with any service that implements the ``/v1/audio/speech`` endpoint
    (e.g., LocalAI, some OpenAI proxy servers).
    """

    def __init__(self, name: str, base_url: str, model: str, api_key: str = "", voice: str = "alloy"):
        self.name = name
        self.model = model
        self.voice = voice
        self.base_url = base_url.rstrip("/")
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=api_key or "not-needed"
        )
        std_log.info(f"🔌 Custom TTS '{name}' registered | url={self.base_url} model={model}")

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        std_log.info(f"🔊 Custom TTS '{self.name}': Synthesis | model={self.model} voice={self.voice} text=\"{text[:60]}\"")
        try:
            audio_response = await self.client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="wav"
            )

            audio_bytes = audio_response.content
            total_size = len(audio_bytes)
            std_log.info(f"✅ Custom TTS '{self.name}': Audio received | size={total_size} bytes ({total_size // 1024}KB)")

            chunk_size = 32 * 1024
            for i in range(0, total_size, chunk_size):
                yield audio_bytes[i:i + chunk_size]

        except Exception as e:
            std_log.error(f"❌ Custom TTS '{self.name}': Synthesis failed | {type(e).__name__}: {e}")


async def test_custom_endpoint(base_url: str, api_key: str = "", model: str = "") -> dict:
    """
    Quick health check for an OpenAI-compatible endpoint.
    Tries /v1/models first, then a minimal chat completion.
    Returns {"ok": True/False, "detail": "..."}.
    """
    client = AsyncOpenAI(base_url=base_url.rstrip("/"), api_key=api_key or "not-needed")

    # Try listing models (most compatible endpoints support this)
    try:
        models = await client.models.list()
        model_ids = [m.id for m in models.data[:5]]
        return {"ok": True, "detail": f"Connected. Available models: {', '.join(model_ids)}"}
    except Exception as model_err:
        std_log.warning(f"⚠️ /models endpoint failed for {base_url}: {model_err}")

    # Fall back to a minimal completion to test reachability
    if model:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=5
            )
            text = resp.choices[0].message.content or "(empty)"
            return {"ok": True, "detail": f"Connected. Test response: {text}"}
        except Exception as chat_err:
            return {"ok": False, "detail": f"Could not reach endpoint: {chat_err}"}

    return {"ok": False, "detail": f"Could not list models at {base_url}"}
