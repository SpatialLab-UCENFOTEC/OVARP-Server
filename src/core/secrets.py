"""
Open Virtual Agent Research Platform (OVARP) — Secret Handling

Encrypts provider credentials at rest and keeps them out of API responses.
Encryption is opt-in: set ``OVARP_SECRET_KEY`` in the environment and stored
keys become ciphertext. Without it the registry keeps working in plain text so
an existing local setup does not break on upgrade.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

std_log = logging.getLogger("OVARP.secrets")

ENCRYPTED_PREFIX = "enc:"


def _cipher() -> Fernet | None:
    """Build the cipher from OVARP_SECRET_KEY, or None when it is not configured."""
    secret = os.getenv("OVARP_SECRET_KEY")
    if not secret:
        return None
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def protect(value: str) -> str:
    """Encrypt a credential for storage. Returns it unchanged if no key is set."""
    if not value:
        return value
    if value.startswith(ENCRYPTED_PREFIX):
        return value  # already protected

    cipher = _cipher()
    if cipher is None:
        std_log.warning(
            "⚠️ OVARP_SECRET_KEY not set — provider API key stored in plain text."
        )
        return value
    return ENCRYPTED_PREFIX + cipher.encrypt(value.encode("utf-8")).decode("utf-8")


def reveal(value: str) -> str:
    """Decrypt a stored credential for use. Plain-text values pass through."""
    if not value or not value.startswith(ENCRYPTED_PREFIX):
        return value

    cipher = _cipher()
    if cipher is None:
        std_log.error(
            "❌ Stored credential is encrypted but OVARP_SECRET_KEY is not set. "
            "Restore the key or re-register the provider."
        )
        return ""
    try:
        return cipher.decrypt(value[len(ENCRYPTED_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        std_log.error("❌ Could not decrypt a stored credential — wrong OVARP_SECRET_KEY?")
        return ""


def redact(registry: dict) -> dict:
    """Strip credentials out of a provider registry before it leaves the server.

    Callers only ever need to know whether a key is on file, never its value —
    the registry used to travel to the browser verbatim.
    """
    return {
        name: {
            **{k: v for k, v in cfg.items() if k != "api_key"},
            "has_key": bool(cfg.get("api_key")),
        }
        for name, cfg in registry.items()
    }
