"""
Open Virtual Agent Research Platform (OVARP) — Custom Provider Routes

Registration, listing, connectivity testing and removal of OpenAI-compatible
endpoints (Ollama, LM Studio, vLLM, ...). The registry is persisted to
``custom_providers.yaml`` so registrations survive a restart.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

from src.core.runtime import runtime
from src.core.secrets import protect, redact, reveal
from src.providers.custom_provider import (
    CustomLLMProvider,
    CustomTTSProvider,
    test_custom_endpoint,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])

CUSTOM_PROVIDERS_FILE = Path(__file__).resolve().parents[3] / "custom_providers.yaml"

BUILTIN_PROVIDERS = ("openai", "gemini")


def _read_custom_registry() -> dict:
    """Read the current registry from disk."""
    if not CUSTOM_PROVIDERS_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(CUSTOM_PROVIDERS_FILE.read_text(encoding="utf-8")) or {}
        return data.get("providers", {})
    except Exception:
        return {}


def _save_custom_providers(registry: dict):
    """Persist the custom providers registry to YAML."""
    CUSTOM_PROVIDERS_FILE.write_text(
        yaml.dump({"providers": registry}, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def load_custom_providers():
    """Load custom providers from YAML on boot."""
    if not CUSTOM_PROVIDERS_FILE.exists():
        return
    try:
        data = yaml.safe_load(CUSTOM_PROVIDERS_FILE.read_text(encoding="utf-8")) or {}
        providers = data.get("providers", {})
        for name, cfg in providers.items():
            base_url = cfg.get("base_url", "")
            api_key = reveal(cfg.get("api_key", ""))
            model = cfg.get("model", "")
            types = cfg.get("types", [])
            if "llm" in types:
                runtime.orchestrator.register_provider(
                    name, CustomLLMProvider(name, base_url, model, api_key), "llm"
                )
            if "tts" in types:
                runtime.orchestrator.register_provider(
                    name, CustomTTSProvider(name, base_url, model, api_key), "tts"
                )
        logging.getLogger("OVARP.custom").info(
            f"🔌 Loaded {len(providers)} custom provider(s) from {CUSTOM_PROVIDERS_FILE.name}"
        )
    except Exception as e:
        logging.getLogger("OVARP.custom").warning(f"⚠️ Could not load custom providers: {e}")


class ProviderRegisterRequest(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    model: str
    types: list[str]  # ["llm"], ["tts"], or ["llm", "tts"]


@router.get("")
async def list_providers():
    """List all registered providers (built-in + custom)."""
    return {
        "builtin": list(BUILTIN_PROVIDERS),
        "custom": redact(_read_custom_registry()),
        "available_llm": list(runtime.orchestrator.llm_providers.keys()),
        "available_tts": list(runtime.orchestrator.tts_providers.keys()),
        "active_llm": runtime.orchestrator.active_llm_id,
    }


@router.post("/register")
async def register_provider(req: ProviderRegisterRequest):
    """Register a new custom OpenAI-compatible provider."""
    name = req.name.strip().lower().replace(" ", "-")
    if name in BUILTIN_PROVIDERS:
        return {"error": "Cannot overwrite built-in providers."}

    if "llm" in req.types:
        runtime.orchestrator.register_provider(
            name, CustomLLMProvider(name, req.base_url, req.model, req.api_key), "llm"
        )
    if "tts" in req.types:
        runtime.orchestrator.register_provider(
            name, CustomTTSProvider(name, req.base_url, req.model, req.api_key), "tts"
        )

    registry = _read_custom_registry()
    registry[name] = {
        "base_url": req.base_url,
        "api_key": protect(req.api_key),
        "model": req.model,
        "types": req.types,
    }
    _save_custom_providers(registry)

    return {
        "status": "ok",
        "name": name,
        "available_llm": list(runtime.orchestrator.llm_providers.keys()),
        "available_tts": list(runtime.orchestrator.tts_providers.keys()),
    }


@router.delete("/{name}")
async def unregister_provider_endpoint(name: str):
    """Remove a custom provider."""
    removed = runtime.orchestrator.unregister_provider(name)
    if not removed:
        return {"error": f"Provider '{name}' not found or is built-in."}

    registry = _read_custom_registry()
    registry.pop(name, None)
    _save_custom_providers(registry)

    return {
        "status": "ok",
        "available_llm": list(runtime.orchestrator.llm_providers.keys()),
        "available_tts": list(runtime.orchestrator.tts_providers.keys()),
    }


@router.post("/{name}/test")
async def test_provider_endpoint(name: str):
    """Test connectivity to a custom provider's base_url."""
    registry = _read_custom_registry()
    cfg = registry.get(name)
    if not cfg:
        return {"ok": False, "detail": f"Provider '{name}' not found in registry."}
    return await test_custom_endpoint(
        cfg["base_url"], reveal(cfg.get("api_key", "")), cfg.get("model", "")
    )


class ProviderTestRequest(BaseModel):
    base_url: str
    api_key: str = ""
    model: str = ""


@router.post("/test")
async def test_provider_url(req: ProviderTestRequest):
    """Test connectivity to any OpenAI-compatible endpoint (before registering)."""
    return await test_custom_endpoint(req.base_url, req.api_key, req.model)
