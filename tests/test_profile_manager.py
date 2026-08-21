"""Tests for the Agent Profiles system."""

import pytest
from src.core.profile_manager import (
    ProfileManager,
    AgentProfile,
    ProfileIdentity,
    ProfileVoice,
    ProfilePersonality,
    ProfileGuardrails,
    build_system_prompt,
)


@pytest.fixture
def fresh_manager():
    """Return a fresh ProfileManager (not the singleton) for test isolation."""
    mgr = ProfileManager.__new__(ProfileManager)
    mgr._profiles = {}
    return mgr


@pytest.fixture
def sample_profile():
    return AgentProfile(
        id="test_therapist",
        name="Dr. Test",
        identity=ProfileIdentity(
            age=40,
            gender="masculine",
            role="Therapist",
            backstory="A calm therapist with 15 years experience.",
        ),
        voice=ProfileVoice(provider="gemini", voice_id="Charon", speed=1.0),
        personality=ProfilePersonality(
            system_prompt="You are Dr. Test.",
            self_disclosure="low",
            formality="high",
            empathy="high",
        ),
        guardrails=ProfileGuardrails(
            rules=["Never give medical diagnoses", "Do not discuss politics"],
            max_response_words=150,
        ),
        avatar="male_casual",
    )


class TestProfileModels:
    def test_minimal_profile(self):
        p = AgentProfile(id="min", name="Minimal")
        assert p.id == "min"
        assert p.identity is None
        assert p.voice is None

    def test_full_profile(self, sample_profile):
        assert sample_profile.identity.age == 40
        assert sample_profile.voice.voice_id == "Charon"
        assert sample_profile.personality.empathy == "high"
        assert len(sample_profile.guardrails.rules) == 2


