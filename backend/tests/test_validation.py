import copy
import json
from pathlib import Path

import pytest

from agent_builder import validate_agent

EXAMPLE = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())


def agent(**overrides):
    """A small valid agent: start -> done (end node)."""
    base = {
        "name": "Test",
        "initial_node": "start",
        "nodes": [
            {
                "name": "start",
                "task_messages": [{"role": "developer", "content": "Say hi."}],
                "edges": [{"function": "finish", "description": "When done.", "target": "done"}],
            },
            {"name": "done", "task_messages": [{"role": "developer", "content": "Bye."}], "end": True},
        ],
    }
    base.update(overrides)
    return base


def issues(data):
    return {(i.severity, i.message, i.node, i.edge) for i in validate_agent(data)}


def edge(data, **fields):
    """The first edge of the start node, updated with `fields`."""
    data["nodes"][0]["edges"][0].update(fields)
    return data


# ---- valid agents ---------------------------------------------------------------
def test_valid_agents_have_no_issues():
    assert issues(agent()) == set()
    assert issues(copy.deepcopy(EXAMPLE)) == set()


# ---- structure that stops validation early ---------------------------------------
def test_not_an_object():
    assert issues([]) == {("error", "Agent must be a JSON object.", None, None)}


@pytest.mark.parametrize("nodes", [None, [], "x"])
def test_no_nodes(nodes):
    assert ("error", "Agent has no nodes.", None, None) in issues(agent(nodes=nodes))


# ---- agent-level rules -----------------------------------------------------------
def test_agent_needs_a_name():
    assert ("error", "Agent needs a name.", None, None) in issues(agent(name="  "))


def test_missing_start_node():
    assert ("error", "No start node selected.", None, None) in issues(agent(initial_node=""))


def test_unknown_start_node():
    assert ("error", "Start node 'nope' is not a defined node.", None, None) in issues(agent(initial_node="nope"))


def test_node_without_name():
    data = agent()
    data["nodes"].append({"task_messages": []})
    assert ("error", "Node #3 has no name.", None, None) in issues(data)


def test_duplicate_node_name():
    data = agent()
    data["nodes"].append(copy.deepcopy(data["nodes"][1]))
    assert ("error", "Duplicate node name 'done'.", "done", None) in issues(data)


# ---- node rules ------------------------------------------------------------------
def test_node_without_instructions():
    data = agent()
    data["nodes"][1]["task_messages"] = [{"role": "developer", "content": "  "}]
    assert ("warning", "Node has no instructions.", "done", None) in issues(data)


def test_end_node_with_transitions():
    data = agent()
    data["nodes"][0]["end"] = True
    assert ("warning", "End node has transitions; the call ends after this node anyway.", "start", None) in issues(data)


def test_dead_end():
    data = agent()
    data["nodes"][1]["end"] = False
    assert ("warning", "Dead end: no transitions and not marked as an end node.", "done", None) in issues(data)


# ---- edge rules ------------------------------------------------------------------
@pytest.mark.parametrize("fn", ["", "has space", "x" * 65, "bad.name"])
def test_invalid_function_name(fn):
    label = f"'{fn}'" if fn else "#1"
    msg = f"Transition {label}: function name must be 1-64 letters, digits, '_' or '-'."
    assert ("error", msg, "start", 0) in issues(edge(agent(), function=fn))


def test_duplicate_function_name():
    data = agent()
    data["nodes"][0]["edges"].append({"function": "finish", "description": "Again.", "target": "done"})
    assert ("error", "Duplicate transition function 'finish'.", "start", 1) in issues(data)


def test_edge_needs_description():
    msg = "Transition 'finish' needs a description (the LLM uses it to decide)."
    assert ("error", msg, "start", 0) in issues(edge(agent(), description=" "))


def test_edge_without_target():
    assert ("error", "Transition 'finish' has no target node.", "start", 0) in issues(edge(agent(), target=""))


def test_edge_with_unknown_target():
    msg = "Transition 'finish' targets unknown node 'nope'."
    assert ("error", msg, "start", 0) in issues(edge(agent(), target="nope"))


def test_invalid_field_type():
    data = edge(agent(), properties={"when": {"type": "date"}})
    assert ("error", "Transition 'finish': field 'when' has invalid type 'date'.", "start", 0) in issues(data)


def test_required_field_not_defined():
    data = edge(agent(), properties={}, required=["when"])
    assert ("error", "Transition 'finish': required field 'when' is not defined.", "start", 0) in issues(data)


# ---- graph rules -----------------------------------------------------------------
def test_unreachable_node():
    data = agent()
    data["nodes"].append({"name": "island", "task_messages": [{"role": "developer", "content": "x"}], "end": True})
    assert ("warning", "Unreachable from the start node.", "island", None) in issues(data)


def test_no_reachable_end_node():
    data = agent()
    data["nodes"][1]["end"] = False
    data["nodes"][1]["edges"] = [{"function": "loop", "description": "Again.", "target": "start"}]
    assert ("warning", "No end node is reachable, so the call never hangs up on its own.", None, None) in issues(data)


def test_broken_edges_do_not_count_for_reachability():
    data = edge(agent(), target="nope")
    found = issues(data)
    assert ("warning", "Unreachable from the start node.", "done", None) in found


# ---- issue format ------------------------------------------------------------------
def test_to_dict_omits_missing_location():
    [issue] = validate_agent([])
    assert issue.to_dict() == {"severity": "error", "message": "Agent must be a JSON object."}

