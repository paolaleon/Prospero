#
# Agent validation — checks a raw agent dict and reports every problem at once.
#
# The builder only needs to know "is this runnable?", but the editor needs to know
# *what* is wrong and *where*, so issues carry the node / edge they belong to and the
# UI can pin them to the canvas. Errors make an agent unrunnable; warnings are
# likely mistakes (unreachable nodes, dead ends) that still compile.
#
# Each check is a small rule registered with one of three decorators:
#
#   @agent_rule  def rule(ctx)                    -> issues about the whole agent
#   @node_rule   def rule(ctx, node)              -> issues about one node
#   @edge_rule   def rule(ctx, node, index, edge) -> issues about one transition
#
# The runner does the looping, and `Context` holds the facts several rules need
# (node names, the graph, what's reachable), computed once. To add a check, write
# one decorated function that returns (or yields) Issues; nothing else changes.
#

import re
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Literal, Optional

# OpenAI tool names: ^[a-zA-Z0-9_-]{1,64}$
FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


@dataclass
class Issue:
    severity: Literal["error", "warning"]
    message: str
    node: Optional[str] = None   # node name the issue belongs to
    edge: Optional[int] = None   # index into that node's edges

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def error(message: str, node: Optional[str] = None, edge: Optional[int] = None) -> Issue:
    return Issue("error", message, node, edge)


def warning(message: str, node: Optional[str] = None, edge: Optional[int] = None) -> Issue:
    return Issue("warning", message, node, edge)


# ---- facts shared by the rules -------------------------------------------------
@dataclass
class Context:
    data: dict                      # the raw agent
    nodes: list                     # every entry of data["nodes"], as given
    named: list = field(default_factory=list)   # node dicts that have a name
    known: set = field(default_factory=set)     # their names
    graph: dict = field(default_factory=dict)   # name -> targets of its valid edges
    reachable: set = field(default_factory=set) # names reachable from the start node

    @classmethod
    def build(cls, data: dict) -> "Context":
        ctx = cls(data=data, nodes=data["nodes"])
        ctx.named = [n for n in ctx.nodes if isinstance(n, dict) and _has_text(n.get("name"))]
        ctx.known = {n["name"] for n in ctx.named}
        ctx.graph = {name: [] for name in ctx.known}
        for node in ctx.named:
            for edge in node.get("edges") or []:
                if edge.get("target") in ctx.known:
                    ctx.graph[node["name"]].append(edge["target"])
        # The runtime can send a call to the fallback node from anywhere (D-16).
        ctx.reachable = _reachable(ctx.graph, data.get("initial_node"))
        if data.get("fallback_node") in ctx.known:
            ctx.reachable |= _reachable(ctx.graph, data["fallback_node"])
        return ctx

    @property
    def initial(self) -> Optional[str]:
        return self.data.get("initial_node")


