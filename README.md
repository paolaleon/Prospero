# Prosper Challenge — Agent Composer

Voice AI for healthcare scheduling. An agent is a **graph of nodes**: each node is a step in the conversation, and each edge is a transition the LLM can take. Agents are defined as JSON, compiled into a [Pipecat Flows](https://github.com/pipecat-ai/pipecat-flows) graph, and run as a real-time voice pipeline:

```
browser mic  ->  ElevenLabs STT  ->  OpenAI LLM  ->  ElevenLabs TTS  ->  browser
```

- **Phase 1** — a visual editor for the node graph, with test calls placed from the browser.
- **Phase 2** — **ProsperO**, an AI copilot that builds and edits medical voice agents from plain-language descriptions, plus the tools to check them against recorded calls (regression tests, call outcomes, cost per call).

The reasoning behind the main design choices, and their known weaknesses, is in [Solution.md](Solution.md).

## What the editor does

- **Agents:** create (named up front; the name sets the agent's link), open, duplicate and delete agents.
- **Graph canvas:**
  - Each node shows its instructions, its transitions, and any validation issues.
  - Drag from a transition's handle to connect it to a node. Drop on empty canvas to create a connected node.
  - Drag nodes to move them. **Tidy up** lays the graph out automatically.
- **Inspector:**
  - **Nodes:** rename (every reference follows), edit instructions, mark as the start or an end node, override the persona.
  - **Transitions:** function name, "when to take it" description, target, and the fields the LLM must collect (type, description, allowed values, required).
  - **Agent:** name, persona, voice and model, plus where a stuck call goes (a node, or a polite ending). Agents speak English only.
  - **Advanced (per node):** Pipecat Flows actions as raw JSON, run before or after the node, such as a fixed sentence to say word for word.
- **Live validation:** errors (red) and warnings (amber) are checked by the backend as you edit and pinned to the node or transition they belong to.
- **Undo/redo** (⌘Z / ⇧⌘Z), with a readable label for every change.
- **Versions:** each save is a new, immutable version with a message. History lists them, and any version can be restored.
- **Test calls:**
  - Talk to the agent from the browser, running exactly what's on screen, even unsaved.
  - The transcript appears live, with each transition and the data it collected.
  - The active node lights up on the canvas.
  - A transition the LLM attempts without its required data is refused and shown in amber, and the agent asks again.
- **ProsperO, the copilot:** describe a medical voice agent, or a change to one, and ProsperO draws it on the canvas as a proposal to review, test and accept. See [ProsperO](#prospero-the-copilot) below.
- **Call history:**
  - Every call is recorded with its transcript, path, collected data, the agent version it ran, its outcome and its estimated cost. Opening a call replays its path on the canvas.
  - Each call's outcome is one of: completed, couldn't help, stuck (fallback), or caller hung up. History shows a count of each, and the average cost per call overall and by version.
- **Tests:** save any recorded call as a regression test, then replay it against the current draft, version or proposal. See [Regression tests](#regression-tests) below.

### Built into every agent

The runtime adds these to every agent, whatever its persona says or who wrote it:
- **Safety rules on every node:** no medical advice, and nothing shared about other patients.
- **English only:** speech recognition, the voice and every node are fixed to English.
- **Two attempts, then a way out:** after two refused transitions in a row in one node, the call goes to the agent's fallback node, or a built-in polite ending.
- **Hanging up:** every node that isn't an end node can end the call once the caller needs nothing else, or keeps asking for something the agent can't help with.

## Requirements

- **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/getting-started/installation/). uv will fetch a matching Python if needed.
- **Node.js 20.19+ or 22.12+**, as Vite 7 requires (developed with Node 24). If Node isn't on your `PATH`, pass its folder to make: `make dev NODE_BIN=/path/to/node/bin`. The default is `~/.local/node/bin`.
- **API keys** in `backend/.env`:
  ```
  ELEVENLABS_API_KEY=...
  OPENAI_API_KEY=...
  ```
  Optional settings, in the same file:

  | Variable | What it sets | Default |
  |---|---|---|
  | `PROSPERO_MODEL` | The OpenAI model ProsperO uses | `gpt-5.5` |
  | `PROSPERO_REASONING` | ProsperO's reasoning effort (`none` was faster with the same results in testing) | `none` |
  | `GRADER_MODEL` | The model that judges regression tests | `gpt-5.5` |

  This file is gitignored. An agent's voice and model are set on the agent, not here.

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

## ProsperO, the copilot

ProsperO builds and edits **voice agents for medical practices** (scheduling, intake, reminders, refills, billing questions) from a description in plain language.

### Using it

1. **Start it.**
   - For a new agent, click **Describe a new agent** on the agent list. Give it a name and a description, and the editor opens and ProsperO starts building.
   - For an existing agent, open the **ProsperO** panel from the left edge of the editor and describe a change ("add a cancellation path", "verify the date of birth before rescheduling").
2. **Watch it build.** Each edit appears on the canvas as it's made, with nodes marked **New**, **Changed** or **Removed**. The graph is tidied after every edit. **Stop** keeps the edits made so far.
3. **Review the proposal.**
   - ProsperO ends with a summary and the assumptions it made (opening hours, the emergency number…) for you to check.
   - Editing is paused while a proposal is open, but **you can place a test call or run tests against it**.
   - Follow-up messages keep building on the same proposal.
4. **Accept or reject it** from the bar above the canvas.
   - **Accept** applies everything as one undoable step and saves it as a version marked as ProsperO's, with its summary as the message.
   - **Reject** discards it.

ProsperO is told whether you accepted or rejected, so the conversation continues from there.

### What it builds by default

Unless you say otherwise, agents get:
- **An emergency path from the start:** callers describing something urgent are told to hang up and call emergency services.
- **Identity before details:** full name and date of birth before discussing an existing appointment.
- **Only the data the call needs.**
- **Short, spoken replies, one question at a time.**
- **A handoff-to-staff node** as the agent's fallback for stuck calls.

No medical advice, patient privacy and English only are enforced by the runtime on every agent (see [Built into every agent](#built-into-every-agent)), so ProsperO only makes sure nothing contradicts them.

### How it works

- **One turn per message** (`POST /api/copilot`). The editor sends the agent as it stands (without canvas positions), the chat so far and the new message. The server keeps nothing between turns.
- **ProsperO edits through the same operations as the editor** (`backend/agent_builder/operations/`, kept identical to the TypeScript ones by `shared/operation-cases.json`). Each edit is applied and checked as it's made. An edit that doesn't fit is refused, and the exact error goes back to the model to fix.
- **It can't finish with errors.** It validates with the same rules as the editor and calls, so what it hands over can always run. A turn stops after 40 model calls.
- **Its edits stream to the editor as server-sent events**, and the editor applies them to the proposal with the same code a person's edits use.
- **Code:** the system prompt is in `backend/prospero/prompt.py`, the tools (generated from the operations, without layout or whole-agent replacement) in `tools.py`, and the loop in `loop.py`.

### Limits

- **A build takes about 20 to 30 seconds** with the default model. Edits arrive in bursts, because OpenAI delivers `gpt-5.5`'s tool calls at the end of each reply.
- **It doesn't read call data yet.** Improving agents from recorded calls is done with [regression tests](#regression-tests) for now.
- **Proposals are all or nothing,** and removed transitions aren't marked on the canvas (only removed nodes are).
- **Its own model use isn't included in the cost figures.**

## Regression tests

Any recorded call can become a test that's replayed against your changes:

1. Open a call in **History** and click **Save as test**.
2. In the **Tests** tab, adjust what's expected:

   | Expectation | Default |
   |---|---|
   | The caller's lines, one per line | what the caller said |
   | Where the call ends | where it ended |
   | Fields it collects | the fields it collected |
   | Never falls back | on |
   | Longest reply | 40 words |
   | Turn limit | the original call's turns + 2 |
   | Checks on what the agent says, e.g. "Offers to book an appointment" | none |

3. **Run** a test, or **Run all tests**. Each test is replayed 3 times, as text, through the real graph, safety rules and model, against the draft, version or proposal on the canvas. It reports how many replays passed, each check's evidence, the transcript and the cost.

Routing, data, fallbacks, reply length and turns are checked in code. Checks on what the agent says are judged by a grader model, which quotes the agent's words as evidence. **No medical advice** and **nothing about other patients** are always checked. Speech recognition and the voice aren't part of a replay, so test calls remain the way to check those.

## Layout

| Path | Responsibility |
|---|---|
| `backend/bot.py` | Voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Picks each call's agent from the request, records the call and its usage, streams live state to the browser over RTVI. |
| `backend/agent_builder/` | The agent format (`schema.py`); validation as small registered rules (`validation.py`); `AgentBuilder` (`builder.py`), which compiles an agent into a Pipecat Flows graph and adds the runtime's guards (required data, fallback, ending the call); the rules added to every node (`medical.py`, `english.py`); and the agent operations (`operations/`). |
| `backend/call_record.py` | Builds each call's record: transcript, transitions, refusals, fallbacks, endings, outcome. |
| `backend/usage.py`, `backend/pricing.py`, `backend/pricing.json` | Usage metering for calls and replays, and the price table used to estimate costs. |
| `backend/api.py` | The editor's HTTP API, added to the Pipecat runner's server (one process). |
| `backend/call_guard.py`, `backend/http_common.py` | Refuses call requests for agents with errors before a session is created; shared HTTP helpers. |
| `backend/store.py` | Storage: agent versions in `backend/agents/{id}/versions/`, tests in `backend/agents/{id}/tests/`, call records in `backend/calls/` (gitignored). |
| `backend/prospero/` | ProsperO, the copilot: system prompt, tools generated from the operations, and the tool loop. |
| `backend/regression/` | Regression tests: making a test from a call, text replays, the grader, and running a test several times. |
| `shared/operation-cases.json` | Test cases both the Python and TypeScript operations must pass. |
| `backend/tests/` | pytest suite: validation, builder and runtime guards, operations, ProsperO (with a scripted model), regression tests, usage and cost, store, call guard. |
| `backend/example_flow.json` | The example agent, and the default for calls that don't name one. |
| `frontend/src/lib/` | The editor's logic, with no UI: API client, agent operations (every edit is one), editor and call state, ProsperO's stream and proposals, diffs, layout, costs. |
| `frontend/src/components/` | The screens: agent list, canvas, inspector, ProsperO panel, test call, tests, history. |

## HTTP API

Served on `:7860` next to Pipecat's own call endpoints (`/start`, `/sessions/…`).

| Endpoint | Purpose |
|---|---|
| `GET` / `POST /api/agents` | List agents; create one (as version 1) |
| `GET` / `PUT` / `DELETE /api/agents/{id}` | Latest version; save a new version (`base_version` guards against overwriting newer work, `409`); delete |
| `GET /api/agents/{id}/versions[/{n}]` | Version history; one version |
| `POST /api/agents/{id}/versions/{n}/restore` | Restore an old version as a new one |
| `GET` / `POST /api/agents/{id}/tests`, `PUT` / `DELETE …/tests/{test_id}` | Regression tests: list, create from a call (`call_id`), edit, delete |
| `POST /api/agents/{id}/tests/{test_id}/run` | Replay a test (3 times by default) against the latest version, or a draft sent as `agent` |
| `GET /api/calls[?agent_id=…]`, `GET /api/calls/{id}` | Recorded calls, with usage and estimated cost (prices in `backend/pricing.json`) |
| `POST /api/validate` | Errors and warnings for a draft agent |
| `GET /api/voices` | ElevenLabs voices for the voice picker |
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

Other optional fields: `fallback_node` (agent level) is the node a stuck call goes to, instead of the built-in polite ending; `role_message` (node level) overrides the persona for that node; `pre_actions` and `post_actions` are Pipecat Flows actions. When an agent runs, the builder adds the rules from [Built into every agent](#built-into-every-agent) to every node, so they don't belong in the JSON. `end_call` is reserved and can't be used as a transition's function name.

## Troubleshooting

- **The voice picker only lists four voices:** the ElevenLabs key can't list voices (`401`), so a built-in list is used. Calls are unaffected.
- **"Microphone access was blocked":** allow the microphone for `localhost:5173` in the browser, then start the call again.
- **"The agent has errors, so the call was refused":** fix the red issues shown on the canvas; calls only run valid agents.
- **ProsperO seems stuck:** a build takes 20 to 30 seconds and edits arrive in bursts. **Stop** keeps what's been built so far.
- **`npm: command not found`:** Node isn't on your `PATH`. Use `make … NODE_BIN=/path/to/node/bin`, or add Node's `bin` folder to your `PATH`.

The original starter README and Makefile are kept as `README.original.md` and `Makefile.original`.
