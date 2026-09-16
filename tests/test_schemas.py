"""
Open Virtual Agent Research Platform (OVARP) — Schema Validation Tests

Unit tests for ``BaseCommand`` Pydantic schema validation. Verifies
that valid commands are parsed correctly, unregistered devices are
rejected, and invalid custom action values raise ``ValidationError``.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import pytest
from pydantic import ValidationError

from src.core.config import config_manager
from src.core.schemas import BaseCommand

# Force the config manager to load the config.yaml before trying to instantiate Baseline schema validations
config_manager.load_config()

def test_valid_command_parsing():
    """Test that a command matching the config processes successfully."""
    valid_payload = {
        "sender": "quest_vr_01",
        "target_device": "all",
        "target_agent": "agent_alpha",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {
            "emotions": "happy"
        }
    }
    
    cmd = BaseCommand(**valid_payload)
    assert cmd.sender == "quest_vr_01"
    assert cmd.target_device == "all"
    assert cmd.target_agent == "agent_alpha"
    assert isinstance(cmd.subcommand, dict)
    assert cmd.subcommand["emotions"] == "happy"

def test_invalid_device_rejected():
    """Test that an unregistered device throws a Pydantic Validation Error."""
    invalid_payload = {
        "sender": "quest_vr_01",
        "target_device": "unregistered_device",
        "target_agent": "agent_alpha",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {}
    }
    
    with pytest.raises(ValidationError) as exc_info:
        BaseCommand(**invalid_payload)
        
    assert "Invalid target_device 'unregistered_device'" in str(exc_info.value)
    
def test_invalid_action_rejected():
    """Test that an unregistered custom action throws a Pydantic Validation Error."""
    invalid_payload = {
        "sender": "quest_vr_01",
        "target_device": "all",
        "target_agent": "agent_alpha",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {
            "emotions": "confused" # Not in the config.yaml MVP list
        }
    }
    
    with pytest.raises(ValidationError) as exc_info:
        BaseCommand(**invalid_payload)
        
    assert "Invalid value" in str(exc_info.value)
    assert "confused" in str(exc_info.value)

def test_valid_movement_command():
    """Test that movement commands from config pass validation."""
    valid_payload = {
        "sender": "quest_vr_01",
        "target_device": "all",
        "target_agent": "agent_alpha",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {
            "movement": "move_closer"
        }
    }
    
    cmd = BaseCommand(**valid_payload)
    assert cmd.subcommand["movement"] == "move_closer"

def test_invalid_movement_rejected():
    """Test that unregistered movement values are rejected."""
    invalid_payload = {
        "sender": "quest_vr_01",
        "target_device": "all",
        "target_agent": "agent_alpha",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {
            "movement": "teleport"
        }
    }
    
    with pytest.raises(ValidationError) as exc_info:
        BaseCommand(**invalid_payload)
    
    assert "Invalid value" in str(exc_info.value)
    assert "teleport" in str(exc_info.value)

def test_valid_avatar_command():
    """Test that avatar change commands pass validation."""
    valid_payload = {
        "sender": "quest_vr_01",
        "target_device": "all",
        "target_agent": "agent_alpha",
        "command_type": "action",
        "command": "execute_state",
        "subcommand": {
            "avatar": "robot"
        }
    }
    
    cmd = BaseCommand(**valid_payload)
    assert cmd.subcommand["avatar"] == "robot"

def test_valid_new_animations():
    """Test that the newly added animation values pass validation."""
    for animation in ["clap", "bow", "thumbs_up", "thinking", "shrug", "dance"]:
        valid_payload = {
            "sender": "quest_vr_01",
            "target_device": "all",
            "target_agent": "agent_alpha",
            "command_type": "action",
            "command": "execute_state",
            "subcommand": {
                "actions": animation
            }
        }
        cmd = BaseCommand(**valid_payload)
        assert cmd.subcommand["actions"] == animation
