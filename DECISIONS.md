# Architectural Decisions

This file records the project's architectural decisions (ADs): decisions that are hard to undo and that shape how the system works. Most describe code that exists; an AD recorded ahead of its code says so. Each one is written to be defended from an AI product engineer's point of view:

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
| AD-4 | Agents are stored as immutable versions in JSON files |
| AD-5 | A test call carries the agent definition with it |
| AD-6 | Live call state reaches the browser over RTVI |
| AD-7 | Every call is recorded with the agent it ran |
| AD-8 | The frontend and backend are separate apps that only communicate over HTTP |
| AD-9 | Every edit to an agent is a named, serialisable operation |
| AD-10 | A transition without the data it requires is refused, and the call stays in its node |
| AD-11 | ProsperO, the copilot, specialises in voice agents for the medical field |
| AD-12 | Operations exist in Python and TypeScript, held identical by shared test cases |
| AD-13 | ProsperO is a stateless tool loop on the backend that edits through operations and can't finish with errors |
| AD-14 | ProsperO's work is a proposal over the draft, reviewed on the canvas and accepted as one step |
| AD-15 | Each agent has a list of languages, English only by default, enforced by the runtime |

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

**Decision.** `AgentBuilder` has an optional `on_transition` attribute: an async `(from_node, function, to_node, args)` listener. It's called each time a transition is taken, just before the next node starts. Whoever runs the call assigns it (`builder.on_transition = listener`), because the listener usually needs objects that only exist once the call has started; `bot.py` gives each call its own, bound to that call's recorder. If it fails, the error is logged and the call carries on.

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

## AD-4: Agents are stored as immutable versions in JSON files

**Decision.** A save never overwrites. Each one appends `backend/agents/{id}/versions/{n}.json`, which holds the agent plus `version`, `created_at`, a `message` and a `source` (`human`, `copilot` or `restore`). The latest version is the current agent. Rolling back appends a copy of an old version rather than deleting anything. A save sends the `base_version` it started from, and if someone saved in between, it's refused with `409`. All storage lives in `backend/store.py`, and `/api/agents` and `/api/agents/{id}/versions` sit on top of it.

**Product argument.**
- Nothing to set up or run.
- Agents can be diffed, reviewed in a pull request and committed, which treats the agent as code.
- Users get history and one-click rollback.
- A stale editor tab can't silently overwrite newer work.

**AI angle.** This decision exists for the copilot.
- **Every AI edit is reviewable and reversible.** A copilot change becomes a version tagged `source: "copilot"` with a message explaining it ("Shortened the greeting after 3 callers hung up"). It can be compared with the previous version and undone in one step. Users won't let an AI edit their production agent without that.
- **Calls point at exact versions** (AD-7). "Version 4 fixed the drop-off seen in version 3" is a claim the data can back up, which is the basis for measuring whether an iteration helped.

