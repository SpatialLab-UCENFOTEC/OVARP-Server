"""
Open Virtual Agent Research Platform (OVARP) — LLM and TTS Routes

Runtime configuration of the dialog pipeline: active LLM provider, system
prompt, TTS provider and voice, plus provider health checks.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.runtime import runtime

router = APIRouter(prefix="/api", tags=["llm"])


class LLMConfigUpdate(BaseModel):
    provider_id: str | None = None
    system_prompt: str | None = None
    agent_id: str | None = None  # None edits the global default prompt


def _agents_overriding_global() -> list[dict]:
    """Agents whose applied profile makes them ignore the global system prompt.

    The console needs this to stop presenting the global prompt as if it were
    in effect everywhere: an agent with a profile reads its own composed prompt,
    so editing the global one silently does nothing for it.
    """
    orchestrator = runtime.orchestrator
    overriding = []
    for agent in runtime.config_manager.config.agents:
        info = orchestrator.get_agent_info(agent.id)
        if info.get("has_custom_prompt"):
            overriding.append({
                "agent_id": agent.id,
                "name": agent.name,
                "profile_id": info.get("profile_id"),
            })
    return overriding


@router.get("/llm/config")
async def get_llm_config():
    """Returns the current active LLM state"""
    orchestrator = runtime.orchestrator
    return {
        "active_provider": orchestrator.active_llm_id,
        "available_providers": list(orchestrator.llm_providers.keys()),
        "active_tts_provider": orchestrator.active_tts_id,
        "available_tts_providers": list(orchestrator.tts_providers.keys()),
        "active_stt_provider": orchestrator.active_stt_id,
        "available_stt_providers": list(orchestrator.stt_providers.keys()),
        "system_prompt": orchestrator.system_prompt,
        "tts_enabled": orchestrator.tts_enabled,
        "agents_overriding_global": _agents_overriding_global(),
    }


@router.post("/llm/config")
async def set_llm_config(update: LLMConfigUpdate):
    """Dynamically updates the Orchestrator without restarting.

    With ``agent_id`` the prompt is stored on that agent, which is the same slot
    an applied profile writes to. Without it the global default is edited, and
    the response reports which agents will not see the change.
    """
    orchestrator = runtime.orchestrator
    if update.provider_id:
        orchestrator.set_active_llm(update.provider_id)
    if update.system_prompt:
        orchestrator.set_system_prompt(update.system_prompt, agent_id=update.agent_id)

    return {
        "active_provider": orchestrator.active_llm_id,
        "active_tts_provider": orchestrator.active_tts_id,
        "system_prompt": orchestrator.system_prompt,
        "tts_enabled": orchestrator.tts_enabled,
        "agent_id": update.agent_id,
        "agents_overriding_global": _agents_overriding_global(),
    }


@router.post("/llm/tts")
async def toggle_tts():
    """Toggles TTS audio generation on/off"""
    runtime.orchestrator.tts_enabled = not runtime.orchestrator.tts_enabled
    return {"tts_enabled": runtime.orchestrator.tts_enabled}


@router.get("/tts/voices")
async def get_tts_voices():
    """Returns available TTS voices for the active provider, including gender metadata."""
    return runtime.orchestrator.get_tts_config()


class TtsVoiceUpdate(BaseModel):
    voice_id: str


@router.post("/tts/voice")
async def set_tts_voice(update: TtsVoiceUpdate):
    """Switch the active TTS voice at runtime."""
    runtime.orchestrator.set_tts_voice(update.voice_id)
    return runtime.orchestrator.get_tts_config()


class TtsProviderUpdate(BaseModel):
    provider_id: str


@router.post("/tts/provider")
async def set_tts_provider(update: TtsProviderUpdate):
    """Switch the TTS provider independently of the LLM provider."""
    success = runtime.orchestrator.set_active_tts(update.provider_id)
    if not success:
        return {"error": f"Unknown TTS provider '{update.provider_id}'"}
    return runtime.orchestrator.get_tts_config()


class SttProviderUpdate(BaseModel):
    provider_id: str


@router.get("/stt/provider")
async def get_stt_provider():
    """Which provider transcribes audio arriving from clients."""
    return {
        "provider": runtime.orchestrator.active_stt_id,
        "available": list(runtime.orchestrator.stt_providers.keys()),
    }


@router.post("/stt/provider")
async def set_stt_provider(update: SttProviderUpdate):
    """Switch the transcription provider, independently of LLM and TTS."""
    if not runtime.orchestrator.set_active_stt(update.provider_id):
        return {"error": f"Unknown STT provider '{update.provider_id}'"}
    return {
        "provider": runtime.orchestrator.active_stt_id,
        "available": list(runtime.orchestrator.stt_providers.keys()),
    }


@router.post("/llm/history/clear")
async def clear_history():
    """Clears the conversation memory"""
    runtime.orchestrator.clear_history()
    return {"status": "ok", "message": "Conversation history cleared"}


@router.get("/health/providers")
async def check_provider_health():
    """Validates API key connectivity for each registered provider dynamically."""
    orchestrator = runtime.orchestrator
    results = {}
    for name in orchestrator.llm_providers:
        try:
            if name == "openai":
                from src.providers.openai_provider import OpenAIClientSingleton
                client = OpenAIClientSingleton.get_client()
                await client.models.list()
                results[name] = "ok"
            elif name == "gemini":
                from src.providers.gemini_provider import GeminiClientSingleton
                client = GeminiClientSingleton.get_client()
                if client is None:
                    raise ValueError("GEMINI_API_KEY not set")
                await asyncio.to_thread(client.models.list)
                results[name] = "ok"
            else:
                # Custom / third-party providers — test via their base_url
                provider = orchestrator.llm_providers[name]
                if hasattr(provider, "base_url"):
                    from src.providers.custom_provider import test_custom_endpoint
                    ok, _ = await test_custom_endpoint(
                        provider.base_url,
                        getattr(provider, "api_key", ""),
                        getattr(provider, "model", ""),
                    )
                    results[name] = "ok" if ok else "error"
                else:
                    results[name] = "ok"  # No way to test, assume ok
        except Exception as e:
            results[name] = "error"
            results[f"{name}_error"] = str(e)[:120]
    return results
