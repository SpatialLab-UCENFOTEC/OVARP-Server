"""
Open Virtual Agent Research Platform (OVARP) — Provider Key Store

Holds the built-in provider credentials the console can edit at runtime.
Values live in ``provider_keys.yaml`` encrypted through :mod:`src.core.secrets`
and are mirrored into ``os.environ`` so the provider singletons pick them up.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import logging
import os
from pathlib import Path

import yaml

from src.core.secrets import ENCRYPTED_PREFIX, protect, reveal

std_log = logging.getLogger("OVARP.keys")

KEY_STORE_FILE = Path(__file__).resolve().parent.parent.parent / "provider_keys.yaml"

TRACKED_KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "ELEVENLABS_API_KEY")

# Accepts either the provider id the console sends or the raw env var name.
PROVIDER_ALIASES = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}

MASK_VISIBLE_CHARS = 4


def resolve_key_name(name: str) -> str:
    """Map a provider id ('openai') or env var name onto the tracked env var."""
    return PROVIDER_ALIASES.get(name, name)


def _read_store() -> dict:
    if not KEY_STORE_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(KEY_STORE_FILE.read_text(encoding="utf-8")) or {}
        return data.get("keys", {})
    except Exception as e:
        std_log.warning(f"⚠️ Could not read {KEY_STORE_FILE.name}: {e}")
        return {}


def _write_store(stored: dict):
    KEY_STORE_FILE.write_text(
        yaml.dump({"keys": stored}, default_flow_style=False, sort_keys=True),
        encoding="utf-8",
    )


def _reset_provider_clients():
    """Drop cached SDK clients so the next call authenticates with the new key."""
    from src.providers.gemini_provider import GeminiClientSingleton
    from src.providers.openai_provider import OpenAIClientSingleton

    OpenAIClientSingleton.reset_client()
    GeminiClientSingleton.reset_client()


def apply_to_environment(key_name: str, value: str):
    """Put a key into the process environment, or take it out when cleared."""
    if value:
        os.environ[key_name] = value
    else:
        os.environ.pop(key_name, None)


def load_stored_keys():
    """Restore saved credentials into the environment on boot.

    A stored key wins over ``.env``: it is what the researcher set last, from
    the console, and they expect it to survive a restart.
    """
    stored = _read_store()
    restored = 0
    for key_name, raw in stored.items():
        value = reveal(raw)
        if value:
            apply_to_environment(key_name, value)
            restored += 1
    if restored:
        _reset_provider_clients()
        std_log.info(f"🔑 Restored {restored} provider key(s) from {KEY_STORE_FILE.name}")


def set_keys(updates: dict, persist: bool = False) -> dict:
    """Apply key updates in memory and, when asked, to the encrypted store.

    An empty value clears the key from both. Returns the resolved env var names.
    """
    resolved = {resolve_key_name(name): value or "" for name, value in updates.items()}

    for key_name, value in resolved.items():
        apply_to_environment(key_name, value)

    if persist and resolved:
        stored = _read_store()
        for key_name, value in resolved.items():
            if value:
                stored[key_name] = protect(value)
            else:
                stored.pop(key_name, None)
        _write_store(stored)

    _reset_provider_clients()
    return resolved


def mask(value: str) -> str:
    """Render a credential for display without giving it away."""
    if not value:
        return ""
    if len(value) <= MASK_VISIBLE_CHARS * 2:
        return "***"
    return f"{value[:MASK_VISIBLE_CHARS]}...{value[-MASK_VISIBLE_CHARS:]}"


def key_status(key_name: str) -> dict:
    """Describe one credential: whether it is set, where it lives, how it shows."""
    value = os.getenv(key_name, "")
    stored_raw = _read_store().get(key_name, "")
    is_set = bool(value)
    is_stored = bool(stored_raw)
    is_encrypted = stored_raw.startswith(ENCRYPTED_PREFIX)

    if is_stored and is_encrypted:
        badge, state = "[SAVED, ENCRYPTED]", "encrypted"
    elif is_stored:
        badge, state = "[SAVED, PLAIN TEXT]", "plaintext"
    elif is_set:
        badge, state = "[IN MEMORY ONLY]", "memory_only"
    else:
        badge, state = "[NOT CONFIGURED]", "unconfigured"

    return {
        "key_name": key_name,
        "is_set": is_set,
        "masked_key": mask(value),
        "persisted": is_stored,
        "encrypted": is_encrypted,
        "badge": badge,
        "storage_state": state,
    }


def all_key_status() -> dict:
    """Status for every credential the console offers to manage."""
    return {name: key_status(name) for name in TRACKED_KEYS}


def read_key(key_name: str) -> str:
    """The raw credential, for the console's explicit reveal action only."""
    return os.getenv(key_name, "")
