"""
Open Virtual Agent Research Platform (OVARP) — Application Entry Point

FastAPI application that bootstraps the entire OVARP server:
initializes transports (ZMQ + WebSocket), registers AI providers
(OpenAI, Gemini), configures the dialog orchestrator, and exposes
REST/WebSocket endpoints for the Wizard-of-Oz console, LLM chat,
telemetry export, and real-time system logs.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# Load .env BEFORE anything tries to read API keys
load_dotenv()
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from structlog import get_logger

from src.core.config import config_manager
from src.core.router import router
from src.core.orchestrator import DialogOrchestrator
from src.transport.zmq_layer import ZMQTransport
from src.transport.ws_layer import WebSocketTransport
from src.core.telemetry import telemetry

# Using OpenAI as the default fully functional provider for the MVP
from src.providers.openai_provider import OpenAISTTProvider, OpenAILLMProvider, OpenAITTSProvider
from src.providers.gemini_provider import GeminiLLMProvider, GeminiTTSProvider
from pydantic import BaseModel

logger = get_logger()

# --- Backward-compat: accept legacy OAF_* env vars with deprecation warning ---
def _is_testing():
    if os.getenv("OVARP_TESTING"):
        return True
    if os.getenv("OAF_TESTING"):
        logging.getLogger("OVARP").warning("⚠️  OAF_TESTING is deprecated, use OVARP_TESTING instead.")
        return True
    return False

# 1. Initialize Configuration (skip in test mode — tests mock the config)
if not _is_testing():
    config_manager.load_config()

    # 2. Setup Transports
    zmq_transport = ZMQTransport(pub_port=5555, sub_port=5556)
    ws_transport = WebSocketTransport()

    # Bind both to the router so messages flow bidirectionally everywhere
    router.add_transport(zmq_transport)
    router.add_transport(ws_transport)

    # 3. Setup AI Orchestrator
    # (Requires API Keys in .env to function fully)
    stt_provider = OpenAISTTProvider()
    llm_providers = {
        "openai": OpenAILLMProvider(),
        "gemini": GeminiLLMProvider()
    }
    tts_provider = OpenAITTSProvider()
    gemini_tts_provider = GeminiTTSProvider()

    orchestrator = DialogOrchestrator(
        stt_provider=stt_provider,
        llm_providers=llm_providers,
        tts_providers={
            "openai": tts_provider,
            "gemini": gemini_tts_provider
        },
        default_llm="openai",
        default_tts="openai"
    )

    # Pipe the Router to the Orchestrator so audio commands trigger AI responses
    router.set_orchestrator(orchestrator)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifecycle manager for FastAPI to start and stop background resources."""
        logger.info("Starting OpenVirtualAgentResearchPlatform Server...", experiment=config_manager.config.experiment.name)
        
        # Start all registered transports
        await zmq_transport.start()
        await ws_transport.start()
        
        yield
        
        # Shutdown gracefully
        await zmq_transport.stop()
        await ws_transport.stop()
        logger.info("OVARP Server fully stopped.")

    # 4. Initialize FastAPI App
    app = FastAPI(
        title="OVARP Server (Wizard of Oz & Gateway)",
        description="OpenVirtualAgentResearchPlatform Routing Server",
        version=config_manager.config.experiment.version,
        lifespan=lifespan
    )
else:
    # Minimal app for testing — routes still get registered below
    app = FastAPI(title="OVARP Server (Test Mode)")

# 4. HTTP and WebSocket Mounts
@app.get("/api/config")
async def get_config():
    """Returns the current loaded topology directly from config.yaml"""
    return config_manager.config.model_dump()


