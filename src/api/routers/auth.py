"""
Open Virtual Agent Research Platform (OVARP) — Auth Status

A single unauthenticated endpoint so the console can discover whether this
server demands a token before it starts issuing API calls.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from fastapi import APIRouter, Header

from src.api.deps import TOKEN_HEADER, access_token_required, require_console_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def auth_status():
    """Whether a token is required to reach the rest of the API."""
    return {"required": access_token_required(), "header": TOKEN_HEADER}


@router.post("/verify")
async def verify_token(x_ovarp_token: str = Header(default=None)):
    """Check a token before the console stores it for the session."""
    await require_console_token(x_ovarp_token)
    return {"status": "ok"}
