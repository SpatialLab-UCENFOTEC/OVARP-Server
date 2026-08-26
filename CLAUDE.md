# OVARP-Server

Open Virtual Agent Research Platform — FastAPI server that orchestrates embodied virtual agents
for XR/web HCI experiments. Sits between AI providers (OpenAI / Gemini / any OpenAI-compatible
endpoint) and clients (Unity WebGL, XREAL, Unreal, web), and ships a Wizard-of-Oz console for
researchers.

Companion repo (second working directory): `../OVARP-UnityWebClient` — Unity 6 WebGL reference client.

## Environment

Python 3.10+ is **required** (`str | Path` annotations evaluate at import time).
The machine default `python3` is 3.9.6 and will fail on import. Use `/opt/homebrew/bin/python3.11`.

```bash
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt -r requirements_dev.txt
```

`.env` holds the API keys and the optional security settings — see `.env.example`.

## Commands

```bash
# Run (full WoZ console at http://localhost:8000)
./venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000

# Run headless (lightweight dashboard, no 3D avatar)
OVARP_HEADLESS=true ./venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000

# Tests — OVARP_TESTING=1 skips transport/provider bootstrap and serves a bare app
OVARP_TESTING=1 OPENAI_API_KEY=sk-dummy GEMINI_API_KEY=dummy ./venv/bin/python -m pytest -q

# Lint
./venv/bin/python -m ruff check src/ tests/
```

Expose the server to a phone or another machine with a tunnel; a browser page served over HTTPS
cannot open a `ws://` socket, so LAN IPs only work for native XR builds:

```bash
cloudflared tunnel --url http://localhost:8000     # then use the wss:// form of the printed URL
```

## Architecture

Message bus, not a request/response API. Everything on the wire is a `BaseCommand`.

```
Transports (ZMQ 5555/5556, WS /ws/client/{id})
    ↓ raw JSON
CommandRouter (src/core/router.py)          — validate → telemetry → dispatch
    ↓ intercepts by (command_type, command)
DialogOrchestrator (src/core/orchestrator.py) — STT → LLM → TTS, per-agent state
    ↓ providers/ (openai | gemini | custom, all OpenAI-compatible)
back through Router → dispatch_outbound → all transports
```

### Layout

- **`src/main.py`** — bootstrap only: build the orchestrator, wire the runtime, mount routers.
  Route handlers live in `src/api/routers/`; adding an endpoint means editing a router, not this.
- **`src/core/runtime.py`** — the composition root. Routers read `runtime.orchestrator`,
  `runtime.telemetry`, etc. rather than importing singletons, which is also how tests substitute
  them (`monkeypatch.setattr(runtime, "orchestrator", mock)`).
- **`src/core/schemas.py`** — `BaseCommand`. Its `target_device`, `target_agent` and `subcommand`
  validators check against `config.yaml` at runtime. **A device or command value missing from
  `config.yaml` is a hard `ValidationError`**, not a warning.
- **`src/core/config.py`** — `config_manager` singleton; `config.yaml` defines the experiment
  vocabulary. Changing it changes what the schema accepts and what the WoZ UI renders.
- **`src/core/orchestrator.py`** — per-agent state (`_agent_state`): prompt, history, voice.
- **`src/core/profile_manager.py`** — YAML personas in `profiles/`, persisted on create/update.
- **`src/core/survey_manager.py`** — questionnaires in `surveys/`, with SUS and UEQ scoring.
- **`src/core/secrets.py`** — encrypts provider credentials at rest, redacts them from responses.
- **`src/api/deps.py`** — the console access token.
- **`src/static/index.html`** — the WoZ console shell. New behaviour goes in `src/static/js/*.js`
  modules, which the shell imports; they talk to it through DOM ids and `document` events.

### Single sources of truth

Several settings used to be reachable two ways, with one silently winning:

- **Prompt** — the Playground writes the global prompt, a profile writes the agent's own, and the
  agent's wins. `/api/llm/config` reports `agents_overriding_global` so the console can say so, and
  `POST /api/agents/{id}/reset` releases an agent back to the global one.
- **Voice** — `_resolve_tts(agent_id)` decides what an agent speaks with. A profile pins it; anything
  unpinned follows the console's picker.
- **Conditions** — legacy `conditions` in `config.yaml` migrate to `condition_*` profiles at boot.
  The scenario runner resolves a step's `condition` through the profile system, so it and the
  Profiles tab take the same code path.

### Wire protocol

Client → server, raw `BaseCommand` JSON:

| command_type | command | subcommand | effect |
|---|---|---|---|
| `audio` | `stt_request` | `{audio_base64}` | STT → LLM → TTS pipeline; not rebroadcast |
| `message` | `llm_request` | `{text}` | LLM → TTS pipeline |
| `message` | `direct_tts` | `{text}` | WoZ text spoken verbatim, bypasses the LLM |
| `system` | `log_marker` | `{label, metadata}` | timestamped event marker |
| `action` | `execute_state` | see below | forwarded to clients |

