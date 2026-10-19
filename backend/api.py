#
# Editor API — the HTTP surface the agent editor (frontend/) talks to.
#
# Mounted onto the Pipecat dev runner's FastAPI app (see bot.py), so one backend
# process serves the agent store and the WebRTC test-call endpoints. It serves
# JSON only; the editor is a separate app.
#
#   /api/agents[/{id}]   CRUD over agent JSON files in backend/agents/
#   /api/validate        structured errors/warnings for a draft agent
#   /api/voices          ElevenLabs voices for the voice picker
#
# Agents are plain JSON files on purpose: they stay diffable, hand-editable and
# exactly the format AgentBuilder consumes.
#

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Response
from loguru import logger

from agent_builder import validate_agent

AGENTS_DIR = Path(__file__).parent / "agents"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Used when the ElevenLabs voices API is unreachable, so the picker still works.
FALLBACK_VOICES = [
    {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "labels": {"gender": "female"}},
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "labels": {"gender": "female"}},
    {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "labels": {"gender": "male"}},
    {"voice_id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh", "labels": {"gender": "male"}},
]


# ---- agent store -------------------------------------------------------------
def _path(agent_id: str) -> Path:
    if not ID_RE.match(agent_id):
        raise HTTPException(400, f"Invalid agent id '{agent_id}'.")
    return AGENTS_DIR / f"{agent_id}.json"


def _unique_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "agent"
    agent_id, n = base, 2
    while (AGENTS_DIR / f"{agent_id}.json").exists():
        agent_id, n = f"{base}-{n}", n + 1
    return agent_id


def _write(agent_id: str, agent: dict) -> None:
    AGENTS_DIR.mkdir(exist_ok=True)
    path = _path(agent_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(agent, indent=2) + "\n")
    tmp.replace(path)  # atomic: never leave a half-written agent


def load_agent(agent_id: str) -> dict:
    path = _path(agent_id)
    if not path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found.")
    return json.loads(path.read_text())


def _summary(path: Path) -> dict:
    try:
        agent = json.loads(path.read_text())
    except json.JSONDecodeError:
        agent = {}
    return {
        "id": path.stem,
        "name": agent.get("name") or path.stem,
        "node_count": len(agent.get("nodes", [])),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
    }


def _response(agent_id: str, agent: dict) -> dict:
    return {
        "id": agent_id,
        "agent": agent,
        "issues": [i.to_dict() for i in validate_agent(agent)],
    }


# ---- routes ------------------------------------------------------------------
def register_routes(app: FastAPI) -> None:
    """Attach the editor API to the runner's FastAPI app."""

    @app.get("/api/agents")
    async def list_agents():
        AGENTS_DIR.mkdir(exist_ok=True)
        paths = sorted(AGENTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [_summary(p) for p in paths]

    @app.post("/api/agents", status_code=201)
    async def create_agent(agent: dict):
        agent_id = _unique_id(agent.get("name") or "agent")
        _write(agent_id, agent)
        return _response(agent_id, agent)

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str):
        return _response(agent_id, load_agent(agent_id))

    @app.put("/api/agents/{agent_id}")
    async def save_agent(agent_id: str, agent: dict):
        # Drafts with errors are saved too, so work in progress is never lost.
        # The test call is what refuses to run an invalid agent.
        _write(agent_id, agent)
        return _response(agent_id, agent)

    @app.delete("/api/agents/{agent_id}", status_code=204)
    async def delete_agent(agent_id: str):
        path = _path(agent_id)
        if not path.exists():
            raise HTTPException(404, f"Agent '{agent_id}' not found.")
        path.unlink()
        return Response(status_code=204)

    @app.post("/api/validate")
    async def validate(agent: dict):
        return {"issues": [i.to_dict() for i in validate_agent(agent)]}

    voices_cache: dict = {"at": 0.0, "voices": None}

    @app.get("/api/voices")
    async def voices():
        if voices_cache["voices"] and time.time() - voices_cache["at"] < 600:
            return voices_cache["voices"]
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")},
                )
                r.raise_for_status()
            result = [
                {
                    "voice_id": v["voice_id"],
                    "name": v["name"],
                    "labels": v.get("labels") or {},
                    "preview_url": v.get("preview_url"),
                }
                for v in r.json().get("voices", [])
            ]
            voices_cache.update(at=time.time(), voices=result)
            return result
        except Exception as e:
            logger.warning(f"Could not fetch ElevenLabs voices, using fallback list: {e}")
            return FALLBACK_VOICES
