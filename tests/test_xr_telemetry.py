"""
Tests for XR Telemetry ingest endpoint.
"""
import os
import pytest

os.environ["OVARP_TESTING"] = "1"

from fastapi.testclient import TestClient
from src.main import app


client = TestClient(app)


def test_xr_telemetry_ingest():
    """Test that the XR telemetry endpoint accepts batched frames."""
    batch = {
        "device_id": "quest_vr_01",
        "frames": [
            {"timestamp": 1710000000.0, "head_pos_x": 0.0, "head_pos_y": 1.6, "head_pos_z": 0.0},
            {"timestamp": 1710000000.1, "head_pos_x": 0.1, "head_pos_y": 1.6, "head_pos_z": 0.05},
        ]
    }
    resp = client.post("/api/xr/telemetry", json=batch)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["frames_received"] == 2


def test_xr_telemetry_empty_batch():
    """Test that an empty batch is accepted."""
    batch = {"device_id": "quest_vr_01", "frames": []}
    resp = client.post("/api/xr/telemetry", json=batch)
    assert resp.status_code == 200
    assert resp.json()["frames_received"] == 0


def test_xr_telemetry_rich_frames():
    """Test with full XR tracking data (head, hands, gaze)."""
    batch = {
        "device_id": "quest_vr_01",
        "frames": [
            {
                "timestamp": 1710000000.0,
                "head_pos_x": 0.0, "head_pos_y": 1.6, "head_pos_z": 0.0,
                "head_rot_x": 0.0, "head_rot_y": 0.0, "head_rot_z": 0.0, "head_rot_w": 1.0,
                "hand_left_pos_x": -0.3, "hand_left_pos_y": 1.0, "hand_left_pos_z": 0.2,
                "hand_right_pos_x": 0.3, "hand_right_pos_y": 1.0, "hand_right_pos_z": 0.2,
                "gaze_target": "agent_alpha",
            }
        ]
    }
    resp = client.post("/api/xr/telemetry", json=batch)
    assert resp.status_code == 200
    assert resp.json()["frames_received"] == 1