**Alternatives considered.**
- One mutable file per agent (the previous form of this decision). Replaced because it had no history, no rollback and no protection against stale writes.
- Using git itself as the version store. Rejected because it ties the product to a repository on disk and is awkward to expose through an API.
- SQLite or Postgres. Rejected for now: it's infrastructure the challenge doesn't need yet.
- A draft and publish workflow (like Retell's). Deferred: every save is a version for now. A "published" pointer for production traffic can be added later without changing the storage.

**Cost of reversal.** Low. All storage is in `store.py`, so moving to a database changes one module, not the API or the frontend.

**Likely challenges.**
- *"Every save keeps a full copy. Won't that grow without limit?"* An agent is a few KB, so thousands of versions are a few MB. Diffs between versions are computed on demand rather than stored.
- *"There are no tenants, no sign-in, no permissions."* Out of scope for Phase 1. It would come with the move to a database.
- *"Deleting an agent deletes its history."* True, and deliberate for a dev tool. A production system would archive instead.

**Revisit when** you need to tell production traffic apart from work in progress (add a published pointer), or you host it for more than one team (database and tenants).

---

## AD-5: A test call carries the agent definition with it

**Decision.** The `/start` request body decides which agent a call runs (`store.resolve_call_agent`), in this order:

1. An inline `agent`: an unsaved draft. The editor also sends the `agent_id` it's a draft of, so the call record (AD-7) is linked to that agent, with `agent_version` set to `null`.
2. A saved `agent_id`, at a given `version` or the latest.
3. Neither: `AGENT_FLOW`.

The editor sends the agent by reference (`agent_id` and `version`) when there are no unsaved changes, so the call record is tied to that version. Otherwise it sends the draft itself. A middleware (`StartValidationMiddleware` in `backend/call_guard.py`) checks that agent before the runner creates a session: an agent with errors is refused with `422` and its issues, and an unknown `agent_id` gets `404`.

**Product argument.** This is the iteration loop that matters most for a voice-agent builder: change a prompt, then call within seconds, with no save, deploy or restart. Each call is independent, so you could compare two versions of an agent side by side.

**AI angle.** Prompt engineering is trial and error, so the faster the loop, the better the agent. The loop is also ready for the copilot: it suggests an edit, the user calls the draft straight away, and only then decides to keep it.

**Alternatives considered.**
- Saving before every call and running only saved agents. Rejected because it's slower and fills the store with half-finished agents.
- Restarting the bot with a new `AGENT_FLOW` (the original setup). Rejected because it's far too slow.

**Cost of reversal.** Low. Allowing only saved versions is a one-line change in `store.resolve_call_agent`.

**Likely challenges.**
- *"Anyone who can reach the backend can run any prompt on your OpenAI and ElevenLabs keys."* **This is the main security and cost risk.** Acceptable for a local tool. In production, require sign-in, run only saved and validated versions, and rate-limit calls and minutes per user.
- *"What happens if the draft is invalid?"* The call is refused at `/start` with the same issues the editor shows, before any session or WebRTC connection exists. Without that check, the bot would only fail to build after the connection was up, and the client would wait for a call that never starts.
- *"Why a middleware rather than your own endpoint?"* `/start` belongs to the Pipecat runner, which keeps its sessions internally. Putting the check in front of it keeps the runner's own behaviour and its upgrades untouched.
- *"Can a client get round the check?"* Yes, by posting straight to the runner's `/api/offer` with an agent inside the request. The bot still refuses to build and logs the error, but that client gets no explanation. The editor never uses that path. For a deployment, only allow saved agents (see the cost risk above).
- *"The draft is sent in full on every call."* Agents are a few KB, so it doesn't matter.

**Revisit when** the tool is deployed beyond localhost, or calls start to cost real money.

---

## AD-6: Live call state reaches the browser over RTVI

**Decision.** `bot.py` sends two kinds of RTVI server message over the call's existing WebRTC connection:
- `{"type": "flow.node", ...}`: once when the client is ready (with the start node), and after every transition (with `from_node`, `function` and the collected `args`). The editor uses these to light up the active node and the edges taken.
- `{"type": "call.event", "event": ...}`: every event the call recorder writes (user turns, agent turns, transitions), as it's written (AD-7).

The live transcript is built from `call.event`, not from the SDK's own transcription callbacks, so what the editor shows during a call is exactly what gets saved.

**Product argument.** Users can debug by watching. The active node lights up, the data each step collected appears, and the transcript lines up with the path through the graph. That trust is what users of ElevenLabs Agents and Retell rely on.

**AI angle.** It explains LLM decisions. When the agent misroutes, the user sees which edge the model chose and with what arguments, and can fix that edge's description on the spot. That turns a black box into something the user can debug.

**Alternatives considered.**
- A separate WebSocket or a polling endpoint for call state. Rejected because it's an extra channel and needs its own session matching.
- Showing only the transcript. Rejected because users can't see the routing decisions.

**Cost of reversal.** Medium. The frontend will depend on the message format.

**Likely challenges.**
- *"Nothing is stored when the call ends."* It is: the same transitions are written to the call record (AD-7). RTVI is only the live view.
- *"It sends patient data (names, reasons for visit) to the browser."* **This is a healthcare compliance point.** For a local test tool, the person testing is the caller. In production, transcripts and collected fields are protected health information: they need encryption, retention limits and access controls, and may need masking in shared views.
- *"The agent's line only appears once it has finished speaking."* True. Events are sent when a turn is recorded. Streaming the text word by word from the SDK's callbacks would feel livelier, but it would be a second version of the transcript that could differ from the saved record.
- *"It only works with Pipecat clients."* True, and acceptable because the editor is a Pipecat client. Telephony calls wouldn't get the live view, but they would get call logs.

**Revisit when** you add phone calls or real patient traffic.

---

## AD-7: Every call is recorded with the agent it ran

**Decision.** `bot.py` records each call on the server (`CallRecorder`) and writes it to `backend/calls/{id}.json` when the call ends, whether the agent hung up or the caller did. The record is self-contained:
- **Agent:** a snapshot of the agent it ran, plus `agent_id` and `agent_version` (`null` for an unsaved draft).
- **Timeline:** user turns, agent turns (marked if interrupted), transitions (with their arguments) and refused transitions (AD-10).
- **Outcome:** `final_node`, the merged `collected` data, and `ended_by` (`agent` if it finished on an end node, otherwise `caller`).
- **Source:** `test`, `production` or `mock`.

Records are read through `/api/calls`. The client is told the call id when it connects (an RTVI `call.started` message). The `calls/` folder is gitignored.

**Product argument.** Every test call becomes something you can come back to. Users can replay what happened, see where callers dropped off (`ended_by: caller` before an end node), and compare calls across versions. Recording on the server, not in the browser, means production calls get recorded in exactly the same format even though they never pass through the editor.

**AI angle.** This is the copilot's raw material for the "production iteration" workflow.
- **Calls are evidence tied to nodes.** Each turn falls between known transitions, so an issue ("the agent offered times before asking the reason for the visit") can be pinned to a node and edge. The copilot can then propose a targeted edit instead of rewriting the prompt.
- **Snapshots keep evidence readable.** A call stays interpretable after the agent changes or nodes are renamed, because it carries the agent it ran. That's why node names can stay as identifiers without separate ids.
- **Ready for issue detection.** An LLM pass over the records can flag likely problems (loops, drop-offs, wrong transitions, missing data) without anyone listening to calls. That's the "detection is a burden" part of the brief.
- **Mock calls use the same format** (`source: "mock"`), so the copilot's loop can be shown without real call data.

**Alternatives considered.**
- Recording in the browser from the RTVI events. Rejected because production and phone calls never pass through the editor.
- Storing only a reference to the agent version. Rejected because drafts have no version, and a call would become unreadable if a version were ever deleted.
- Using Pipecat's audio recording. Deferred: text and structure are what the copilot reasons over. Audio can be added for tone and latency analysis.

**Cost of reversal.** Medium. The copilot and the call-history views will depend on the record format.

**Likely challenges.**
- *"Transcripts of a healthcare line are protected health information."* Yes. That's why `calls/` is gitignored. In production it needs encryption, retention limits, access controls, and masking before anything goes to an LLM.
- *"Turns have no audio timing or latency."* True. Timestamps are when each event was recorded, not when audio played. Latency analysis would need Pipecat's metrics added to the record.
- *"A record is only written when the call ends."* If the process crashes mid-call, that call is lost. Acceptable for now. Appending events to the file as they happen would fix it.

**Revisit when** you add real traffic (privacy controls), need latency or audio analysis, or call volume outgrows one folder of files (database).

---

## AD-8: The frontend and backend are separate apps that only communicate over HTTP

**Decision.** The editor lives in `frontend/` (React, TypeScript, React Flow) with its own dependencies, build and dev server. The backend serves JSON and the WebRTC call endpoints only, never UI files. The frontend finds the backend through one setting, `VITE_API_URL`. The Pipecat runner already allows cross-origin requests, so no backend changes were needed. The only contracts between the two are the HTTP API and the agent JSON format.

**Product argument.** Each side can be built, deployed and changed without touching the other. The UI ships as static files to any host, and the voice backend scales with the number of calls, not with editor traffic.

**AI angle.** Because the API is the only way in, the Phase 2 copilot gets the same capabilities a human has: it can run as a backend service, a CLI or an MCP tool and call `/api/agents`, `/api/validate` and `/api/calls` directly. Nothing the copilot needs is hidden inside the UI.

**Alternatives considered.**
- Having the backend serve the built frontend. Rejected because it ties backend releases to frontend builds.
- A no-build page loading libraries from a CDN. Rejected because it's harder to maintain as the editor grows.
- A full-stack framework such as Next.js. Rejected because the backend is Python, and a second server layer would add nothing.

**Cost of reversal.** Low to medium. Serving `frontend/dist` from the backend would take a few lines, but undoing the separation would mean merging two release cycles.

**Likely challenges.**
- *"Two processes to run in development."* True. Each is one command: `npm run dev` in `frontend/` and `python bot.py` in `backend/`.
- *"`allow_origins=*` is permissive."* True, and it's the runner's default. A deployment should restrict it to the editor's origin with the runner's `--allowed-origins` option.

**Revisit when** the editor is deployed (restrict origins, add sign-in).

---

## AD-9: Every edit to an agent is a named, serialisable operation

**Decision.** The editor's draft only changes through `applyOp(agent, op)` in `frontend/src/lib/operations/`. That function is pure and is the single place where an agent is modified. An `Op` is plain data: `addNode`, `renameNode`, `updateEdge`, `moveNodes` and so on, each with a readable label from `describeOp`. The canvas, the inspector, JSON import and undo/redo all dispatch operations through the store (`frontend/src/lib/store.ts`). Operations whose meaning spans the graph handle every reference: renaming a node rewrites the start node and every edge that targets it, and deleting a node keeps the transitions that pointed at it but clears their target, so validation flags each one.

**Product argument.**
- One undo/redo history, with readable labels, covers every kind of edit.
- Typing in a field becomes a single undo step instead of one per keystroke.
- No part of the UI can leave the graph inconsistent, for example a rename that breaks the edges pointing at a node.

**AI angle.** This is how the copilot plugs into the editor.
- **One vocabulary for people and the AI.** The copilot doesn't return a whole new JSON for the agent; it proposes a list of operations ("rename `offer_times` to `offer_slots`", "edit the description of `select_time`"). Small, targeted edits are easier for an LLM to get right than regenerating the whole document, and a reviewer can read them.
- **Reviewable by construction.** A proposal is a list of labelled operations that can be previewed on the canvas, then accepted or rejected one by one. It becomes a version with `source: "copilot"` (AD-4).
- **Safe to apply.** `applyOp` refuses operations that don't fit the agent (an unknown node, a name collision), so a hallucinated edit fails loudly instead of corrupting the graph. Validation (AD-2) then catches anything that's structurally wrong.

**Alternatives considered.**
- Letting each component edit the agent object directly. Rejected because there'd be no history, no labels, and nothing a copilot could share.
- JSON Patch (RFC 6902). Rejected as the main vocabulary because paths like `/nodes/3/edges/1` mean nothing to a reviewer and break when nodes move. Patches could still be produced from operations if needed.
- Having the copilot regenerate the whole agent JSON. Rejected because it costs more tokens, drifts unpredictably, and is hard to review.

**Cost of reversal.** High once the copilot exists. Its tool definitions would be these operations.

**Likely challenges.**
- *"Can the backend use the operations too?"* Yes, since AD-12: the same operations exist in Python, and both implementations are held to the same shared test cases. ProsperO applies them on the backend.
- *"Undo history is lost on reload."* True. It's per session. Versions (AD-4) are the long-term history.

**Revisit when** you build the copilot's tool interface (decide where `applyOp` runs), or need edits from several people at once (operations are the basis for merging).

---

## AD-10: A transition without the data it requires is refused, and the call stays in its node

**Decision.** Before taking a transition, its handler (`check_args` in `backend/agent_builder/builder.py`) checks the arguments the LLM supplied against the edge's own schema:
- every **required** field must be present and not blank;
- any field with **allowed values** (`enum`) must use one of them.

If a check fails, the transition is **refused**:
- the call stays in the current node and nothing is saved to the call's state;
- the handler returns an error to the LLM ("Missing required field 'reason'. Ask the caller for it, then call this function again."). Pipecat Flows runs the LLM again straight away, so the agent asks the caller for what's missing;
- an `on_transition_refused` listener is notified. `bot.py` records it as a `refused` event in the call record (AD-7) and streams it to the editor, where it shows in amber in the transcript.

**Product argument.** A field marked "Required" in the editor now means what it says. Without this, an agent could move on to `offer_times` without a name, and the booking would fail later, or never, with nothing in the transcript to explain why. Builders get the behaviour they configured, and see it in the transcript when the model tries to cut corners.

**AI angle.**
- **The schema is a request, not a guarantee.** OpenAI's models usually respect a tool's required fields, but nothing forces them to: without strict mode, a model can leave a field out, send an empty string, or choose a value outside the allowed list. This turns those failures into a recoverable step instead of corrupt data.
- **Self-correction instead of failure.** The refusal is phrased as an instruction the LLM can act on, so the usual outcome is one extra question to the caller, not a broken call.
- **A signal for Phase 2.** Each refusal is recorded with its node, function and problems. Several refusals in the same node across calls mean its instructions don't make the model gather the data, which is the kind of issue the copilot should detect and fix (for example, by adding "ask for the reason for the visit" to the node).

**Alternatives considered.**
- OpenAI's strict structured outputs. Not used for now: they constrain the format, but a model can still fill a required field with an invented value, and they're specific to OpenAI. Our check runs the same way for any LLM provider. The two could also be combined later.
- Refusing only in the editor, through validation. Not possible: whether the data is present is only known during the call.
- Transitioning anyway and flagging the problem afterwards. Rejected because the call would continue without data that later nodes rely on.

**Cost of reversal.** Low. Removing the check restores the previous behaviour; recorded `refused` events would simply stop appearing.

**Likely challenges.**
- *"Can the call get stuck asking again and again?"* In principle, if the caller never gives the information. There's no limit yet on refusals per node; the caller can still hang up, and the repeated refusals show up in the record. A limit, or a fallback edge after N refusals, is part of gap 3.
- *"It doesn't catch invented values."* Correct. "Unknown" or a misheard name passes, because it's a non-empty string. Detecting that needs checks specific to each field (e.g. a date format) or an LLM review of the call afterwards.
- *"Only required fields and allowed values are checked, not types."* True. A number sent as text, for example, isn't refused. Type checks could be added to `check_args` the same way.

**Revisit when** you add stricter field types (dates, phone numbers), when a limit on refusals per node is needed, or if strict structured outputs become simple to enable through Pipecat.

---

## AD-11: ProsperO, the copilot, specialises in voice agents for the medical field

**Decision.** ProsperO, the Phase 2 copilot that builds and edits agents from natural-language prompts, is designed for **voice agents used by medical practices**: clinics and practices handling scheduling, rescheduling and cancellations, patient intake, reminders, prescription refill requests, billing questions, and routing urgent calls. It's being built on the `phase-2-copilot` branch, and this decision shapes it from the start.

The domain shows up in what ProsperO does by default when it builds an agent:
- **Identity before details:** verify the caller (e.g. full name and date of birth) before discussing an existing appointment or record.
- **No medical advice:** the agent never diagnoses or advises on treatment; it offers to book or to pass the question to staff.
- **Emergencies first:** an urgent or emergency path that tells the caller to hang up and call emergency services, or transfers them, reachable from the start of the call.
- **Collect only what's needed:** each piece of patient data must serve the call's purpose, in line with handling protected health information (PHI) carefully.
- **Spoken, plain language:** short replies, one question at a time, confirmation of key details (date, time, name) before ending.

**Product argument.**
- **It matches Prosper's market.** Prosper's clients are healthcare organisations, and the deployment team's manual work is building agents for them. A copilot that already knows how a clinic call should go produces a usable first draft, not a generic one that needs heavy rework.
- **Fewer iterations to a deployable agent.** The safety basics (emergencies, no medical advice, identity checks) are present from the first draft instead of being remembered by whoever writes the prompt.
- **It's a sharper product than a generic agent builder:** specialist copilots can be judged on outcomes in their domain.

**AI angle.**
- **A narrower domain makes the LLM more reliable.** The system prompt can carry a concrete checklist, real examples of good clinic flows, and domain vocabulary, instead of generic advice. That improves first drafts more than a larger model would.
- **Safety-critical behaviour shouldn't depend on the user remembering to ask for it.** Emergency escalation and refusing medical advice are built in by default, and can later be checked by validation rules. For example: "no emergency path reachable from the start node" as a warning, using the rule registry from AD-2.
- **Evaluation gets concrete.** Test scenarios for Phase 2's regression tests (a new patient booking, a caller describing chest pain, a refill request) come from a known set of call types.

**Alternatives considered.**
- **A general-purpose copilot** for any kind of voice agent. Rejected: the defaults would be weaker exactly where mistakes are most costly, and nothing would distinguish it from generic builders.
- **One specialty only** (e.g. dental). Rejected as too narrow for Prosper's client base; the same core flows recur across specialties.
- **Pluggable "domain packs"** (medical, legal, retail…), each with its own prompt, examples and rules. Deferred: a good design once a second domain exists, premature with one.

**Cost of reversal.** Low to medium. The architecture (operations, validation, versions, calls) is domain-neutral. The specialisation lives in ProsperO's system prompt, examples and any medical validation rules, which could later become one domain pack among several.

**Likely challenges.**
- *"Is a prompt enough for compliance?"* No. Defaults in the prompt make agents behave more safely, but compliance with regulations such as HIPAA also needs agreements with vendors, encryption, access controls and retention policies (gap 5). ProsperO makes better agents; it doesn't make the platform compliant.
- *"What if the LLM drops a safety default while editing?"* Possible, since prompt guidance isn't enforcement. Validation rules for the critical defaults would catch it on every edit, by a person or by ProsperO. That's the planned backstop.
- *"What about a client outside medicine?"* ProsperO can still build their agent, but its defaults will assume a medical practice and need overriding. Domain packs are the answer if that becomes common.
- *"Medical knowledge varies by country and specialty."* True, so ProsperO should ask about specifics that matter (e.g. the local emergency number, after-hours policy) rather than assume them.

**Revisit when** a client outside medicine needs a copilot (introduce domain packs), or a specialty needs rules the general medical defaults don't cover.

---

## AD-12: Operations exist in Python and TypeScript, held identical by shared test cases

**Decision.** The operations from AD-9 now have two implementations:
- **TypeScript** (`frontend/src/lib/operations/`), which the editor uses for people's edits, undo/redo and previews;
- **Python** (`backend/agent_builder/operations/`), which ProsperO will use on the backend to build and edit agents.

Both are organised the same way: one entry per operation, in a file per area (`agent`, `node`, `edge`), holding how it's applied and how it's labelled. The Python entry also holds the operation's JSON schema, which ProsperO's tool definitions are built from. In TypeScript, a mapped type makes the build fail if any operation lacks an entry. Operations are the same plain JSON in both languages, so an operation produced on the backend can be applied unchanged in the browser.

**`shared/operation-cases.json`** keeps the two identical. Each case names a starting agent, an operation, and the expected result, label or exact error message. Both pytest and Vitest run every case and also check that the input agent is never modified. Changing either implementation without the other fails a test.

**Product argument.** ProsperO's edits and a person's edits behave exactly the same. A rename by ProsperO rewrites references the way a rename on the canvas does, and an invalid edit fails with the same message. So what the user previews in the browser is precisely what was built on the server.

**AI angle.**
- **Precise errors the LLM can act on.** An operation that doesn't fit is refused with a specific message ("No node named 'verify_patient'.", "Node 'greeting' has no transition #3."), returned to the LLM so it can correct itself. Both languages raise errors instead of doing nothing silently, for example for a negative transition index or an unknown start node.
- **Tools that match the code.** ProsperO's tool definitions come from the same registry entry that applies the operation, so the LLM can't be told about a field the code doesn't accept.

**Alternatives considered.**
- **Operations only in the browser, with ProsperO streaming them there to be applied.** Rejected: the backend couldn't validate or repair ProsperO's work before showing it, and a proposal would depend on a browser tab being open.
- **Operations only on the backend,** with the editor calling the API for every edit. Rejected: every keystroke and drag would wait for the network, and undo/redo would need the server.
- **Generating one implementation from the other,** or from a shared schema. Rejected for now: the operations are short, and the shared cases catch differences with far less machinery. It would be worth reconsidering if the number of operations grows a lot.

**Cost of reversal.** Medium. Dropping one implementation means moving its users (the editor or ProsperO) to the other side of the network.

**Likely challenges.**
- *"Two implementations means double the work."* Each operation is about ten lines in each language, and the shared cases make a missed change fail immediately. The duplication is small and checked.
- *"The shared cases might not cover everything."* A test fails if any registered operation has no shared case, but a case can still miss an edge case within an operation. New behaviour should come with a new shared case.
- *"The TypeScript side has no schema."* True. It doesn't need one: the editor builds operations in code, where TypeScript's types check them. Schemas live where operations arrive as untrusted JSON, which is the backend.

**Revisit when** there are many more operations, or a third consumer (a CLI, another service) needs them; then generating implementations from one definition would pay off.

---

## AD-13: ProsperO is a stateless tool loop on the backend that edits through operations and can't finish with errors

**Decision.** ProsperO (`backend/prospero/`) runs one turn per user message at `POST /api/copilot`:
- **Input:** the agent as it currently stands (none for a new agent), the chat so far, and the new message. The server keeps nothing between turns.
- **Tools:** the agent operations, generated from the operation registry (AD-12), minus `moveNodes` (layout is the editor's job) and `replaceAgent` (no wholesale rewrites). Plus `validate`, which runs the shared validator (AD-2), and `finish(summary, assumptions)`.
- **The loop:** the LLM proposes edits; the server applies each one to a working copy with `apply_op`. A misfit is refused and the exact error goes back to the LLM. `finish` is refused while the agent has errors. A turn stops after 40 LLM calls.
- **Output:** a stream of server-sent events: every applied edit (`op`), validation results, notes, and finally `done` (summary, assumptions, final agent), `reply` (a question for the user) or `error`.
- **The model** is OpenAI, `gpt-5.5` by default, set with `PROSPERO_MODEL`, with reasoning off by default (`PROSPERO_REASONING`). Replies are streamed, and each tool call is applied as soon as it's complete. The system prompt (`prompt.py`) carries the agent format and the medical defaults from AD-11.

**Product argument.**
- **The user watches the agent being built,** edit by edit, instead of waiting for a finished blob, and every edit has a readable label.
- **What ProsperO hands over is runnable.** It can't finish with errors, so the user never receives an agent the voice runtime would reject.
- **No lost conversations.** Because turns are stateless, a backend restart or a second browser tab can't lose or corrupt a session.

**AI angle.**
- **Small edits instead of one big document.** Producing many small, checked edits is more reliable for an LLM than writing a whole JSON agent in one go, and each mistake is caught at the edit that made it.
- **Self-correction with precise feedback.** Refused edits and validation results come back as exact messages ("No node named 'verify_patient'."), so the model fixes its own errors within the turn.
- **The agent the LLM sees is the real one.** It gets the current agent, without canvas positions, on every turn, so edits in a later turn ("add a cancellation path") apply to what's really there, including the user's own changes.
- **The LLM is swappable.** The loop takes the LLM call as a function. Tests drive it with a scripted fake (12 tests, no cost, deterministic), and changing provider or model touches one function.

**Alternatives considered.**
- **Generating the whole agent JSON in one structured response.** Rejected: no live drawing, harder to review, and one mistake means regenerating everything.
- **Running the loop in the browser.** Rejected: it would expose the API key, and the backend owns validation.
- **Keeping sessions on the server.** Rejected for now: stateless turns are simpler and survive restarts. The cost is resending the agent each turn, a few thousand tokens.
- **Claude instead of OpenAI.** The user chose OpenAI, which reuses the existing key. The loop is provider-neutral apart from `openai_complete`.

**Cost of reversal.** Medium. The event format is the contract with the editor, and the operation-based approach shapes how proposals are reviewed.

**Likely challenges.**
- *"It's slow."* Measured on the same prompt: `gpt-5.5` with default reasoning took about 30 seconds, with the first edits after about 15. With reasoning off (now the default, `PROSPERO_REASONING=none`), the first edits arrive after about 9 seconds and a build takes 23 to 29 seconds, with the same validity and medical defaults. Most of the time is spent writing out the edits (about 1,000 tokens per reply), not thinking. The loop streams replies and applies each tool call as soon as it's complete, but OpenAI delivers `gpt-5.5`'s tool calls all at the end of a reply, on both its APIs, so edits still arrive in bursts. `gpt-4.1` streams small replies and draws continuously from about 2 seconds (21 seconds per build, all checks passed on one prompt), but it's a less capable model; it remains available through `PROSPERO_MODEL`. `gpt-5.4-mini` was faster still but stopped before finishing. The editor plays bursts onto the canvas one edit at a time and shows what ProsperO is doing, so the wait is visible rather than silent.
- *"Valid isn't the same as good."* True. Validation guarantees the agent runs, not that it handles callers well. The medical defaults in the prompt help; regression tests from recorded calls (Phase 2 backlog) are the real measure.
- *"Anyone who reaches the endpoint spends your OpenAI credit."* As with test calls (AD-5), fine locally; a deployment needs sign-in and rate limits.
- *"The model could ignore the medical defaults."* It followed them in the first real build, but nothing enforces them yet. Medical validation rules (AD-11) are the planned backstop.

**Revisit when** turns get slow enough to hurt the experience (stream the LLM's output), conversations get long (summarise history), or several people work on one agent (server-side sessions).

---

## AD-14: ProsperO's work is a proposal over the draft, reviewed on the canvas and accepted as one step

**Decision.** ProsperO never edits the draft directly. Its edits form a **proposal** held next to the draft in the editor store (`frontend/src/lib/store.ts`):
- **While it builds,** each streamed edit is applied to a copy of the draft with the same `applyOp` as people's edits (AD-12). The canvas shows the proposal read-only, with nodes marked **New**, **Changed** or **Removed** (removed ones faded in place), compared with the draft by `diffAgents` (`frontend/src/lib/diff.ts`).
- **Editing and undo are paused** while a proposal is open, so a person's edits and ProsperO's can't interleave.
- **Test calls run the proposal,** so it can be called before it's accepted.
- **Accept** applies the whole proposal as **one undoable step** and saves it as a version with `source: "copilot"` and ProsperO's summary as the message (AD-4). **Reject** discards it. Follow-up messages keep building on the same proposal.
- **ProsperO doesn't place nodes:** positions are left out of its tools, and the editor lays out new nodes.

**Product argument.**
- **The user stays in control.** Nothing ProsperO does is kept without an explicit Accept, and the summary and assumptions are shown next to the button.
- **Changes are easy to review:** they're marked on the graph itself rather than in a JSON diff, which suits non-engineers on the deployment team.
- **Try before you accept.** A test call against the proposal is the most direct check of a voice agent.
- **One undo reverts it all,** and the copilot version in History says exactly what ProsperO changed and when.

**AI angle.**
- **Human review is the backstop for what validation can't judge,** such as tone, flow and medical appropriateness (AD-11). Making review the default path is what makes an LLM safe to use on production agents.
- **Attribution is preserved.** Copilot versions are kept separate from human versions, which matters for auditing and for measuring whether ProsperO's changes help (Phase 2's call data and regression tests).

**Alternatives considered.**
- **Applying edits straight into the draft,** like a person's. Rejected (the user's choice): AI and human edits blur together, and there's no single place to accept or reject.
- **A text or JSON diff view.** Rejected as the main view: hard to read for a graph; the canvas shows structure directly.
- **Letting the user edit while ProsperO works.** Rejected for now: merging concurrent edits needs conflict handling that isn't worth it yet.

**Cost of reversal.** Medium. The store, canvas, call panel and Accept flow all assume proposals.

**Likely challenges.**
- *"Accept also saves any unsaved changes I made before asking ProsperO."* True: the proposal starts from the draft, unsaved edits included, and Accept saves the result as one copilot version. Saving before asking avoids mixing them.
- *"Removed transitions aren't shown."* Correct. Removed nodes are, but a removed transition only shows as its node being "Changed". A per-transition view would need ghost edges.
- *"I can't accept part of a proposal."* Not yet: it's all or nothing. Rejecting and asking ProsperO for a narrower change is the workaround. Per-edit accept would build on the same edit list.

**Revisit when** users need partial acceptance, or several people (or ProsperO and a person) need to edit at the same time.

---

## AD-15: Each agent has a list of languages, English only by default, enforced by the runtime

**Decision.** An agent has an optional `languages` field: ISO 639-1 codes, default first (`["en"]`, `["en", "es"]`). Without it, the agent is **English only**. It's set per agent, like the voice: in Agent settings or by ProsperO. The runtime enforces it in three places (`backend/agent_builder/languages.py`):
- **The LLM:** the builder adds a language rule to **every node's** role message, after the persona or the node's persona override, so no node can drop it. With one language: "speak only English, whatever language the caller uses". With several: start in the default, offer the choice at the start of the call, then keep to the caller's choice.
- **Callers in other languages:** told, in the default language, that the agent can only help in its languages, and offered a call back from staff (taking their name and phone number). That's option 1 of three considered.
- **Speech-to-text and text-to-speech:** fixed to the language when there's one; left to detect it when there are several.

Validation refuses an empty list, unsupported codes, and duplicates. The supported languages are served at `/api/languages`, so the editor's picker can't drift from the backend.

**Product argument.**
- **Clinics decide which languages their agent speaks.** In testing, the agent switched to whatever language the caller used. For a medical practice, that means instructions, confirmations and safety messages in a language nobody at the clinic can verify.
- **Multilingual clinics get it as a setting, not a prompt hack:** list the languages, and the agent offers them in the greeting.
- **No caller is stranded:** callers in other languages are offered a call back instead of a dead end.

**AI angle.**
- **Enforced outside the prompt the user writes.** The rule is added by the builder at runtime, not written into the persona, so neither a person nor ProsperO can forget or remove it while editing. ProsperO is told not to write language rules itself.
- **Speech services fixed to one language** are more accurate for that language, and reduce the chance of the LLM receiving text in another language at all.
- **Verified on a real call:** a Spanish-speaking caller to an English-only agent got English replies and an offer of a call back.

**Alternatives considered.**
- **A persona instruction only.** Rejected: easy to edit away or forget, and it does nothing for speech recognition.
- **Ignoring other languages, or explaining without offering anything.** Rejected in favour of offering a call back, so callers aren't left without help.
- **Detecting the language and refusing in the caller's own language.** Rejected for now: it means speaking a language the clinic didn't approve, which is what this decision prevents.

**Cost of reversal.** Low. The field is optional, and removing the rule restores the previous behaviour.

**Likely challenges.**
- *"Speech in other languages gets misheard."* Yes. With speech-to-text fixed to English, a Spanish caller's words are partly transcribed as English ("Hola… por favor" came out as "Homer. All favor."). The agent still noticed and offered a call back, but a name or number taken for the call back can be garbled.
- *"The call-back details aren't stored as data."* True. They're only in the transcript, because no transition collects them. A dedicated "take a message" transition, or a global edge, would make it structured.
- *"Multilingual agents aren't tested on a real call."* The rule for several languages is covered by unit tests only so far.
- *"The voice may not suit the language."* ElevenLabs voices are multilingual but sound most natural in their own accent. The voice picker shows each voice's accent; matching them is left to the user.

**Revisit when** call-back requests need to be structured data, or clinics need different languages per node (for example, a Spanish-only line).

---

## Gaps to prepare for

These aren't decisions yet. They're the questions an AI product reviewer is most likely to ask.

1. **Reviewing AI edits.** Versions and rollback exist (AD-4). Still missing is a visual diff of a proposed change on the canvas, with accept and reject, before it becomes a version.
2. **Evaluations.** Calls are recorded (AD-7). Still missing are scripted test conversations with expected paths ("a caller who wants to cancel should reach `cancel_confirm`"), run after every change to catch regressions. (AD-3, AD-7)
3. **Routing reliability.** Partly addressed: a transition missing required data, or with a value outside its allowed list, is refused and the LLM asks again (AD-10). Still missing: a fallback if the LLM never calls a function or picks the wrong edge, global edges available from every node (such as "talk to a human"), a limit on turns per node, and detecting plausible but invented values. (AD-2, AD-3, AD-10)
4. **Running arbitrary prompts on shared keys.** Sign-in, rate limits and per-user quotas before anything is deployed. (AD-5)
5. **Patient data in transcripts and collected fields.** Encryption, retention limits, access controls and masking before real traffic. (AD-6, AD-7)
