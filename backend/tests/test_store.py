import pytest

import store


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AGENTS_DIR", tmp_path / "agents")


def make(name):
    return {"name": name, "initial_node": "a", "nodes": [{"name": "a", "end": True}]}


def test_id_comes_from_the_name():
    agent_id, record = store.create_agent(make("Dental Reminders"))
    assert agent_id == "dental-reminders"
    assert record["version"] == 1


def test_taken_ids_get_a_number():
    ids = [store.create_agent(make("Intake"))[0] for _ in range(3)]
    assert ids == ["intake", "intake-2", "intake-3"]


def test_names_without_letters_still_get_an_id():
    assert store.create_agent(make("🦷🦷"))[0] == "agent"


@pytest.mark.parametrize("name", [None, "", "   ", 42])
def test_a_name_is_required(name):
    with pytest.raises(ValueError, match="needs a name"):
        store.create_agent(make(name))


def test_renaming_keeps_the_id():
    agent_id, _ = store.create_agent(make("Intake"))
    store.save_version(agent_id, make("Patient Intake"), base_version=1)
    [summary] = store.list_agents()
    assert (summary["id"], summary["name"], summary["version"]) == ("intake", "Patient Intake", 2)
