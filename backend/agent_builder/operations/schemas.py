#
# JSON schemas for the parts of an agent that operations carry (nodes, edges,
# fields). They mirror agent_builder/schema.py and frontend/src/lib/types.ts.
#

POSITION = {
    "type": "object",
    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
    "required": ["x", "y"],
}

FIELD = {
    "type": "object",
    "description": "One piece of information the LLM collects when taking the transition.",
    "properties": {
        "type": {"enum": ["string", "number", "integer", "boolean", "array", "object"]},
        "description": {"type": "string"},
        "enum": {"type": "array", "items": {"type": "string"}, "description": "Allowed values (optional)."},
    },
    "required": ["type"],
}

EDGE = {
    "type": "object",
    "description": "A transition: a tool the LLM calls to move to another node.",
    "properties": {
        "function": {"type": "string", "description": "Tool name: 1-64 letters, digits, '_' or '-'."},
        "description": {"type": "string", "description": "When the LLM should take this transition."},
        "target": {"type": "string", "description": "Name of the node to move to."},
        "properties": {"type": "object", "additionalProperties": FIELD},
        "required": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["function", "description", "target"],
}

TASK_MESSAGE = {
    "type": "object",
    "properties": {"role": {"type": "string"}, "content": {"type": "string"}},
    "required": ["role", "content"],
}

NODE_FIELDS = {
    "task_messages": {"type": "array", "items": TASK_MESSAGE, "description": "The node's instructions."},
    "role_message": {"type": ["string", "null"], "description": "Overrides the agent's persona in this node."},
    "pre_actions": {"type": "array"},
    "post_actions": {"type": "array"},
    "end": {"type": "boolean", "description": "End the call after this node."},
    "position": POSITION,
}

NODE = {
    "type": "object",
    "description": "A step in the conversation.",
    "properties": {"name": {"type": "string"}, **NODE_FIELDS, "edges": {"type": "array", "items": EDGE}},
    "required": ["name", "task_messages"],
}

AGENT_FIELDS = {
    "name": {"type": "string"},
    "languages": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "description": "ISO 639-1 codes the agent speaks, default first (e.g. [\"en\", \"es\"]). English only if omitted.",
    },
    "persona": {"type": "string", "description": "Applies to every node unless overridden."},
    "voice_id": {"type": "string"},
    "model": {"type": "string"},
}

AGENT = {
    "type": "object",
    "properties": {**AGENT_FIELDS, "initial_node": {"type": "string"}, "nodes": {"type": "array", "items": NODE}},
    "required": ["name", "initial_node", "nodes"],
}