def _reachable(graph: dict, start: Optional[str]) -> set:
    if start not in graph:
        return set()
    seen, queue = {start}, deque([start])
    while queue:
        for nxt in graph[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _has_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _label(edge: dict, index: int) -> str:
    """How a transition is named in messages: its function, or its position."""
    return f"'{edge['function']}'" if edge.get("function") else f"#{index + 1}"


# ---- registry --------------------------------------------------------------------
Issues = Iterable[Issue]
_AGENT_RULES: list[Callable[[Context], Issues]] = []
_NODE_RULES: list[Callable[[Context, dict], Issues]] = []
_EDGE_RULES: list[Callable[[Context, dict, int, dict], Issues]] = []


def agent_rule(fn):
    _AGENT_RULES.append(fn)
    return fn


def node_rule(fn):
    _NODE_RULES.append(fn)
    return fn


def edge_rule(fn):
    _EDGE_RULES.append(fn)
    return fn


def validate_agent(data: dict) -> list[Issue]:
    # Without a node list nothing else can be checked meaningfully.
    if not isinstance(data, dict):
        return [error("Agent must be a JSON object.")]
    if not isinstance(data.get("nodes"), list) or not data["nodes"]:
        return [*_name_issues(data), error("Agent has no nodes.")]

    ctx = Context.build(data)
    issues: list[Issue] = []
    for rule in _AGENT_RULES:
        issues += rule(ctx) or []
    for node in ctx.named:
        for rule in _NODE_RULES:
            issues += rule(ctx, node) or []
        for index, edge in enumerate(node.get("edges") or []):
            for rule in _EDGE_RULES:
                issues += rule(ctx, node, index, edge) or []
    # Errors first, so the most serious problem is what the editor shows first.
    return sorted(issues, key=lambda i: i.severity != "error")


# ---- agent rules -------------------------------------------------------------------
def _name_issues(data: dict) -> Issues:
    if not _has_text(str(data.get("name", ""))):
        yield error("Agent needs a name.")


@agent_rule
def agent_needs_name(ctx: Context) -> Issues:
    # Also reported for agents with no nodes, before the context exists.
    return _name_issues(ctx.data)


@agent_rule
def nodes_have_unique_names(ctx: Context) -> Issues:
    seen = set()
    for i, node in enumerate(ctx.nodes):
        name = node.get("name") if isinstance(node, dict) else None
        if not _has_text(name):
            yield error(f"Node #{i + 1} has no name.")
        elif name in seen:
            yield error(f"Duplicate node name '{name}'.", node=name)
        else:
            seen.add(name)


@agent_rule
def start_node_exists(ctx: Context) -> Issues:
    if not ctx.initial:
        yield error("No start node selected.")
    elif ctx.initial not in ctx.known:
        yield error(f"Start node '{ctx.initial}' is not a defined node.")


@agent_rule
def fallback_node_exists(ctx: Context) -> Issues:
    fallback = ctx.data.get("fallback_node")
    if fallback and fallback not in ctx.known:
        yield error(f"Fallback node '{fallback}' is not a defined node.")


@agent_rule
def nodes_are_reachable(ctx: Context) -> Issues:
    if ctx.initial not in ctx.known:
        return  # reported by start_node_exists
    for node in ctx.named:
        if node["name"] not in ctx.reachable:
            yield warning("Unreachable from the start node.", node=node["name"])


@agent_rule
def an_end_node_is_reachable(ctx: Context) -> Issues:
    if ctx.initial not in ctx.known:
        return
    if not any(n.get("end") and n["name"] in ctx.reachable for n in ctx.named):
        yield warning("No end node is reachable, so the call never hangs up on its own.")


# ---- node rules --------------------------------------------------------------------
@node_rule
def node_has_instructions(_ctx: Context, node: dict) -> Issues:
    tasks = node.get("task_messages") or []
    if not any(_has_text(str(m.get("content", ""))) for m in tasks if isinstance(m, dict)):
        yield warning("Node has no instructions.", node=node["name"])


@node_rule
def end_node_has_no_transitions(_ctx: Context, node: dict) -> Issues:
    if node.get("end") and node.get("edges"):
        yield warning("End node has transitions; the call ends after this node anyway.", node=node["name"])


@node_rule
def node_is_not_a_dead_end(_ctx: Context, node: dict) -> Issues:
    if not node.get("end") and not node.get("edges"):
        yield warning("Dead end: no transitions and not marked as an end node.", node=node["name"])


# ---- edge rules --------------------------------------------------------------------
@edge_rule
def function_name_is_valid_and_unique(_ctx: Context, node: dict, index: int, edge: dict) -> Issues:
    fn = edge.get("function") or ""
    if not FUNCTION_NAME_RE.match(fn):
        yield error(
            f"Transition {_label(edge, index)}: function name must be 1-64 letters, digits, '_' or '-'.",
            node=node["name"], edge=index,
        )
    elif any(e.get("function") == fn for e in node["edges"][:index]):
        yield error(f"Duplicate transition function '{fn}'.", node=node["name"], edge=index)


@edge_rule
def edge_has_description(_ctx: Context, node: dict, index: int, edge: dict) -> Issues:
    if not _has_text(str(edge.get("description", ""))):
        yield error(
            f"Transition {_label(edge, index)} needs a description (the LLM uses it to decide).",
            node=node["name"], edge=index,
        )


@edge_rule
def edge_targets_a_node(ctx: Context, node: dict, index: int, edge: dict) -> Issues:
    target = edge.get("target")
    if not target:
        yield error(f"Transition {_label(edge, index)} has no target node.", node=node["name"], edge=index)
    elif target not in ctx.known:
        yield error(
            f"Transition {_label(edge, index)} targets unknown node '{target}'.", node=node["name"], edge=index
        )


@edge_rule
def edge_fields_are_well_formed(_ctx: Context, node: dict, index: int, edge: dict) -> Issues:
    props = edge.get("properties") or {}
    for prop, schema in props.items():
        ptype = schema.get("type") if isinstance(schema, dict) else None
        if ptype not in JSON_TYPES:
            yield error(
                f"Transition {_label(edge, index)}: field '{prop}' has invalid type '{ptype}'.",
                node=node["name"], edge=index,
            )
    for req in edge.get("required") or []:
        if req not in props:
            yield error(
                f"Transition {_label(edge, index)}: required field '{req}' is not defined.",
                node=node["name"], edge=index,
            )