def _detect_lan_ip() -> str:
    """Best-effort detection of this machine's primary LAN IP (the address
    XR/Web clients on the same network must connect to). Falls back to
    127.0.0.1 if no external route is available."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is actually sent; this just picks the outbound interface.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@app.get("/api/server/info")
async def get_server_info():
    """Connection details clients (e.g. XREAL/Unity headsets) need to reach
    this server: the LAN IP plus the WebSocket and ZeroMQ ports."""
    lan_ip = _detect_lan_ip()
    ws_port = int(os.getenv("OVARP_PORT", "8000"))
    return {
        "lan_ip": lan_ip,
        "ws_port": ws_port,
        "zmq_pub_port": 5555,
        "zmq_sub_port": 5556,
        "ws_url_template": f"ws://{lan_ip}:{ws_port}/ws/client/<device_id>",
    }

class LLMConfigUpdate(BaseModel):
    provider_id: str | None = None
    system_prompt: str | None = None

@app.get("/api/llm/config")
async def get_llm_config():
    """Returns the current active LLM state"""
    return {
        "active_provider": orchestrator.active_llm_id,
        "available_providers": list(orchestrator.llm_providers.keys()),
        "active_tts_provider": orchestrator.active_tts_id,
        "available_tts_providers": list(orchestrator.tts_providers.keys()),
        "system_prompt": orchestrator.system_prompt,
        "tts_enabled": orchestrator.tts_enabled
    }

@app.post("/api/llm/config")
async def set_llm_config(update: LLMConfigUpdate):
    """Dynamically updates the Orchestrator without restarting"""
    if update.provider_id:
        orchestrator.set_active_llm(update.provider_id)
    if update.system_prompt:
        orchestrator.set_system_prompt(update.system_prompt)
        
    return {
        "active_provider": orchestrator.active_llm_id,
        "active_tts_provider": orchestrator.active_tts_id,
        "system_prompt": orchestrator.system_prompt,
        "tts_enabled": orchestrator.tts_enabled
    }

@app.post("/api/llm/tts")
async def toggle_tts():
    """Toggles TTS audio generation on/off"""
    orchestrator.tts_enabled = not orchestrator.tts_enabled
    return {"tts_enabled": orchestrator.tts_enabled}

@app.get("/api/tts/voices")
async def get_tts_voices():
    """Returns available TTS voices for the active provider, including gender metadata."""
    return orchestrator.get_tts_config()

class TtsVoiceUpdate(BaseModel):
    voice_id: str

@app.post("/api/tts/voice")
async def set_tts_voice(update: TtsVoiceUpdate):
    """Switch the active TTS voice at runtime."""
    orchestrator.set_tts_voice(update.voice_id)
    return orchestrator.get_tts_config()

class TtsProviderUpdate(BaseModel):
    provider_id: str

@app.post("/api/tts/provider")
async def set_tts_provider(update: TtsProviderUpdate):
    """Switch the TTS provider independently of the LLM provider."""
    success = orchestrator.set_active_tts(update.provider_id)
    if not success:
        return {"error": f"Unknown TTS provider '{update.provider_id}'"}
    return orchestrator.get_tts_config()

@app.post("/api/llm/history/clear")
async def clear_history():
    """Clears the conversation memory"""
    orchestrator.clear_history()
    return {"status": "ok", "message": "Conversation history cleared"}

@app.get("/api/health/providers")
async def check_provider_health():
    """Validates API key connectivity for each registered provider dynamically."""
    import asyncio
    results = {}
    for name in orchestrator.llm_providers:
        try:
            if name == "openai":
                from src.providers.openai_provider import OpenAIClientSingleton
                client = OpenAIClientSingleton.get_client()
                await client.models.list()
                results[name] = "ok"
            elif name == "gemini":
                from src.providers.gemini_provider import GeminiClientSingleton
                client = GeminiClientSingleton.get_client()
                if client is None:
                    raise ValueError("GEMINI_API_KEY not set")
                await asyncio.to_thread(client.models.list)
                results[name] = "ok"
            else:
                # Custom / third-party providers — test via their base_url
                provider = orchestrator.llm_providers[name]
                if hasattr(provider, 'base_url'):
                    from src.providers.custom_provider import test_custom_endpoint
                    ok, _ = await test_custom_endpoint(
                        provider.base_url,
                        getattr(provider, 'api_key', ''),
                        getattr(provider, 'model', '')
                    )
                    results[name] = "ok" if ok else "error"
                else:
                    results[name] = "ok"  # No way to test, assume ok
        except Exception as e:
            results[name] = "error"
            results[f"{name}_error"] = str(e)[:120]
    return results

@app.get("/api/export")
async def export_telemetry():
    """Exports the current session JSONL into a structured CSV file for analysis"""
    csv_path = telemetry.export_to_csv()
    if csv_path and csv_path.exists():
        return FileResponse(path=csv_path, filename=csv_path.name, media_type='text/csv')
    return {"error": "Failed to generate CSV export."}

# --- Custom Provider Registration ---
import yaml
from pathlib import Path
from src.providers.custom_provider import CustomLLMProvider, CustomTTSProvider, test_custom_endpoint

CUSTOM_PROVIDERS_FILE = Path(__file__).resolve().parent.parent / "custom_providers.yaml"

def _load_custom_providers():
    """Load custom providers from YAML on boot."""
    if not CUSTOM_PROVIDERS_FILE.exists():
        return
    try:
        data = yaml.safe_load(CUSTOM_PROVIDERS_FILE.read_text(encoding="utf-8")) or {}
        providers = data.get("providers", {})
        for name, cfg in providers.items():
            base_url = cfg.get("base_url", "")
            api_key = cfg.get("api_key", "")
            model = cfg.get("model", "")
            types = cfg.get("types", [])
            if "llm" in types:
                orchestrator.register_provider(name, CustomLLMProvider(name, base_url, model, api_key), "llm")
            if "tts" in types:
                orchestrator.register_provider(name, CustomTTSProvider(name, base_url, model, api_key), "tts")
        std_log = logging.getLogger("OVARP.custom")
        std_log.info(f"🔌 Loaded {len(providers)} custom provider(s) from {CUSTOM_PROVIDERS_FILE.name}")
    except Exception as e:
        logging.getLogger("OVARP.custom").warning(f"⚠️ Could not load custom providers: {e}")

def _save_custom_providers(registry: dict):
    """Persist the custom providers registry to YAML."""
    CUSTOM_PROVIDERS_FILE.write_text(
        yaml.dump({"providers": registry}, default_flow_style=False, sort_keys=False),
        encoding="utf-8"
    )

def _read_custom_registry() -> dict:
    """Read the current registry from disk."""
    if not CUSTOM_PROVIDERS_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(CUSTOM_PROVIDERS_FILE.read_text(encoding="utf-8")) or {}
        return data.get("providers", {})
    except Exception:
        return {}

# Load on boot (only outside test mode)
if not _is_testing():
    _load_custom_providers()

class ProviderRegisterRequest(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    model: str
    types: list[str]  # ["llm"], ["tts"], or ["llm", "tts"]

@app.get("/api/providers")
async def list_providers():
    """List all registered providers (built-in + custom)."""
    custom = _read_custom_registry()
    return {
        "builtin": ["openai", "gemini"],
        "custom": custom,
        "available_llm": list(orchestrator.llm_providers.keys()),
        "available_tts": list(orchestrator.tts_providers.keys()),
        "active_llm": orchestrator.active_llm_id
    }

@app.post("/api/providers/register")
async def register_provider(req: ProviderRegisterRequest):
    """Register a new custom OpenAI-compatible provider."""
    name = req.name.strip().lower().replace(" ", "-")
    if name in ("openai", "gemini"):
        return {"error": "Cannot overwrite built-in providers."}

    # Create and register provider instances
    if "llm" in req.types:
        provider = CustomLLMProvider(name, req.base_url, req.model, req.api_key)
        orchestrator.register_provider(name, provider, "llm")
    if "tts" in req.types:
        provider = CustomTTSProvider(name, req.base_url, req.model, req.api_key)
        orchestrator.register_provider(name, provider, "tts")

    # Persist to YAML
    registry = _read_custom_registry()
    registry[name] = {
        "base_url": req.base_url,
        "api_key": req.api_key,
        "model": req.model,
        "types": req.types
    }
    _save_custom_providers(registry)

    return {
        "status": "ok",
        "name": name,
        "available_llm": list(orchestrator.llm_providers.keys()),
        "available_tts": list(orchestrator.tts_providers.keys())
    }

@app.delete("/api/providers/{name}")
async def unregister_provider_endpoint(name: str):
    """Remove a custom provider."""
    removed = orchestrator.unregister_provider(name)
    if not removed:
        return {"error": f"Provider '{name}' not found or is built-in."}

    # Remove from YAML
    registry = _read_custom_registry()
    registry.pop(name, None)
    _save_custom_providers(registry)

    return {
        "status": "ok",
        "available_llm": list(orchestrator.llm_providers.keys()),
        "available_tts": list(orchestrator.tts_providers.keys())
    }

@app.post("/api/providers/{name}/test")
async def test_provider_endpoint(name: str):
    """Test connectivity to a custom provider's base_url."""
    registry = _read_custom_registry()
    cfg = registry.get(name)
    if not cfg:
        return {"ok": False, "detail": f"Provider '{name}' not found in registry."}
    result = await test_custom_endpoint(cfg["base_url"], cfg.get("api_key", ""), cfg.get("model", ""))
    return result