Server → client, **wrapped by the WS transport**: `{"topic": <command_type>, "payload": <BaseCommand>}`.
ZMQ sends the bare command with a topic frame. Outbound: `user_transcript`, `llm_reply`,
`tts_chunk` (base64 WAV slices), `tts_complete`, `execute_state`, `marker_logged`.

`execute_state` subcommand keys map 1:1 to `config.yaml → custom_commands`:
`emotions`, `actions`, `looks`, `movement`, `avatar`.

### Routing gotchas

- `sender` is **not** validated; `target_device` and `target_agent` **are**.
- For `stt_request` the router replies to `command.sender` as the target device. If that sender ID
  is not a registered device, the pipeline raises inside a fire-and-forget task and dies silently.
- `llm_reply` and `tts_chunk` are always broadcast to `all` so the WoZ console hears them too;
  only `execute_state` is targeted.

### Telemetry is append-only

`data/sessions/*.jsonl` is the record of what happened live. Editing a marker never rewrites the
original entry — it appends `marker_amended` with the previous value. Keep that property when
adding anything that lets a researcher change recorded data.

## Security

Both are opt-in via `.env`, and absent by default so a localhost run needs no setup:

- `OVARP_ACCESS_TOKEN` — required in the `X-OVARP-Token` header on every `/api/` call. The agent
  WebSocket and the participant survey page are exempt: XR clients and participants have no token.
- `OVARP_SECRET_KEY` — encrypts custom provider API keys in `custom_providers.yaml`. Provider
  credentials are never returned by the API; `GET /api/providers` reports `has_key` instead.

Set both before exposing the server through a tunnel.

## Unity client contract (`../OVARP-UnityWebClient`)

- `Assets/Scripts/OvarpServerConnector.cs` — WebSocket client (NativeWebSocket). Parses the
  `topic`/`command` envelope with a hand-rolled string extractor, not a JSON parser: **field
  names and nesting must stay flat and stable**.
- Identifies itself as `web_01`, baked into the build. That ID must exist in `config.yaml → devices`.
- Audio only — the Unity client never sends `llm_request`. Text injection is WoZ-console-only.
- A page served over HTTPS can only reach `wss://` or `localhost`. `/api/server/info` returns
  `public_ws_url` (scheme-aware, honours `X-Forwarded-Proto`) and `lan_ws_url` separately for this.
- Vocabulary drift to watch: the client's `GesturePlayer` supports `thumbs_up`, absent from
  `config.yaml → custom_commands.actions` and rejected server-side.
- Avatar swap (`OnAgentAvatarChange`) is a logged TODO in `Controller.cs`, not implemented.

## Conventions

- Naming migrated OAF → OVAF → OVARP. `OAF_TESTING` / `OAF_HEADLESS` still work with a deprecation
  warning; use `OVARP_*`. Loggers are namespaced `OVARP.<module>` and do not propagate to root.
- Dual logging on purpose: `structlog` for machine-readable telemetry, stdlib `logging` for the
  human/WS log stream. Follow whichever the surrounding module uses.
- A new provider implements `BaseLLMProvider.generate_response_with_actions` returning
  `(spoken_reply, actions_dict)`. Anything OpenAI-compatible needs no code — register it at
  `/api/providers/register`.
- Functions used from inline `onclick=` must be assigned to `window` explicitly: the console runs
  as a `<script type="module">`, where declarations are not global.

## Known state (2026-08-25)

Tests: 224 passing. `ruff check` is clean on `src/api/`, `src/main.py` and the modules added
recently; the older files still carry ~416 violations (whitespace, line length, `Optional[X]`),
not gated in CI.

### What `612f22c` did

`feat: ux improvements` (2026-08-21, straight to main, no PR) imported the parallel AuraLab
rework on top of Elena's console. It brought the good architecture — `src/api/routers/`,
`runtime.py`, `survey_manager`, `secrets` — and dropped work that had been merged the day
before via PR #12/#13. Recovered since: the latency pipeline, the two validation scenarios,
and the parts of `test_qa_protocol.py` that still apply. Still gone, deliberately:

- `src/static/player.html` and its `@app.get("/player")` route, plus `sdk/ovaf-client.js`.
  `/player` 404s because both the file and the route were removed, not because one lost the
  other. Reviving it is a product call, not a repair.
- `src/core/evaluations.py` — genuinely superseded by `survey_manager.py`.
- The marker tests keyed to `EventMarker.category` and `PUT /api/session/markers/{id}`;
  that API is now `notes`/`amended` and `PATCH`, covered by `test_api_sessions.py`.

Anything else it removed is still reachable at `dbbafd1`, the commit before it.

Pre-existing, not things to fix unprompted:

- `venv/` is broken — its interpreter points at the pre-rename path
  `/Users/briammora/Projects/github/OpenVirtualAgentFramework-Server/venv`. Recreate it, or
  go through `./venv/bin/python -m pip` / `-m pytest`, which ignores the shebang.
- `.env` has no `GEMINI_API_KEY`, so the Gemini provider is disabled at boot.
- `.github/workflows/pytest.yml` is stale after the rename: uses `OVAF_TESTING` and a codecov slug
  of `AURAxLab/OpenVirtualAgentFramework-Server`.
- `src/woz/` and `src/base/` are empty packages left from an earlier layout.
