"""
Open Virtual Agent Research Platform (OVARP) — Dialog Orchestrator

Central AI pipeline manager that coordinates the full interaction cycle:
STT (speech-to-text) → LLM (language model) → TTS (text-to-speech).
Maintains conversation history, dispatches actions to connected XR
clients, and manages provider hot-swapping at runtime.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
import base64
import logging
import time
from typing import Optional
from structlog import get_logger

from src.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider
from src.core.schemas import BaseCommand
from src.core.router import router

logger = get_logger()
std_log = logging.getLogger("OVARP.orchestrator")

class DialogOrchestrator:
    """
    Manages the core AI Pipeline for the Framework:
    1. STT: Binary Audio -> Text
    2. LLM: Text -> Response Text + JSON Actions
    3. TTS: Response Text -> Binary Audio Stream
    4. Routing: Dispatch Actions and TTS Audio back to XR
    """
    MAX_HISTORY_TURNS = 20  # Keep last N messages to prevent token overflow

    def __init__(self, 
                 stt_provider: BaseSTTProvider,
                 llm_providers: dict[str, BaseLLMProvider], 
                 tts_providers: dict[str, BaseTTSProvider],
                 default_llm: str = "gemini",
                 default_tts: str = "gemini"):
                     
        self.stt = stt_provider
        self.llm_providers = llm_providers
        self.active_llm_id = default_llm
        self.tts_providers = tts_providers
        self.active_tts_id = default_tts
        self.tts_enabled = True  # Toggle from UI
        self.conversation_history: list[dict[str, str]] = []
        self._last_latency: dict = {}  # Populated after each interaction
        
        # Default system prompt (used when no profile is active)
        self.system_prompt = (
            "You are an embodied virtual agent in an XR environment. "
            "Be concise and reply in natural spoken language. "
            "Pay close attention to the user's emotional state and respond empathetically. "
            "If the user expresses frustration, sadness, or excitement, reflect that in your emotion choice. "
            "Always call the update_agent_state function with your spoken reply and appropriate state."
        )

        # Per-agent state: agent_id -> {prompt, history, profile_id, voice_override}
        self._agent_state: dict[str, dict] = {}

    def _get_agent_state(self, agent_id: str) -> dict:
        """Get or create the state dict for a specific agent."""
        if agent_id not in self._agent_state:
            self._agent_state[agent_id] = {
                "profile_id": None,
                "system_prompt": None,   # None = use global default
                "history": [],
                "voice_provider": None,  # None = use active LLM's TTS
                "voice_id": None,
            }
        return self._agent_state[agent_id]

    def clear_history(self, agent_id: str = None):
        """Clears conversation memory. If agent_id given, only that agent."""
        if agent_id:
            state = self._get_agent_state(agent_id)
            state["history"].clear()
            std_log.info(f"🗑️ Orchestrator: History cleared for {agent_id}")
        else:
            self.conversation_history.clear()
            for state in self._agent_state.values():
                state["history"].clear()
            std_log.info("🗑️ Orchestrator: All conversation history cleared")

    @property
    def llm(self) -> BaseLLMProvider:
        """Returns the currently active LLM provider instance."""
        provider = self.llm_providers.get(self.active_llm_id)
        if not provider:
            logger.error(f"Active LLM Provider '{self.active_llm_id}' not found. Falling back to first available.")
            return next(iter(self.llm_providers.values()))
        return provider

    @property
    def tts(self) -> BaseTTSProvider:
        """Returns the independently-selected TTS provider, or first available."""
        provider = self.tts_providers.get(self.active_tts_id)
        if not provider:
            provider = next(iter(self.tts_providers.values()))
        return provider

    def set_active_llm(self, provider_id: str):
        if provider_id in self.llm_providers:
            self.active_llm_id = provider_id
            logger.info("Orchestrator: LLM Provider Swapped", new_provider=provider_id)
            return True
        logger.warning("Orchestrator: Ignored request to swap to unknown provider", unknown_id=provider_id)
        return False

    def set_active_tts(self, provider_id: str):
        """Switch TTS provider independently of LLM."""
        if provider_id in self.tts_providers:
            self.active_tts_id = provider_id
            std_log.info(f"🔊 Orchestrator: TTS Provider Swapped to '{provider_id}'")
            return True
        std_log.warning(f"⚠️ Orchestrator: Unknown TTS provider '{provider_id}'")
        return False

    def register_provider(self, name: str, provider, provider_type: str):
        """Register a custom provider at runtime. type is 'llm' or 'tts'."""
        if provider_type == "llm":
            self.llm_providers[name] = provider
            std_log.info(f"🔌 Orchestrator: Registered custom LLM provider '{name}'")
        elif provider_type == "tts":
            self.tts_providers[name] = provider
            std_log.info(f"🔌 Orchestrator: Registered custom TTS provider '{name}'")

    def unregister_provider(self, name: str):
        """Remove a custom provider. Won't remove built-in openai/gemini."""
        if name in ("openai", "gemini"):
            return False
        removed = False
        if name in self.llm_providers:
            del self.llm_providers[name]
            removed = True
        if name in self.tts_providers:
            del self.tts_providers[name]
            removed = True
        # If we just removed the active provider, fall back to openai
        if self.active_llm_id == name:
            self.active_llm_id = "openai"
            std_log.info(f"⚠️ Orchestrator: Active provider '{name}' removed, fell back to openai")
        if removed:
            std_log.info(f"🗑️ Orchestrator: Unregistered provider '{name}'")
        return removed
        
    def set_system_prompt(self, prompt: str, agent_id: str = None):
        """Set the system prompt globally or for a specific agent."""
        if agent_id:
            state = self._get_agent_state(agent_id)
            state["system_prompt"] = prompt
            std_log.info(f"Orchestrator: System prompt updated for {agent_id}")
        else:
            self.system_prompt = prompt
            logger.info("Orchestrator: Global system prompt updated")

    def apply_profile(self, agent_id: str, profile):
        """
        Apply an AgentProfile to a specific agent.

        Sets the agent's system prompt (composed from profile fields),
        voice, and avatar. The profile's voice provider overrides the
        default TTS matching behavior.
        """
        from src.core.profile_manager import build_system_prompt

        state = self._get_agent_state(agent_id)
        state["profile_id"] = profile.id
        state["system_prompt"] = build_system_prompt(profile)

        llm_id = getattr(profile, "llm_provider", None)
        if llm_id and llm_id != "auto":
            self.set_active_llm(llm_id)

        # Voice override from profile
        if profile.voice:
            state["voice_provider"] = profile.voice.provider
            state["voice_id"] = profile.voice.voice_id

            if profile.voice.provider != "auto" and profile.voice.provider in self.tts_providers:
                self.set_active_tts(profile.voice.provider)
                self.tts_providers[profile.voice.provider].voice = profile.voice.voice_id

        std_log.info(
            f"📋 Orchestrator: Profile '{profile.id}' applied to {agent_id} "
            f"| llm={self.active_llm_id} "
            f"| tts={self.active_tts_id} "
            f"| voice={profile.voice.voice_id if profile.voice else 'default'}"
        )
        return state

    def get_agent_info(self, agent_id: str) -> dict:
        """Returns the current state for an agent."""
        state = self._get_agent_state(agent_id)
        return {
            "agent_id": agent_id,
            "profile_id": state["profile_id"],
            "history_length": len(state["history"]),
            "llm_provider": self.active_llm_id,
            "voice_provider": state["voice_provider"] or self.active_tts_id,
            "tts_provider": self.active_tts_id,
            "voice_id": state["voice_id"],
            "has_custom_prompt": state["system_prompt"] is not None,
        }

    def get_runtime_selection(self) -> dict:
        """Currently selected LLM / TTS / voice, for consoles and telemetry."""
        llm = self.llm
        tts = self.tts
        return {
            "llm": self.active_llm_id,
            "tts": self.active_tts_id,
            "voice": getattr(tts, "voice", None),
            "model": getattr(llm, "model", None),
        }
        tts_provider = self.tts
        tts_provider.voice = voice_id
        std_log.info(f"🔊 Orchestrator: TTS voice changed to '{voice_id}' on {self.active_llm_id}")

    def get_tts_config(self) -> dict:
        """Returns the current TTS state and available voices from config."""
        from src.core.config import config_manager

        tts_provider = self.tts
        provider_id = self.active_tts_id

        # Pull voice options from config if available
        voices = []
        config = config_manager.config
        if config.tts and provider_id in config.tts:
            voices = [v.model_dump() for v in config.tts[provider_id]]

        return {
            "provider": provider_id,
            "current_voice": tts_provider.voice,
            "voices": voices,
        }

        
    async def process_audio_interaction(self, audio_bytes: bytes, target_device: str, target_agent: str):
        """Full pipeline from raw audio bytes out to TTS playback."""
        logger.info("Orchestrator: Starting STT...")
        stt_start = time.perf_counter()
        user_text = await self.stt.transcribe(audio_bytes)
        stt_ms = round((time.perf_counter() - stt_start) * 1000)
        
        if not user_text.strip():
            logger.info("Orchestrator: STT returned empty transcription. Aborting.")
            return

        logger.info("Orchestrator: STT Result", text=user_text, stt_ms=stt_ms)

        # Echo transcript back so XR client can display the user's speech in chat
        transcript_cmd = BaseCommand(
            sender="server_orchestrator",
            target_device=target_device,
            target_agent=target_agent,
            command_type="message",
            command="user_transcript",
            subcommand={"text": user_text}
        )
        await router.route_command(transcript_cmd)

        await self.process_text_interaction(user_text, target_device, target_agent, stt_ms=stt_ms)

    async def process_text_interaction(self, text: str, target_device: str, target_agent: str, stt_ms: int = 0):
        """Pipeline starting from parsed Text (Useful for WoZ injection or direct Web chat)."""
        interaction_start = time.perf_counter()
        try:
            # Resolve per-agent state (falls back to global if no profile)
            agent_state = self._get_agent_state(target_agent)
            history = agent_state["history"] if agent_state["profile_id"] else self.conversation_history
            prompt = agent_state["system_prompt"] or self.system_prompt

            # Append user message to the appropriate history
            history.append({"role": "user", "content": text})
            
            std_log.info(f"🧠 Orchestrator: Starting LLM call | provider={self.active_llm_id} | agent={target_agent} | prompt=\"{text[:80]}\" | history_turns={len(history)}")
            logger.info("Orchestrator: Asking LLM...", prompt=text)
            
            llm_start = time.perf_counter()
            spoken_reply, actions = await self.llm.generate_response_with_actions(
                prompt=text,
                system_prompt=prompt,
                history=history[:-1]  # Everything except current msg (already in prompt)
            )
            llm_ms = round((time.perf_counter() - llm_start) * 1000)
            
            # Append assistant reply to the appropriate history
            if spoken_reply:
                history.append({"role": "assistant", "content": spoken_reply})
            
            # Trim history to prevent token overflow
            if len(history) > self.MAX_HISTORY_TURNS:
                del history[:-self.MAX_HISTORY_TURNS]
            
            std_log.info(f"✅ Orchestrator: LLM responded | reply=\"{str(spoken_reply)[:120]}\" | actions={actions}")
            logger.info("Orchestrator: LLM Reply", text=spoken_reply, actions=actions)
            
            # Build latency dict for this interaction
            latency = {
                "stt_ms": stt_ms,
                "llm_ms": llm_ms,
            }

            # 0. Broadcast the raw text so the Web UI Chat window can display what the Bot is thinking
            if spoken_reply:
                std_log.info(f"📡 Orchestrator: Broadcasting llm_reply to all transports")
                text_cmd = BaseCommand(
                    sender="server_orchestrator",
                    target_device="all", # Send to UI
                    target_agent=target_agent,
                    command_type="message",
                    command="llm_reply",
                    subcommand={
                        "text": spoken_reply,
                        "provider": self.active_llm_id,
                        "model": self.llm.model,
                        "agent": target_agent,
                        "latency": latency
                    }
                )
                await router.route_command(text_cmd)
                std_log.info(f"✅ Orchestrator: llm_reply broadcast complete")
            else:
                std_log.warning(f"⚠️ Orchestrator: LLM returned empty spoken_reply")
            
            # 1. Dispatch the chosen actions (Emotions/Transformations) FIRST
            if actions:
                await self._dispatch_actions(actions, target_device, target_agent)
                
            # 2. Dispatch the TTS Audio Stream (only if enabled)
            tts_ms = 0
            if spoken_reply and self.tts_enabled:
                tts_start = time.perf_counter()
                await self._dispatch_tts(spoken_reply, target_device, target_agent)
                tts_ms = round((time.perf_counter() - tts_start) * 1000)
            elif spoken_reply and not self.tts_enabled:
                std_log.info("🔇 Orchestrator: TTS disabled, skipping audio generation")

            # Finalize latency metrics
            total_ms = round((time.perf_counter() - interaction_start) * 1000)
            latency["tts_ms"] = tts_ms
            latency["total_ms"] = total_ms
            self._last_latency = latency
            std_log.info(f"⏱️ Orchestrator: Latency | stt={stt_ms}ms llm={llm_ms}ms tts={tts_ms}ms total={total_ms}ms")

        except Exception as e:
            std_log.error(f"💥 Orchestrator: CRITICAL ERROR in process_text_interaction | {type(e).__name__}: {str(e)}")
            logger.error("Orchestrator pipeline crashed", error=str(e))

    async def _dispatch_actions(self, actions_dict: dict, target_device: str, target_agent: str):
        """Packages LLM JSON actions into a valid BaseCommand and pushes it to Router."""
        try:
            std_log.info(f"⚡ Orchestrator: Dispatching actions | {actions_dict}")
            cmd = BaseCommand(
                sender="server_orchestrator",
                target_device=target_device,
                target_agent=target_agent,
                command_type="action",
                command="execute_state",
                subcommand=actions_dict
            )
            # Route back out to ZMQ/WS
            await router.route_command(cmd)
            
        except Exception as e:
            std_log.error(f"❌ Orchestrator: Failed to dispatch actions | {str(e)}")
            logger.error("Failed to parse and route LLM actions", error=str(e), actions=actions_dict)

    async def _dispatch_tts(self, text: str, target_device: str, target_agent: str):
        """Starts TTS generation and streams audio chunks through the router as they arrive."""
        try:
            std_log.info(f"🔊 Orchestrator: Starting TTS synthesis | target={target_device} text=\"{text[:60]}\"")
            audio_generator = self.tts.synthesize_stream(text)
            
            chunk_count = 0
            async for audio_chunk in audio_generator:
                # We encode the raw bytes into base64 to transport inside the JSON command via ZMQ
                b64_chunk = base64.b64encode(audio_chunk).decode("utf-8")
                chunk_count += 1
                
                cmd = BaseCommand(
                    sender="server_orchestrator",
                    target_device="all",  # Broadcast so WoZ console also receives audio
                    target_agent=target_agent,
                    command_type="audio",
                    command="tts_chunk",
                    subcommand={"audio_base64": b64_chunk}
                )
                await router.route_command(cmd)
            
            std_log.info(f"📤 Orchestrator: TTS chunks sent | count={chunk_count}")
                
            # Send a final 'tts_complete' flag 
            end_cmd = BaseCommand(
                sender="server_orchestrator",
                target_device="all",  # Broadcast so WoZ console also receives audio
                target_agent=target_agent,
                command_type="audio",
                command="tts_complete"
            )
            await router.route_command(end_cmd)
            std_log.info(f"✅ Orchestrator: TTS complete signal sent")
            
        except Exception as e:
            std_log.error(f"❌ Orchestrator: TTS Streaming failed | {type(e).__name__}: {str(e)}")
            logger.error("TTS Streaming failed", error=str(e))

    async def process_direct_tts(self, text: str, target_device: str, target_agent: str):
        """Bypasses the LLM — sends researcher-typed text directly to TTS and broadcasts it.
        The VR user experiences this identically to an LLM-generated response."""
        try:
            std_log.info(f"🎤 Orchestrator: Direct TTS | text=\"{text[:80]}\" | target={target_device}")

            # Broadcast the text as a normal llm_reply so all clients display it like agent speech
            text_cmd = BaseCommand(
                sender="server_orchestrator",
                target_device="all",
                target_agent=target_agent,
                command_type="message",
                command="llm_reply",
                subcommand={
                    "text": text,
                    "provider": "woz_direct",
                    "model": "n/a",
                    "agent": target_agent
                }
            )
            await router.route_command(text_cmd)

            # Generate and stream TTS audio to the target device
            if self.tts_enabled:
                await self._dispatch_tts(text, target_device, target_agent)
            else:
                std_log.info("🔇 Orchestrator: TTS disabled, skipping audio for direct message")

        except Exception as e:
            std_log.error(f"❌ Orchestrator: Direct TTS failed | {type(e).__name__}: {str(e)}")
            logger.error("Direct TTS pipeline failed", error=str(e))
