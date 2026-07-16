"""
Open Virtual Agent Research Platform (OVARP) — Scenario Runner

Manages scripted experiment protocols. Scenarios are YAML-defined sequences
of steps that guide researchers through structured experiment procedures.
Each step can auto-apply conditions, execute actions, and log event markers.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import os
import logging
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
import yaml

std_log = logging.getLogger("OVARP.scenario")


class ScenarioStep(BaseModel):
    """A single step in an experiment protocol."""
    id: str = Field(description="Unique step identifier, e.g. 'intro_greeting'")
    instruction: str = Field(description="Researcher-facing instruction text")
    action: Optional[dict] = Field(default=None, description="Auto-execute command, e.g. {'emotions': 'happy'}")
    condition: Optional[str] = Field(default=None, description="Auto-apply experimental condition")
    auto_marker: Optional[str] = Field(default=None, description="Auto-log marker label when step starts")
    duration_seconds: Optional[int] = Field(default=None, description="Auto-advance after N seconds (0 = manual)")


class Scenario(BaseModel):
    """A complete experiment protocol with ordered steps."""
    id: str = Field(description="Unique scenario identifier")
    name: str = Field(description="Human-readable scenario name")
    description: str = Field(description="Short description of the protocol")
    steps: list[ScenarioStep] = Field(description="Ordered list of protocol steps")


class ScenarioRunner:
    """
    Manages loading and executing scripted experiment scenarios.
    Only one scenario can be active at a time.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._scenarios = {}
            cls._instance._active_scenario = None
            cls._instance._current_step_index = -1
        return cls._instance

    @property
    def active_scenario(self) -> Optional[Scenario]:
        return self._active_scenario

    @property
    def current_step(self) -> Optional[ScenarioStep]:
        if self._active_scenario and 0 <= self._current_step_index < len(self._active_scenario.steps):
            return self._active_scenario.steps[self._current_step_index]
        return None

    @property
    def is_active(self) -> bool:
        return self._active_scenario is not None

    def load_scenarios_from_dir(self, directory: str = "scenarios") -> dict[str, Scenario]:
        """Discover and load all YAML scenario files from the given directory."""
        scenario_dir = Path(directory)
        if not scenario_dir.exists():
            std_log.warning(f"Scenario directory not found: {directory}")
            return {}

        self._scenarios = {}
        for yaml_file in sorted(scenario_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                scenario = Scenario(**data)
                self._scenarios[scenario.id] = scenario
                std_log.info(f"📋 Loaded scenario: {scenario.name} ({len(scenario.steps)} steps)")
            except Exception as e:
                std_log.error(f"Failed to load scenario {yaml_file}: {e}")

        return self._scenarios

    def list_scenarios(self) -> list[dict]:
        """Return a summary list of all loaded scenarios."""
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "step_count": len(s.steps),
            }
            for s in self._scenarios.values()
        ]

    def start(self, scenario_id: str) -> ScenarioStep:
        """Start a scenario from step 0."""
        if scenario_id not in self._scenarios:
            raise ValueError(f"Unknown scenario '{scenario_id}'")

        self._active_scenario = self._scenarios[scenario_id]
        self._current_step_index = 0
        step = self.current_step
        std_log.info(f"🎬 Scenario STARTED: {self._active_scenario.name} | step 1/{len(self._active_scenario.steps)}")
        return step

    def advance(self) -> Optional[ScenarioStep]:
        """Advance to the next step. Returns None if scenario is complete."""
        if not self._active_scenario:
            raise ValueError("No active scenario to advance")

        self._current_step_index += 1

        if self._current_step_index >= len(self._active_scenario.steps):
            std_log.info(f"✅ Scenario COMPLETED: {self._active_scenario.name}")
            completed = self._active_scenario
            self._active_scenario = None
            self._current_step_index = -1
            return None

        step = self.current_step
        std_log.info(
            f"▶ Scenario step {self._current_step_index + 1}/{len(self._active_scenario.steps)} "
            f"| {step.id}: {step.instruction[:60]}"
        )
        return step

    def stop(self):
        """Stop the active scenario without completing it."""
        if self._active_scenario:
            std_log.info(f"⏹ Scenario STOPPED: {self._active_scenario.name}")
        self._active_scenario = None
        self._current_step_index = -1

    def get_status(self) -> dict:
        """Return the current scenario runner state for the API."""
        if not self._active_scenario:
            return {"active": False}

        total = len(self._active_scenario.steps)
        current = self._current_step_index + 1
        step = self.current_step

        return {
            "active": True,
            "scenario_id": self._active_scenario.id,
            "scenario_name": self._active_scenario.name,
            "current_step": current,
            "total_steps": total,
            "progress_pct": round((current / total) * 100),
            "step": {
                "id": step.id,
                "instruction": step.instruction,
                "action": step.action,
                "condition": step.condition,
                "auto_marker": step.auto_marker,
                "duration_seconds": step.duration_seconds,
            } if step else None,
        }


# Global accessor
scenario_runner = ScenarioRunner()
