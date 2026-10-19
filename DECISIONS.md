# Architectural Decisions

This file records the architectural decisions (ADs) built into the project so far: decisions that are hard to undo and that shape how the system works. Each one is written to be defended from an AI product engineer's point of view:

- **Decision**: what we chose.
- **Product argument**: why it helps the people building and testing agents.
- **AI angle**: how it affects LLM reliability, observability or the Phase 2 copilot.
- **Alternatives considered**: what we could have done instead.
- **Cost of reversal**: how hard it would be to undo.
- **Likely challenges**: what a reviewer is likely to push on, with an answer for each.
- **Revisit when**: the signal that it's time to change it.

| AD | Architectural decision |
|----|------------------------|
| AD-1 | The canvas layout is stored in the agent JSON |
| AD-2 | Validation rules live in one place, in the backend |
| AD-3 | `AgentBuilder` reports transitions through a callback |
| AD-4 | Agents are stored as JSON files on disk |
| AD-5 | A test call carries the agent definition with it |
| AD-6 | Live call state reaches the browser over RTVI |

The **Gaps to prepare for** section at the end isn't a set of decisions. It lists the open questions a reviewer is most likely to raise.

---

## AD-1: The canvas layout is stored in the agent JSON

**Decision.** Each node has an optional `position: {x, y}`. The voice runtime ignores it.

**Product argument.** One file is the whole agent. It can be exported, shared and committed without a layout file kept beside it that can fall out of sync. Renaming a node doesn't break the layout, because the position belongs to the node rather than to a map keyed by its name.

**AI angle.** It's neutral to slightly negative. The Phase 2 copilot reads and writes this format, and positions are tokens that mean nothing to the LLM.

**Alternatives considered.**
- A layout file stored next to the agent, keyed by node name. Rejected because it breaks on rename and can fall out of sync.
- Always laying the graph out automatically, with nothing stored. Rejected because users lose the arrangement they chose.

**Cost of reversal.** Low. It's an optional field, so a short script could move positions into a separate file.

**Likely challenges.**
- *"You've mixed editor data into your runtime config."* True, but it's optional and the runtime ignores it. The agent format is the product's artifact, not just the runtime's input.
- *"The copilot will waste tokens on coordinates, or move nodes around."* Remove positions before sending an agent to the LLM, add them back to unchanged nodes afterwards, and lay out new nodes automatically.

**Revisit when** a second client needs a different layout (for example a mobile view), or the copilot's token budget gets tight.

---

## AD-2: Validation rules live in one place, in the backend

**Decision.** `validate_agent` is the only copy of the rules. The editor (`/api/validate`), the call request (`POST /start`, see AD-5) and every way of creating an `AgentBuilder` all use it. Each issue says how serious it is and which node and edge it belongs to.

**Product argument.** The editor and the runtime can't disagree. If the canvas shows no errors, the call will build. The issues point at a specific node and edge, so the UI can mark the exact problem on the graph instead of showing a vague "invalid agent".

**AI angle.** This is the strongest decision for Phase 2.
- **Generate → validate → repair.** The copilot's output is checked against the same rules as a human's edits, and the errors are machine-readable and specific ("Transition `select_time` targets unknown node `confirmation`"). They can go straight back to the LLM so it fixes its own output. The repair loop is ready before Phase 2 starts.
- **Rules written for LLM behaviour.** A transition with no description is an *error*, not a warning, because the description is the only thing the LLM uses to decide when to take that edge. Function names must follow OpenAI's tool-name rules, which would otherwise fail at call time rather than at edit time.
- **Errors and warnings are separate.** Errors block a run. Warnings (unreachable nodes, dead ends, no reachable end node) are likely design mistakes that still run, so users and the copilot can work through a half-built graph.

**Alternatives considered.**
- Re-implementing the rules in TypeScript for instant feedback. Rejected because two copies drift apart.
- JSON Schema only. Rejected because it can't express checks across the graph (reachability, unknown targets, duplicate names).
- Validating only when the agent is built (the old behaviour). Rejected because it stopped at the first error and only checked two things.

**Cost of reversal.** Medium. The UI and the copilot will both rely on the issue format (severity, node, edge).

