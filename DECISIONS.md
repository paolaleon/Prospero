# Architectural Decisions

This file records the architectural decisions (ADs) built into the project so far: decisions that are hard to undo and that shape how the system works.

| AD | Architectural decision |
|----|------------------------|
| AD-1 | The canvas layout is stored in the agent JSON |
| AD-2 | Validation rules live in one place, in the backend |
| AD-3 | `AgentBuilder` reports transitions through a callback |
| AD-4 | Agents are stored as JSON files on disk |
| AD-5 | A test call carries the agent definition with it |
| AD-6 | Live call state reaches the browser over RTVI |

---

## AD-1: The canvas layout is stored in the agent JSON

`Node` has an optional `position: {x, y}` field (`backend/agent_builder/schema.py`). The voice runtime ignores it.

**Why:** the layout is saved with the agent. Keeping it on the node, rather than in a separate map keyed by node name, means renaming a node doesn't break it.

**Consequences:**
- The agent format now holds data that's only for the editor. Anything that generates agents can leave it out.
- Existing JSON without positions, such as `example_flow.json`, still loads as before.

## AD-2: Validation rules live in one place, in the backend

`validate_agent` in `backend/agent_builder/validation.py` holds the only copy of the rules. `AgentBuilder.from_dict` runs it before building and raises one `ValueError` listing every error.

Each issue it reports has:
- a `severity`: an `error` (the agent can't run) or a `warning` (it runs, but something is probably wrong);
- a `message`;
- the `node` and `edge` it belongs to, when there is one.

**Why:**
- Every consumer of the format (the runtime, an editor, a generator) checks agents against the same rules, so they can't disagree about what is valid.
- Tying each issue to a node and edge lets a UI show it in the right place.

**Consequence:** creating `AgentBuilder(config)` directly from an `AgentConfig` skips validation. The loading paths (`from_dict` and `from_json`) both validate.

## AD-3: `AgentBuilder` reports transitions through a callback

`AgentBuilder` accepts an optional async `on_transition(from_node, function, to_node, args)` callback (`backend/agent_builder/builder.py`). It runs after every transition. If it raises, the error is logged and the call carries on.

**Why:** Pipecat Flows' `FlowManager` doesn't raise an event when a transition happens. Each edge's handler is the one place that knows both ends of the transition, and the callback lets code outside the builder observe the call without the builder knowing who's listening.

**Consequence:** anything that needs to follow a call's progress through the graph depends on this callback.

## AD-4: Agents are stored as JSON files on disk

Each agent is a file in `backend/agents/{id}.json`. They're read and written through `/api/agents` in `backend/api.py` (list, create, read, update, delete).

**Why:**
- The files use exactly the format `AgentBuilder` reads.
- They can be diffed, edited by hand and committed to git.
- There's no database to run.

**Consequences:**
- There's no protection against two people editing the same agent at once, which suits a single-user tool.
- Moving to a database later would only change the storage behind `/api/agents`. The HTTP contract would stay the same.

## AD-5: A test call carries the agent definition with it

The body of the Pipecat runner's `/start` request decides which agent a call runs (`_builder_for` in `backend/bot.py`). The first of these that's present wins:

1. `{"agent": {...}}`: an inline agent definition, which can be an unsaved draft.
2. `{"agent_id": "..."}`: a saved agent.
3. Neither: `AGENT_FLOW`.

**Why:** edits can be tested without saving or restarting the backend. Each call is independent, so different calls can run different agents.

**Consequence:** the backend runs whatever agent definition a client sends. That's fine for a local dev tool, but a deployed version would need to authenticate clients or only allow saved agents.

## AD-6: Live call state reaches the browser over RTVI

`bot.py` sends an RTVI server message, `{"type": "flow.node", "node": ...}`, when the client becomes ready (with the start node) and after every transition. Messages sent after a transition also include `from_node`, `function` and the collected `args`. They're produced through the `on_transition` callback from AD-3. The transcript comes through RTVI's standard transcription events.

**Why:** RTVI already runs in `PipelineWorker` and uses the existing WebRTC connection, so no extra WebSocket or polling endpoint is needed.

**Consequence:** live call state is only available to clients connected over Pipecat/RTVI.
