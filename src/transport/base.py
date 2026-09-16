"""
Open Virtual Agent Research Platform (OVARP) — Transport Base Class

Defines ``BaseTransport``, the abstract base class for all communication
layers. Transports handle bidirectional message flow between the server
and connected clients (XR headsets, web browsers, mobile apps).
Supports callback registration for inbound message dispatching.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Any

class BaseTransport(ABC):
    """
    Abstract base class for all communication layers in OVARP.
    Transports can be ZMQ, WebSockets or mock implementations.
    """
    
    def __init__(self):
        # List of callbacks to run when a message is received
        self._message_callbacks: list[Callable[[str], Awaitable[None]]] = []
        
    def register_callback(self, callback: Callable[[str], Awaitable[None]]):
        """Register an async callback to trigger when messages arrive."""
        self._message_callbacks.append(callback)
        
    async def _dispatch_message(self, raw_message: str):
        """Called internally by implementations to bubble up a received message."""
        tasks = [callback(raw_message) for callback in self._message_callbacks]
        if tasks:
            await asyncio.gather(*tasks)

    @abstractmethod
    async def start(self):
        """Initialize connections and start listening to incoming messages."""
        pass
        
    @abstractmethod
    async def stop(self):
        """Gracefully close connections."""
        pass
        
    @abstractmethod
    async def send(self, target_device: str, topic: str, message: str):
        """Send a message/command out to connected clients.
        If target_device is 'all', broadcast it. 
        Otherwise, unicast it to the specific device.
        """
        pass
