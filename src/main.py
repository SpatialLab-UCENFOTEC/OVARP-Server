"""
Open Virtual Agent Research Platform (OVARP) — Application Entry Point

Bootstraps the server: loads the experiment configuration, starts the ZMQ and
WebSocket transports, registers the AI providers, wires the dialog
orchestrator into the runtime container, and mounts the API routers and the
Wizard-of-Oz console.

Route handlers live in ``src/api/routers/``.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env BEFORE anything tries to read API keys
load_dotenv()

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from structlog import get_logger  # noqa: E402

from src.api import websockets  # noqa: E402
from src.api.deps import require_console_token  # noqa: E402
from src.api.routers import (  # noqa: E402
    auth,
    llm,
    profiles,
    providers,
    scenarios,
    sessions,
    surveys,
    system,
)
from src.core.logging_setup import configure_logging  # noqa: E402
from src.core.orchestrator import DialogOrchestrator  # noqa: E402
from src.core.runtime import is_headless, is_testing, runtime  # noqa: E402
from src.providers.gemini_provider import (  # noqa: E402
    GeminiLLMProvider,
    GeminiSTTProvider,
    GeminiTTSProvider,
)
from src.providers.openai_provider import (  # noqa: E402
    OpenAILLMProvider,
    OpenAISTTProvider,
    OpenAITTSProvider,
)
from src.transport.ws_layer import WebSocketTransport  # noqa: E402
from src.transport.zmq_layer import ZMQTransport  # noqa: E402

logger = get_logger()

ZMQ_PUB_PORT = 5555
ZMQ_SUB_PORT = 5556


def _build_orchestrator() -> DialogOrchestrator:
    """Assemble the dialog pipeline from the built-in providers.

    All three stages are registered per vendor and selected independently, so a
    study can run transcription on one provider and speech on another.
    """
    return DialogOrchestrator(
        stt_providers={
            "openai": OpenAISTTProvider(),
            "gemini": GeminiSTTProvider(),
        },
        llm_providers={
            "openai": OpenAILLMProvider(),
            "gemini": GeminiLLMProvider(),
        },
        tts_providers={
            "openai": OpenAITTSProvider(),
            "gemini": GeminiTTSProvider(),
        },
        default_llm=os.getenv("OVARP_DEFAULT_LLM", "gemini"),
        default_tts=os.getenv("OVARP_DEFAULT_TTS", "gemini"),
        default_stt=os.getenv("OVARP_DEFAULT_STT", "gemini"),
    )


def _bootstrap():
    """Load configuration and wire every collaborator into the runtime container."""
    runtime.config_manager.load_config()

    runtime.zmq_transport = ZMQTransport(pub_port=ZMQ_PUB_PORT, sub_port=ZMQ_SUB_PORT)
    runtime.ws_transport = WebSocketTransport()
    runtime.router.add_transport(runtime.zmq_transport)
    runtime.router.add_transport(runtime.ws_transport)

    runtime.orchestrator = _build_orchestrator()
    runtime.router.set_orchestrator(runtime.orchestrator)

    runtime.profile_manager.load_profiles("profiles")
    if runtime.config_manager.config.conditions:
        runtime.profile_manager.migrate_conditions(runtime.config_manager.config.conditions)

    runtime.scenario_runner.load_scenarios_from_dir("scenarios")
    runtime.survey_manager.load_surveys_from_dir("surveys")

    from src.api.routers.providers import load_custom_providers
    load_custom_providers()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts and stops the transports alongside the HTTP server."""
    logger.info(
        "Starting OVARP Server...",
        experiment=runtime.config_manager.config.experiment.name,
    )
    await runtime.zmq_transport.start()
    await runtime.ws_transport.start()

    yield

    await runtime.zmq_transport.stop()
    await runtime.ws_transport.stop()
    logger.info("OVARP Server fully stopped.")


if is_testing():
    # Minimal app — tests substitute the collaborators on the runtime container
    app = FastAPI(title="OVARP Server (Test Mode)")
else:
    _bootstrap()
    app = FastAPI(
        title="OVARP Server (Wizard of Oz & Gateway)",
        description="Open Virtual Agent Research Platform Routing Server",
        version=runtime.config_manager.config.experiment.version,
        lifespan=lifespan,
    )

# Reachable without a token so the console can ask for one when it needs to
app.include_router(auth.router)

# Participants answer questionnaires on their own device, with no token to carry
app.include_router(surveys.router)

# Everything a researcher can drive is behind the console token when one is set
for api_router in (system.router, llm.router, providers.router,
                   sessions.router, profiles.router, scenarios.router):
    app.include_router(api_router, dependencies=[Depends(require_console_token)])

# XR clients authenticate by being a device declared in config.yaml, not by token
app.include_router(websockets.router)

configure_logging()

# The static mount must come last: it claims "/" and would shadow the API routes.
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    if is_headless():
        logger.info("Starting in HEADLESS mode. Full WoZ console & 3D Avatar are disabled.")

        @app.get("/")
        async def serve_headless():
            return FileResponse(os.path.join(static_path, "headless.html"))

        app.mount("/", StaticFiles(directory=static_path, html=False), name="static")
    else:
        app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
else:
    logger.warning("Static directory not found. UI will not be available.", path=static_path)
