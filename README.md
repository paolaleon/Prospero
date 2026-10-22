# Prosper Challenge — Agent Composer

Voice AI for healthcare scheduling. An agent is a **graph of nodes**: each node is a step in the conversation, and each edge is a transition the LLM can take. Agents are defined as JSON, compiled into a [Pipecat Flows](https://github.com/pipecat-ai/pipecat-flows) graph, and run as a real-time voice pipeline:

```
browser mic  ->  ElevenLabs STT  ->  OpenAI LLM  ->  ElevenLabs TTS  ->  browser
```

- **Phase 1** — a visual editor for the node graph, with test calls placed from the browser.
- **Phase 2** — an AI Copilot that builds agents from natural-language guidelines and improves them from call data.

The reasoning behind the main design choices, and their known weaknesses, is in [DECISIONS.md](DECISIONS.md).

## What the editor does

- **Agents:** create (named up front; the name sets the agent's link), open, duplicate and delete agents.
- **Graph canvas:**
  - Each node shows its instructions, its transitions, and any validation issues.
  - Drag from a transition's handle to connect it to a node. Drop on empty canvas to create a connected node.
  - Drag nodes to move them. **Tidy up** lays the graph out automatically.
- **Inspector:**
  - **Nodes:** rename (every reference follows), edit instructions, mark as the start or an end node, override the persona.
  - **Transitions:** function name, "when to take it" description, target, and the fields the LLM must collect (type, description, allowed values, required).
  - **Agent:** name, persona, voice, languages (English only by default; callers in other languages are offered a call back) and model.
- **Live validation:** errors (red) and warnings (amber) are checked by the backend as you edit and pinned to the node or transition they belong to.
- **Undo/redo** (⌘Z / ⇧⌘Z), with a readable label for every change.
- **Versions:** each save is a new, immutable version with a message. History lists them, and any version can be restored.
- **Test calls:**
  - Talk to the agent from the browser, running exactly what's on screen, even unsaved.
  - The transcript appears live, with each transition and the data it collected.
  - The active node lights up on the canvas.
  - A transition the LLM attempts without its required data is refused and shown in amber, and the agent asks again.
- **ProsperO, the copilot:** describe a medical voice agent, or a change to one, and ProsperO draws it on the canvas as a proposal you review, test with a call, then accept or reject. Start from **Describe a new agent** on the agent list, or the ProsperO panel in the editor.
- **Call history:** every call is recorded with its transcript, path, collected data and the agent version it ran. Opening a call replays its path on the canvas.

## Requirements

- **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/getting-started/installation/). uv will fetch a matching Python if needed.
- **Node.js 20.19+ or 22.12+**, as Vite 7 requires (developed with Node 24). If Node isn't on your `PATH`, pass its folder to make: `make dev NODE_BIN=/path/to/node/bin`. The default is `~/.local/node/bin`.
- **API keys** in `backend/.env`:
  ```
  ELEVENLABS_API_KEY=...
  OPENAI_API_KEY=...
  ```
  Optional: `PROSPERO_MODEL` picks the OpenAI model ProsperO uses (default `gpt-5.5`).
  This file is gitignored. Voice, languages and model are set per agent, not here.

## Quickstart

Run from the repo root:

```bash
make install   # backend (uv sync) + frontend (npm ci), from the lock files
make dev       # backend on :7860 + editor on :5173; Ctrl+C stops both
```

Open **http://localhost:5173**, pick an agent, and use the **Test call** tab (allow microphone access).

| Command | What it does |
|---|---|
| `make dev` | Backend and editor together |
| `make backend` / `make frontend` | Either one on its own |
| `make test` | Backend tests (pytest), frontend tests (Vitest) and the type check |
| `make build` | Production build of the editor into `frontend/dist` |
| `make clean` | Remove installed dependencies, builds and caches |
| `make help` | List all targets |

Without make:

```bash
uv sync --directory backend && uv run --directory backend python bot.py   # backend
cd frontend && npm ci && npm run dev                                      # editor
```

The editor finds the backend through `VITE_API_URL` (default `http://localhost:7860`; see `frontend/.env.example`). Pipecat's own prebuilt test client still works at http://localhost:7860/client and runs the default agent.

## Layout

| Path | Responsibility |
|---|---|
| `backend/bot.py` | Voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Picks each call's agent from the request, records the call, streams live state to the browser over RTVI. |
| `backend/agent_builder/` | The agent format (`schema.py`), validation as small registered rules (`validation.py`), and `AgentBuilder`, which compiles an agent into a Pipecat Flows graph and enforces each transition's required data (`builder.py`). |
| `backend/api.py` | The editor's HTTP API, added to the Pipecat runner's server (one process). |
| `backend/call_guard.py` | Refuses call requests for agents with errors before a session is created. |
| `backend/store.py` | Storage: agent versions in `backend/agents/{id}/versions/`, call records in `backend/calls/` (gitignored). |
| `backend/prospero/` | ProsperO, the copilot: system prompt, tools generated from the operations, and the tool loop. |
| `shared/operation-cases.json` | Test cases both the Python and TypeScript operations must pass. |
| `backend/tests/` | pytest suite: validation, builder and transitions, call guard, store. |
| `backend/example_flow.json` | The example agent, and the default for calls that don't name one. |
| `frontend/src/lib/` | The editor's logic, with no UI: API client, agent operations (every edit is one), editor and call state, layout. |
| `frontend/src/components/` | The screens: agent list, canvas, inspector, test call, history. |

## HTTP API

Served on `:7860` next to Pipecat's own call endpoints (`/start`, `/sessions/…`).

| Endpoint | Purpose |
|---|---|
| `GET` / `POST /api/agents` | List agents; create one (as version 1) |
| `GET` / `PUT` / `DELETE /api/agents/{id}` | Latest version; save a new version (`base_version` guards against overwriting newer work, `409`); delete |
| `GET /api/agents/{id}/versions[/{n}]` | Version history; one version |
| `POST /api/agents/{id}/versions/{n}/restore` | Restore an old version as a new one |
| `GET /api/calls[?agent_id=…]`, `GET /api/calls/{id}` | Recorded calls |
| `POST /api/validate` | Errors and warnings for a draft agent |
| `GET /api/voices` | ElevenLabs voices for the voice picker |
| `GET /api/languages` | Languages an agent can speak |
| `POST /api/copilot` | One ProsperO turn: the current agent, the chat and a message in; edits streamed out as server-sent events |

## Agent format

An agent is plain JSON. See [`backend/example_flow.json`](backend/example_flow.json):

```json
{
  "name": "Prosper Scheduler",
  "persona": "You are a warm, efficient scheduling assistant...",
  "voice_id": "21m00Tcm4TlvDq8ikWAM",
  "model": "gpt-4o",
  "initial_node": "greeting",
  "nodes": [
    {
      "name": "greeting",
      "task_messages": [{ "role": "developer", "content": "Greet the caller..." }],
      "edges": [
        {
          "function": "choose_intent",
          "description": "Record what the caller wants to do once they say it.",
          "target": "collect_details",
          "properties": { "intent": { "type": "string", "enum": ["book", "reschedule", "cancel"] } },
          "required": ["intent"]
        }
      ],
      "position": { "x": 0, "y": 0 }
    }
  ]
}
```

Each edge becomes a tool the LLM can call, and `properties` and `required` are the data it must provide. `end: true` makes a node hang up after it speaks. `position` is only used by the editor.

## Troubleshooting

- **The voice picker only lists four voices:** the ElevenLabs key can't list voices (`401`), so a built-in list is used. Calls are unaffected.
- **"Microphone access was blocked":** allow the microphone for `localhost:5173` in the browser, then start the call again.
- **"The agent has errors, so the call was refused":** fix the red issues shown on the canvas; calls only run valid agents.
- **`npm: command not found`:** Node isn't on your `PATH`. Use `make … NODE_BIN=/path/to/node/bin`, or add Node's `bin` folder to your `PATH`.

The original starter README and Makefile are kept as `README.original.md` and `Makefile.original`.