class ProviderTestRequest(BaseModel):
    base_url: str
    api_key: str = ""
    model: str = ""

@app.post("/api/providers/test")
async def test_provider_url(req: ProviderTestRequest):
    """Test connectivity to any OpenAI-compatible endpoint (before registering)."""
    result = await test_custom_endpoint(req.base_url, req.api_key, req.model)
    return result

# --- Session Management ---
from src.core.session_manager import session_manager

class SessionStartRequest(BaseModel):
    participant_id: str

class MarkerRequest(BaseModel):
    label: str
    metadata: dict | None = None

@app.get("/api/session/status")
async def get_session_status():
    """Returns the current experiment session state"""
    return session_manager.get_status()

@app.post("/api/session/start")
async def start_session(req: SessionStartRequest):
    """Start a new experiment session with a participant ID"""
    session = session_manager.start_session(req.participant_id)
    telemetry.log_session_event("started", {"participant_id": req.participant_id})
    return session_manager.get_status()

@app.post("/api/session/pause")
async def pause_session():
    """Pause the active experiment session"""
    try:
        session_manager.pause_session()
        telemetry.log_session_event("paused")
        return session_manager.get_status()
    except ValueError as e:
        return {"error": str(e)}

@app.post("/api/session/resume")
async def resume_session():
    """Resume a paused experiment session"""
    try:
        session_manager.resume_session()
        telemetry.log_session_event("resumed")
        return session_manager.get_status()
    except ValueError as e:
        return {"error": str(e)}

