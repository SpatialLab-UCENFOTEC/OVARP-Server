"""
Open Virtual Agent Research Platform (OVARP) — WebSocket Endpoints

Two sockets: the command bus clients connect to (``/ws/client/{id}``), and a
read-only log stream the WoZ console subscribes to (``/ws/logs``).

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from fastapi import APIRouter, WebSocket

from src.core.logging_setup import log_subscribers
from src.core.runtime import runtime

router = APIRouter(tags=["websockets"])


@router.websocket("/ws/client/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Client entrypoint for the Wizard of Oz panel or Web Agents.
    Hands the connection over to the WS Transport Layer so it can track
    who is sending or receiving commands.
    """
    await runtime.ws_transport.connect(websocket, client_id)
    await runtime.ws_transport.handle_incoming(websocket, client_id)


@router.websocket("/ws/logs")
async def websocket_logs_endpoint(websocket: WebSocket):
    """Streams server logs to the WoZ console UI."""
    await websocket.accept()
    log_subscribers.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        if websocket in log_subscribers:
            log_subscribers.remove(websocket)
