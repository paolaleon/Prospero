#
# Store — agents, as immutable versions in JSON files.
#
#   agents/{agent_id}/versions/0001.json   {"version", "created_at", "message", "source", "agent"}
#
# A save never overwrites: it appends a version. That gives rollback, and every
# change (by a person or a copilot) stays reviewable and reversible.
#

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).parent
AGENTS_DIR = BACKEND_DIR / "agents"

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
    base = re.sub(r"[^a-z0-9]+", "-", (agent.get("name") or "").lower()).strip("-")[:48] or "agent"
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