class TestPromptComposition:
    def test_base_prompt_included(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "You are Dr. Test." in prompt

    def test_backstory_included(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "15 years experience" in prompt

    def test_guardrails_included(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "Never give medical diagnoses" in prompt
        assert "MUST follow" in prompt

    def test_formality_high(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "professional" in prompt.lower()

    def test_empathy_high(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "emotional state" in prompt.lower()

    def test_self_disclosure_low(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "very little about yourself" in prompt.lower()

    def test_max_words_included(self, sample_profile):
        prompt = build_system_prompt(sample_profile)
        assert "150 words" in prompt

    def test_minimal_profile_prompt(self):
        p = AgentProfile(id="min", name="Min")
        prompt = build_system_prompt(p)
        assert prompt == ""  # No personality = empty prompt


class TestProfileManager:
    def test_create_profile(self, fresh_manager):
        p = fresh_manager.create_profile({
            "id": "runtime_1",
            "name": "Runtime Agent",
            "personality": {"system_prompt": "You are a test agent."},
        })
        assert p.id == "runtime_1"
        assert fresh_manager.get_profile("runtime_1") is not None

    def test_list_profiles(self, fresh_manager, sample_profile):
        fresh_manager._profiles["test"] = sample_profile
        profiles = fresh_manager.list_profiles()
        assert len(profiles) == 1
        assert profiles[0]["id"] == "test_therapist"
        assert profiles[0]["gender"] == "masculine"

    def test_get_profile_not_found(self, fresh_manager):
        assert fresh_manager.get_profile("nonexistent") is None

    def test_composed_prompt(self, fresh_manager, sample_profile):
        fresh_manager._profiles["test_therapist"] = sample_profile
        prompt = fresh_manager.get_composed_prompt("test_therapist")
        assert "Dr. Test" in prompt

    def test_load_profiles_from_disk(self, fresh_manager, tmp_path):
        # Write a minimal profile YAML
        (tmp_path / "test.yaml").write_text(
            "id: disk_profile\nname: Disk Agent\npersonality:\n  system_prompt: Hello\n"
        )
        fresh_manager.load_profiles(tmp_path)
        assert fresh_manager.get_profile("disk_profile") is not None

    def test_load_profiles_missing_dir(self, fresh_manager):
        """Should not crash when profiles dir is missing."""
        fresh_manager.load_profiles("nonexistent_dir_xyz")
        assert len(fresh_manager.list_profiles()) == 0


class TestConditionsMigration:
    def test_migrate_conditions(self, fresh_manager):
        """Conditions should become profiles with condition_ prefix."""
        from unittest.mock import MagicMock

        cond = MagicMock()
        cond.system_prompt = "Be happy."
        cond.avatar = "happy_avatar"
        cond.voice = "alloy"

        fresh_manager.migrate_conditions({"happy": cond})

        migrated = fresh_manager.get_profile("condition_happy")
        assert migrated is not None
        assert migrated.name == "Happy (migrated)"
        assert migrated.voice.voice_id == "alloy"

    def test_migrate_empty_conditions(self, fresh_manager):
        """Empty conditions dict should be a no-op."""
        fresh_manager.migrate_conditions({})
        assert len(fresh_manager.list_profiles()) == 0

    def test_migrate_skips_existing(self, fresh_manager, sample_profile):
        """Should not overwrite an existing profile with the same ID."""
        fresh_manager._profiles["condition_happy"] = sample_profile

        from unittest.mock import MagicMock
        cond = MagicMock()
        cond.system_prompt = "Be happy."
        cond.avatar = "happy_avatar"
        cond.voice = "alloy"

        fresh_manager.migrate_conditions({"happy": cond})
        # Should still be the original
        assert fresh_manager.get_profile("condition_happy").name == "Dr. Test"


class TestProfilePersistence:
    """A profile authored at runtime must survive a restart, or the console
    would be offering to create personas that vanish."""

    @pytest.fixture
    def mgr(self, tmp_path):
        manager = ProfileManager()
        manager._profiles = {}
        manager.load_profiles(tmp_path)
        return manager

    def _payload(self, profile_id="new_persona"):
        return {
            "id": profile_id,
            "name": "New Persona",
            "personality": {"system_prompt": "Be kind."},
        }

    def test_create_writes_a_yaml_file(self, mgr, tmp_path):
        mgr.create_profile(self._payload())

        assert (tmp_path / "new_persona.yaml").exists()

    def test_created_profile_reloads_from_disk(self, mgr, tmp_path):
        mgr.create_profile(self._payload())

        reloaded = ProfileManager()
        reloaded._profiles = {}
        reloaded.load_profiles(tmp_path)

        assert reloaded.get_profile("new_persona").name == "New Persona"

    def test_duplicate_id_is_rejected(self, mgr):
        mgr.create_profile(self._payload())

        with pytest.raises(ValueError):
            mgr.create_profile(self._payload())

    def test_update_rewrites_the_file(self, mgr, tmp_path):
        mgr.create_profile(self._payload())

        mgr.update_profile("new_persona", {"id": "ignored", "name": "Renamed"})

        reloaded = ProfileManager()
        reloaded._profiles = {}
        reloaded.load_profiles(tmp_path)
        assert reloaded.get_profile("new_persona").name == "Renamed"

    def test_update_keeps_the_original_id(self, mgr):
        mgr.create_profile(self._payload())

        updated = mgr.update_profile("new_persona", {"id": "attempted_rename", "name": "X"})

        assert updated.id == "new_persona"

    def test_delete_removes_profile_and_file(self, mgr, tmp_path):
        mgr.create_profile(self._payload())

        mgr.delete_profile("new_persona")

        assert mgr.get_profile("new_persona") is None
        assert not (tmp_path / "new_persona.yaml").exists()

    def test_deleting_an_unknown_profile_raises(self, mgr):
        with pytest.raises(ValueError):
            mgr.delete_profile("nope")

    def test_persist_false_keeps_it_in_memory_only(self, mgr, tmp_path):
        mgr.create_profile(self._payload(), persist=False)

        assert mgr.get_profile("new_persona") is not None
        assert not (tmp_path / "new_persona.yaml").exists()
