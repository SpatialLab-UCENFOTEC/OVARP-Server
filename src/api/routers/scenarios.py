"""
Open Virtual Agent Research Platform (OVARP) — Scenario Routes

Scripted experiment protocols defined in ``scenarios/*.yaml``: load, advance
step by step, and stop. Each step can auto-fire a marker, apply an agent
profile and dispatch an action to the connected clients.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.runtime import runtime

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


class ScenarioLoadRequest(BaseModel):
    scenario_id: str


class ScenarioStepRequest(BaseModel):
    id: str
    instruction: str
    action: dict | None = None
    condition: str | None = None
    auto_marker: str | None = None
    duration_seconds: int | None = None


class ScenarioCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    steps: list[ScenarioStepRequest] = []


@router.get("")
async def list_scenarios():
    """List all available experiment scenarios."""
    return {"scenarios": runtime.scenario_runner.list_scenarios()}


@router.post("")
async def create_scenario(req: ScenarioCreateRequest):
    """Create an experiment protocol and persist it to scenarios/<id>.yaml."""
    from src.core.scenario_runner import Scenario, ScenarioStep

    try:
        scenario = Scenario(
            id=req.id,
            name=req.name,
            description=req.description,
            steps=[ScenarioStep(**s.model_dump()) for s in req.steps],
        )
        runtime.scenario_runner.add_scenario(scenario, save_to_disk=True)
        return {
            "status": "ok",
            "scenario": scenario.model_dump(),
            "scenarios": runtime.scenario_runner.list_scenarios(),
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/load")
async def load_scenario(req: ScenarioLoadRequest):
    """Load and start a scenario from step 1."""
    try:
        step = runtime.scenario_runner.start(req.scenario_id)
        await execute_step_side_effects(step)
        return {"status": "ok", **runtime.scenario_runner.get_status()}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/advance")
async def advance_scenario():
    """Advance to the next step in the active scenario."""
    try:
        step = runtime.scenario_runner.advance()
        if step is None:
            return {"status": "completed", "active": False}
        await execute_step_side_effects(step)
        return {"status": "ok", **runtime.scenario_runner.get_status()}
    except ValueError as e:
        return {"error": str(e)}


@router.get("/status")
async def get_scenario_status():
    """Get the current scenario runner state."""
    return runtime.scenario_runner.get_status()


@router.post("/stop")
async def stop_scenario():
    """Stop the active scenario without completing it."""
    runtime.scenario_runner.stop()
    return {"status": "ok", "active": False}


async def execute_step_side_effects(step):
    """Execute auto-actions, profiles and markers for a scenario step."""
    if step.auto_marker:
        try:
            runtime.session_manager.add_marker(step.auto_marker, {"source": "scenario"})
            runtime.telemetry.log_marker(step.auto_marker, {"source": "scenario"})
        except ValueError:
            pass  # No active session — skip marker

    if step.condition:
        await apply_step_profile(step.condition)

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
        await runtime.router.route_command(action_cmd)


async def apply_step_profile(condition_id: str):
    """Resolve a scenario's ``condition`` through the profile system.

    Legacy conditions are migrated to ``condition_<id>`` profiles at boot, so a
    scenario written against the old vocabulary still resolves — but it now
    takes the same code path as the Profiles tab instead of setting the global
    prompt behind the orchestrator's back.
    """
    profile = runtime.profile_manager.get_profile(condition_id)
    if not profile:
        profile = runtime.profile_manager.get_profile(f"condition_{condition_id}")
    if not profile:
        return

    runtime.orchestrator.apply_profile("all", profile)
    runtime.telemetry.log_session_event("profile_applied", {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "source": "scenario",
    })
