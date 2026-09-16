"""
Open Virtual Agent Research Platform (OVARP) — Command Router

Receives raw JSON messages from all transports, validates them against
the experiment schema, logs them via the telemetry module, and dispatches
them to the appropriate handler (orchestrator for AI interactions, or
broadcast for direct commands). Acts as the central message bus.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import base64
import asyncio
import logging

from pydantic import ValidationError
from structlog import get_logger

from src.core.schemas import BaseCommand
from src.core.config import config_manager
from src.core.telemetry import telemetry
from src.transport.base import BaseTransport

logger = get_logger()
std_log = logging.getLogger("OVARP.router")

class CommandRouter:
    """
    Core bus that receives messages from any Transport Layer (ZMQ or WebSockets),
    validates them against the Experiment Configuration (via BaseCommand), 
    and routes them to the appropriate destinations or AI Providers.
    """
    def __init__(self):
        self._transports: list[BaseTransport] = []
        self._orchestrator = None
        
    def set_orchestrator(self, orchestrator):
        self._orchestrator = orchestrator
        
    def add_transport(self, transport: BaseTransport):
        """Register a transport layer and bind the router's incoming handler."""
        self._transports.append(transport)
        transport.register_callback(self.handle_incoming_raw)
        logger.info("Transport registered to Router", transport_type=type(transport).__name__)
        
    async def handle_incoming_raw(self, raw_message: str):
        """
        Entrypoint for all raw string messages arriving from ZMQ or WS.
        Validates against the dynamic Pydantic schema first.
        """
        try:
            command = BaseCommand.from_json(raw_message)
            std_log.info(f"✅ Router: Valid command received | type={command.command_type} cmd={command.command} sender={command.sender}")
            await self.route_command(command)
            
        except ValidationError as e:
            std_log.error(f"❌ Router: Invalid command schema | error={str(e)[:200]}")
            logger.error("Invalid command schema received", error=str(e), raw=raw_message)
        except Exception as e:
            std_log.error(f"❌ Router: Unexpected error processing message | error={str(e)}")
            logger.error("Error processing incoming message", error=str(e), raw=raw_message)
            
    async def route_command(self, command: BaseCommand):
        """
        Determines where the command should go based on target_device and command_type.
        """
        # If the command is an audio blob sent from a client, intercept it and route to the AI Orchestrator
        if command.command_type == "audio" and command.command == "stt_request":
            if self._orchestrator and command.subcommand and "audio_base64" in command.subcommand:
                try:
                    audio_bytes = base64.b64decode(command.subcommand["audio_base64"])
                    # Fire-and-forget the processing so the router doesn't block incoming ZMQ traffic
                    asyncio.create_task(
                        self._orchestrator.process_audio_interaction(
                            audio_bytes=audio_bytes, 
                            target_device=command.sender, # Reply goes back to the sender
                            target_agent=command.target_agent
                        )
                    )
                except Exception as e:
                    logger.error("Failed to decode and route audio to orchestrator", error=str(e))
            return # Do not broadcast pure STT audio back to everyone
            
        # If it's a direct text message intended for the AI
        if command.command_type == "message" and command.command == "llm_request":
             if self._orchestrator and command.subcommand and "text" in command.subcommand:
                 # Use 'all' as target so replies reach all connected clients including the WoZ console
                 reply_target = command.target_device if command.target_device != "all" else command.sender
                 # If sender isn't a registered device (e.g. woz_console), default to 'all'
                 valid_devices = [d.id for d in config_manager.config.devices] + ["all"]
                 if reply_target not in valid_devices:
                     reply_target = "all"
                 std_log.info(f"🧠 Router: Dispatching to Orchestrator | text=\"{command.subcommand['text'][:100]}\" | reply_target={reply_target}")
                 asyncio.create_task(
                     self._orchestrator.process_text_interaction(
                         text=command.subcommand["text"],
                         target_device=reply_target,
                         target_agent=command.target_agent
                     )
                 )
             else:
                 std_log.warning(f"⚠️ Router: llm_request received but no orchestrator or missing text")
             return

        # If it's a researcher-injected message that should speak via TTS (bypasses LLM entirely)
        if command.command_type == "message" and command.command == "direct_tts":
            if self._orchestrator and command.subcommand and "text" in command.subcommand:
                std_log.info(f"🎤 Router: Direct TTS request | text=\"{command.subcommand['text'][:100]}\" | target={command.target_device}")
                asyncio.create_task(
                    self._orchestrator.process_direct_tts(
                        text=command.subcommand["text"],
                        target_device=command.target_device,
                        target_agent=command.target_agent
                    )
                )
            else:
                std_log.warning(f"⚠️ Router: direct_tts received but no orchestrator or missing text")
            return

        # Programmatic event marker: any device or agent can fire a marker over the command bus
        if command.command_type == "system" and command.command == "log_marker":
            if command.subcommand and "label" in command.subcommand:
                label = command.subcommand["label"]
                metadata = command.subcommand.get("metadata")
                # Inject the sender as source so researchers know who triggered it
                meta = dict(metadata) if metadata else {}
                meta["source"] = command.sender
                try:
                    from src.core.session_manager import session_manager
                    session_manager.add_marker(label, meta)
                    telemetry.log_marker(label, meta)
                    std_log.info(f"📌 Router: Programmatic marker logged | label=\"{label}\" | sender={command.sender}")
                    # Broadcast confirmation to all clients so WoZ console updates live
                    confirm = BaseCommand(
                        sender="server_orchestrator",
                        target_device="all",
                        target_agent="all",
                        command_type="system",
                        command="marker_logged",
                        subcommand={"label": label, "metadata": meta}
                    )
                    await self.dispatch_outbound(confirm)
                except ValueError as e:
                    std_log.warning(f"⚠️ Router: Marker skipped (no active session) | label=\"{label}\"")
            else:
                std_log.warning(f"⚠️ Router: log_marker received but missing 'label' in subcommand")
            return
             
        # Otherwise (normal WoZ commands, TTS chunks returning, agent actions), dispatch them
        await self.dispatch_outbound(command)

    async def dispatch_outbound(self, command: BaseCommand):
        """Funnels a validated command down to all active transport layers using targeted messaging."""
        telemetry.log_interaction(command)
        std_log.info(f"📡 Router: Dispatching | type={command.command_type} cmd={command.command} target={command.target_device} to {len(self._transports)} transports")
        
        json_payload = command.to_json()
        
        # Use a generic 'framework.cmd' topic for ZMQ or WS envelopes
        
        for transport in self._transports:
            # We skip the WoZ ws logic here since WS handles it internally via the client dict
            # We pass the target_device down to the transport explicitly
            await transport.send(command.target_device, command.command_type, json_payload)
        

router = CommandRouter()
