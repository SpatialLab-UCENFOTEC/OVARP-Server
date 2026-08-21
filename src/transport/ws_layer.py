"""
Open Virtual Agent Research Platform (OVARP) — WebSocket Transport

Bidirectional transport layer for web-based clients using FastAPI's
WebSocket support. Manages connection lifecycle, broadcasts outbound
messages to all connected clients, and dispatches inbound messages
to registered framework callbacks.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from structlog import get_logger
from typing import Dict, Set

from src.transport.base import BaseTransport

logger = get_logger()

class WebSocketTransport(BaseTransport):
    """
    WebSocket Bidirectional Transport integrated via FastAPI Router.
    Allows Web, Mobile and Wizard-of-Oz clients to connect and send/receive commands.
    Supports targeting specific devices for multi-client compatibility.
    """
    def __init__(self):
        super().__init__()
        # Keep track of active websocket connections by client_id
        # A single client_id could theoretically have multiple active sockets (e.g. multiple tabs)
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        
    async def start(self):
        # WebSocket server doesn't bind a port directly here.
        # It relies on the main FastAPI application to mount its endpoints
        # and trigger the connection manager methods.
        logger.info("WebSocket Transport initialized (Awaiting FastAPI mount).")
        
    async def stop(self):
        logger.info("Stopping WebSocket Transport...")
        for client_id, connections in self.active_connections.items():
            for connection in connections:
                await connection.close(code=1001, reason="Server shutting down")
        self.active_connections.clear()
        logger.info("WebSocket Transport stopped.")

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = set()
        self.active_connections[client_id].add(websocket)
        logger.info("WebSocket client connected", client_id=client_id, total_clients=len(self.active_connections))

    def disconnect(self, websocket: WebSocket, client_id: str):
        if client_id in self.active_connections:
            if websocket in self.active_connections[client_id]:
                self.active_connections[client_id].remove(websocket)
            if not self.active_connections[client_id]:
                self.active_connections.pop(client_id, None)
            logger.info("WebSocket client disconnected", client_id=client_id, total_clients=len(self.active_connections))

    async def handle_incoming(self, websocket: WebSocket, client_id: str):
        """Loop to read incoming messages from a specific active connecton"""
        try:
            while True:
                data = await websocket.receive_text()
                # Dispatch up to the framework
                await self._dispatch_message(data)
        except WebSocketDisconnect:
            self.disconnect(websocket, client_id)
        except Exception as e:
            logger.error("WebSocket Listener error", client_id=client_id, error=str(e))
            self.disconnect(websocket, client_id)

    async def send(self, target_device: str, topic: str, message: str):
        """
        Sends the message wrapper with topic to a specific client_id or broadcasts to all.
        """
        if not self.active_connections:
            return
            
        payload = f'{{"topic": "{topic}", "payload": {message}}}'
        dead_connections = []
        
        # Determine targets
        sockets_to_ping = []
        if target_device == "all":
            for sockets in self.active_connections.values():
                sockets_to_ping.extend(sockets)
        else:
            if target_device in self.active_connections:
                sockets_to_ping.extend(self.active_connections[target_device])
                
        for connection in sockets_to_ping:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.error("Failed to send WS message", error=str(e))
                # Need client_id back to remove correctly
                for cid, socks in self.active_connections.items():
                    if connection in socks:
                        dead_connections.append((connection, cid))
                        break
                
        for dead_sock, cid in dead_connections:
            self.disconnect(dead_sock, cid)