@app.post("/api/session/end")
async def end_session():
    """End the active session and return the final session data"""
    try:
        completed = session_manager.end_session()
        telemetry.log_session_event("ended", {
            "participant_id": completed.participant_id,
            "marker_count": len(completed.markers),
        })
        return {
            "status": "completed",
            "session": completed.model_dump(),
        }
    except ValueError as e:
        return {"error": str(e)}

@app.post("/api/session/marker")
async def add_marker(req: MarkerRequest):
    """Add an event marker to the active session"""
    try:
        marker = session_manager.add_marker(req.label, req.metadata)
        telemetry.log_marker(req.label, req.metadata)
        return {"status": "ok", "marker": marker.model_dump()}
    except ValueError as e:
        return {"error": str(e)}

@app.get("/api/session/markers/presets")
async def get_marker_presets():
    """Returns the pre-programmed event marker presets from config.yaml"""
    config = config_manager.config
    if config.event_markers:
        return {"presets": [m.model_dump() for m in config.event_markers]}
    return {"presets": []}

# --- Agent Profiles ---
from src.core.profile_manager import profile_manager

# Load profiles at startup (non-test mode)
if not _is_testing():
    profile_manager.load_profiles("profiles")
    # Auto-migrate legacy conditions into profiles
    if config_manager.config.conditions:
        profile_manager.migrate_conditions(config_manager.config.conditions)

@app.get("/api/profiles")
async def list_profiles():
    """List all available agent profiles."""
    return {"profiles": profile_manager.list_profiles()}

@app.get("/api/profiles/{profile_id}")
async def get_profile(profile_id: str):
    """Get full details for a specific profile."""
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        return {"error": f"Profile '{profile_id}' not found"}
    return profile.model_dump()

class ProfileApplyRequest(BaseModel):
    profile_id: str
    agent_id: str = "all"  # Which agent to apply the profile to

@app.post("/api/profiles/apply")
async def apply_profile(req: ProfileApplyRequest):
    """Apply an agent profile — sets system prompt, voice, and avatar for the target agent."""
    profile = profile_manager.get_profile(req.profile_id)
    if not profile:
        return {"error": f"Profile '{req.profile_id}' not found"}

    # Determine which agents to apply to
    if req.agent_id == "all":
        agent_ids = [a.id for a in config_manager.config.agents]
    else:
        agent_ids = [req.agent_id]

    results = []
    for agent_id in agent_ids:
        # Apply profile to the orchestrator's per-agent state
        orchestrator.apply_profile(agent_id, profile)

        # Send avatar change to XR clients (if the profile specifies one)
        if profile.avatar:
            from src.core.schemas import BaseCommand
            avatar_cmd = BaseCommand(
                sender="server_orchestrator",
                target_device="all",
                target_agent=agent_id,
                command_type="action",
                command="execute_state",
                subcommand={"avatar": profile.avatar}
            )
            await router.route_command(avatar_cmd)

        results.append(orchestrator.get_agent_info(agent_id))

    # Log the profile change
    telemetry.log_session_event("profile_applied", {
        "profile_id": req.profile_id,
        "profile_name": profile.name,
        "agents": agent_ids,
    })

    return {
        "status": "ok",
        "profile_id": req.profile_id,
        "profile_name": profile.name,
        "agents": results,
    }

