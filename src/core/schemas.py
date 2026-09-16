"""
Open Virtual Agent Research Platform (OVARP) — Command Schemas

Defines the ``BaseCommand`` Pydantic model that is the universal message
structure flowing through ZMQ and WebSocket transports. Commands are
validated dynamically against the current experiment configuration loaded
from ``config.yaml``.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, Literal
import json

from src.core.config import config_manager

class BaseCommand(BaseModel):
    """
    Universal Command structure that flows through ZMQ and WebSockets.
    Validated dynamically against the current Experiment Configuration.
    """
    sender: str = Field(description="Entity sending the command (e.g., 'server', 'agent_alpha', 'web_panel_01')")
    target_device: str = Field(description="Target device ID or 'all'")
    target_agent: str = Field(description="Target agent ID or 'all'")
    command_type: Literal["audio", "message", "action", "scene_change", "system"]
    command: str = Field(description="Main instruction or payload")
    subcommand: Optional[Dict[str, Any]] = Field(default=None, description="Additional structured parameters")

    @field_validator('target_device')
    def validate_target_device(cls, v):
        valid = config_manager.get_valid_devices()
        if v not in valid:
            raise ValueError(f"Invalid target_device '{v}'. Must be one of {valid}")
        return v
        
    @field_validator('target_agent')
    def validate_target_agent(cls, v):
        valid = config_manager.get_valid_agents()
        if v not in valid:
            raise ValueError(f"Invalid target_agent '{v}'. Must be one of {valid}")
        return v
        
    @field_validator('subcommand')
    def validate_subcommand(cls, v):
        if v is None:
            return v
        
        # Only validate action/state subcommands against our custom dicts for now
        config = config_manager.config
        if not config or not config.custom_commands:
            return v

        for key, val in v.items():
            if key in config.custom_commands:
                valid_vals = config.custom_commands[key].values
                if val not in valid_vals:
                    raise ValueError(f"Invalid value '{val}' for command category '{key}'. Must be in {valid_vals}")
        return v

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "BaseCommand":
        return cls(**json.loads(json_str))
