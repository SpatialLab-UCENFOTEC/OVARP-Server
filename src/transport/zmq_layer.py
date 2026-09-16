"""
Open Virtual Agent Research Platform (OVARP) — ZeroMQ Transport

Low-latency bidirectional transport for XR clients (Unity, Unreal).
Uses ZMQ PUB/SUB sockets: a PUB socket broadcasts commands from the
server to clients, and a SUB socket receives telemetry and audio
from XR clients back to the server.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
import zmq
import zmq.asyncio
from structlog import get_logger

from src.transport.base import BaseTransport

logger = get_logger()

class ZMQTransport(BaseTransport):
    """
    ZeroMQ Publish/Subscribe Bidirectional Transport.
    - Binds a PUB socket to broadcast commands from Server -> XR Clients.
    - Binds a SUB socket to receive telemetry/audio from XR Clients -> Server.
    """
    def __init__(self, pub_port: int = 5555, sub_port: int = 5556):
        super().__init__()
        self.pub_port = pub_port
        self.sub_port = sub_port
        
        self.ctx = zmq.asyncio.Context()
        self.pub_socket = self.ctx.socket(zmq.PUB)
        self.sub_socket = self.ctx.socket(zmq.SUB)
        self._listener_task = None
        
    async def start(self):
        # Set LINGER to 0 to prevent TIME_WAIT port locking on restarts
        self.pub_socket.setsockopt(zmq.LINGER, 0)
        self.sub_socket.setsockopt(zmq.LINGER, 0)

        # Publisher Binding
        pub_addr = f"tcp://*:{self.pub_port}"
        self.pub_socket.bind(pub_addr)
        logger.info("ZMQ Publisher bound", address=pub_addr)
        
        # Subscriber Binding
        sub_addr = f"tcp://*:{self.sub_port}"
        self.sub_socket.bind(sub_addr)
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, "") # Subscribe to everything
        logger.info("ZMQ Subscriber bound", address=sub_addr)
        
        # Start listening loop in background
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("ZMQ Transport started.")
        
    async def stop(self):
        logger.info("Stopping ZMQ Transport...")
        if self._listener_task:
            self._listener_task.cancel()
        
        self.pub_socket.close()
        self.sub_socket.close()
        self.ctx.term()
        logger.info("ZMQ Transport stopped.")
        
    async def _listen_loop(self):
        try:
            while True:
                # Expecting multipart: [topic, payload] or just [payload]
                message_parts = await self.sub_socket.recv_multipart()
                
                # If there's only one part, it's just the payload.
                payload = message_parts[-1].decode("utf-8")
                
                # Dispatch up to the framework
                await self._dispatch_message(payload)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("ZMQ Listener error", error=str(e))

    async def send(self, target_device: str, topic: str, message: str):
        # Format: "target_device topic payload"
        # If target_device is "all", clients subscribing to "all" will get it.
        # XR Clients should ideally subscribe to both their specific ID AND "all".
        payload = f"{target_device} {topic} {message}"
        await self.pub_socket.send_string(payload)
        logger.debug("ZMQ Sent message", target=target_device, topic=topic, message_len=len(message))
