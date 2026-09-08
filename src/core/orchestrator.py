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
from src.core.telemetry import telemetry

logger = get_logger()
std_log = logging.getLogger("OVARP.orchestrator")

# How many sentences are allowed to synthesize concurrently for one reply. Bounds
# API load/cost on long replies; three is enough to keep synthesis of sentence N+1
# ahead of the client finishing playback of sentence N.
_MAX_CONCURRENT_TTS_SYNTH = 3

_SENTENCE_BOUNDARY_CHARS = ".!?"
_TRAILING_CLOSERS = "\"')]"


def _split_ready_sentences(buffer: str) -> tuple[list[str], str]:
    """Splits `buffer` into complete sentences plus a leftover fragment.

    A sentence only counts as complete once its terminal punctuation is confirmed
    by a following character (whitespace, closing quote/paren) -- so streaming text
    like "3.1" or a still-arriving "Hi ther" is never cut on a guess, only once the
    next character actually confirms the boundary. This is what lets TTS start on
    the first sentence while the LLM is still generating the rest of the reply.
    Known simplification: abbreviations like "Dr." split like a sentence end.
    """
    sentences: list[str] = []
    start = 0
    i = 0
    n = len(buffer)
    while i < n:
        ch = buffer[i]
        if ch == "\n":
            fragment = buffer[start:i].strip()
            if fragment:
                sentences.append(fragment)
            start = i + 1
        elif ch in _SENTENCE_BOUNDARY_CHARS and i + 1 < n:
            j = i + 1
            while j < n and buffer[j] in _TRAILING_CLOSERS:
                j += 1
            if j < n and buffer[j].isspace():
                fragment = buffer[start:j].strip()
                if fragment:
                    sentences.append(fragment)
                start = j
                i = j
                continue
        i += 1
    return sentences, buffer[start:]


