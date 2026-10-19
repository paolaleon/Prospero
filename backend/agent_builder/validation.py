#
# Agent validation — checks a raw agent dict and reports every problem at once.
#
# The builder only needs to know "is this runnable?", but the editor needs to know
# *what* is wrong and *where*, so issues carry the node / edge they belong to and the
# UI can pin them to the canvas. Errors make an agent unrunnable; warnings are
# likely mistakes (unreachable nodes, dead ends) that still compile.
#

import re
from collections import deque
from dataclasses import asdict, dataclass
from typing import Literal, Optional

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


def validate_agent(data: dict) -> list[Issue]:
    issues: list[Issue] = []

    def error(msg, node=None, edge=None):
        issues.append(Issue("error", msg, node, edge))

    def warn(msg, node=None, edge=None):
        issues.append(Issue("warning", msg, node, edge))

    if not isinstance(data, dict):
        return [Issue("error", "Agent must be a JSON object.")]
    if not str(data.get("name", "")).strip():
        error("Agent needs a name.")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        error("Agent has no nodes.")
        return issues

    names: list[str] = []
    for i, node in enumerate(nodes):
        name = node.get("name") if isinstance(node, dict) else None
        if not isinstance(name, str) or not name.strip():
            error(f"Node #{i + 1} has no name.")
            continue
        if name in names:
            error(f"Duplicate node name '{name}'.", node=name)
        names.append(name)
    known = set(names)

    initial = data.get("initial_node")
    if not initial:
        error("No start node selected.")
    elif initial not in known:
        error(f"Start node '{initial}' is not a defined node.")

    graph: dict[str, list[str]] = {n: [] for n in known}
    for node in nodes:
        if not isinstance(node, dict) or node.get("name") not in known:
            continue
        name = node["name"]
        edges = node.get("edges", []) or []
        tasks = node.get("task_messages", []) or []

        if not any(str(m.get("content", "")).strip() for m in tasks if isinstance(m, dict)):
            warn("Node has no instructions.", node=name)
        if node.get("end") and edges:
            warn("End node has transitions; the call ends after this node anyway.", node=name)
        if not node.get("end") and not edges:
            warn("Dead end: no transitions and not marked as an end node.", node=name)

        seen_functions: set[str] = set()
        for j, edge in enumerate(edges):
            fn = edge.get("function", "")
            label = f"'{fn}'" if fn else f"#{j + 1}"
            if not FUNCTION_NAME_RE.match(fn or ""):
                error(
                    f"Transition {label}: function name must be 1-64 letters, digits, '_' or '-'.",
                    node=name, edge=j,
                )
            elif fn in seen_functions:
                error(f"Duplicate transition function '{fn}'.", node=name, edge=j)
            seen_functions.add(fn)

            if not str(edge.get("description", "")).strip():
                error(f"Transition {label} needs a description (the LLM uses it to decide).", node=name, edge=j)

            target = edge.get("target")
            if not target:
                error(f"Transition {label} has no target node.", node=name, edge=j)
            elif target not in known:
                error(f"Transition {label} targets unknown node '{target}'.", node=name, edge=j)
            else:
                graph[name].append(target)

            props = edge.get("properties", {}) or {}
            for prop, schema in props.items():
                ptype = schema.get("type") if isinstance(schema, dict) else None
                if ptype not in JSON_TYPES:
                    error(f"Transition {label}: field '{prop}' has invalid type '{ptype}'.", node=name, edge=j)
            for req in edge.get("required", []) or []:
                if req not in props:
                    error(f"Transition {label}: required field '{req}' is not defined.", node=name, edge=j)

    if initial in known:
        reachable = {initial}
        queue = deque([initial])
        while queue:
            for nxt in graph[queue.popleft()]:
                if nxt not in reachable:
                    reachable.add(nxt)
                    queue.append(nxt)
        for name in names:
            if name not in reachable:
                warn("Unreachable from the start node.", node=name)
        end_nodes = {n["name"] for n in nodes if isinstance(n, dict) and n.get("end")}
        if not (end_nodes & reachable):
            warn("No end node is reachable, so the call never hangs up on its own.")

    return issues
