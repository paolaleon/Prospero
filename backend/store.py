#
# Store — agents (as immutable versions) and call records, as JSON files.
#
#   agents/{agent_id}/versions/0001.json   {"version", "created_at", "message", "source", "agent"}
#   calls/{call_id}.json                   one record per call (see save_call)
#
# A save never overwrites: it appends a version. That gives rollback, and lets a
# call record point at the exact agent version it ran on, which is what makes
# calls usable as evidence when iterating on an agent (by a person or a copilot).
#

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).parent
AGENTS_DIR = BACKEND_DIR / "agents"
CALLS_DIR = BACKEND_DIR / "calls"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION_SOURCES = {"human", "copilot", "restore"}


class NotFound(LookupError):
    pass


class Conflict(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_id(value: str) -> str:
    if not ID_RE.match(value or ""):
        raise ValueError(f"Invalid id '{value}'.")
    return value


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)  # atomic: never leave a half-written file


# ---- agents -------------------------------------------------------------------
def _versions_dir(agent_id: str) -> Path:
    return AGENTS_DIR / _check_id(agent_id) / "versions"


def _version_numbers(agent_id: str) -> list[int]:
    d = _versions_dir(agent_id)
    return sorted(int(p.stem) for p in d.glob("*.json") if p.stem.isdigit()) if d.exists() else []


def latest_version(agent_id: str) -> int:
    numbers = _version_numbers(agent_id)
    if not numbers:
        raise NotFound(f"Agent '{agent_id}' not found.")
    return numbers[-1]


def get_version(agent_id: str, version: Optional[int] = None) -> dict:
    """Return a version record; the latest one when `version` is None."""
    if version is None:
        version = latest_version(agent_id)
    path = _versions_dir(agent_id) / f"{int(version):04d}.json"
    if not path.exists():
        raise NotFound(f"Agent '{agent_id}' has no version {version}.")
    return json.loads(path.read_text())


def list_versions(agent_id: str) -> list[dict]:
    """Version metadata, newest first (without the agent bodies)."""
    out = []
    for n in reversed(_version_numbers(agent_id)):
        record = get_version(agent_id, n)
        out.append({k: v for k, v in record.items() if k != "agent"}
                   | {"node_count": len(record["agent"].get("nodes", []))})
    if not out:
        raise NotFound(f"Agent '{agent_id}' not found.")
    return out


def save_version(
    agent_id: str,
    agent: dict,
    message: str = "",
    source: str = "human",
    base_version: Optional[int] = None,
) -> dict:
    """Append a new version. `base_version` is the version the edit started from;
    if someone saved in between, the write is refused instead of silently lost."""
    if source not in VERSION_SOURCES:
        raise ValueError(f"Unknown version source '{source}'.")
    numbers = _version_numbers(agent_id)
    current = numbers[-1] if numbers else 0
    if base_version is not None and base_version != current:
        raise Conflict(f"Agent changed since version {base_version} (now {current}).")
    record = {
        "version": current + 1,
        "created_at": now(),
        "message": message,
        "source": source,
        "agent": agent,
    }
    _write_json(_versions_dir(agent_id) / f"{current + 1:04d}.json", record)
    return record


def create_agent(agent: dict, message: str = "Created") -> tuple[str, dict]:
    """Store a new agent as version 1, with an id made from its name.

    The agent can be renamed freely afterwards (its `name` is just a field), but
    the id is kept, so links, its folder and its call records stay valid.
    """
    name = agent.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A new agent needs a name.")
    # Names with no usable letters (e.g. only emoji) still get an id.
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "agent"
    agent_id, n = base, 2
    while (AGENTS_DIR / agent_id).exists():
        agent_id, n = f"{base}-{n}", n + 1
    return agent_id, save_version(agent_id, agent, message=message)


def delete_agent(agent_id: str) -> None:
    latest_version(agent_id)  # raises NotFound
    for p in _versions_dir(agent_id).glob("*"):
        p.unlink()
    _versions_dir(agent_id).rmdir()
    (AGENTS_DIR / agent_id).rmdir()


def list_agents() -> list[dict]:
    AGENTS_DIR.mkdir(exist_ok=True)
    out = []
    for d in AGENTS_DIR.iterdir():
        if not d.is_dir() or not ID_RE.match(d.name) or not _version_numbers(d.name):
            continue
        record = get_version(d.name)
        out.append({
            "id": d.name,
            "name": record["agent"].get("name") or d.name,
            "version": record["version"],
            "node_count": len(record["agent"].get("nodes", [])),
            "updated_at": record["created_at"],
        })
    return sorted(out, key=lambda a: a["updated_at"], reverse=True)


# ---- which agent a call runs ---------------------------------------------------
def resolve_call_agent(body: dict) -> tuple[Optional[dict], Optional[str], Optional[int]]:
    """Pick the agent for a call from the /start request body.

    Returns (agent, agent_id, version). `agent` is None when the body names no
    agent (the bot then uses its default). An inline `agent` is an unsaved draft:
    its version is None even if `agent_id` says which agent it is a draft of.
    """
    agent_id = body.get("agent_id")
    if isinstance(body.get("agent"), dict):
        return body["agent"], agent_id, None
    if agent_id:
        record = get_version(agent_id, body.get("version"))
        return record["agent"], agent_id, record["version"]
    return None, None, None


# ---- calls --------------------------------------------------------------------
def new_call_id() -> str:
    return uuid.uuid4().hex[:12]


def save_call(record: dict) -> None:
    """Persist one call. A record is self-contained: it carries the snapshot of
    the agent it ran, so it stays readable after the agent changes.

    {
      "id", "source": "test" | "production" | "mock",
      "agent_id", "agent_version" (None for an unsaved draft), "agent",
      "started_at", "ended_at", "ended_by": "agent" | "caller",
      "final_node", "collected": {...},
      "events": [
        {"t", "type": "transition", "from_node", "function", "to_node", "args"},
        {"t", "type": "user", "text"},
        {"t", "type": "agent", "text", "interrupted"},
        {"t", "type": "refused", "node", "function", "args", "problems"},
        {"t", "type": "language", "action": "locked" | "blocked", "language", "text"},
        {"t", "type": "fallback", "from_node", "reason", "to_node"},
      ]
    }
    """
    _write_json(CALLS_DIR / f"{_check_id(record['id'])}.json", record)


def get_call(call_id: str) -> dict:
    path = CALLS_DIR / f"{_check_id(call_id)}.json"
    if not path.exists():
        raise NotFound(f"Call '{call_id}' not found.")
    return json.loads(path.read_text())


def list_calls(agent_id: Optional[str] = None) -> list[dict]:
    """Call summaries, newest first."""
    CALLS_DIR.mkdir(exist_ok=True)
    out = []
    for p in CALLS_DIR.glob("*.json"):
        call = json.loads(p.read_text())
        if agent_id and call.get("agent_id") != agent_id:
            continue
        out.append({
            "id": call["id"],
            "source": call.get("source"),
            "agent_id": call.get("agent_id"),
            "agent_name": (call.get("agent") or {}).get("name"),
            "agent_version": call.get("agent_version"),
            "started_at": call.get("started_at"),
            "ended_at": call.get("ended_at"),
            "ended_by": call.get("ended_by"),
            "final_node": call.get("final_node"),
            "turns": sum(1 for e in call.get("events", []) if e["type"] in ("user", "agent")),
        })
    return sorted(out, key=lambda c: c["started_at"] or "", reverse=True)
