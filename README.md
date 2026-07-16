<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/ZeroMQ-26.0-DF0000?logo=zeromq&logoColor=white" alt="ZMQ" />
  <img src="https://img.shields.io/badge/Three.js-r170-black?logo=three.js" alt="Three.js" />
</p>

<h1 align="center">🧬 Open Virtual Agent Research Platform — Server</h1>

<p align="center">
  <strong>A modular, research-oriented server for driving embodied virtual agents across heterogeneous platforms (e.g., Web, Mobile, XR), featuring real-time AI orchestration with provider-agnostic LLM/TTS support, and a built-in Wizard-of-Oz console.</strong>
</p>

<p align="center">
  <em>Part of the <a href="https://github.com/AURAxLab">AURAxLab</a> and <a href="https://github.com/SpatialLab-UCENFOTEC">SpatialLab</a> research initiative</em>
</p>

---

## ✨ What is OVARP?

The **Open Virtual Agent Research Platform (OVARP)** is a provider-agnostic server that sits between AI services (such as OpenAI, Google Gemini, or any OpenAI-compatible endpoint) and client applications (such as web apps, mobile clients, or XR engines like Unity and Unreal) to orchestrate the behavior of embodied virtual agents. It provides:

- 🧠 **Multi-provider LLM** — Hot-swap between any supported LLM (e.g., OpenAI, Gemini, Ollama, LM Studio, vLLM) mid-conversation
- 🔊 **Multi-provider TTS** — Auto-matched to active LLM (e.g., OpenAI voices, Gemini voices)
- 🔌 **Custom Endpoints** — Register any OpenAI-compatible API from the UI — no code changes needed
- 🎙️ **STT** — Speech-to-text transcription from client microphone audio
- 🎤 **Voice Selection** — Pick from 22 TTS voices with gender badges (♂️/♀️/⚧️), switchable at runtime
- 👤 **Agent Profiles** — Rich persona definitions (identity, voice, personality, guardrails, backstory) in YAML, applied per-agent
- 🧑 **3D Avatar** — Lip-synced, emotion-reactive embodied agent via `@OVARP/web-client`
- 🎮 **Wizard-of-Oz Console** — Full web dashboard for researchers to monitor and control experiments
- 📡 **Dual Transport** — WebSocket (for web and mobile clients) + ZeroMQ (for low-latency XR engines), extensible to other protocols
- 📊 **Telemetry & Logging** — Structured JSONL event capture with CSV export
- 🧪 **Session Management** — Start/pause/resume/end experiment sessions with participant tracking
- 📌 **Event Markers** — Timestamped researcher annotations during sessions
- ⏱️ **Latency Metrics** — Real-time pipeline timing (STT, LLM, TTS) per interaction
- 📋 **Scripted Scenarios** — YAML-defined experiment protocols with step-by-step execution
- 🥽 **XR Telemetry Ingest** — Batch head/hand/gaze tracking data from XR clients
- 🗂️ **Per-Agent State** — Each agent maintains its own conversation history, prompt, and voice

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  XR Client (Unity / Unreal)                                     │
│  ───────────────────────                                        │
│  • Sends audio/text via ZMQ                                     │
│  • Receives TTS audio + action commands                         │
└────────────────────┬────────────────────────────────────────────┘
                     │ ZeroMQ (TCP 5555/5556)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  OVARP Server (FastAPI + Uvicorn)                                 │
