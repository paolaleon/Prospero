#
# AgentBuilder — loads a declarative agent (JSON / dict) and compiles its node
# graph into Pipecat Flows objects.
#
#   JSON  ->  AgentConfig (validated)  ->  Pipecat Flows NodeConfig graph
#
# This is the seam between "agent as data" (what the Phase 2 Composer produces)
# and "agent as a running conversation" (what bot.py executes). Keeping the
# compile + validation here means bot.py never touches the graph internals.
#

import json
from dataclasses import asdict
from pathlib import Path
from typing import Awaitable, Callable, Optional, Union

from loguru import logger
from pipecat_flows import FlowManager, FlowsFunctionSchema, NodeConfig

from .english import ENGLISH_ONLY_RULE
from .medical import NO_MEDICAL_ADVICE_RULE
from .schema import AgentConfig, Edge, Node
from .validation import validate_agent

# Called each time a transition is taken, just before the next node starts:
# (from_node, function, to_node, collected_args). bot.py uses it to record the
# call and stream its position in the graph to the editor.
TransitionHook = Callable[[str, str, str, dict], Awaitable[None]]

# Called when the LLM tries a transition without the data it requires, so the
# call stays where it is: (node, function, args, problems).
RefusalHook = Callable[[str, str, dict, list], Awaitable[None]]

# Called when a stuck call is moved to its fallback: (from_node, reason, to_node).
FallbackHook = Callable[[str, str, str], Awaitable[None]]

# A call whose transitions are refused this many times in a row in one node
# goes to its fallback (D-16).
FAILURE_LIMIT = 2

# Used when the agent has no fallback node of its own.
BUILT_IN_FALLBACK = "built_in_fallback"
BUILT_IN_FALLBACK_TASK = (
    "Apologise briefly that you couldn't help with this on the call, and say the clinic's staff "
    "can help directly. Then say goodbye. Don't ask the caller anything."
)


def check_args(edge: Edge, args: dict) -> list[str]:
    """What's wrong with the arguments the LLM gave for `edge`, if anything.

    The edge's schema is sent to the LLM, but nothing makes the model obey it:
    it can leave out a required field, send an empty one, or pick a value that
    isn't allowed. Those transitions are refused instead of moving on without
    the data. (A plausible but invented value can't be detected here.)
    """
    problems = []
    for name in edge.required:
        value = args.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"Missing required field '{name}'.")
    for name, schema in edge.properties.items():
        allowed = schema.get("enum") if isinstance(schema, dict) else None
        if allowed and name in args and args[name] not in allowed:
            options = ", ".join(str(a) for a in allowed)
            problems.append(f"Field '{name}' must be one of: {options} (got {args[name]!r}).")
    return problems


def _raise_if_invalid(data: dict) -> None:
    errors = [i.message for i in validate_agent(data) if i.severity == "error"]
    if errors:
        raise ValueError("Invalid agent: " + " ".join(errors))


