# OVARP-Server

Open Virtual Agent Research Platform — FastAPI server that orchestrates embodied virtual agents
for XR/web HCI experiments. Sits between AI providers (OpenAI / Gemini / any OpenAI-compatible
endpoint) and clients (Unity WebGL, XREAL, Unreal, web), and ships a Wizard-of-Oz console for
researchers.

Companion repos (additional working directories):

- `../OVARP-UnityWebClient` — Unity 6 WebGL reference client.
- `../OVARP-Server-Alex` — **Alex's repo (`alebar000/OVARP-Server`) is the base of truth.**
  It shares no git history with this one; the two trees were synced by copying snapshots.
  When Alex has already solved something, follow his shape. See "Converging on Alex's base".

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
- **`src/core/key_store.py`** — the provider keys the console can set at runtime. Values live in
  `provider_keys.yaml` (git-ignored) through `secrets.py`, are mirrored into `os.environ`, and
  are restored on boot, where a stored key **wins over `.env`**.
- **`src/api/deps.py`** — the console access token.
- **`src/static/index.html`** — the WoZ console shell, built on Alex's design system v3.0
  (CSS custom properties per theme, `.card` / `.metric-box` / `.badge-*` / `.btn-ghost` /
  `.btn-action-primary`, monospace pill nav). Colours come from those tokens, not from Bootstrap
  semantic classes, and the markup carries **no emoji** — that was a deliberate sweep on both
  sides. New behaviour goes in `src/static/js/*.js` modules, which the shell imports; they talk
  to it through DOM ids and `document` events.
  Tabs are numbered in study order: `(01) OVERVIEW` … `(08) SYSTEM LOGS`. Overview is the
  landing tab and must stay that way — opening on a control surface was the single loudest
  usability complaint.

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
- `OVARP_SECRET_KEY` — encrypts stored credentials: custom providers in `custom_providers.yaml`
  and the built-in provider keys in `provider_keys.yaml`. Without it both keep working in plain
  text, so an existing localhost setup does not break on upgrade.

Set both before exposing the server through a tunnel.

Credentials never ride along on a response that something polls. `GET /api/providers` reports
`has_key`, `GET /api/keys/status` reports a mask and a badge, and the raw value is only returned
by `POST /api/keys/reveal`, which the console calls when a researcher presses **Show**. Alex's
version put `full_key` in every status response; this is the one place the implementation
deliberately departs from his, and the UX is unchanged.

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
- **Provider SDK clients are lazy `@property` reads, never bound in `__init__`.** The console can
  change an API key at runtime; an eagerly bound client would keep authenticating with the old
  one. `OpenAIClientSingleton.reset_client()` / `GeminiClientSingleton.reset_client()` drop the
  cache, and `key_store.set_keys()` calls both. This regressed once already — see below.
- `/api/health/providers` checks **key presence, not connectivity**. Probing the providers for
  real took 10s+ and left the console showing stale error badges while it waited.
- Functions used from inline `onclick=` must be assigned to `window` explicitly: the console runs
  as a `<script type="module">`, where declarations are not global.

## Known state (2026-09-16)

Tests: 280 passing. `ruff check` is clean on `src/api/`, `src/main.py`, `src/core/key_store.py`
and the modules added recently; the older files still carry ~400 violations (whitespace, line
length, `Optional[X]`), not gated in CI. New code in an older file matches that file's existing
style rather than importing a second convention into it.

## Converging on Alex's base

`../OVARP-Server-Alex` is the base of truth. The rule agreed on 2026-09-16: **where Alex already
solved something, follow his shape; where only this repo has something functional, keep it and
port it into his shape.** Two things were settled explicitly and should not be re-litigated:

- **The routers architecture stays.** Alex's `src/main.py` is a 1118-line monolith; this repo
  keeps `src/api/routers/` + `runtime.py`, and his endpoints were brought *into* the routers.
