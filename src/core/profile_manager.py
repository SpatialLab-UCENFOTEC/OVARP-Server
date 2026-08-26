"""
Open Virtual Agent Research Platform (OVARP) — Profile Manager

Manages Agent Profiles: rich persona definitions that bundle identity,
voice, personality, guardrails, and avatar into a single switchable unit.
Profiles are loaded from YAML files in the ``profiles/`` directory and
can also be created at runtime via the API.

When a profile is applied to an agent, the system prompt is auto-composed
from all persona fields — backstory, guardrails, and personality traits
are woven into the final LLM prompt automatically.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import yaml
import logging
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

std_log = logging.getLogger("OVARP.profiles")


# ---------------------------------------------------------------------------
# Pydantic models for profile structure
# ---------------------------------------------------------------------------

class ProfileIdentity(BaseModel):
    """Who the agent is — demographics and backstory."""
    age: Optional[int] = None
    gender: Optional[str] = None          # "masculine", "feminine", "neutral"
    role: Optional[str] = None            # e.g. "Virtual therapist"
    backstory: Optional[str] = None

class ProfileVoice(BaseModel):
    """How the agent sounds."""
    provider: str = "auto"                # "openai", "gemini", or "auto"
    voice_id: str = "alloy"
    speed: float = 1.0                    # 0.5 = slow, 2.0 = fast

class ProfilePersonality(BaseModel):
    """How the agent behaves — the prompt and trait knobs."""
    system_prompt: str
    self_disclosure: str = "medium"       # low, medium, high
    formality: str = "medium"
    empathy: str = "medium"

class ProfileGuardrails(BaseModel):
    """Hard rules the agent must always follow."""
    rules: list[str] = Field(default_factory=list)
    max_response_words: Optional[int] = None

class AgentProfile(BaseModel):
    """A complete persona definition for a virtual agent."""
    id: str
    name: str
    identity: Optional[ProfileIdentity] = None
    voice: Optional[ProfileVoice] = None
    personality: Optional[ProfilePersonality] = None
    guardrails: Optional[ProfileGuardrails] = None
    avatar: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt composition — weaves all profile fields into a single LLM prompt
# ---------------------------------------------------------------------------

def build_system_prompt(profile: AgentProfile) -> str:
    """
    Compose a rich system prompt from all profile fields.

    The base system_prompt from personality is augmented with backstory,
    self-disclosure instructions, formality cues, and guardrails — so
    researchers don't have to do manual prompt engineering.
    """
    parts = []

    # Start with the researcher-written base prompt
    if profile.personality and profile.personality.system_prompt:
        parts.append(profile.personality.system_prompt.strip())

    # Identity enrichment
    if profile.identity:
        identity = profile.identity
        if identity.backstory:
            parts.append(f"\n[Backstory]\n{identity.backstory.strip()}")

    # Personality trait instructions
    if profile.personality:
        p = profile.personality

        if p.self_disclosure == "low":
            parts.append(
                "\n[Self-Disclosure] "
                "Share very little about yourself. Keep the focus on the user."
            )
        elif p.self_disclosure == "high":
            parts.append(
                "\n[Self-Disclosure] "
                "Feel free to share personal anecdotes and opinions when relevant."
            )

        if p.formality == "high":
            parts.append(
                "\n[Formality] "
                "Use professional, polished language. Avoid slang."
            )
        elif p.formality == "low":
            parts.append(
                "\n[Formality] "
                "Be casual and conversational. Use everyday language."
            )

        if p.empathy == "high":
            parts.append(
                "\n[Empathy] "
                "Pay close attention to the user's emotional state. "
                "Reflect their feelings and validate them before responding."
            )

    # Guardrails — hard rules
    if profile.guardrails and profile.guardrails.rules:
        rules_text = "\n".join(f"- {r}" for r in profile.guardrails.rules)
        parts.append(f"\n[Guardrails — you MUST follow these rules]\n{rules_text}")

    if profile.guardrails and profile.guardrails.max_response_words:
        parts.append(
            f"\n[Response Length] "
            f"Keep responses under {profile.guardrails.max_response_words} words."
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Profile Manager — loads, stores, and provides profiles
# ---------------------------------------------------------------------------

class ProfileManager:
    """
    Singleton that manages all agent profiles.

    Loads profiles from YAML files on disk and supports runtime creation
    via the API. Profiles can be listed, retrieved, and applied to agents.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._profiles: dict[str, AgentProfile] = {}
        return cls._instance

    def load_profiles(self, profiles_dir: str | Path = "profiles"):
        """Load all .yaml profile files from the given directory."""
        profiles_path = Path(profiles_dir)
        self._profiles_dir = profiles_path
        if not profiles_path.exists():
            std_log.warning(f"Profiles directory not found: {profiles_path.absolute()}")
            return

        count = 0
        for yaml_file in sorted(profiles_path.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                profile = AgentProfile(**data)
                self._profiles[profile.id] = profile
                count += 1
                std_log.info(f"📋 Loaded profile: {profile.id} ({profile.name})")
            except Exception as e:
                std_log.error(f"Failed to load profile {yaml_file.name}: {e}")

        std_log.info(f"📋 Profiles loaded: {count} total")

    def list_profiles(self) -> list[dict]:
        """Returns a summary of all available profiles."""
        results = []
        for profile in self._profiles.values():
            results.append({
                "id": profile.id,
                "name": profile.name,
                "gender": profile.identity.gender if profile.identity else None,
                "role": profile.identity.role if profile.identity else None,
                "avatar": profile.avatar,
                "voice_id": profile.voice.voice_id if profile.voice else None,
            })
        return results

    def get_profile(self, profile_id: str) -> Optional[AgentProfile]:
        """Get a profile by ID, or None if not found."""
        return self._profiles.get(profile_id)

    def create_profile(self, data: dict, persist: bool = True) -> AgentProfile:
        """Create a profile and, by default, write it to the profiles directory.

        Persisting is what makes a profile authored in the console outlive the
        process — without it the console would offer to create personas that
        vanish on the next restart.
        """
        profile = AgentProfile(**data)
        if profile.id in self._profiles:
            raise ValueError(f"Profile '{profile.id}' already exists")

        self._profiles[profile.id] = profile
        if persist:
            self._write_profile(profile)
        std_log.info(f"📋 Profile created: {profile.id} ({profile.name})")
        return profile

    def update_profile(self, profile_id: str, data: dict) -> AgentProfile:
        """Replace a profile's definition, keeping its id."""
        if profile_id not in self._profiles:
            raise ValueError(f"Profile '{profile_id}' not found")

        profile = AgentProfile(**{**data, "id": profile_id})
        self._profiles[profile_id] = profile
        self._write_profile(profile)
        std_log.info(f"📋 Profile updated: {profile_id}")
        return profile

    def duplicate_profile(
        self,
        source_id: str,
        new_id: str,
        new_name: Optional[str] = None,
        persist: bool = True,
    ) -> AgentProfile:
        """Copy an existing profile to a new id and persist it as YAML.

        Conditions in a study are usually one persona with a single trait
        changed, so authoring the variant from scratch invites the copies to
        drift apart in ways the researcher did not intend.
        """
        source = self.get_profile(source_id)
        if not source:
            raise ValueError(f"Profile '{source_id}' not found")
        payload = source.model_dump(mode="json")
        payload["id"] = new_id
        payload["name"] = new_name or f"{source.name} (copy)"
        return self.create_profile(payload, persist=persist)

    def delete_profile(self, profile_id: str) -> bool:
        """Remove a profile and its YAML file."""
        if profile_id not in self._profiles:
            raise ValueError(f"Profile '{profile_id}' not found")

        del self._profiles[profile_id]
        path = self._profile_path(profile_id)
        if path and path.exists():
            path.unlink()
        std_log.info(f"🗑️ Profile deleted: {profile_id}")
        return True

    def _profile_path(self, profile_id: str) -> Optional[Path]:
        directory = getattr(self, "_profiles_dir", None)
        return directory / f"{profile_id}.yaml" if directory else None

    def _write_profile(self, profile: AgentProfile):
        """Serialize a profile to its YAML file."""
        path = self._profile_path(profile.id)
        if path is None:
            std_log.warning(f"⚠️ No profiles directory known — '{profile.id}' stays in memory only")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(profile.model_dump(exclude_none=True),
                      default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def get_composed_prompt(self, profile_id: str) -> Optional[str]:
        """Build the full system prompt for a profile."""
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        return build_system_prompt(profile)

    def migrate_conditions(self, conditions: dict):
        """
        Auto-migrate legacy 'conditions' from config.yaml into profiles.

        Each condition becomes a minimal profile with only personality,
        voice, and avatar — preserving backwards compatibility while
        deprecating the conditions system.
        """
        if not conditions:
            return

        migrated = 0
        for cond_id, cond in conditions.items():
            profile_id = f"condition_{cond_id}"
            # Skip if a real profile with this ID already exists
            if profile_id in self._profiles:
                continue

            # Build a profile from the condition fields
            profile_data = {
                "id": f"condition_{cond_id}",
                "name": f"{cond_id.replace('_', ' ').title()} (migrated)",
                "personality": {
                    "system_prompt": cond.system_prompt,
                },
                "avatar": cond.avatar,
            }

            # Map the condition's voice to a ProfileVoice
            if cond.voice:
                profile_data["voice"] = {
                    "provider": "auto",
                    "voice_id": cond.voice,
                }

            profile = AgentProfile(**profile_data)
            self._profiles[profile.id] = profile
            migrated += 1

        if migrated:
            std_log.info(
                f"📋 Auto-migrated {migrated} legacy condition(s) to profiles "
                f"(the 'conditions:' config section is deprecated — use profiles/ instead)"
            )


# Global accessor
profile_manager = ProfileManager()
