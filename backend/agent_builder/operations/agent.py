# Operations on the agent as a whole.

from .registry import find_node, operation
from .schemas import AGENT, AGENT_FIELDS


@operation(
    "updateAgent",
    description="Change the agent's name, persona, voice or model.",
    fields={"patch": {"type": "object", "properties": AGENT_FIELDS, "additionalProperties": False}},
    describe=lambda op: f"Edited agent {', '.join(op['patch'])}",
)
def update_agent(agent: dict, op: dict) -> dict:
    agent.update(op["patch"])
    return agent


@operation(
    "setInitialNode",
    description="Make an existing node the one every call starts at.",
    fields={"node": {"type": "string"}},
    describe=lambda op: f"Set start node to '{op['node']}'",
)
def set_initial_node(agent: dict, op: dict) -> dict:
    find_node(agent, op["node"])
    agent["initial_node"] = op["node"]
    return agent


@operation(
    "replaceAgent",
    description="Replace the whole agent (e.g. importing JSON or restoring a version).",
    fields={"agent": AGENT, "reason": {"type": "string", "description": "Shown as the change's label."}},
    describe=lambda op: op["reason"],
)
def replace_agent(_agent: dict, op: dict) -> dict:
    return op["agent"]