- **The console adopted his UI wholesale** — design system, tab order, Overview and API Key
  Store — and this repo's own tabs (Surveys, `/player`) were ported into it.

Brought over from his line:

- `GET /api/keys/*` (API Key Store), rewired to the encrypted store instead of plaintext `.env`
- instant `/api/health/providers`, and the lazy `@property` provider clients that `612f22c`
  had reverted
- `GET /api/session/export/csv` and `EventMarker.category`, kept alongside this repo's
  append-only `PATCH` amendment rather than replacing it
- the Overview tab, theme toggle, pipeline status card, latency panel, Stop Audio
- the marker preset builder, the scenario builder, the system-log filter/search/export toolbar
- the zero-emoji sweep and the BOM strip across `src/`

What is still only here: `survey_manager` + the Surveys tab, `/player`, `/api/clients`,
`/api/latency/last`, `/api/avatars`, `/api/server/info`, profile duplicate/PUT, the
`condition_*` profiles, `secrets.py`, and `web_01` / `xreal_01` in `config.yaml` (without which
the Unity client is rejected — Alex's `config.yaml` does not declare them).

Not adopted from his line: `friet256` (demo-specific character, and the GLB is not a VRM so
`avatar.js` cannot load it), and `full_key` in the key status response (see Security).

### What `612f22c` did, and what came back

`feat: ux improvements` (2026-08-21, straight to main, no PR) imported the parallel AuraLab
rework on top of Elena's console. It brought the good architecture — `src/api/routers/`,
`runtime.py`, `survey_manager`, `secrets` — and dropped work merged the day before via
PR #12/#13. The deletions were collateral, not decisions: the AuraLab tree simply never
contained those files, and the commit body was empty.

Recovered since: the latency pipeline, `/player` and its route, `GET /api/clients`,
`GET /api/latency/last`, `POST /api/profiles/{id}/duplicate`,
`POST /api/session/markers/presets`, `POST /api/scenarios`, both validation scenarios,
and the QA protocol tests. The restored write endpoints took typed Pydantic models,
which the originals lacked.

Deliberately **not** recovered, each superseded rather than lost:

- `src/core/evaluations.py` → `survey_manager.py`
- `src/static/sdk/ovaf-client.js` → renamed `OVARP-client.js` in the AuraLab line (R095);
  restoring it would reinstate the duplicate SDK Elena had already flagged as unused
- `PUT /api/session/markers/{id}` → `PATCH /api/session/marker/{id}`
- `GET /api/session/export/csv` → `GET /api/telemetry/export`
- The marker tests keyed to `EventMarker.category`; that field is now `notes`/`amended`,
  covered by `test_api_sessions.py`
- `friet256.glb` / `.fbx` / `test_friet.html` / `profiles/friet256.yaml` — a demo-specific
  character. The GLB is not a VRM, so `avatar.js` cannot load it through `VRMLoaderPlugin`.
- The API Key Store as Alex wrote it — it writes provider keys to `.env` in plaintext. Re-added
  on 2026-09-16 through the encrypted path instead; see "Converging on Alex's base".

Two QA assertions now check the capability instead of Elena's implementation, and say so
inline: the console builds its device list from `config.yaml` rather than hardcoding
`web_panel_01`, and it targets devices through its own `sendCommand` rather than the SDK's
`setTargets`.

Anything still missing is reachable at `dbbafd1`, the commit before the import.

Pre-existing, not things to fix unprompted:

- `venv/` is broken — its interpreter points at the pre-rename path
  `/Users/briammora/Projects/github/OpenVirtualAgentFramework-Server/venv`. Recreate it, or
  go through `./venv/bin/python -m pip` / `-m pytest`, which ignores the shebang.
- `.github/workflows/pytest.yml` is stale after the rename: uses `OVAF_TESTING` and a codecov slug
  of `AURAxLab/OpenVirtualAgentFramework-Server`.
- `src/woz/` and `src/base/` are empty packages left from an earlier layout.
