import copy
import json
from pathlib import Path

import pytest

from agent_builder.operations import OPERATIONS, OperationError, apply_op, describe_op

SHARED = json.loads((Path(__file__).parents[2] / "shared" / "operation-cases.json").read_text())
CASES = SHARED["cases"]
_MISSING = object()


def get(value, path: str):
    """Follow a dot-separated path (numbers index lists); _MISSING if it doesn't exist."""
    for part in path.split("."):
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)] if int(part) < len(value) else _MISSING
        elif isinstance(value, dict):
            value = value.get(part, _MISSING)
        else:
            return _MISSING
        if value is _MISSING:
            return _MISSING
    return value


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_case(case):
    agent = copy.deepcopy(SHARED["fixtures"][case["agent"]])
    before = copy.deepcopy(agent)

    if "error" in case:
        with pytest.raises(OperationError) as raised:
            apply_op(agent, case["op"])
        assert str(raised.value) == case["error"]
    else:
        result = apply_op(agent, case["op"])
        if case.get("same"):
            assert result == before
        for path, expected in case.get("expect", {}).items():
            actual = get(result, path)
            if expected == {"$absent": True}:
                assert actual is _MISSING, f"{path} should not exist"
            else:
                assert actual == expected, f"{path}: {actual!r} != {expected!r}"
        if "label" in case:
            assert describe_op(case["op"]) == case["label"]

    assert agent == before, "the input agent must not change"


def test_every_operation_has_a_shared_case():
    covered = {c["op"]["type"] for c in CASES}
    assert set(OPERATIONS) <= covered, f"no shared case for {set(OPERATIONS) - covered}"


@pytest.mark.parametrize("name", sorted(OPERATIONS))
def test_schemas_are_consistent(name):
    schema = OPERATIONS[name].schema()
    json.dumps(schema)  # serialisable, so it can become an LLM tool definition
    assert schema["properties"]["type"] == {"const": name}
    assert set(schema["required"]) <= set(schema["properties"])
    assert OPERATIONS[name].description