class _TTSPipeline:
    """Feeds sentences to TTS as soon as each is ready and streams their audio to
    clients strictly in arrival order, while later sentences keep synthesizing
    concurrently in the background.

    This is what turns "wait for the whole reply, then speak" into "speak the
    first sentence while the rest is still generating" -- the highest-leverage fix
    identified in OPA-335: TTS on the full assembled text was consistently the
    single biggest chunk of total latency (measured: 1586-8356ms of total_ms
    3266-12055ms in data/sessions/*.jsonl).
    """

    def __init__(self, orchestrator: "DialogOrchestrator", target_agent: str,
                 max_concurrent: int = _MAX_CONCURRENT_TTS_SYNTH):
        self._orchestrator = orchestrator
        self._target_agent = target_agent
        self._queue: asyncio.Queue = asyncio.Queue()
        self._sem = asyncio.Semaphore(max_concurrent)
        self._start = time.perf_counter()
        self._first_chunk_ms: Optional[int] = None
        self._last_sent_ms: Optional[int] = None
        self._any_sent = False
        self._consumer = asyncio.create_task(self._consume())

    def feed(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        task = asyncio.create_task(
            self._orchestrator._synthesize_sentence(sentence, self._target_agent, self._sem)
        )
        self._queue.put_nowait(task)

    async def _consume(self) -> None:
        while True:
            task = await self._queue.get()
            if task is None:
                break
            chunks = await task
            if not chunks:
                continue
            if self._first_chunk_ms is None:
                self._first_chunk_ms = round((time.perf_counter() - self._start) * 1000)
            await self._orchestrator._send_sentence_audio(chunks, self._target_agent)
            self._any_sent = True
            self._last_sent_ms = round((time.perf_counter() - self._start) * 1000)

    async def finish(self) -> tuple[int, Optional[int]]:
        """No more sentences coming: drain the queue, return (tts_ms, first_chunk_ms).

        tts_ms is timestamped when the last audio chunk was actually sent, not
        when finish() happens to be awaited -- callers may await something else
        (e.g. a slow actions-classification call) first, and that wait must not
        leak into this metric."""
        self._queue.put_nowait(None)
        await self._consumer
        tts_ms = self._last_sent_ms if self._any_sent else 0
        return tts_ms, self._first_chunk_ms


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
                 stt_provider: BaseSTTProvider = None,
                 llm_providers: dict[str, BaseLLMProvider] = None,
                 tts_providers: dict[str, BaseTTSProvider] = None,
                 stt_providers: dict[str, BaseSTTProvider] = None,
                 default_llm: str = "gemini",
                 default_tts: str = "gemini",
                 default_stt: str = None):

        # STT accepts either a registry or a single provider. All three stages are
        # swappable at runtime; STT used to be the one fixed at construction, which
        # left the microphone tied to whichever vendor was wired in at boot.
        self.stt_providers = dict(stt_providers) if stt_providers else {}
        if stt_provider is not None and not self.stt_providers:
            self.stt_providers = {"openai": stt_provider}
        self.active_stt_id = default_stt or next(iter(self.stt_providers), None)

        self.llm_providers = llm_providers or {}
        self.active_llm_id = default_llm
        self.tts_providers = tts_providers or {}
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
    def stt(self) -> BaseSTTProvider:
        """The active transcription provider, or the first available as a fallback."""
        provider = self.stt_providers.get(self.active_stt_id)
        if not provider:
            return next(iter(self.stt_providers.values()), None)
        return provider

    def set_active_stt(self, provider_id: str) -> bool:
        """Switch the transcription provider, independently of LLM and TTS."""
        if provider_id in self.stt_providers:
            self.active_stt_id = provider_id
            std_log.info(f"🎤 Orchestrator: STT Provider Swapped to '{provider_id}'")
            return True
        std_log.warning(f"⚠️ Orchestrator: Unknown STT provider '{provider_id}'")
        return False

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
        elif provider_type == "stt":
            self.stt_providers[name] = provider
            std_log.info(f"🔌 Orchestrator: Registered custom STT provider '{name}'")

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
        if name in self.stt_providers:
            del self.stt_providers[name]
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

        # Voice override from profile
        if profile.voice:
            state["voice_provider"] = profile.voice.provider
            state["voice_id"] = profile.voice.voice_id

            # If profile specifies a concrete provider, switch TTS voice now
            if profile.voice.provider != "auto" and profile.voice.provider in self.tts_providers:
                self.tts_providers[profile.voice.provider].voice = profile.voice.voice_id

        std_log.info(
            f"📋 Orchestrator: Profile '{profile.id}' applied to {agent_id} "
            f"| voice={profile.voice.voice_id if profile.voice else 'default'}"
        )
        return state

    def clear_profile(self, agent_id: str) -> dict:
        """Release an agent back to the global prompt and voice.

        Applying a profile parks a prompt and voice on the agent that win over
        the globals for good. This is the way back, so the console's settings
        become the single source of truth again.
        """
        state = self._get_agent_state(agent_id)
        state["profile_id"] = None
        state["system_prompt"] = None
        state["voice_provider"] = None
        state["voice_id"] = None
        std_log.info(f"↩️ Orchestrator: {agent_id} released back to global prompt and voice")
        return self.get_agent_info(agent_id)

    def get_agent_info(self, agent_id: str) -> dict:
        """Returns the current state for an agent."""
        state = self._get_agent_state(agent_id)
        return {
            "agent_id": agent_id,
            "profile_id": state["profile_id"],
            "history_length": len(state["history"]),
            "voice_provider": state["voice_provider"],
            "voice_id": state["voice_id"],
            "has_custom_prompt": state["system_prompt"] is not None,
        }

    def set_tts_voice(self, voice_id: str, agent_id: str = None):
        """Change the TTS voice, globally or for one agent.

        Without ``agent_id`` this moves the active provider's voice, which is
        what agents running on the global defaults will speak with. With an
        ``agent_id`` it pins an override that survives a global voice change.
        """
        if agent_id:
            self._get_agent_state(agent_id)["voice_id"] = voice_id
            std_log.info(f"🔊 Orchestrator: TTS voice for {agent_id} pinned to '{voice_id}'")
            return

        self.tts.voice = voice_id
        std_log.info(f"🔊 Orchestrator: TTS voice changed to '{voice_id}' on {self.active_tts_id}")

    def _resolve_tts(self, agent_id: str):
        """Return the (provider, voice_id) pair this agent should speak with.

        An applied profile pins the agent's provider and voice; anything the
        profile leaves open falls back to the globally selected provider and its
        current voice. Returning the pair here is what keeps the per-agent state
        and the console's voice picker from being two disconnected settings.
        """
        state = self._agent_state.get(agent_id, {})

        provider_id = state.get("voice_provider")
        if provider_id in (None, "auto") or provider_id not in self.tts_providers:
            provider_id = self.active_tts_id

        provider = self.tts_providers.get(provider_id) or self.tts
        return provider, state.get("voice_id")

    def get_effective_voice(self, agent_id: str) -> dict:
        """What this agent will actually speak with, and whether a profile pinned it."""
        provider, voice_id = self._resolve_tts(agent_id)
        pinned = voice_id is not None
        return {
            "agent_id": agent_id,
            "provider": next(
                (name for name, p in self.tts_providers.items() if p is provider),
                self.active_tts_id,
            ),
            "voice": voice_id or provider.voice,
            "pinned_by_profile": pinned,
            "profile_id": self._agent_state.get(agent_id, {}).get("profile_id"),
        }

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
            await self._report_pipeline_error(
                "stt", self.active_stt_id,
                RuntimeError("No speech was transcribed from the audio"), target_agent,
            )
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
            llm_first_chunk_ms = None
            tts_pipeline: Optional[_TTSPipeline] = None
            actions_task: Optional[asyncio.Task] = None
            if hasattr(self.llm, "stream_reply"):
                # Real text streaming (Gemini-only, see gemini_provider.py): the reply
                # streams to clients chunk by chunk as it's generated. Each completed
                # sentence is handed to TTS immediately (_TTSPipeline) instead of
                # waiting for the full text, and gesture/emotion classification
                # (extract_actions) runs as a background task in parallel with that
                # speech instead of blocking in front of the first audio byte.
                spoken_reply = ""
                sentence_buffer = ""
                if self.tts_enabled:
                    tts_pipeline = _TTSPipeline(self, target_agent)
                async for delta in self.llm.stream_reply(
                    prompt=text,
                    system_prompt=prompt,
                    history=history[:-1]  # Everything except current msg (already in prompt)
                ):
                    if not delta:
                        continue
                    if llm_first_chunk_ms is None:
                        llm_first_chunk_ms = round((time.perf_counter() - llm_start) * 1000)
                    spoken_reply += delta
                    sentence_buffer += delta
                    await router.route_command(BaseCommand(
                        sender="server_orchestrator",
                        target_device="all",
                        target_agent=target_agent,
                        command_type="message",
                        command="llm_reply_chunk",
                        subcommand={"text": delta, "agent": target_agent},
                    ))
                    if tts_pipeline is not None:
                        ready, sentence_buffer = _split_ready_sentences(sentence_buffer)
                        for sentence in ready:
                            tts_pipeline.feed(sentence)
                if tts_pipeline is not None and sentence_buffer.strip():
                    tts_pipeline.feed(sentence_buffer)
                actions_task = (
                    asyncio.create_task(self.llm.extract_actions(spoken_reply, prompt))
                    if spoken_reply else None
                )
                actions = {}  # resolved below, awaited in parallel with the TTS pipeline
            else:
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
            if llm_first_chunk_ms is not None:
                latency["llm_first_chunk_ms"] = llm_first_chunk_ms

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
            
            # 1 & 2. Resolve actions and finish the TTS audio stream concurrently.
            # Both have been running in the background since the reply text finished
            # (extract_actions as a task, TTS sentences as they came off the stream).
            # Awaiting them one after the other would let whichever is slower (in
            # practice, Gemini's non-streaming actions-classification call, observed
            # 2-12s) hold up dispatching the other -- gather so neither blocks on
            # the other's tail.
            tts_ms = 0
            tts_first_chunk_ms = None
            if actions_task is not None and tts_pipeline is not None:
                actions, (tts_ms, tts_first_chunk_ms) = await asyncio.gather(
                    actions_task, tts_pipeline.finish()
                )
            elif actions_task is not None:
                actions = await actions_task
            elif tts_pipeline is not None:
                tts_ms, tts_first_chunk_ms = await tts_pipeline.finish()

            if actions:
                await self._dispatch_actions(actions, target_device, target_agent)

            if tts_pipeline is None and spoken_reply and self.tts_enabled:
                tts_start = time.perf_counter()
                await self._dispatch_tts(spoken_reply, target_device, target_agent)
                tts_ms = round((time.perf_counter() - tts_start) * 1000)
            elif spoken_reply and not self.tts_enabled:
                std_log.info("🔇 Orchestrator: TTS disabled, skipping audio generation")

            # Finalize latency metrics
            total_ms = round((time.perf_counter() - interaction_start) * 1000)
            latency["tts_ms"] = tts_ms
            if tts_first_chunk_ms is not None:
                latency["tts_first_chunk_ms"] = tts_first_chunk_ms
            latency["total_ms"] = total_ms
            latency["target_device"] = target_device
            latency["target_agent"] = target_agent
            self._last_latency = dict(latency)

            # The llm_reply broadcast above carries only stt/llm: tts_ms and total_ms
            # do not exist until TTS has finished. Persist and announce the complete
            # figures here so the session record and the console agree.
            telemetry.log_latency(latency)
            try:
                await router.route_command(BaseCommand(
                    sender="server_orchestrator",
                    target_device="all",
                    target_agent=target_agent if target_agent else "all",
                    command_type="system",
                    command="latency",
                    subcommand={
                        "stt_ms": latency.get("stt_ms", 0),
                        "llm_ms": latency.get("llm_ms", 0),
                        "llm_first_chunk_ms": latency.get("llm_first_chunk_ms", 0),
                        "tts_ms": latency.get("tts_ms", 0),
                        "tts_first_chunk_ms": latency.get("tts_first_chunk_ms", 0),
                        "total_ms": latency.get("total_ms", 0),
                    },
                ))
            except Exception as lat_err:
                std_log.warning(f"⚠️ Orchestrator: Could not broadcast latency | {lat_err}")
            std_log.info(f"⏱️ Orchestrator: Latency | stt={stt_ms}ms llm={llm_ms}ms llm_first_chunk={llm_first_chunk_ms}ms tts={tts_ms}ms tts_first_chunk={tts_first_chunk_ms}ms total={total_ms}ms")

        except Exception as e:
            std_log.error(f"💥 Orchestrator: CRITICAL ERROR in process_text_interaction | {type(e).__name__}: {str(e)}")
            logger.error("Orchestrator pipeline crashed", error=str(e))
            await self._report_pipeline_error("llm", self.active_llm_id, e, target_agent)

    async def _report_pipeline_error(self, stage: str, provider: str, error: Exception,
                                     target_agent: str = "all"):
        """Tell the connected consoles that a stage failed.

        A provider outage or a rate limit used to surface only as silence, with
        the reason buried in the server log — indistinguishable from an agent
        that simply had nothing to say.
        """
        detail = str(error)
        # Provider SDKs wrap the useful sentence in a long payload; the tail is noise
        summary = detail[:300]
        try:
            cmd = BaseCommand(
                sender="server_orchestrator",
                target_device="all",
                target_agent=target_agent,
                command_type="system",
                command="pipeline_error",
                subcommand={
                    "stage": stage,
                    "provider": provider,
                    "error": type(error).__name__,
                    "detail": summary,
                },
            )
            await router.dispatch_outbound(cmd)
        except Exception as report_failure:
            std_log.error(f"❌ Orchestrator: could not report {stage} failure | {report_failure}")

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

    async def _synthesize_sentence(self, text: str, target_agent: str,
                                    sem: "asyncio.Semaphore") -> list[bytes]:
        """Runs one sentence/fragment through the active TTS provider and buffers its
        audio chunks (used by ``_TTSPipeline`` so synthesis of the next sentence can
        start while this one's audio is still being sent). ``sem`` bounds how many of
        these run concurrently for one reply."""
        async with sem:
            provider, voice_id = self._resolve_tts(target_agent)
            if voice_id and provider.voice != voice_id:
                provider.voice = voice_id
            chunks: list[bytes] = []
            try:
                async for chunk in provider.synthesize_stream(text):
                    chunks.append(chunk)
            except Exception as e:
                std_log.error(
                    f"❌ Orchestrator: sentence TTS synthesis failed | text=\"{text[:60]}\" "
                    f"| {type(e).__name__}: {str(e)}"
                )
            return chunks

    async def _send_sentence_audio(self, chunks: list[bytes], target_agent: str) -> None:
        """Streams pre-synthesized audio chunks for one sentence to clients, then signals
        completion for that sentence so playback can start without waiting for the rest
        of the reply. See ``_TTSPipeline``."""
        for audio_chunk in chunks:
            b64_chunk = base64.b64encode(audio_chunk).decode("utf-8")
            await router.route_command(BaseCommand(
                sender="server_orchestrator",
                target_device="all",  # Broadcast so WoZ console also receives audio
                target_agent=target_agent,
                command_type="audio",
                command="tts_chunk",
                subcommand={"audio_base64": b64_chunk}
            ))
        await router.route_command(BaseCommand(
            sender="server_orchestrator",
            target_device="all",  # Broadcast so WoZ console also receives audio
            target_agent=target_agent,
            command_type="audio",
            command="tts_complete"
        ))

    async def _dispatch_tts(self, text: str, target_device: str, target_agent: str):
        """Starts TTS generation and streams audio chunks through the router as they arrive."""
        try:
            provider, voice_id = self._resolve_tts(target_agent)
            if voice_id and provider.voice != voice_id:
                provider.voice = voice_id
            std_log.info(
                f"🔊 Orchestrator: Starting TTS synthesis | target={target_device} "
                f"agent={target_agent} voice={provider.voice} text=\"{text[:60]}\""
            )
            audio_generator = provider.synthesize_stream(text)
            
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
            await self._report_pipeline_error("tts", self.active_tts_id, e, target_agent)

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
