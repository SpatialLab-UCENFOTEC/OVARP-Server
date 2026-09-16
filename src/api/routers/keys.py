"""
Open Virtual Agent Research Platform (OVARP) — API Key Store Routes

Lets a researcher configure the built-in provider credentials from the console
instead of editing ``.env`` and restarting. Saving encrypts through
:mod:`src.core.key_store`; the raw value only leaves the server on an explicit
reveal.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core import key_store

router = APIRouter(prefix="/api/keys", tags=["keys"])


class KeyUpdateRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    keys: dict[str, str] | None = None
    persist: bool = False


class KeyRevealRequest(BaseModel):
    key_name: str


def _collect_updates(provider: str | None, api_key: str | None,
                     keys: dict[str, str] | None) -> dict:
    """Accept either a single provider/api_key pair or a batch of named keys."""
    updates = {}
    if provider and api_key is not None:
        updates[provider] = api_key
    if keys:
        updates.update(keys)
    return updates


@router.get("/status")
async def get_keys_status():
    """Where each tracked credential stands: set, saved, encrypted."""
    return {"status": "ok", "keys": key_store.all_key_status()}


@router.post("/update")
async def update_api_keys(req: KeyUpdateRequest):
    """Apply keys to the running server, and save them when ``persist`` is set.

    An empty ``api_key`` clears the credential from memory and from the store.
    """
    updates = _collect_updates(req.provider, req.api_key, req.keys)
    if not updates:
        raise HTTPException(status_code=400, detail="No key supplied")

    resolved = key_store.set_keys(updates, persist=req.persist)
    statuses = key_store.all_key_status()
    first = next(iter(resolved))
    return {
        "status": "ok",
        "badge": statuses[first]["badge"] if first in statuses else "[IN MEMORY ONLY]",
        "keys": statuses,
    }


@router.post("/persist")
async def persist_api_keys(req: KeyUpdateRequest):
    """Write the supplied keys, or everything currently in memory, to the store."""
    updates = _collect_updates(req.provider, req.api_key, req.keys)
    if not updates:
        updates = {
            name: key_store.read_key(name)
            for name in key_store.TRACKED_KEYS
            if key_store.read_key(name)
        }
    if not updates:
        raise HTTPException(status_code=400, detail="No keys to persist")

    key_store.set_keys(updates, persist=True)
    return {"status": "ok", "keys": key_store.all_key_status()}


@router.post("/reveal")
async def reveal_api_key(req: KeyRevealRequest):
    """Return one credential in the clear, for the console's Show toggle.

    Deliberately not part of ``/status``: the console polls that, and a key a
    researcher never asked to see should not ride along on every poll.
    """
    key_name = key_store.resolve_key_name(req.key_name)
    if key_name not in key_store.TRACKED_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown key '{req.key_name}'")
    return {"key_name": key_name, "api_key": key_store.read_key(key_name)}
