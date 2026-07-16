import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os
import json

# Setup environment variable for tests
os.environ["OVARP_TESTING"] = "1"

# Import app after setting env vars
from src.main import app
from src.core.config import config_manager, OVARPConfig
from unittest.mock import PropertyMock

@pytest.fixture
def mock_config():
    """Provides a mocked OVARPConfig for testing."""
    data = {
        "experiment": {
            "name": "Test Experiment",
            "description": "desc",
            "version": "1.0.0"
        },
        "devices": [
            {"id": "vr_headset", "name": "Quest 3", "type": "xr"}
        ],
        "agents": [
            {"id": "agent_test", "name": "Test Agent", "description": "desc"},
            {"id": "agent_alpha", "name": "Alpha Agent", "description": "desc"}
        ],
        "custom_commands": {
            "emotions": {"description": "desc", "values": ["happy", "sad"]},
            "actions": {"description": "desc", "values": ["wave", "nod", "clap", "bow", "thumbs_up", "thinking", "shrug", "dance"]},
            "movement": {"description": "desc", "values": ["move_closer", "move_farther", "move_left", "move_right", "reset_position"]},
            "avatar": {"description": "desc", "values": ["default", "male_casual", "female_formal", "robot"]}
        },
        "conditions": {
            "empathetic": {
                "description": "High empathy condition",
                "system_prompt": "Be empathetic and warm.",
                "avatar": "female_formal",
                "voice": "Kore"
            },
            "neutral": {
                "description": "Neutral condition",
                "system_prompt": "Be neutral and factual.",
                "avatar": "default",
                "voice": "Puck"
            }
        }
    }
    return OVARPConfig(**data)

@pytest.fixture(autouse=True)
def patch_config_manager(mocker, mock_config):
    """Automatically patches the global config_manager to return our mock OVARPConfig."""
    # We patch the property 'config' on the ConfigManager class
    mocker.patch("src.core.config.ConfigManager.config", new_callable=PropertyMock, return_value=mock_config)
    return config_manager

@pytest_asyncio.fixture
async def async_client():
    """Provides an AsyncClient bound to the FastAPI app for HTTP/WS testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