**Likely challenges.**
- *"A round trip to the server on every edit is slow."* It runs locally, is debounced, and is a pure function that takes microseconds. If it ever mattered, the same Python could run in the browser, but it hasn't been needed.
- *"Can something unvalidated still be compiled?"* No. The `AgentBuilder` constructor validates, so creating a builder directly from an `AgentConfig` is covered as well as `from_dict` and `from_json`. `from_dict` also checks the raw dict first, so a missing key gives a readable error instead of a `KeyError`.
- *"It doesn't check `pre_actions` / `post_actions`."* True. They're passed through to Pipecat unchecked, and the editor won't expose them beyond raw JSON.
- *"It checks structure, not quality."* Correct. A valid agent can still be a bad conversation. That's what evaluations are for (see Gaps).

**Revisit when** you add new kinds of nodes or edges (conditional edges, tool-call nodes), or the copilot needs quality checks such as "this prompt is too long to read aloud".

---

## AD-3: `AgentBuilder` reports transitions through a callback

**Decision.** An optional async `on_transition(from_node, function, to_node, args)` callback runs after every transition. If it fails, the error is logged and the call carries on.

**Product argument.** Users can see where the conversation is in the graph as it happens. The builder doesn't know who's listening, so the same hook can later feed call logs, analytics or alerts without changes to the builder.

**AI angle.** It's the foundation for observability. Which path the agent took (`greeting → collect_details → offer_times → confirm`) is the unit that analytics and evaluations measure: "Did the agent reach `confirm`?", "How often does it loop back?", "Which edge does the LLM take wrongly?". Without it, LLM routing decisions are invisible.

**Alternatives considered.**
- Changing Pipecat Flows' `FlowManager` to raise an event. Rejected because we'd have to maintain a modified copy of a dependency.
- Working out transitions afterwards from the LLM's function-call frames. Rejected because it's fragile and depends on Pipecat's internals.

**Cost of reversal.** Low. It's one optional parameter.

**Likely challenges.**
- *"Only the live UI uses it."* That's deliberate. Storing call logs later is purely additive.
- *"It runs inside the transition, so a slow listener slows the call down."* True. Anything heavier than sending a message should go on a queue instead of being awaited inside the transition.

**Revisit when** you add call logs (put a queue in front) or more node types (it may need to report more than transitions).

---

## AD-4: Agents are stored as JSON files on disk

**Decision.** Each agent is `backend/agents/{id}.json`, accessed through `/api/agents`. Writes go to a temporary file that then replaces the original, so a crash can't leave a half-written agent.

**Product argument.** Nothing to set up or run. Agents can be diffed, reviewed in a pull request and committed, which treats the agent as code. It's the same format the builder runs and the copilot will generate.

**AI angle.** Versioning becomes important once an LLM is editing agents. Plain JSON files give a cheap path to that: git history, or a timestamped snapshot on each save.

**Alternatives considered.**
- SQLite or Postgres. Rejected for now: it's infrastructure the challenge doesn't need yet.
- Keeping agents only in browser storage. Rejected because the backend has to be able to load saved agents.

**Cost of reversal.** Low. Storage sits behind `/api/agents`, so moving to a database changes only `api.py`, not the frontend.

**Likely challenges.**
- *"There's no version history in the product."* **This is the weakest point once the copilot exists.** Users need to see what the AI changed and undo it. Plan: store each save as a snapshot, and show the copilot's edits as a diff the user accepts or rejects.
- *"Two people saving at once will overwrite each other."* True, and fine for a single-user tool. The fix is a version check on save that rejects a stale write.
- *"There are no tenants, no sign-in, no permissions."* Out of scope for Phase 1. It would come with the move to a database.

**Revisit when** you add the copilot (versioning), more than one user (version checks on save), or a hosted deployment (a database and tenants).

---

## AD-5: A test call carries the agent definition with it

**Decision.** The `/start` request body decides which agent a call runs, in this order: an inline `agent`, then a saved `agent_id`, then `AGENT_FLOW`. The editor sends the current draft, saved or not. A middleware (`StartValidationMiddleware` in `api.py`) checks that agent before the runner creates a session: an agent with errors is refused with `422` and its issues, and an unknown `agent_id` gets `404`.

**Product argument.** This is the iteration loop that matters most for a voice-agent builder: change a prompt, then call within seconds, with no save, deploy or restart. Each call is independent, so you could compare two versions of an agent side by side.

