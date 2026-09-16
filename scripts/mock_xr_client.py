"""
Open Virtual Agent Research Platform (OVARP) — Mock XR Client

Development utility that simulates a Unity/Unreal XR client connecting
to the OVARP server via ZeroMQ. Sends periodic telemetry messages and
listens for server commands. Useful for testing the ZMQ transport
pipeline without a real XR headset.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
import zmq
import zmq.asyncio
import json
import uuid

async def xr_client_mock():
    """
    Simulates a Unity/Unreal XR Client connecting to the Python Server via ZMQ.
    """
    ctx = zmq.asyncio.Context()
    
    # 1. Setup Publisher (to send Telemetry TO Server)
    pub = ctx.socket(zmq.PUB)
    pub.connect("tcp://127.0.0.1:5556")  # Connect to Server's SUB port
    
    # 2. Setup Subscriber (to receive Commands FROM Server)
    sub = ctx.socket(zmq.SUB)
    sub.connect("tcp://127.0.0.1:5555")  # Connect to Server's PUB port
    sub.setsockopt_string(zmq.SUBSCRIBE, "") 
    
    print("Mock XR Client connected to OVARP Server.")
    
    # Task to listen for commands
    async def listen():
        while True:
            msg = await sub.recv_string()
            print(f"[XR CLIENT] Received from Server: {msg}")

    # Task to send telemetry
    async def send_telemetry():
        while True:
            # Valid schema matching our config
            payload = {
                "sender": "quest_vr_01",
                "target_device": "all",
                "target_agent": "agent_alpha",
                "command_type": "scene_change",
                "command": "position_update",
                "subcommand": {"x": 1.0, "y": 2.5, "z": -1.2}
            }
            await pub.send_string(json.dumps(payload))
            print("[XR CLIENT] Sent Telemetry block")
            await asyncio.sleep(2)  # Emit every 2 seconds
            
    # Send a bad payload to test validation
    async def send_bad_telemetry():
        await asyncio.sleep(5)
        bad_payload = {
            "sender": "quest_vr_01",
            "target_device": "wrong_device_id", # Should fail Pydantic validation
            "target_agent": "all",
            "command_type": "invalid_type",
            "command": "test"
        }
        await pub.send_string(json.dumps(bad_payload))
        print("[XR CLIENT] Sent BAD Validation Telemetry block")

    await asyncio.gather(listen(), send_telemetry(), send_bad_telemetry())

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(xr_client_mock())
    except KeyboardInterrupt:
        print("Exiting...")
