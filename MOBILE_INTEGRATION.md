# Mobile Integration Guide (React Native / Flutter)

The Open Virtual Agent Research Platform (OVARP) is fully agnostic to the client rendering technology. Thanks to its lightweight WebSocket + Base64 architecture, you can easily integrate a 3D Virtual Agent into any **iOS** or **Android** application.

We recommend using **React Native** or **Flutter**, as both have ecosystems capable of rendering 3D VRM models and tapping into the microphone.

---

## Architecture Overview

A mobile integration requires three core pillars:
1. **Networking:** A bidirectional WebSocket connection to the OVARP Server.
2. **Audio I/O:** Capturing the user's microphone as chunks and playing back received Base64 WAV chunks.
3. **3D Avatar (Optional):** Rendering a `.vrm` 3D model with blendshapes for lip sync and emotions.

---

## Step 1: Connecting to the Server

Connect to the server using the standard WebSocket libraries available in your framework.

**Endpoint:** `ws://<server_ip>:8000/ws/client/<your_device_id>`

### Flutter (using `web_socket_channel`)
```dart
import 'package:web_socket_channel/web_socket_channel.dart';

final channel = WebSocketChannel.connect(
  Uri.parse('ws://192.168.1.100:8000/ws/client/mobile_app_01'),
);

channel.stream.listen((message) {
  print('Received from Server: $message');
  // Route payload to STT or LLM handler
});
```

### React Native (native `WebSocket`)
```javascript
const ws = new WebSocket('ws://192.168.1.100:8000/ws/client/mobile_app_01');

ws.onopen = () => console.log('Connected to OVARP');
ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    handleServerMessage(data);
};
```

---

## Step 2: Bi-directional Communication (JSON)

Everything inside OVARP uses a strict JSON schema.

### Sending Microphone (STT) Data to Server
When you want the user to talk to the agent, capture the microphone, convert it to Base64, and send an `audio` command.

```json
{
  "sender": "mobile_app_01",
  "target_device": "server",
  "target_agent": "agent_alpha",
  "command_type": "audio",
  "command": "stt_request",
  "subcommand": {
    "audio_base64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAf..."
  }
}
```

### Receiving TTS (Agent Voice)
The server will respond with chunks of Base64 audio as the LLM streams the text. You must decode these and play them back sequentially.

```json
{
  "sender": "server_orchestrator",
  "command_type": "audio",
  "command": "tts_chunk",
  "subcommand": {
    "audio_base64": "UklGRiQAAAB...",
    "chunk_id": 1,
    "is_final": false
  }
}
```

---

## Step 3: Rendering the 3D Avatar (VRM)

Depending on your mobile framework, rendering anime/humanoid VRM models requires specific libraries.

### Option A: React Native + React Three Fiber (Recommended)
You can use `react-three-fiber` along with `@pixiv/three-vrm` directly inside your React Native application to render the avatar just like the browser does.

1. Install `three`, `@react-three/fiber`, and `@pixiv/three-vrm`.
2. Load the `.vrm` model into a `<Canvas>`.
3. Feed the Audio Analyzer data into the avatar's `VRMExpressionPresetName.Aa` blendshape to achieve lip-sync.

### Option B: Flutter + `flutter_3d_controller`
While Flutter has native 3D support, it is usually optimized for standard `glb/gltf`. A `.vrm` file is a GLTF with custom extensions.
If you have trouble playing VRM animations natively in Flutter, you can use a `WebView` widget that loads the [OVARP Web SDK](./README.md) internally, bridging the UI cleanly.

---

## Step 4: Multi-Client Support

If you have thousands of users downloading your mobile app, you must dynamically generate a UUID for each phone and pass it in the WebSocket URL:
`ws://server/ws/client/<phone_uuid>`

In `config.yaml`, ensure your server has the hardware capable of scaling multiple simultaneous agents, or refer to the Load Balancing scenario in the Main README.

---

## Step 5: Session Management (REST API)

OVARP tracks experiment sessions with participant IDs, elapsed time, and timestamped event markers. Your mobile app can programmatically manage sessions via REST API.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/session/status` | Get current session state |
| `POST` | `/api/session/start`  | Start session |
| `POST` | `/api/session/pause`  | Pause active session |
| `POST` | `/api/session/resume` | Resume paused session |
| `POST` | `/api/session/end`    | End session and retrieve data |
| `POST` | `/api/session/marker` | Add event marker |

### React Native

```javascript
// Start a session
const startSession = async (participantId) => {
    const res = await fetch(`http://${SERVER_URL}/api/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ participant_id: participantId }),
    });
    return res.json();
};

// Add an event marker
const addMarker = async (label, metadata = null) => {
    const res = await fetch(`http://${SERVER_URL}/api/session/marker`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, metadata }),
    });
    return res.json();
};
```

### Flutter

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

Future<Map> startSession(String participantId) async {
  final res = await http.post(
    Uri.parse('http://$serverUrl/api/session/start'),
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode({'participant_id': participantId}),
  );
  return jsonDecode(res.body);
}

Future<Map> addMarker(String label, [Map? metadata]) async {
  final res = await http.post(
    Uri.parse('http://$serverUrl/api/session/marker'),
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode({'label': label, 'metadata': metadata}),
  );
  return jsonDecode(res.body);
}
```

---

## Step 6: Agent Profiles (REST API)

Profiles are rich persona definitions (identity, voice, personality, guardrails, backstory) that can be applied to any agent at runtime. This enables switching experimental conditions directly from the mobile app.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/profiles`           | List all profiles |
| `GET`  | `/api/profiles/{id}`      | Get profile details |
| `POST` | `/api/profiles/apply`     | Apply profile to agent |
| `GET`  | `/api/agents/{agent_id}`  | Get agent's current state |

### React Native

```javascript
// List all profiles
const listProfiles = async () => {
    const res = await fetch(`http://${SERVER_URL}/api/profiles`);
    return res.json();
};

// Apply a profile
const applyProfile = async (profileId, agentId = 'all') => {
    const res = await fetch(`http://${SERVER_URL}/api/profiles/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_id: profileId, agent_id: agentId }),
    });
    return res.json();
};
```

### Flutter

```dart
Future<Map> applyProfile(String profileId, {String agentId = 'all'}) async {
  final res = await http.post(
    Uri.parse('http://$serverUrl/api/profiles/apply'),
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode({'profile_id': profileId, 'agent_id': agentId}),
  );
  return jsonDecode(res.body);
}
```

> **Tip:** Use profiles to implement between-subjects experimental conditions. Load different profiles per participant group without modifying any code.

