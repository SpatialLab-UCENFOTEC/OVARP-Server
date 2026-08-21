"""
Open Virtual Agent Research Platform (OVARP) — System Routes

Experiment topology, client connection details, telemetry export and XR
telemetry ingest.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
import socket

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.runtime import runtime

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/config")
async def get_config():
    """Returns the current loaded topology directly from config.yaml"""
    return runtime.config_manager.config.model_dump()


def _detect_lan_ip() -> str:
    """Best-effort detection of this machine's primary LAN IP (the address
    XR/Web clients on the same network must connect to). Falls back to
    127.0.0.1 if no external route is available."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is actually sent; this just picks the outbound interface.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@router.get("/server/info")
async def get_server_info(request: Request):
    """Connection details, split by how the client will actually reach us.

    A browser page served over HTTPS cannot open a ws:// socket, so a hosted web
    client needs the wss:// address this request arrived on, not the LAN IP. A
    native XR build has no such restriction and wants the LAN IP. Reporting a
    single URL is what made the console advertise an address the web client
    could not use.
    """
    lan_ip = _detect_lan_ip()
    ws_port = int(os.getenv("OVARP_PORT", "8000"))

    # A tunnel or reverse proxy terminates TLS and tells us so in this header
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    is_secure = proto == "https"
    host = request.headers.get("host") or f"{lan_ip}:{ws_port}"
    ws_scheme = "wss" if is_secure else "ws"

    return {
        "lan_ip": lan_ip,
        "ws_port": ws_port,
        "zmq_pub_port": 5555,
        "zmq_sub_port": 5556,
        # For native XR builds on the same Wi-Fi
        "lan_ws_url": f"ws://{lan_ip}:{ws_port}",
        # For a browser client, matching the scheme this request came in on
        "public_ws_url": f"{ws_scheme}://{host}",
        "is_secure": is_secure,
        "client_url": runtime.config_manager.config.client_url,
        "ws_url_template": f"{ws_scheme}://{host}/ws/client/<device_id>",
    }


@router.get("/export")
async def export_telemetry():
    """Exports the current session JSONL into a structured CSV file for analysis"""
    csv_path = runtime.telemetry.export_to_csv()
    if csv_path and csv_path.exists():
        return FileResponse(path=csv_path, filename=csv_path.name, media_type="text/csv")
    return {"error": "Failed to generate CSV export."}


class XRTelemetryBatch(BaseModel):
    device_id: str
    frames: list[dict]


@router.post("/xr/telemetry")
async def ingest_xr_telemetry(batch: XRTelemetryBatch):
    """Receive batched XR telemetry frames (head/hand/gaze) from clients."""
    runtime.telemetry.log_xr_telemetry(batch.device_id, batch.frames)
    return {"status": "ok", "frames_received": len(batch.frames)}
