# Unity Integration Guide: Open Virtual Agent Research Platform (OVARP)

This manual provides all the necessary information for a Unity Developer to connect a 3D XR application (PCVR, Meta Quest, WebGL) to the OVARP Server.

OVARP acts as the "brain," handling Speech-to-Text (STT), Large Language Model (LLM) processing, and Text-to-Speech (TTS) synthesis. Unity acts as the "body," handling user microphone input, 3D rendering, avatar lip-sync, and animations.

---

## 1. Connection Protocols

The OVARP Server supports two concurrent protocols. You only need to implement **one**.

### Option A: WebSockets (Recommended)
Best for Meta Quest, WebGL, and mobile builds.
- **URL**: `ws://<server_ip>:8000/ws/client/<your_client_id>`
  - *Example*: `ws://192.68.1.100:8000/ws/client/quest_vr_01`
- **Unity Package**: We recommend [NativeWebSocket](https://github.com/endel/NativeWebSocket) or Unity's native `System.Net.WebSockets.ClientWebSocket`.

### Option B: ZeroMQ (Local/PCVR)
Best for low-latency desktop VR (PCVR) running on the same network or local machine.
- **PUB/SUB Port**: `tcp://<server_ip>:5555` (Subscribe to receive commands from the server).
  - *Note*: You MUST subscribe to your specific `device_id` AND the `"all"` topic. Otherwise, you will not receive messages.
- **REQ/REP Port**: `tcp://<server_ip>:5556` (Send requests to the server).
- **Unity Package**: [NetMQ](https://github.com/zeromq/netmq) via NuGet.

---

## 2. Universal Payload Structure

Every message sent to or received from the OVARP Server uses a strict JSON schema called `BaseCommand`.

```json
{
  "sender": "quest_vr_01",         // Your Device ID 
  "target_device": "server",       // Who the message is for
  "target_agent": "agent_alpha",   // The specific Avatar/Agent ID
  "command_type": "audio",         // Can be: "audio", "message", "action", "scene_change", "system"
  "command": "stt_request",        // The specific action
  "subcommand": {                  // Optional: Data payload
    "key": "value"
  }
}
```

> **Important Configuration Note**: 
> The values for `sender`, `target_device`, and `target_agent` MUST match the IDs declared in the server's `config.yaml`. Default IDs are:
> - Devices: `quest_vr_01`, `quest_vr_02`, `woz_console`
> - Agents: `agent_alpha`, `agent_beta`

---

## 3. Scaling: Multiple Headsets & Multiple Servers

The OVARP Server architecture supports scaling up to accommodate multiple users.

### Scenario A: Multiple Quest 3s connecting to ONE Server
If you have three users in the same physical space (or remote) connecting to the same embodied agent, you must configure the server to recognize them.
1. Open the server's `config.yaml`.
2. Under the `devices` array, add the new headsets:
```yaml
devices:
  - id: "quest_vr_01"
    name: "Player 1 VR Headset"
  - id: "quest_vr_02"
    name: "Player 2 VR Headset"
  - id: "quest_vr_03"
    name: "Player 3 VR Headset"
```
3. In Unity, modify the connecting script for each headset to use its specific `device_id`.
   - **WebSocket:** Connect to `ws://server_ip:8000/ws/client/quest_vr_02`.
   - **ZeroMQ:** Subscribe to the `"quest_vr_02"` topic AND the `"all"` topic. Set the `sender` in JSON payloads to `"quest_vr_02"`.
4. The server will now automatically route actions and audio **only** to the headset that is currently interacting with the agent. 

### Scenario B: Multiple Quest 3s connecting to MULTIPLE Servers (Load Balancing)
LLMs and TTS generation require significant processing. If you have 10 headsets, one server might bottleneck.
1. Deploy the OVARP Server codebase onto multiple physical machines or cloud instances (e.g., Server A at `192.168.1.10`, Server B at `192.168.1.20`).
2. Group your headsets in Unity. 
   - Headsets 1-5 connect their WebSockets to `ws://192.168.1.10:8000/...`
   - Headsets 6-10 connect their WebSockets to `ws://192.168.1.20:8000/...`
3. Because OVARP is stateless between requests (the conversation history memory is maintained in the Orchestrator per server instance), each server runs its own independent AI agent. No special configuration is needed; just point the Unity clients to the IP address of the server you want them to talk to.

---

## 4. Core Workflows

### A. Sending Voice (Microphone to STT)
When the user speaks, record the microphone data in Unity, convert it to a `.WAV` byte array, encode it in Base64, and send it to the server.

**Unity -> Server (JSON Payload)**:
```json
{
  "sender": "quest_vr_01",
  "target_device": "server",
  "target_agent": "agent_alpha",
  "command_type": "audio",
  "command": "stt_request",
  "subcommand": {
    "audio_base64": "UklGR...<base64 string>..."
  }
}
```

### B. Sending Text (Direct LLM Request)
If you have a virtual keyboard or a debug UI, you can skip the STT and send text directly to the LLM.

**Unity -> Server (JSON Payload)**:
```json
{
  "sender": "quest_vr_01",
  "target_device": "server",
  "target_agent": "agent_alpha",
  "command_type": "message",
  "command": "llm_request",
  "subcommand": {
    "text": "Hello, how are you today?"
  }
}
```

### C. Receiving Agent Audio Responses (TTS)
When the LLM finishes thinking, the server generates audio and streams it down in base64 chunks. You must capture these chunks, decode them into byte arrays, and buffer them into a Unity `AudioClip` for the avatar to speak.

**Server -> Unity  (Incoming JSON)**:
```json
{
  "sender": "server",
  "target_device": "quest_vr_01",
  "target_agent": "agent_alpha",
  "command_type": "audio",
  "command": "tts_chunk",
  "subcommand": {
    "audio_base64": "UklGR..." // Part of the continuous WAV audio
  }
}
```
*Note: Depending on the provider (OpenAI vs Gemini), the audio will be either MP3 or WAV format.*

When the agent finishes talking, the server sends a completion signal:
```json
{
  "sender": "server",
  "target_device": "quest_vr_01",
  "target_agent": "agent_alpha",
  "command_type": "audio",
  "command": "tts_complete"
}
```

### D. Receiving Agent Actions (Emotions & Body Language)
The LLM can decide what emotion to show or what animation to play alongside its voice. This is sent dynamically.

**Server -> Unity (Incoming JSON)**:
```json
{
  "sender": "server",
  "target_device": "quest_vr_01",
  "target_agent": "agent_alpha",
  "command_type": "action",
  "command": "agent_action",
  "subcommand": {
    "emotion": "joy",       // Values: neutral, joy, sorrow, angry, fun, surprised
    "animation": "wave"     // Custom values defined in config.yaml
  }
}
```
In Unity, parse the `subcommand`, look for `emotion` or `animation`, and trigger the corresponding BlendShapes or Animator triggers on your VRM/3D Model.

---

## 4. Implementation Steps for Unity Dev

1. **Connect**: Open a standard WebSocket connection to `ws://server_ip:8000/ws/client/quest_vr_01` (Replace `quest_vr_01` with your actual device ID).
2. **Handle OnMessage**: Parse incoming text as JSON. Switch based on `command_type` and `command`.
3. **Audio Playback**: Use `Convert.FromBase64String()` on the incoming `tts_chunk` payloads. Pipe the byte arrays into a Unity AudioClip or use the Meta MR Utility Kit's audio streaming tools.
4. **Lip Sync**: Attach a script (like Oculus OVRLipSync) to the AudioSource playing the TTS so the avatar's mouth moves automatically with the audio.
5. **Mic Recording**: Use `Microphone.Start()` in Unity. Ensure you trim silence, package the clip as a WAV byte array, Base64 encode it, and construct the `stt_request` JSON to send over the socket.

---

## 5. XR Telemetry Ingest

OVARP provides a dedicated REST endpoint for streaming XR tracking data (head pose, hand tracking, gaze vectors) from XR headsets. This data is stored alongside session events for synchronized analysis.

### Endpoint

`POST /api/xr/telemetry`

### Payload

```json
{
  "device_id": "quest_vr_01",
  "frames": [
    {
      "timestamp": 1711234567.123,
      "head_position": { "x": 0.0, "y": 1.65, "z": 0.0 },
      "head_rotation": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 },
      "left_hand_position": { "x": -0.3, "y": 1.0, "z": 0.2 },
      "right_hand_position": { "x": 0.3, "y": 1.0, "z": 0.2 },
      "gaze_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
    }
  ]
}
```

### Unity Implementation (C#)

We recommend batching frames (e.g., every 200ms) rather than sending per-frame to avoid overwhelming the network:

```csharp
using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System.Collections.Generic;

public class OVARPTelemetry : MonoBehaviour
{
    [SerializeField] private string serverUrl = "http://192.168.1.100:8000";
    [SerializeField] private string deviceId = "quest_vr_01";
    [SerializeField] private float batchInterval = 0.2f; // 5 batches/sec

    private List<Dictionary<string, object>> frameBuffer = new();

    void Update()
    {
        // Capture tracking data each frame
        var frame = new Dictionary<string, object>
        {
            ["timestamp"] = Time.realtimeSinceStartupAsDouble,
            ["head_position"] = VecToDict(Camera.main.transform.position),
            ["head_rotation"] = QuatToDict(Camera.main.transform.rotation)
        };
        frameBuffer.Add(frame);
    }

    IEnumerator Start()
    {
        while (true)
        {
            yield return new WaitForSeconds(batchInterval);
            if (frameBuffer.Count > 0)
            {
                StartCoroutine(SendBatch(new List<Dictionary<string, object>>(frameBuffer)));
                frameBuffer.Clear();
            }
        }
    }

    IEnumerator SendBatch(List<Dictionary<string, object>> frames)
    {
        var payload = JsonUtility.ToJson(new { device_id = deviceId, frames });
        var request = new UnityWebRequest($"{serverUrl}/api/xr/telemetry", "POST");
        request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(payload));
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        yield return request.SendWebRequest();
    }

    Dictionary<string, float> VecToDict(Vector3 v) =>
        new() { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z };
    Dictionary<string, float> QuatToDict(Quaternion q) =>
        new() { ["x"] = q.x, ["y"] = q.y, ["z"] = q.z, ["w"] = q.w };
}
```

---

## 6. Session Management (REST API)

OVARP tracks experiment sessions with participant IDs, elapsed time, and event markers. Your Unity client can programmatically start/end sessions.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/session/status` | Get current session state |
| `POST` | `/api/session/start`  | Start session (`{"participant_id": "P001"}`) |
| `POST` | `/api/session/pause`  | Pause active session |
| `POST` | `/api/session/resume` | Resume paused session |
| `POST` | `/api/session/end`    | End session and retrieve data |
| `POST` | `/api/session/marker` | Add event marker (`{"label": "task_start"}`) |

### Example: Starting a Session from Unity

```csharp
IEnumerator StartExperimentSession(string participantId)
{
    string json = $"{{\"participant_id\": \"{participantId}\"}}";
    var request = new UnityWebRequest($"{serverUrl}/api/session/start", "POST");
    request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(json));
    request.downloadHandler = new DownloadHandlerBuffer();
    request.SetRequestHeader("Content-Type", "application/json");
    yield return request.SendWebRequest();
    Debug.Log($"Session started: {request.downloadHandler.text}");
}
```

### Example: Adding an Event Marker

```csharp
IEnumerator AddMarker(string label, string metadata = null)
{
    string json = metadata != null
        ? $"{{\"label\": \"{label}\", \"metadata\": {metadata}}}"
        : $"{{\"label\": \"{label}\"}}";
    var request = new UnityWebRequest($"{serverUrl}/api/session/marker", "POST");
    request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(json));
    request.downloadHandler = new DownloadHandlerBuffer();
    request.SetRequestHeader("Content-Type", "application/json");
    yield return request.SendWebRequest();
}
```

---

## 7. Agent Profiles (REST API)

Profiles are rich persona definitions (identity, voice, personality, guardrails, backstory) that can be applied to any agent at runtime. This is useful for switching between experimental conditions directly from the VR app.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/profiles`           | List all profiles |
| `GET`  | `/api/profiles/{id}`      | Get profile details |
| `POST` | `/api/profiles/apply`     | Apply profile to agent |
| `GET`  | `/api/agents/{agent_id}`  | Get agent's current state |

### Example: Applying a Profile from Unity

```csharp
IEnumerator ApplyProfile(string profileId, string agentId = "all")
{
    string json = $"{{\"profile_id\": \"{profileId}\", \"agent_id\": \"{agentId}\"}}";
    var request = new UnityWebRequest($"{serverUrl}/api/profiles/apply", "POST");
    request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(json));
    request.downloadHandler = new DownloadHandlerBuffer();
    request.SetRequestHeader("Content-Type", "application/json");
    yield return request.SendWebRequest();
    Debug.Log($"Profile applied: {request.downloadHandler.text}");
}
```

> **Tip:** Use profiles to implement between-subjects experimental conditions. Load different profiles per participant group without modifying any code.