class ProfileCreateRequest(BaseModel):
    id: str
    name: str
    identity: dict = None
    voice: dict = None
    personality: dict = None
    guardrails: dict = None
    avatar: str = None

@app.post("/api/profiles/create")
async def create_profile(req: ProfileCreateRequest):
    """Create a new profile at runtime (from WoZ console or XR device)."""
    try:
        profile = profile_manager.create_profile(req.model_dump(exclude_none=True))
        return {"status": "ok", "profile": profile.model_dump()}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/agents/{agent_id}")
async def get_agent_state(agent_id: str):
    """Returns the current profile and state for a specific agent."""
    return orchestrator.get_agent_info(agent_id)

# --- Deprecated: Conditions (auto-redirected to profiles) ---

class ConditionApplyRequest(BaseModel):
    condition_id: str

@app.get("/api/conditions")
async def get_conditions():
    """[Deprecated] Use GET /api/profiles instead. Returns profiles as conditions for compatibility."""
    return {"conditions": {p["id"]: p for p in profile_manager.list_profiles()}}

@app.post("/api/conditions/apply")
async def apply_condition(req: ConditionApplyRequest):
    """[Deprecated] Use POST /api/profiles/apply instead. Redirects to profile application."""
    # Try the condition ID as-is, then with condition_ prefix (from migration)
    profile = profile_manager.get_profile(req.condition_id)
    if not profile:
        profile = profile_manager.get_profile(f"condition_{req.condition_id}")
    if not profile:
        return {"error": f"No profile found for condition '{req.condition_id}'"}

    # Delegate to profile application
    orchestrator.apply_profile("all", profile)
    telemetry.log_session_event("condition_applied", {
        "condition_id": req.condition_id,
        "migrated_to_profile": profile.id,
    })
    return {
        "status": "ok",
        "condition_id": req.condition_id,
        "profile_id": profile.id,
        "deprecated": "Use POST /api/profiles/apply instead",
    }

# --- Scripted Scenarios ---
from src.core.scenario_runner import scenario_runner

# Load scenarios at import time (non-test mode)
if not _is_testing():
    scenario_runner.load_scenarios_from_dir("scenarios")

class ScenarioLoadRequest(BaseModel):
    scenario_id: str

@app.get("/api/scenarios")
async def list_scenarios():
    """List all available experiment scenarios."""
    return {"scenarios": scenario_runner.list_scenarios()}

@app.post("/api/scenarios/load")
async def load_scenario(req: ScenarioLoadRequest):
    """Load and start a scenario from step 1."""
    try:
        step = scenario_runner.start(req.scenario_id)
        # Handle auto-actions for the first step
        await _execute_step_side_effects(step)
        return {"status": "ok", **scenario_runner.get_status()}
    except ValueError as e:
        return {"error": str(e)}

@app.post("/api/scenarios/advance")
async def advance_scenario():
    """Advance to the next step in the active scenario."""
    try:
        step = scenario_runner.advance()
        if step is None:
            return {"status": "completed", "active": False}
        await _execute_step_side_effects(step)
        return {"status": "ok", **scenario_runner.get_status()}
    except ValueError as e:
        return {"error": str(e)}

@app.get("/api/scenarios/status")
async def get_scenario_status():
    """Get the current scenario runner state."""
    return scenario_runner.get_status()

@app.post("/api/scenarios/stop")
async def stop_scenario():
    """Stop the active scenario without completing it."""
    scenario_runner.stop()
    return {"status": "ok", "active": False}

async def _execute_step_side_effects(step):
    """Execute auto-actions, conditions, and markers for a scenario step."""
    from src.core.scenario_runner import ScenarioStep

    # Auto-log marker
    if step.auto_marker:
        try:
            session_manager.add_marker(step.auto_marker, {"source": "scenario"})
            telemetry.log_marker(step.auto_marker, {"source": "scenario"})
        except ValueError:
            pass  # No active session — skip marker

    # Auto-apply condition
    if step.condition:
        config = config_manager.config
        if config.conditions and step.condition in config.conditions:
            cond = config.conditions[step.condition]
            orchestrator.set_system_prompt(cond.system_prompt)
            telemetry.log_session_event("condition_applied", {
                "condition_id": step.condition,
                "source": "scenario",
            })

    # Auto-execute action
    if step.action:
        from src.core.schemas import BaseCommand
        action_cmd = BaseCommand(
            sender="server_orchestrator",
            target_device="all",
            target_agent="all",
            command_type="action",
            command="execute_state",
            subcommand=step.action,
        )
        await router.route_command(action_cmd)

