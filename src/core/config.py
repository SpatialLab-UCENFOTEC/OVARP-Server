"""
Open Virtual Agent Research Platform (OVARP) — Configuration Manager

Loads and validates the experiment configuration from ``config.yaml``.
Defines Pydantic models for devices, agents, and custom command categories,
and exposes a singleton ``ConfigManager`` for global access.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class DeviceConfig(BaseModel):
    """A connected device in the experiment (VR headset, web dashboard, etc.)."""
    id: str
    name: str
    type: str

class AgentConfig(BaseModel):
    """A virtual agent that can be controlled and addressed by commands."""
    id: str
    name: str
    description: Optional[str] = None

class CustomCommandCategory(BaseModel):
    """A named group of commands (e.g. emotions, actions) with allowed values."""
    description: str
    values: List[str]

class ConditionConfig(BaseModel):
    """An experimental condition preset — bundles a system prompt with avatar/voice."""
    description: str
    system_prompt: str
    avatar: Optional[str] = None
    voice: Optional[str] = None

class TtsVoiceConfig(BaseModel):
    """A single TTS voice option with gender metadata for the UI."""
    id: str
    label: str
    gender: str  # "masculine", "feminine", or "neutral"

class EventMarkerPreset(BaseModel):
    """A pre-programmed event marker that researchers can trigger with one click."""
    id: str = Field(description="Machine-readable identifier, e.g. 'task_started'")
    label: str = Field(description="Human-readable button label")
    description: Optional[str] = Field(default=None, description="Tooltip/help text")
    color: Optional[str] = Field(default=None, description="CSS color for the button, e.g. '#28a745'")

class ExperimentConfig(BaseModel):
    name: str
    description: str
    version: str

class OVARPConfig(BaseModel):
    """Root configuration model, parsed from config.yaml."""
    experiment: ExperimentConfig
    client_url: Optional[str] = Field(
        default=None,
        description="Where the participant-facing client is hosted, so the console can open it",
    )
    devices: List[DeviceConfig]
    agents: List[AgentConfig]
    custom_commands: Dict[str, CustomCommandCategory]
    conditions: Optional[Dict[str, ConditionConfig]] = None
    tts: Optional[Dict[str, List[TtsVoiceConfig]]] = None
    event_markers: Optional[List[EventMarkerPreset]] = None

class ConfigManager:
    """Singleton to load and manage the dynamic configuration throughout the server."""
    _instance = None
    _config: Optional[OVARPConfig] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
        
    def load_config(self, config_path: str | Path = "config.yaml") -> OVARPConfig:
        """Loads and parses the YAML config file into Pydantic models."""
        p = Path(config_path)
        if not p.exists():
            raise FileNotFoundError(f"Configuration file not found at {p.absolute()}")
            
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        self._config = OVARPConfig(**data)
        return self._config
        
    @property
    def config(self) -> OVARPConfig:
        if self._config is None:
            raise ValueError("Config not loaded. Call load_config() first.")
        return self._config

    def get_valid_devices(self) -> List[str]:
        return [dev.id for dev in self.config.devices] + ["all"]
        
    def get_valid_agents(self) -> List[str]:
        return [agent.id for agent in self.config.agents] + ["all"]

# Global accessor
config_manager = ConfigManager()
