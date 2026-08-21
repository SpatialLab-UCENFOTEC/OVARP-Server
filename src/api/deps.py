"""
Open Virtual Agent Research Platform (OVARP) — Request Dependencies

Access control for the researcher-facing API. Authentication is opt-in: with no
``OVARP_ACCESS_TOKEN`` configured the server stays open, which is what a local
run on localhost wants. Set the variable before exposing the server through a
tunnel or a deployment and every API call must carry the token.

The agent WebSocket is deliberately exempt — XR clients authenticate by being a
device declared in config.yaml, not by carrying a researcher's token.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
import secrets as _secrets

from fastapi import Header, HTTPException

TOKEN_HEADER = "X-OVARP-Token"


def access_token_required() -> bool:
    """True when the server is configured to demand a token."""
    return bool(os.getenv("OVARP_ACCESS_TOKEN"))


async def require_console_token(x_ovarp_token: str = Header(default=None)):
    """Reject API calls that do not carry the configured console token."""
    expected = os.getenv("OVARP_ACCESS_TOKEN")
    if not expected:
        return  # Open mode — local development

    if not x_ovarp_token or not _secrets.compare_digest(x_ovarp_token, expected):
        raise HTTPException(
            status_code=401,
            detail=f"Missing or invalid {TOKEN_HEADER} header.",
        )