# --- XR Telemetry Ingest ---

class XRTelemetryBatch(BaseModel):
    device_id: str
    frames: list[dict]

@app.post("/api/xr/telemetry")
async def ingest_xr_telemetry(batch: XRTelemetryBatch):
    """Receive batched XR telemetry frames (head/hand/gaze) from clients."""
    telemetry.log_xr_telemetry(batch.device_id, batch.frames)
    return {"status": "ok", "frames_received": len(batch.frames)}

@app.websocket("/ws/client/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Client entrypoint for the Wizard of Oz panel or Web Agents.
    Hands the connection over to the WS Transport Layer so it can track
    who is sending or receiving commands.
    """
    await ws_transport.connect(websocket, client_id)
    # Block and listen to this specific socket
    await ws_transport.handle_incoming(websocket, client_id)

# --- System Logs Streamer ---

log_subscribers = []

@app.websocket("/ws/logs")
async def websocket_logs_endpoint(websocket: WebSocket):
    """
    Dedicated endpoint for streaming server logs to the WoZ console UI.
    """
    await websocket.accept()
    log_subscribers.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        log_subscribers.remove(websocket)

class WebsocketLogHandler(logging.Handler):
    def emit(self, record):
        try:
            if not log_subscribers:
                return
            log_entry = self.format(record)
            payload = json.dumps({"level": record.levelname, "name": record.name, "message": log_entry})
            loop = asyncio.get_running_loop()
            for conn in list(log_subscribers):
                try:
                    loop.create_task(conn.send_text(payload))
                except Exception:
                    pass
        except Exception:
            pass

ws_logger = WebsocketLogHandler()
ws_logger.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'))

# --- File Logging ---
# Write all logs to a rotating log file for future review
log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, "OVARP_server.log")

file_handler = RotatingFileHandler(log_file_path, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'))
file_handler.setLevel(logging.DEBUG)

# Register with root and all relevant loggers
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(ws_logger)
root_logger.addHandler(file_handler)

# Register our custom OVARP loggers (OVARP.router, OVARP.orchestrator, OVARP.gemini)
OVARP_logger = logging.getLogger("OVARP")
OVARP_logger.setLevel(logging.DEBUG)
OVARP_logger.addHandler(ws_logger)
OVARP_logger.addHandler(file_handler)
OVARP_logger.propagate = False  # Prevent duplicate messages from root logger

logging.getLogger("uvicorn.access").addHandler(ws_logger)
logging.getLogger("uvicorn.access").addHandler(file_handler)
logging.getLogger("uvicorn.error").addHandler(ws_logger)
logging.getLogger("uvicorn.error").addHandler(file_handler)
logging.getLogger("fastapi").addHandler(ws_logger)
logging.getLogger("fastapi").addHandler(file_handler)

# --------------------------

# Mount the UI based on OVARP_HEADLESS mode
# If headless is set, the root URL will serve a lightweight dashboard instead of the full 3D WoZ Console
static_path = os.path.join(os.path.dirname(__file__), "static")
_headless_new = os.environ.get("OVARP_HEADLESS", "").lower() in ["true", "1", "yes"]
_headless_legacy = os.environ.get("OAF_HEADLESS", "").lower() in ["true", "1", "yes"]
if _headless_legacy and not _headless_new:
    logging.getLogger("OVARP").warning("⚠️  OAF_HEADLESS is deprecated, use OVARP_HEADLESS instead.")
headless_mode = _headless_new or _headless_legacy

if os.path.exists(static_path):
    if headless_mode:
        logger.info("Starting in HEADLESS mode. Full WoZ console & 3D Avatar are disabled.")
        @app.get("/")
        async def serve_headless():
            return FileResponse(os.path.join(static_path, "headless.html"))
        app.mount("/", StaticFiles(directory=static_path, html=False), name="static")
    else:
        # Default Mode: Serve the full UI at root
        app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
else:
    logger.warning("Static directory not found. UI will not be available.", path=static_path)