│  ───────────────────────────────                                │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Router   │──│ Orchestrator │──│  Providers   │              │
│  │           │  │              │  │  (e.g.)      │              │
│  │ • Validate│  │ • STT → LLM  │  │ • OpenAI LLM │              │
│  │ • Route   │  │ • LLM → TTS  │  │ • Gemini LLM │              │
│  │ • Broadcast│ │ • History    │  │ • OpenAI TTS │              │
│  │           │  │ • Actions    │  │ • Gemini TTS │              │
│  └───────────┘  └──────────────┘  │ • OpenAI STT │              │
│                                   │ • Custom/*   │              │
│                                   └──────────────┘              │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ ZMQ Layer │  │  WS Layer    │  │  Telemetry   │              │
│  │ (XR apps) │  │  (Web/WoZ)   │  │  (CSV/JSON)  │              │
│  └───────────┘  └──────────────┘  └──────────────┘              │
└────────────────────┬────────────────────────────────────────────┘
                     │ WebSocket (HTTP :8000)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Web/Mobile Native Clients (React, Vue, Flutter, iOS)           │
│  ────────────────────────────────────────────────────           │
│  • Import @OVARP/web-client SDK (OVARP-client.js)                   │
│  • Embeds the Voice, Mic (STT), and VRM Avatar seamlessly       │
│  • WoZ Console & Dashboard natively relies on it                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- An API key for at least one provider:
  - [OpenAI API Key](https://platform.openai.com/api-keys) — for LLM + TTS + STT
  - [Google Gemini API Key](https://aistudio.google.com/apikey) — for LLM + TTS

### Installation

```bash
# Clone the repository
git clone https://github.com/AURAxLab/OpenVirtualAgentResearchPlatform-Server.git
cd OpenVirtualAgentResearchPlatform-Server

# Create and activate virtual environment
python -m venv venv
# Windows
.\venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install google-genai   # For Gemini provider

# Configure API keys
cp .env.example .env
# Edit .env and fill in your API keys
```

### Run the Server

To run the server with the graphical Wizard of Oz interface and LLM playground:
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### Headless Monitoring Mode
If you are running the server in production or on a machine where the 3D GUI is unnecessary, you can start it in headless mode. This serves a lightweight, high-performance monitoring dashboard instead:

**Windows (PowerShell):**
```powershell
$env:OVARP_HEADLESS="true"; uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Linux / macOS:**
```bash
OVARP_HEADLESS=true uvicorn src.main:app --host 0.0.0.0 --port 8000
```

---

## 🏗️ Architecture & Scaling

1.  **Transport Layer**: `ZMQTransport` and `WebSocketTransport` handle raw JSON bytes asynchronously. Both support **Unicast Targeted Routing**, allowing multiple XR headsets to connect to the same server simultaneously without crossing audio or action streams.
2.  **Command Router**: Parses incoming standard `BaseCommand` JSON schemas, validates against `config.yaml`, and logs them.
3.  **Dialog Orchestrator**: Manages AI conversations, injecting history and triggering the correct providers.

> **Running Multiple Quest 3s?** 
> Check out the [Scaling Section in the Unity Integration Guide](UNITY_INTEGRATION.md#3-scaling-multiple-headsets--multiple-servers) for details on how to add devices to `config.yaml` and load balance across multiple Server IPs.

---

## 📱 Integration Guides

Detailed step-by-step guides for connecting client applications to OVARP:

| Platform | Guide | Covers |
|----------|-------|--------|
| **Unity** | [UNITY_INTEGRATION.md](UNITY_INTEGRATION.md) | WebSocket/ZMQ, audio workflows, XR telemetry, sessions, profiles |
| **Unreal Engine 5** | [UNREAL_INTEGRATION.md](UNREAL_INTEGRATION.md) | Full C++ WebSocket client, TTS playback, XR telemetry, sessions, profiles |
| **Mobile (React Native / Flutter)** | [MOBILE_INTEGRATION.md](MOBILE_INTEGRATION.md) | WebSocket, VRM rendering, sessions, profiles |

> **Tip:** All guides share the same `BaseCommand` JSON schema and REST API. The main difference is the transport layer and language-specific code examples.

---

## 🎮 WoZ Console Features

The built-in web console provides a full research interface with five tabs:

### 🎮 Remote Agent Control
- **Target selection** — Choose device and agent from config dropdowns
- **Dynamic action buttons** — Auto-generated from `config.yaml` command categories
- **Direct TTS** — Type text → agent speaks it, bypassing LLM
- **Telemetry log** — Real-time event stream with CSV export

### 💬 LLM Playground
Interactive chat interface for testing the AI pipeline:
- **Hot-swap LLM providers** — Switch between OpenAI, Gemini, and custom endpoints mid-conversation
- **Register custom endpoints** — Add Ollama, LM Studio, vLLM, or any OpenAI-compatible endpoint from the UI
- **System prompt editor** — Customize the agent's personality in real time
- **TTS toggle** — Enable/disable voice synthesis
- **Voice picker** — Choose from 22 TTS voices with gender icons (♂️/♀️/⚧️)
- **Auto-matched TTS** — When using Gemini LLM → Gemini TTS voice; when using OpenAI → OpenAI voice
- **Latency badges** — Real-time timing shown on each response (STT, LLM, TTS)
- **Persistent state** — Chat history, config, and avatar selection survive page reloads

### 🧪 Study Session
Dedicated experiment management tab:
- **Session lifecycle** — Start/pause/resume/end with participant ID tracking
- **Live timer** — Tracks active session duration (correctly pauses)
- **Event markers** — Timestamped annotations with history display
- **Session summary** — Live display of session ID, elapsed time, marker count
- **Scenario runner** — Load YAML protocol scripts with progress bar, auto-applied conditions/markers/actions

### 👤 Agent Profiles
Dedicated profile management tab:
- **Profile library** — Browse all available profiles with name, role, gender icon, and voice
- **Profile detail view** — Full identity, personality traits (empathy/formality/self-disclosure), guardrails, voice config, and backstory
- **Apply to agents** — Select target agent (or "All") and apply a profile with one click
- **Runtime creation** — Create new profiles via API from XR devices or the console
- **Conditions migration** — Legacy `conditions:` entries are auto-migrated to profiles on startup

### 🧑 Embodied Agent
A 3D avatar rendered with **Three.js + three-vrm** that:
- 👄 **Lip-syncs** with TTS audio via Web Audio API `AnalyserNode`
- 😊 **Displays emotions** from LLM action calls (happy, sad, angry, surprised)
- 👀 **Blinks** naturally at random intervals
- 🫁 **Breathes** with subtle spine movement
- 🔄 **Sways** gently for lifelike idle behavior
- 📂 **Upload custom VRM models** — Drag-and-drop avatar replacement

### 📋 System Logs & Errors
Real-time streaming logs from all server components with color-coded severity.

---

## ⚙️ Configuration

### `config.yaml` — Experiment Setup

The config file defines your experiment's structure. The LLM uses these as tool schemas, so it can trigger actions, emotions, and gaze targets autonomously.

```yaml
experiment:
  name: "My Study"

agents:
  - id: "agent_alpha"
    name: "Alpha"

custom_commands:
  emotions:
    description: "Agent emotional states"
    values: ["neutral", "happy", "sad", "angry", "surprised"]

  actions:
    description: "Physical actions the agent can perform"
    values: ["wave", "nod", "clap", "bow", "thumbs_up", "thinking", "shrug", "dance"]

  movement:
    description: "Agent spatial movement"
    values: ["move_closer", "move_farther", "move_left", "move_right", "reset_position"]

  avatar:
    description: "Change the agent's avatar appearance"
    values: ["default", "male_casual", "female_formal", "robot"]

# Experimental conditions (one-click presets)
conditions:
  empathetic:
    description: "Agent responds with high empathy and warm tone"
    system_prompt: "Be warm, empathetic, and supportive..."
    avatar: "female_formal"
    voice: "Kore"
  neutral:
    description: "Agent responds factually and neutrally"
    system_prompt: "Be neutral, factual, and concise..."
    avatar: "default"
    voice: "Puck"
```

> **💡 Tip:** Adding a new value to `custom_commands` automatically makes it available to the LLM as a tool call option — no code changes needed.

### `profiles/*.yaml` — Agent Profiles

Profiles define rich personas that can be applied to any agent at runtime. Each profile bundles identity, voice, personality, guardrails, and avatar into a single switchable unit.

```yaml
# profiles/therapist_male.yaml
id: therapist_male
name: "Dr. Marcus"

identity:
  age: 40
  gender: masculine
  role: "Virtual therapist"
  backstory: >
    A calm, experienced therapist who specializes in cognitive behavioral
    therapy. He listens carefully before responding.

voice:
  provider: gemini          # "openai", "gemini", or "auto"
  voice_id: Charon
  speed: 1.0

personality:
  system_prompt: >
    You are Dr. Marcus, a 40-year-old male therapist...
  self_disclosure: low      # low, medium, high
  formality: high
  empathy: high

guardrails:
  rules:
    - "Never give medical diagnoses"
    - "Do not discuss politics or religion"
  max_response_words: 150

avatar: male_casual
```

Drop new `.yaml` files into `profiles/` and they'll appear in the WoZ console Profiles tab automatically. The system prompt is auto-composed from all persona fields — researchers don't need to do manual prompt engineering.

> **💡 Migration:** Legacy `conditions:` entries in `config.yaml` are auto-migrated to profiles at startup. You can safely remove the `conditions:` section and use profiles instead.

### `scenarios/*.yaml` — Scripted Protocols

Scenario files define step-by-step experiment procedures that researchers can follow in the WoZ console. Each step can optionally auto-apply a condition, execute an action, or log an event marker.

```yaml
# scenarios/my_study.yaml
id: my_study
name: "My Custom Study"
description: "A 3-step study protocol."

steps:
  - id: intro
    instruction: "Welcome the participant and obtain consent."

  - id: main_task
    instruction: "Run the main task for 5 minutes."
    condition: empathetic           # auto-switch to this condition
    auto_marker: main_task_start    # auto-log this marker
    action:                         # auto-fire this command
      emotions: happy

  - id: debrief
    instruction: "Thank the participant. End the session."
    auto_marker: debrief_start
```

Drop new `.yaml` files into `scenarios/` and they'll appear in the WoZ console automatically on the next server restart.

### `.env` — API Keys

```env
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIzaSy...
```

---

## 📡 Transport Protocols

### ZeroMQ (XR Clients)

Low-latency bidirectional communication for Unity/Unreal clients.

| Socket | Port | Direction | Purpose |
|--------|------|-----------|---------|
| PUB    | 5555 | Server → Client | Commands, TTS audio |
| SUB    | 5556 | Client → Server | Audio, text messages |

### WebSocket (Web Clients)

Full-duplex communication on `/ws` endpoint.

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // data.type: "message" | "action" | "audio"
    // data.command: "llm_reply" | "execute_state" | "tts_chunk" | "tts_complete"
};
```

---

## 📁 Project Structure

```
OpenVirtualAgentResearchPlatform-Server/
├── config.yaml                  # Experiment & voice configuration
├── requirements.txt             # Python dependencies
├── .env.example                 # API key template
│
├── profiles/                    # Agent persona definitions (YAML)
│   ├── therapist_male.yaml      # Male therapist profile
│   ├── research_assistant.yaml  # Female research assistant profile
│   └── casual_companion.yaml   # Gender-neutral companion profile
│
├── src/
│   ├── main.py                  # FastAPI app, routes, API endpoints
│   │
│   ├── core/
│   │   ├── orchestrator.py      # AI pipeline: STT → LLM → TTS + per-agent state
│   │   ├── router.py            # Command validation & transport routing
│   │   ├── config.py            # YAML config + TTS voice models
│   │   ├── schemas.py           # Pydantic models for commands
│   │   ├── profile_manager.py   # Agent profiles: load, compose, apply
│   │   ├── session_manager.py   # Session lifecycle + event markers
│   │   ├── scenario_runner.py   # YAML-driven experiment protocol engine
│   │   └── telemetry.py         # JSONL event capture & CSV export
│   │
│   ├── providers/
│   │   ├── base.py              # Abstract base classes (STT, LLM, TTS)
│   │   ├── openai_provider.py   # OpenAI STT + LLM + TTS
│   │   ├── gemini_provider.py   # Gemini LLM + TTS
│   │   └── custom_provider.py   # Generic OpenAI-compatible provider (Ollama, LM Studio, etc.)
│   │
│   ├── transport/
│   │   ├── base.py              # Transport base class
│   │   ├── zmq_layer.py         # ZeroMQ PUB/SUB transport
│   │   └── ws_layer.py          # WebSocket transport
│   │
│   └── static/
│       ├── index.html           # WoZ Console (5-tab single-page app)
│       ├── OVARP-client.js        # Web client SDK
│       ├── avatar.js            # 3D avatar engine (Three.js + VRM)
│       └── models/              # VRM avatar models
│           └── default_avatar.vrm
│
├── scripts/
│   └── mock_xr_client.py       # ZMQ test client for development
│
├── tests/
│   ├── conftest.py              # Shared fixtures & mock config
│   ├── test_main.py             # HTTP endpoint tests
│   ├── test_schemas.py          # Pydantic schema tests
│   ├── test_profile_manager.py  # Profile system tests (19 tests)
│   ├── test_session_manager.py  # Session lifecycle tests (11 tests)
│   ├── test_scenario_runner.py  # Scenario lifecycle tests (11 tests)
│   ├── test_xr_telemetry.py     # XR telemetry ingest tests (3 tests)
│   └── core/
│       ├── test_orchestrator.py  # AI pipeline tests
│       └── test_router.py       # Command routing tests
│
├── scenarios/                   # YAML experiment protocol scripts
│   ├── pilot_emotion.yaml       # 5-step empathy study protocol
│   └── usability_test.yaml      # 3-step usability testing protocol
│
└── data/                        # Experiment data (JSONL + CSV)
```

---

## 🔌 Adding a New AI Provider

### From the UI (no code needed)

Most alternative LLM services (Ollama, LM Studio, vLLM, LocalAI, text-generation-webui) expose an **OpenAI-compatible API**. You can register these directly from the WoZ console:

1. Open the **LLM Playground** tab
2. Click **➕ Register Custom Endpoint** below the voice picker
3. Fill in:
   - **Name** — a short identifier (e.g. `my-ollama`)
   - **Base URL** — the endpoint URL (e.g. `http://localhost:11434/v1`)
   - **API Key** — optional for local services
   - **Model** — the model ID (e.g. `llama3.1`)
   - **Type** — check LLM, TTS, or both
4. Click **🔗 Test** to verify connectivity, then **📝 Register**

The provider immediately appears in the LLM dropdown and is persisted to `custom_providers.yaml` across restarts.

You can also register providers via the REST API:
```bash
curl -X POST http://localhost:8000/api/providers/register \
  -H "Content-Type: application/json" \
  -d '{"name": "my-ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1", "types": ["llm"]}'
```

> **💡 Function calling fallback:** If the custom endpoint doesn't support OpenAI-style function/tool calling, the provider falls back to plain text responses. Chat works normally, but the LLM won't auto-trigger avatar emotions or gestures. You can extend `custom_provider.py` to add custom action extraction logic if needed.

### From code (for non-OpenAI-compatible APIs)

For services that don't follow the OpenAI API format, implement the abstract base classes:

```python
from src.providers.base import BaseLLMProvider, BaseTTSProvider

class MyLLMProvider(BaseLLMProvider):
    async def generate_response(self, prompt, system_prompt=None):
        yield "Hello from my custom LLM!"

    async def generate_response_with_actions(self, prompt, system_prompt=None, history=None):
        return "Hello!", {"emotions": "happy", "actions": "wave"}

class MyTTSProvider(BaseTTSProvider):
    async def synthesize_stream(self, text):
        audio_bytes = my_tts_api(text)
        yield audio_bytes
```

Then register in `main.py`:
```python
llm_providers = {
    "openai": OpenAILLMProvider(),
    "gemini": GeminiLLMProvider(),
    "custom": MyLLMProvider(),       # ← Add here
}
```

---

## 🧪 Running Tests

```bash
pytest tests/ -v
# 129 tests across profiles, schemas, sessions, scenarios, XR telemetry, orchestrator, router, providers, and HTTP endpoints
```

---

## 📡 API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|--------|
| `GET` | `/api/config` | Get experiment configuration |
| `GET` | `/api/llm/config` | Get active LLM provider & settings |
| `POST` | `/api/llm/config` | Update LLM provider / system prompt |
| `POST` | `/api/llm/tts` | Toggle TTS audio on/off |
| `POST` | `/api/llm/history/clear` | Clear conversation memory |
| `GET` | `/api/tts/voices` | List TTS voices with gender metadata |
| `POST` | `/api/tts/voice` | Switch the active TTS voice |
| `GET` | `/api/profiles` | List all agent profiles |
| `GET` | `/api/profiles/{id}` | Get full profile details |
| `POST` | `/api/profiles/apply` | Apply a profile to an agent |
| `POST` | `/api/profiles/create` | Create a new profile at runtime |
| `GET` | `/api/agents/{id}` | Get an agent's current state & profile |
| `GET` | `/api/session/status` | Get current session state |
| `POST` | `/api/session/start` | Start a new session with participant ID |
| `POST` | `/api/session/pause` | Pause the active session |
| `POST` | `/api/session/resume` | Resume a paused session |
| `POST` | `/api/session/end` | End the session and return data |
| `POST` | `/api/session/marker` | Add an event marker |
| `GET` | `/api/scenarios` | List available experiment scenarios |
| `POST` | `/api/scenarios/load` | Load and start a scenario |
| `POST` | `/api/scenarios/advance` | Advance to next scenario step |
| `GET` | `/api/scenarios/status` | Get current scenario state |
| `POST` | `/api/scenarios/stop` | Stop the active scenario |
| `GET` | `/api/providers` | List all providers (built-in + custom) |
| `POST` | `/api/providers/register` | Register a custom OpenAI-compatible endpoint |
| `DELETE` | `/api/providers/{name}` | Remove a custom provider |
| `POST` | `/api/providers/{name}/test` | Test a registered provider's connectivity |
| `POST` | `/api/providers/test` | Test any endpoint URL before registering |
| `POST` | `/api/xr/telemetry` | Ingest batch XR tracking frames |
| `GET` | `/api/telemetry/export` | Export session telemetry as CSV |



## 👥 Authors

| Name | Affiliation | Email |
|------|-------------|-------|
| **Alexander Barquero Elizondo*** | AURAxLAB / ECCI / CITIC, Universidad de Costa Rica | alexander.barqueroelizondo@ucr.ac.cr |
| Briam David Mora Villalobos | Spatial Labs, Universidad Cenfotec | bmorav@ucenfotec.ac.cr |
| Stephanie Isabel Martinez Iglesias | Spatial Labs, Universidad Cenfotec | smartinezi@ucenfotec.ac.cr |
| Rodrigo L. Calvo | Ruiz HCI Lab, University of Florida | rodrigo.calvo@ufl.edu |

*Corresponding author.

---

## 📜 License

[MIT License](LICENSE) © 2026 [AURAxLab](https://github.com/AURAxLab)
