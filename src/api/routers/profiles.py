"""
Open Virtual Agent Research Platform (OVARP) — Agent Profile Routes

Agent personas (identity, voice, personality, guardrails) defined in
``profiles/*.yaml``, applied per agent or to every agent at once. The legacy
``/api/conditions`` endpoints remain as a thin shim over the same profiles.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.runtime import runtime

router = APIRouter(prefix="/api", tags=["profiles"])


@router.get("/profiles")
async def list_profiles():
    """List all available agent profiles."""
    return {"profiles": runtime.profile_manager.list_profiles()}


class ProfileApplyRequest(BaseModel):
    profile_id: str
    agent_id: str = "all"  # Which agent to apply the profile to


class ProfileCreateRequest(BaseModel):
    id: str
    name: str
    identity: dict | None = None
    voice: dict | None = None
    personality: dict | None = None
    guardrails: dict | None = None
    avatar: str | None = None


@router.post("/profiles/apply")
async def apply_profile(req: ProfileApplyRequest):
    """Apply an agent profile — sets system prompt, voice, and avatar for the target agent."""
    profile = runtime.profile_manager.get_profile(req.profile_id)
    if not profile:
        return {"error": f"Profile '{req.profile_id}' not found"}

    if req.agent_id == "all":
        agent_ids = [a.id for a in runtime.config_manager.config.agents]
    else:
        agent_ids = [req.agent_id]

    results = []
    for agent_id in agent_ids:
        runtime.orchestrator.apply_profile(agent_id, profile)

        # Send avatar change to XR clients (if the profile specifies one)
        if profile.avatar:
            from src.core.schemas import BaseCommand
            avatar_cmd = BaseCommand(
                sender="server_orchestrator",
                target_device="all",
                target_agent=agent_id,
                command_type="action",
                command="execute_state",
                subcommand={"avatar": profile.avatar},
            )
            await runtime.router.route_command(avatar_cmd)

        results.append(runtime.orchestrator.get_agent_info(agent_id))

    runtime.telemetry.log_session_event("profile_applied", {
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


@router.post("/profiles/create")
async def create_profile(req: ProfileCreateRequest):
    """Create a new profile at runtime (from WoZ console or XR device)."""
    try:
        profile = runtime.profile_manager.create_profile(req.model_dump(exclude_none=True))
        return {"status": "ok", "profile": profile.model_dump()}
    except Exception as e:
        return {"error": str(e)}


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str):
    """Get full details for a specific profile."""
    profile = runtime.profile_manager.get_profile(profile_id)
    if not profile:
        return {"error": f"Profile '{profile_id}' not found"}
    return profile.model_dump()


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: str, req: ProfileCreateRequest):
    """Replace a profile's definition. Agents already using it keep the old one
    until it is applied again, so an edit never changes a running session."""
    try:
        profile = runtime.profile_manager.update_profile(
            profile_id, req.model_dump(exclude_none=True)
        )
        return {"status": "ok", "profile": profile.model_dump()}
    except Exception as e:
        return {"error": str(e)}


class ProfileDuplicateRequest(BaseModel):
    new_id: str
    new_name: str | None = None


@router.post("/profiles/{profile_id}/duplicate")
async def duplicate_profile(profile_id: str, req: ProfileDuplicateRequest):
    """Copy a profile to a new id and persist it as YAML."""
    try:
        profile = runtime.profile_manager.duplicate_profile(
            profile_id, req.new_id, req.new_name
        )
        return {"status": "ok", "profile": profile.model_dump()}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a profile and its YAML file."""
    try:
        runtime.profile_manager.delete_profile(profile_id)
        return {"status": "ok", "deleted": profile_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/agents/{agent_id}")
async def get_agent_state(agent_id: str):
    """Returns the current profile and state for a specific agent."""
    return runtime.orchestrator.get_agent_info(agent_id)


@router.post("/agents/{agent_id}/reset")
async def reset_agent(agent_id: str):
    """Drop the agent's profile so it follows the global prompt and voice again."""
    info = runtime.orchestrator.clear_profile(agent_id)
    runtime.telemetry.log_session_event("profile_cleared", {"agent_id": agent_id})
    return {"status": "ok", "agent": info}


# --- Deprecated: Conditions (thin shim over profiles) ---

class ConditionApplyRequest(BaseModel):
    condition_id: str


@router.get("/conditions")
async def get_conditions():
    """[Deprecated] Use GET /api/profiles instead. Returns profiles as conditions."""
    return {"conditions": {p["id"]: p for p in runtime.profile_manager.list_profiles()}}


@router.post("/conditions/apply")
async def apply_condition(req: ConditionApplyRequest):
    """[Deprecated] Use POST /api/profiles/apply instead. Redirects to profile application."""
    # Try the condition ID as-is, then with condition_ prefix (from migration)
    profile = runtime.profile_manager.get_profile(req.condition_id)
    if not profile:
        profile = runtime.profile_manager.get_profile(f"condition_{req.condition_id}")
    if not profile:
        return {"error": f"No profile found for condition '{req.condition_id}'"}

    runtime.orchestrator.apply_profile("all", profile)
    runtime.telemetry.log_session_event("condition_applied", {
        "condition_id": req.condition_id,
        "migrated_to_profile": profile.id,
    })
    return {
        "status": "ok",
        "condition_id": req.condition_id,
        "profile_id": profile.id,
        "deprecated": "Use POST /api/profiles/apply instead",
    }