class AgentBuilder:
    """Builds a runnable Pipecat Flows graph from a declarative AgentConfig."""

    def __init__(self, config: AgentConfig):
        # Every way of creating a builder validates, so nothing unrunnable compiles.
        _raise_if_invalid(asdict(config))
        self.config = config
        # Optional listeners, set by whoever runs the call (they usually need
        # objects that only exist once the call has started). Assign them before
        # the first transition: `builder.on_transition = my_listener`.
        self.on_transition: Optional[TransitionHook] = None
        self.on_transition_refused: Optional[RefusalHook] = None
        self.on_fallback: Optional[FallbackHook] = None
        # Where the call is, and how many times in a row it has failed there.
        self.current_node: Optional[str] = None
        self._refusals = 0
        self._nodes_by_name = {n.name: n for n in config.nodes}

    # ---- loading -----------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict) -> "AgentBuilder":
        # Validate the raw dict too, so malformed input (e.g. a missing key) gives a
        # readable error instead of a KeyError from the dataclass constructors.
        _raise_if_invalid(data)
        return cls(AgentConfig.from_dict(data))

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "AgentBuilder":
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    # ---- compilation -------------------------------------------------------
    def build_initial_node(self) -> NodeConfig:
        """Return the entry NodeConfig; downstream nodes are built lazily on transition."""
        self._enter(self.config.initial_node)
        return self._make_node(self._nodes_by_name[self.config.initial_node])

    # ---- recovering from a stuck node (D-16) --------------------------------
    @property
    def fallback_name(self) -> str:
        return self.config.fallback_node or BUILT_IN_FALLBACK

    def fallback_node_config(self) -> NodeConfig:
        """The node a stuck call goes to: the agent's own, or a polite ending."""
        if self.config.fallback_node:
            return self._make_node(self._nodes_by_name[self.config.fallback_node])
        return {
            "name": BUILT_IN_FALLBACK,
            "role_message": self._role_message(None),
            "task_messages": [{"role": "developer", "content": BUILT_IN_FALLBACK_TASK}],
            "functions": [],
            "post_actions": [{"type": "end_conversation"}],
        }

    async def take_fallback(self, reason: str) -> NodeConfig:
        """Move the call's bookkeeping to the fallback and return its config."""
        from_node = self.current_node or ""
        config = self.fallback_node_config()
        self._enter(self.fallback_name)
        logger.info(f"[fallback] {from_node} -> {self.fallback_name} | {reason}")
        await _notify(self.on_fallback, from_node, reason, self.fallback_name)
        return config

    def _stuck(self, count: int) -> bool:
        # Never fall back from the fallback itself, or a stuck call would loop.
        return count >= FAILURE_LIMIT and self.current_node != self.fallback_name

    def _enter(self, name: str) -> None:
        self.current_node = name
        self._refusals = 0

    def _make_node(self, node: Node) -> NodeConfig:
        node_config: NodeConfig = {
            "name": node.name,
            "role_message": self._role_message(node.role_message),
            "task_messages": node.task_messages,
            "functions": [self._make_edge_function(node, edge) for edge in node.edges],
        }
        if node.pre_actions:
            node_config["pre_actions"] = node.pre_actions
        # Explicit post_actions win; otherwise a terminal node ends the call.
        if node.post_actions:
            node_config["post_actions"] = node.post_actions
        elif node.end:
            node_config["post_actions"] = [{"type": "end_conversation"}]
        return node_config

    def _role_message(self, override: Optional[str]) -> str:
        # The medical safety and English rules are added to every node, so no
        # persona, written by hand or overridden per node, can drop them
        # (D-17, D-15).
        return f"{override or self.config.persona}\n\n{NO_MEDICAL_ADVICE_RULE}\n\n{ENGLISH_ONLY_RULE}".strip()

    def _make_edge_function(self, node: Node, edge: Edge) -> FlowsFunctionSchema:
        async def handler(args: dict, flow_manager: FlowManager):
            problems = check_args(edge, args)
            if problems:
                logger.info(f"[{edge.function}] refused in {node.name}: {problems} | args: {args}")
                await _notify(self.on_transition_refused, node.name, edge.function, args, problems)
                self._refusals += 1
                if self._stuck(self._refusals):
                    # Stuck: stop asking and move the call on to its fallback.
                    error = " ".join(problems) + " The call can't continue here, so it moves on to wrap up."
                    return {"status": "error", "error": error}, await self.take_fallback("missing information")
                # Stay in this node. Returning no next node makes Flows hand this
                # result straight back to the LLM, which can ask the caller again.
                error = " ".join(problems) + " Ask the caller for it, then call this function again."
                return {"status": "error", "error": error}, None

            # Persist what the caller gave us so later nodes can use it.
            flow_manager.state.update(args)
            logger.info(f"[{edge.function}] -> {edge.target} | collected: {args}")
            self._enter(edge.target)
            next_node = self._make_node(self._nodes_by_name[edge.target])
            await _notify(self.on_transition, node.name, edge.function, edge.target, args)
            return {"status": "success", **args}, next_node

        return FlowsFunctionSchema(
            name=edge.function,
            description=edge.description,
            properties=edge.properties,
            required=edge.required,
            handler=handler,
        )


async def _notify(listener, *args) -> None:
    """Call an optional listener; observability must never break the call."""
    if listener is None:
        return
    try:
        await listener(*args)
    except Exception as e:
        logger.warning(f"{getattr(listener, '__name__', 'listener')} failed: {e}")
