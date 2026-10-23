# Operations on nodes.

from .registry import OperationError, find_node, operation, require_free_name
from .schemas import NODE, NODE_FIELDS, POSITION


@operation(
    "addNode",
    description="Add a new node (a step in the conversation). Its name must be unused.",
    fields={"node": NODE},
    describe=lambda op: f"Added node '{op['node']['name']}'",
)
def add_node(agent: dict, op: dict) -> dict:
    require_free_name(agent, op["node"]["name"])
    agent["nodes"].append(op["node"])
    return agent


@operation(
    "updateNode",
    description="Change a node's instructions, persona override, end flag, actions or position.",
    fields={
        "node": {"type": "string"},
        "patch": {"type": "object", "properties": NODE_FIELDS, "additionalProperties": False},
    },
    describe=lambda op: f"Edited node '{op['node']}'",
)
def update_node(agent: dict, op: dict) -> dict:
    find_node(agent, op["node"]).update(op["patch"])
    return agent


@operation(
    "renameNode",
    description="Rename a node. The start node and every transition pointing at it follow.",
    fields={"from": {"type": "string"}, "to": {"type": "string"}},
    describe=lambda op: f"Renamed node '{op['from']}' to '{op['to']}'",
)
def rename_node(agent: dict, op: dict) -> dict:
    old, new = op["from"], op["to"]
    if old == new:
        return agent
    require_free_name(agent, new)
    find_node(agent, old)["name"] = new
    # A rename rewrites every reference, so the graph stays connected.
    if agent.get("initial_node") == old:
        agent["initial_node"] = new
    if agent.get("fallback_node") == old:
        agent["fallback_node"] = new
    for node in agent["nodes"]:
        for edge in node.get("edges") or []:
            if edge.get("target") == old:
                edge["target"] = new
    return agent


@operation(
    "deleteNode",
    description="Delete a node. Transitions that pointed at it keep their settings but lose their target.",
    fields={"node": {"type": "string"}},
    describe=lambda op: f"Deleted node '{op['node']}'",
)
def delete_node(agent: dict, op: dict) -> dict:
    name = op["node"]
    find_node(agent, name)
    # Incoming transitions lose their target instead of vanishing, so validation
    # points at each one.
    if agent.get("initial_node") == name:
        agent["initial_node"] = ""
    if agent.get("fallback_node") == name:
        agent.pop("fallback_node")  # back to the built-in ending
    agent["nodes"] = [n for n in agent["nodes"] if n.get("name") != name]
    for node in agent["nodes"]:
        for edge in node.get("edges") or []:
            if edge.get("target") == name:
                edge["target"] = ""
    return agent


@operation(
    "moveNodes",
    description="Set the canvas position of some nodes. Names that don't exist are ignored.",
    fields={"positions": {"type": "object", "additionalProperties": POSITION}},
    describe=lambda op: "Moved nodes",
)
def move_nodes(agent: dict, op: dict) -> dict:
    positions = op["positions"]
    if not isinstance(positions, dict):
        raise OperationError("Operation 'moveNodes' needs 'positions' as an object.")
    for node in agent["nodes"]:
        if node.get("name") in positions:
            node["position"] = positions[node["name"]]
    return agent
