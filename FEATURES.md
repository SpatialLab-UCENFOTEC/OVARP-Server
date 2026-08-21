# OVARP Server — Feature Reference

What the platform does, how to use each piece, and where it lives in the code.

OVARP runs HCI studies with an embodied conversational agent. You define the agent's persona,
let a participant talk to it on their own device, steer it live if you need to, and take away a
timestamped record of everything that happened.

- [The console](#the-console)
- [Agent personas](#agent-personas)
- [Sessions and event markers](#sessions-and-event-markers)
- [Questionnaires](#questionnaires)
- [Scripted scenarios](#scripted-scenarios)
- [AI providers](#ai-providers)
- [Connecting clients](#connecting-clients)
- [Security](#security)
- [Telemetry and export](#telemetry-and-export)
- [Architecture](#architecture)
- [API reference](#api-reference)

---

## The console

The Wizard-of-Oz console at `http://localhost:8000` is organised as the steps of a study, in order.

| Tab | What it is for |
|---|---|
| 🧠 **Playground** | Build and try the agent. Opens here by default. |
| 👤 **Profiles** | Author and apply personas. |
| 🧪 **Study Session** | Run a participant through the protocol. |
| 🎮 **Live Control** | Intervene mid-session; also holds the client connection details. |
| 📋 **Feedback** | Send questionnaires and watch scores arrive. |
| 🖥️ **System Logs** | Server stdout and browser errors. |

A dismissible **Getting Started** banner explains the platform and walks through those five steps.
It stays dismissed via `localStorage`.

### Playground

Everything needed to shape the agent, in one column:

- **Agent Persona** — apply a profile to the target agent, or create one with ➕ without leaving
  the tab. Selecting the empty option releases the agent back to the global prompt.
- **System Prompt** — the global prompt, used by agents that have no profile.
- **LLM / TTS provider and voice** — chosen independently of one another.
- **Custom endpoint registration** — see [AI providers](#ai-providers).
- **Simulated conversation** — type or hold 🎤 to talk. STT runs either in the browser (WebSpeech,
  no API key) or through OpenAI Whisper.
- **3D avatar** — lip-synced VRM preview.

> **Why the prompt box can warn you**
> Applying a profile parks a composed prompt on that agent, and it wins over the global one.
> Editing the global prompt then does nothing for that agent. The console says so explicitly:
> a warning above the prompt box names the agents currently following a profile.

### Live Control

Fire `execute_state` commands at connected clients in real time — emotions, gestures, gaze,
movement, avatar. The buttons are generated from `config.yaml → custom_commands`, so the
vocabulary is whatever your experiment declares.

Also holds **Direct TTS**, which makes the agent speak an exact line without involving the LLM,
and the **XR Connection** card described under [Connecting clients](#connecting-clients).

---

## Agent personas

A persona ("profile") bundles identity, voice, personality and guardrails into a preset you can
apply in one click — the unit of an experimental condition.

Profiles live in `profiles/*.yaml` and are composed into a system prompt by
`build_system_prompt()` in [`src/core/profile_manager.py`](src/core/profile_manager.py).

### Authoring from the console

The ➕ **New** button in the Profiles tab, and the ➕ next to the persona picker in the Playground,
open the same editor. Both are places you realise the persona needs a change, so there is one
dialog rather than two.

Fields: id, display name, system prompt, voice provider and voice, avatar, role, gender, age,
backstory, guardrail rules, and a max response length.

**Profiles created in the console are written to `profiles/<id>.yaml`**, so they survive a restart.
Editing rewrites that file; deleting removes it.

### Applying

Apply to one agent or to all of them. Applying sets the agent's prompt and pins its voice, and
sends an `execute_state` avatar command to connected clients if the profile specifies one.

`POST /api/agents/{id}/reset` releases an agent back to the global prompt and voice — the way back
out, so the console's settings become the single source of truth again.

### Legacy conditions

The `conditions:` block in `config.yaml` still works. Each entry is migrated to a
`condition_<id>` profile at boot, and `/api/conditions/*` remains as a thin shim. Scenario steps
that name a `condition` resolve through the same profile system, so a scenario and the Profiles
tab take one code path.

---

## Sessions and event markers

Start a session with a participant ID, then pause, resume and end it. The timer excludes paused
time. Session state is exposed at `GET /api/session/status` and drives the console live.

### Markers

Timestamped annotations of what happened. Fire them three ways:

1. **Preset buttons** — defined in `config.yaml → event_markers`, with labels and colours.
2. **Free-text box** — type a label and hit Enter.
3. **Programmatically** — any connected device or agent can send
   `{command_type: "system", command: "log_marker", subcommand: {label, metadata}}` over the bus.

### Correcting a marker

Markers can be corrected after the fact — the ✎ button on any row in the history opens an inline
editor for the label and a free-text notes field, and 🗑 removes one fired by mistake.

**The timestamp is never touched, and nothing is rewritten.** The session log is append-only: the
original `marker` entry stays as captured and the correction is appended as `marker_amended`,
carrying both the previous and the new value. An edited marker is flagged in the console, and the
CSV export carries `marker_amended_from` / `marker_amended_to` columns.

That property is deliberate — a study record has to keep showing what was captured live, not just
its latest state. Preserve it when adding anything else that lets a researcher change recorded data.

---

## Questionnaires

Send validated instruments to the participant's own phone and collect scored responses next to
the interaction log.

### Shipped instruments

| File | Instrument | Scoring |
|---|---|---|
| `surveys/sus.yaml` | System Usability Scale, 10 items | 0–100 |
| `surveys/ueq.yaml` | User Experience Questionnaire, 26 bipolar items | six scales on −3…+3 |
| `surveys/qualitative.yaml` | Five open questions | none |

All three carry English and Spanish text; the participant page takes `?lang=es`.
SUS and UEQ include their attribution, which UEQ requires.

### How it works

The **📋 Feedback** tab builds a link, fills in the participant ID from the active session, and
either copies it or opens it in a new window. The participant opens
`/survey.html?id=sus&lang=es&participant=P001` on their phone — a standalone, mobile-first page
with a progress bar, per-question validation and a confirmation screen. It needs no console
access and no token.

Submitted responses are scored server-side, appended to the session JSONL, and appear in the
console's results panel with SUS bands and per-scale UEQ values.

### Adding your own

Drop a YAML file in `surveys/` and restart. Same pattern as `scenarios/` and `profiles/`.

```yaml
id: my_questionnaire
name: "Post-task questions"
kind: likert          # likert | bipolar | open
scoring: none         # sus | ueq | none
scale: {min: 1, max: 7, min_label: "Never", max_label: "Always"}
items:
  - id: q1
    text: "The agent understood me"
    text_es: "El agente me entendió"
```

Bipolar items use `left`/`right` instead of `text`, plus a `scale:` name and `reverse:` when the
positive pole sits on the left. Scoring lives in
[`src/core/survey_manager.py`](src/core/survey_manager.py) and is verified against each
instrument's published reference values.

---

## Scripted scenarios

YAML protocols in `scenarios/` that walk a researcher through a study step by step. Each step
carries an instruction and can automatically fire a marker, apply a persona, and dispatch an
action to the clients.

The console shows progress, the current instruction, and Next / Stop controls.

---

## AI providers

Built in: **OpenAI** (STT, LLM, TTS) and **Gemini** (LLM, TTS). LLM and TTS providers are selected
independently, so you can run a local LLM with OpenAI voices.

Anything OpenAI-compatible — Ollama, LM Studio, vLLM — needs no code. Register it from the
Playground with a base URL, model and optional key; test connectivity before committing. The
registry persists to `custom_providers.yaml`.

A health strip shows each provider's key status, with the active one marked.

Writing a genuinely new provider means implementing
`BaseLLMProvider.generate_response_with_actions` in [`src/providers/base.py`](src/providers/base.py),
returning `(spoken_reply, actions_dict)`.

---

## Connecting clients

The **XR Connection** card in Live Control reports the address to use, and which one depends on
how the client is served.

A browser page served over HTTPS cannot open a `ws://` socket — the browser blocks it before any
handshake. `localhost` is the only exception. So:

| Client | Address |
|---|---|
| Native XR build on the same Wi-Fi | `ws://<LAN IP>:8000` |
| Hosted web client, server on the same machine | `ws://localhost:8000` |
| Hosted web client, server anywhere else | `wss://…` — needs a tunnel or TLS |

`GET /api/server/info` returns `lan_ws_url` and `public_ws_url` separately, deriving the scheme
from `X-Forwarded-Proto`. Behind a tunnel it reports `wss://`, and the card tells you which
address applies to which client instead of advertising one that will not connect.

To reach a phone or another machine:

```bash
cloudflared tunnel --url http://localhost:8000
```

Then enter the printed URL **with `wss://`** in the client — not the `https://` form it prints.

Set `client_url` in `config.yaml` and the card gains a button that opens the participant client
directly.

---

## Security

Both settings are opt-in and absent by default, so a localhost run needs no setup. Set both before
exposing the server through a tunnel or a deployment.

### `OVARP_ACCESS_TOKEN`

Every `/api/` call must carry it in an `X-OVARP-Token` header. The console asks once and keeps it
in `sessionStorage`; [`src/static/js/api.js`](src/static/js/api.js) wraps `window.fetch` so every
call is covered without each call site being rewritten.

Two things are deliberately exempt: the agent WebSocket (`/ws/client/{id}`), because XR clients
authenticate by being a device declared in `config.yaml`, and the participant survey page,
because a participant has no token.

### `OVARP_SECRET_KEY`

Encrypts custom provider API keys at rest in `custom_providers.yaml` (Fernet, key derived from the
passphrase). Without it the registry still works in plain text, so upgrading breaks nothing.

Independently of encryption, **credentials are never returned by the API**. `GET /api/providers`
reports `has_key: true|false` instead of the value.

---

## Telemetry and export

Every command through the bus, every marker, every latency measurement and every questionnaire
response is written to `data/sessions/session_<timestamp>.jsonl`, tagged with the participant and
session ID when one is active.

`GET /api/export` flattens it to CSV for SPSS/R:

```
iso_time, host_timestamp, event_type, participant_id, experiment_session_id,
sender, target_device, target_agent, command_type, command, subcommand_json,
marker_label, marker_metadata, marker_id, marker_amended_from, marker_amended_to,
survey_id, survey_score, survey_answers
```

Per-interaction latency is broken down into STT, LLM, TTS and total milliseconds.

XR clients can also batch head/hand/gaze frames to `POST /api/xr/telemetry`.

---

## Architecture

A message bus, not a request/response API. Everything on the wire is a `BaseCommand`, validated
against `config.yaml` at runtime.

```
Transports (ZMQ 5555/5556, WS /ws/client/{id})
    ↓ raw JSON
CommandRouter          — validate → telemetry → dispatch
    ↓ intercepts by (command_type, command)
DialogOrchestrator     — STT → LLM → TTS, per-agent state
    ↓ providers/
back through Router → all transports
```

### Where things live

| Path | Responsibility |
|---|---|
| `src/main.py` | Bootstrap only — build, wire, mount |
| `src/core/runtime.py` | Composition root; routers read collaborators from here |
| `src/api/routers/` | One module per API area |
| `src/api/deps.py` | Console access token |
| `src/api/websockets.py` | `/ws/client/{id}` and `/ws/logs` |
| `src/core/schemas.py` | `BaseCommand`, the single wire format |
| `src/core/orchestrator.py` | The STT → LLM → TTS pipeline and per-agent state |
| `src/core/profile_manager.py` | Personas |
| `src/core/survey_manager.py` | Questionnaires and scoring |
| `src/core/secrets.py` | Credential encryption and redaction |
| `src/core/telemetry.py` | JSONL logging and CSV export |
| `src/static/index.html` | Console shell |
| `src/static/js/*.js` | Console behaviour, one module per area |
| `src/static/survey.html` | Participant-facing questionnaire page |

### Single sources of truth

Three settings used to be reachable two ways, with one silently winning. Each now has one
resolution point:

- **Prompt** — an agent's own prompt wins over the global one. `/api/llm/config` reports
  `agents_overriding_global` so the console can say so, and `/api/agents/{id}/reset` is the way back.
- **Voice** — `DialogOrchestrator._resolve_tts(agent_id)` decides. A profile pins a voice; anything
  unpinned follows the console's picker.
- **Conditions** — the scenario runner resolves a step's `condition` through the profile system.

---

## API reference

47 HTTP endpoints and 2 WebSockets. Interactive docs at `/docs` while the server runs.

### System
| Method | Path | |
|---|---|---|
| GET | `/api/config` | Experiment topology from `config.yaml` |
| GET | `/api/server/info` | Connection addresses, scheme-aware |
| GET | `/api/export` | Session CSV |
| POST | `/api/xr/telemetry` | Batched head/hand/gaze frames |

### Auth
| Method | Path | |
|---|---|---|
| GET | `/api/auth/status` | Whether a token is required (unauthenticated) |
| POST | `/api/auth/verify` | Check a token before storing it |

### LLM and TTS
| Method | Path | |
|---|---|---|
| GET · POST | `/api/llm/config` | Provider and prompt; POST accepts `agent_id` |
| POST | `/api/llm/tts` | Toggle speech synthesis |
| POST | `/api/llm/history/clear` | Reset conversation memory |
| GET | `/api/tts/voices` | Voices for the active provider |
| POST | `/api/tts/voice` · `/api/tts/provider` | Switch voice or provider |
| GET | `/api/health/providers` | Per-provider key check |

### Providers
| Method | Path | |
|---|---|---|
| GET | `/api/providers` | Built-in and custom; credentials redacted |
| POST | `/api/providers/register` | Add an OpenAI-compatible endpoint |
| DELETE | `/api/providers/{name}` | Remove a custom provider |
| POST | `/api/providers/test` · `/api/providers/{name}/test` | Connectivity check |

### Profiles and agents
| Method | Path | |
|---|---|---|
| GET | `/api/profiles` · `/api/profiles/{id}` | List and detail |
| POST | `/api/profiles/create` | Create and persist to YAML |
| PUT · DELETE | `/api/profiles/{id}` | Update or remove |
| POST | `/api/profiles/apply` | Apply to one agent or all |
| GET | `/api/agents/{id}` | Current persona and state |
| POST | `/api/agents/{id}/reset` | Release back to the global prompt |
| GET · POST | `/api/conditions` · `/api/conditions/apply` | Deprecated shim over profiles |

### Sessions
| Method | Path | |
|---|---|---|
| GET | `/api/session/status` | Live session state |
| POST | `/api/session/start` · `pause` · `resume` · `end` | Lifecycle |
| POST | `/api/session/marker` | Fire a marker |
| PATCH · DELETE | `/api/session/marker/{id}` | Correct or retract one |
| GET | `/api/session/markers/presets` | Preset buttons from `config.yaml` |

### Scenarios
| Method | Path | |
|---|---|---|
| GET | `/api/scenarios` · `/api/scenarios/status` | List and current step |
| POST | `/api/scenarios/load` · `advance` · `stop` | Run a protocol |

### Surveys
| Method | Path | |
|---|---|---|
| GET | `/api/surveys` · `/api/surveys/{id}` | List and definition (`?lang=es`) |
| POST | `/api/surveys/response` | Submit and score (unauthenticated) |
| GET | `/api/surveys/responses` | Responses collected this run |

### WebSockets
| Path | |
|---|---|
| `/ws/client/{id}` | The command bus. Exempt from the console token. |
| `/ws/logs` | Read-only log stream for the console. |

---

## Testing

```bash
OVARP_TESTING=1 OPENAI_API_KEY=sk-dummy GEMINI_API_KEY=dummy python -m pytest -q
```

205 tests. `OVARP_TESTING=1` skips transport and provider bootstrap and serves a bare app; tests
substitute collaborators on the runtime container
(`monkeypatch.setattr(runtime, "orchestrator", mock)`).

Areas with the heaviest coverage: personas including persistence round-trips (27), sessions and
markers (34), survey scoring against each instrument's published reference values (15), and access
control and credential handling (13).
