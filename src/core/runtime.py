"""
Open Virtual Agent Research Platform (OVARP) — Runtime Container

Composition root for the server-wide collaborators. API routers read the
orchestrator, transports and managers from here instead of reaching into the
application module, which keeps routers importable on their own and lets tests
swap a collaborator without touching ``src.main``.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os

from src.core.config import config_manager
from src.core.profile_manager import profile_manager
from src.core.router import router
from src.core.scenario_runner import scenario_runner
from src.core.session_manager import session_manager
from src.core.survey_manager import survey_manager
from src.core.telemetry import telemetry


def is_testing() -> bool:
    """True when the server runs under pytest, which skips transport bootstrap."""
    if os.getenv("OVARP_TESTING"):
        return True
    if os.getenv("OAF_TESTING"):
        import logging
        logging.getLogger("OVARP").warning(
            "⚠️  OAF_TESTING is deprecated, use OVARP_TESTING instead."
        )
        return True
    return False


def is_headless() -> bool:
    """True when the root URL should serve the lightweight dashboard."""
    new = os.environ.get("OVARP_HEADLESS", "").lower() in ("true", "1", "yes")
    legacy = os.environ.get("OAF_HEADLESS", "").lower() in ("true", "1", "yes")
    if legacy and not new:
        import logging
        logging.getLogger("OVARP").warning(
            "⚠️  OAF_HEADLESS is deprecated, use OVARP_HEADLESS instead."
        )
    return new or legacy


class Runtime:
    """Mutable holder for everything the routers need at request time."""

    def __init__(self):
        # Wired during application bootstrap
        self.orchestrator = None
        self.zmq_transport = None
        self.ws_transport = None

        # Module singletons, held here so tests can substitute them
        self.router = router
        self.telemetry = telemetry
        self.session_manager = session_manager
        self.scenario_runner = scenario_runner
        self.profile_manager = profile_manager
        self.config_manager = config_manager
        self.survey_manager = survey_manager


runtime = Runtime()
