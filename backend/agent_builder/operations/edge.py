# Operations on transitions (edges), addressed by their node and position.

from .registry import OperationError, find_node, operation
from .schemas import EDGE

_INDEX = {"type": "integer", "minimum": 0, "description": "Position of the transition in its node, from 0."}


def _edge_list(agent: dict, node_name: str, index) -> list:
    """The node's transitions, after checking `index` points at one of them."""
    edges = find_node(agent, node_name).get("edges") or []
    # bool is an int in Python, and negative indexes would count from the end.
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(edges):
        number = index + 1 if isinstance(index, int) and not isinstance(index, bool) else index
        raise OperationError(f"Node '{node_name}' has no transition #{number}.")
    return edges


@operation(
    "addEdge",
    description="Add a transition from a node. It's offered to the LLM as a tool while the call is in that node.",
    fields={"node": {"type": "string"}, "edge": EDGE},
    describe=lambda op: f"Added transition '{op['edge'].get('function')}' from '{op['node']}'",
)
def add_edge(agent: dict, op: dict) -> dict:
    find_node(agent, op["node"]).setdefault("edges", []).append(op["edge"])
    return agent


@operation(
    "updateEdge",
    description="Change a transition's function name, description, target or the fields it collects.",
    fields={
        "node": {"type": "string"},
        "index": _INDEX,
        "patch": {"type": "object", "properties": EDGE["properties"], "additionalProperties": False},
    },
    describe=lambda op: f"Edited a transition of '{op['node']}'",
)
def update_edge(agent: dict, op: dict) -> dict:
    _edge_list(agent, op["node"], op["index"])[op["index"]].update(op["patch"])
    return agent


@operation(
    "deleteEdge",
    description="Delete a transition. Later transitions of the node move up one position.",
    fields={"node": {"type": "string"}, "index": _INDEX},
    describe=lambda op: f"Deleted a transition of '{op['node']}'",
)
def delete_edge(agent: dict, op: dict) -> dict:
    _edge_list(agent, op["node"], op["index"]).pop(op["index"])
    return agent