**AI angle.** Prompt engineering is trial and error, so the faster the loop, the better the agent. The loop is also ready for the copilot: it suggests an edit, the user calls the draft straight away, and only then decides to keep it.

**Alternatives considered.**
- Saving before every call and running only saved agents. Rejected because it's slower and fills the store with half-finished agents.
- Restarting the bot with a new `AGENT_FLOW` (the original setup). Rejected because it's far too slow.

**Cost of reversal.** Low. Allowing only `agent_id` is a one-line change in `_builder_for`.

**Likely challenges.**
- *"Anyone who can reach the backend can run any prompt on your OpenAI and ElevenLabs keys."* **This is the main security and cost risk.** Acceptable for a local tool. In production, require sign-in, run only saved and validated versions, and rate-limit calls and minutes per user.
- *"What happens if the draft is invalid?"* The call is refused at `/start` with the same issues the editor shows, before any session or WebRTC connection exists. Without that check, the bot would only fail to build after the connection was up, and the client would wait for a call that never starts.
- *"Why a middleware rather than your own endpoint?"* `/start` belongs to the Pipecat runner, which keeps its sessions internally. Putting the check in front of it keeps the runner's own behaviour and its upgrades untouched.
- *"Can a client get round the check?"* Yes, by posting straight to the runner's `/api/offer` with an agent inside the request. The bot still refuses to build and logs the error, but that client gets no explanation. The editor never uses that path. For a deployment, only allow saved agents (see the cost risk above).
- *"The draft is sent in full on every call."* Agents are a few KB, so it doesn't matter.

**Revisit when** the tool is deployed beyond localhost, or calls start to cost real money.

---

## AD-6: Live call state reaches the browser over RTVI

**Decision.** `bot.py` sends `{"type": "flow.node", ...}` RTVI messages: once when the client is ready (with the start node), and after every transition (with `from_node`, `function` and the collected `args`). The transcript comes through RTVI's standard events.

**Product argument.** Users can debug by watching. The active node lights up, the data each step collected appears, and the transcript lines up with the path through the graph. That trust is what users of ElevenLabs Agents and Retell rely on.

**AI angle.** It explains LLM decisions. When the agent misroutes, the user sees which edge the model chose and with what arguments, and can fix that edge's description on the spot. That turns a black box into something the user can debug.

**Alternatives considered.**
- A separate WebSocket or a polling endpoint for call state. Rejected because it's an extra channel and needs its own session matching.
- Showing only the transcript. Rejected because users can't see the routing decisions.

**Cost of reversal.** Medium. The frontend will depend on the message format.

**Likely challenges.**
- *"Nothing is stored when the call ends: no history, no replay."* True. That's the obvious next step: write the same events to a call log (see Gaps).
- *"It sends patient data (names, reasons for visit) to the browser."* **This is a healthcare compliance point.** For a local test tool, the person testing is the caller. In production, transcripts and collected fields are protected health information: they need encryption, retention limits and access controls, and may need masking in shared views.
- *"It only works with Pipecat clients."* True, and acceptable because the editor is a Pipecat client. Telephony calls wouldn't get the live view, but they would get call logs.

**Revisit when** you add call logs, phone calls, or real patient traffic.

---

## Gaps to prepare for

These aren't decisions yet. They're the questions an AI product reviewer is most likely to ask.

1. **Versioning and rollback.** Especially once the copilot edits agents: show a diff of each AI change, let the user accept or reject it, and keep a history to undo bad changes. (AD-4)
2. **Call logs and evaluations.** Keep transcripts and node paths after a call. Then build scripted test conversations with expected paths ("a caller who wants to cancel should reach `cancel_confirm`") and run them after every prompt change to catch regressions. (AD-3, AD-6)
3. **Routing reliability.** The LLM chooses an edge only from its description. There's no guard or fallback if it never calls a function, picks the wrong edge, or fills arguments badly. Options: global edges available from every node (such as "talk to a human"), a limit on turns per node, and enum checks on arguments. (AD-2, AD-3)
4. **Running arbitrary prompts on shared keys.** Sign-in, rate limits and per-user quotas before anything is deployed. (AD-5)
5. **Patient data in transcripts and collected fields.** Encryption, retention limits, access controls and masking before real traffic. (AD-6)
