#
# Operation registry — the one place an operation is defined.
#
# Each operation is registered with @operation: its type, a description, the JSON
# schema of its fields, how it's applied, and its human-readable label. The same
# entry drives `apply_op`, `describe_op`, and the schema ProsperO's LLM tools are
# built from. Operations themselves stay plain dicts (JSON), exactly the format the
# frontend's operations use (frontend/src/lib/operations/); both are tested
# against the same cases in shared/operation-cases.json.
#

import copy
from dataclasses import dataclass
from typing import Callable


class OperationError(ValueError):
    """The operation doesn't fit the agent (unknown node, name taken, bad index...)."""


@dataclass(frozen=True)
class OperationDef:
    type: str
    description: str
    fields: dict          # JSON schema of each field, besides "type"
    required: tuple       # required field names
    apply: Callable[[dict, dict], dict]
    describe: Callable[[dict], str]

    def schema(self) -> dict:
        """The full JSON schema of this operation, including its `type`."""
        return {
            "type": "object",
            "description": self.description,
            "properties": {"type": {"const": self.type}, **self.fields},
            "required": ["type", *self.required],
            "additionalProperties": False,
        }


OPERATIONS: dict[str, OperationDef] = {}


def operation(type: str, *, description: str, fields: dict, describe: Callable[[dict], str], required=None):
    """Register the decorated function as how operation `type` is applied.

    The function receives a private deep copy of the agent, so it may change it in
    place, and returns it. `required` defaults to every field.
    """

    def register(apply: Callable[[dict, dict], dict]):
        if type in OPERATIONS:
            raise ValueError(f"Operation '{type}' is registered twice.")
        OPERATIONS[type] = OperationDef(
            type=type,
            description=description,
            fields=fields,
            required=tuple(fields if required is None else required),
            apply=apply,
            describe=describe,
        )
        return apply

    return register


def _definition(op: dict) -> OperationDef:
    if not isinstance(op, dict) or op.get("type") not in OPERATIONS:
        kind = op.get("type") if isinstance(op, dict) else op
        raise OperationError(f"Unknown operation '{kind}'.")
    definition = OPERATIONS[op["type"]]
    for name in definition.required:
        if name not in op:
            raise OperationError(f"Operation '{op['type']}' is missing '{name}'.")
    return definition


def apply_op(agent: dict, op: dict) -> dict:
    """Return a new agent with `op` applied; `agent` is never modified.

    Raises OperationError if the operation doesn't fit the agent.
    """
    return _definition(op).apply(copy.deepcopy(agent), op)


def describe_op(op: dict) -> str:
    """A short, human-readable label, for undo/redo and for reviewing changes."""
    return _definition(op).describe(op)


# ---- helpers shared by the operation modules -----------------------------------
def find_node(agent: dict, name: str) -> dict:
    for node in agent["nodes"]:
        if node.get("name") == name:
            return node
    raise OperationError(f"No node named '{name}'.")


def require_free_name(agent: dict, name: str) -> None:
    if any(n.get("name") == name for n in agent["nodes"]):
        raise OperationError(f"A node named '{name}' already exists.")
