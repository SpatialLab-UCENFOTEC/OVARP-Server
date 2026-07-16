"""
Tests for ScenarioRunner — loading, starting, advancing, and stopping scenarios.
"""
import os
import pytest
import tempfile
import yaml

# Allow import of src modules
os.environ["OVARP_TESTING"] = "1"

from src.core.scenario_runner import ScenarioRunner, Scenario, ScenarioStep


@pytest.fixture(autouse=True)
def reset_scenario_runner():
    """Reset the singleton between tests."""
    runner = ScenarioRunner()
    runner._scenarios = {}
    runner._active_scenario = None
    runner._current_step_index = -1
    yield runner
    runner._scenarios = {}
    runner._active_scenario = None
    runner._current_step_index = -1


@pytest.fixture
def scenario_dir(tmp_path):
    """Create a temp directory with a test scenario YAML."""
    scenario_data = {
        "id": "test_scenario",
        "name": "Test Scenario",
        "description": "A test protocol",
        "steps": [
            {"id": "step1", "instruction": "Do the first thing."},
            {"id": "step2", "instruction": "Do the second thing.", "condition": "neutral", "auto_marker": "step2_start"},
            {"id": "step3", "instruction": "Wrap up.", "action": {"emotions": "happy"}},
        ]
    }
    yaml_file = tmp_path / "test_scenario.yaml"
    with open(yaml_file, "w") as f:
        yaml.dump(scenario_data, f)
    return str(tmp_path)


def test_load_scenarios(reset_scenario_runner, scenario_dir):
    """Test loading scenario YAML files from a directory."""
    runner = reset_scenario_runner
    loaded = runner.load_scenarios_from_dir(scenario_dir)
    assert "test_scenario" in loaded
    assert loaded["test_scenario"].name == "Test Scenario"
    assert len(loaded["test_scenario"].steps) == 3


def test_list_scenarios(reset_scenario_runner, scenario_dir):
    """Test listing loaded scenarios."""
    runner = reset_scenario_runner
    runner.load_scenarios_from_dir(scenario_dir)
    listing = runner.list_scenarios()
    assert len(listing) == 1
    assert listing[0]["id"] == "test_scenario"
    assert listing[0]["step_count"] == 3


def test_start_scenario(reset_scenario_runner, scenario_dir):
    """Test starting a scenario."""
    runner = reset_scenario_runner
    runner.load_scenarios_from_dir(scenario_dir)
    step = runner.start("test_scenario")
    assert step.id == "step1"
    assert runner.is_active
    assert runner.current_step.id == "step1"


def test_advance_scenario(reset_scenario_runner, scenario_dir):
    """Test advancing through scenario steps."""
    runner = reset_scenario_runner
    runner.load_scenarios_from_dir(scenario_dir)
    runner.start("test_scenario")

    # Advance to step 2
    step = runner.advance()
    assert step.id == "step2"
    assert step.condition == "neutral"
    assert step.auto_marker == "step2_start"

    # Advance to step 3
    step = runner.advance()
    assert step.id == "step3"
    assert step.action == {"emotions": "happy"}

    # Advance past the end — should complete
    step = runner.advance()
    assert step is None
    assert not runner.is_active


def test_stop_scenario(reset_scenario_runner, scenario_dir):
    """Test stopping a scenario mid-way."""
    runner = reset_scenario_runner
    runner.load_scenarios_from_dir(scenario_dir)
    runner.start("test_scenario")
    assert runner.is_active
    runner.stop()
    assert not runner.is_active


def test_get_status_active(reset_scenario_runner, scenario_dir):
    """Test get_status with an active scenario."""
    runner = reset_scenario_runner
    runner.load_scenarios_from_dir(scenario_dir)
    runner.start("test_scenario")
    status = runner.get_status()
    assert status["active"] is True
    assert status["scenario_id"] == "test_scenario"
    assert status["current_step"] == 1
    assert status["total_steps"] == 3
    assert status["progress_pct"] == 33
    assert status["step"]["id"] == "step1"


def test_get_status_inactive(reset_scenario_runner):
    """Test get_status with no active scenario."""
    runner = reset_scenario_runner
    status = runner.get_status()
    assert status["active"] is False


def test_start_unknown_scenario_raises(reset_scenario_runner):
    """Test that starting an unknown scenario raises ValueError."""
    runner = reset_scenario_runner
    with pytest.raises(ValueError, match="Unknown scenario"):
        runner.start("nonexistent")


def test_advance_without_start_raises(reset_scenario_runner):
    """Test that advancing without a started scenario raises ValueError."""
    runner = reset_scenario_runner
    with pytest.raises(ValueError, match="No active scenario"):
        runner.advance()


def test_load_empty_directory(reset_scenario_runner, tmp_path):
    """Test loading from an empty directory returns empty dict."""
    runner = reset_scenario_runner
    loaded = runner.load_scenarios_from_dir(str(tmp_path))
    assert loaded == {}


def test_load_nonexistent_directory(reset_scenario_runner):
    """Test loading from a nonexistent directory returns empty dict."""
    runner = reset_scenario_runner
    loaded = runner.load_scenarios_from_dir("/nonexistent/path")
    assert loaded == {}
