#
# ProsperO's tools: the agent operations (D-9, D-12), plus validate and finish.
#
# The edit tools are generated from the operation registry, so the LLM is only
# offered operations that exist, with exactly the fields apply_op accepts.
#

import copy

from agent_builder.operations import OPERATIONS

# Operations ProsperO doesn't get: layout is the editor's job, and regenerating
# the whole agent would defeat reviewable, step-by-step edits.
EXCLUDED = {"moveNodes", "replaceAgent"}


def _without_position(schema):
    """Drop `position` everywhere in a schema: layout is the editor's job, and the
    LLM can't know how big the cards are, so its coordinates would overlap."""
    if isinstance(schema, dict):
        return {k: _without_position(v) for k, v in schema.items() if k != "position"}
    if isinstance(schema, list):
        return [_without_position(v) for v in schema]
    return schema


def _edit_tool(name: str) -> dict:
    definition = OPERATIONS[name]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": definition.description,
            "parameters": {
                "type": "object",
                "properties": _without_position(copy.deepcopy(definition.fields)),
                "required": list(definition.required),
                "additionalProperties": False,
            },
        },
    }


VALIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "validate",
        "description": "Check the agent and list its errors and warnings. Call it before finish.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Hand the agent to the user for review. Refused while the agent has errors.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What you built or changed, in one or two sentences."},
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Assumptions the user should check, one per item.",
                },
            },
            "required": ["summary", "assumptions"],
            "additionalProperties": False,
        },
    },
}

EDIT_TOOL_NAMES = sorted(set(OPERATIONS) - EXCLUDED)
TOOLS = [_edit_tool(name) for name in EDIT_TOOL_NAMES] + [VALIDATE_TOOL, FINISH_TOOL]
