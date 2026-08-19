"""Protocol YAML files used for researcher usability and latency validation."""

import os

os.environ["OVARP_TESTING"] = "1"

from src.core.scenario_runner import ScenarioRunner


def test_validation_protocol_yamls_load():
    runner = ScenarioRunner()
    loaded = runner.load_scenarios_from_dir("scenarios")
    assert "researcher_usability" in loaded
    assert "latency_validation" in loaded
    assert loaded["researcher_usability"].steps[-1].id == "evaluation"
    assert loaded["latency_validation"].steps[1].auto_marker == "latency_turn_text"
    labels = {step.auto_marker for step in loaded["latency_validation"].steps}
    assert "latency_setup" in labels
    assert "latency_debrief" in labels
