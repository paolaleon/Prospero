#
# Editor API — the HTTP surface the agent editor (frontend/) talks to.
#
# Mounted onto the Pipecat dev runner's FastAPI app (see bot.py), so one backend
# process serves the store and the WebRTC test-call endpoints. It serves JSON
# only; the editor is a separate app. Storage lives in store.py.
#
#   /api/agents[/{id}]                     list, create, read latest, save new version, delete
#   /api/agents/{id}/versions[/{n}]        version history
#   /api/agents/{id}/versions/{n}/restore  roll back (as a new version)
#   /api/calls[/{id}]                      recorded calls
#   /api/validate                          structured errors/warnings for a draft agent
#   /api/voices                            ElevenLabs voices for the voice picker
#
# It also checks the agent of every call request (POST /start) before the runner
# accepts it, so an invalid draft is refused with its issues instead of the call
# hanging after the bot fails to build.
#

import json
import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

import store
from agent_builder import validate_agent

# Used when the ElevenLabs voices API is unreachable, so the picker still works.
FALLBACK_VOICES = [
    {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "labels": {"gender": "female"}},
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "labels": {"gender": "female"}},
    {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "labels": {"gender": "male"}},
    {"voice_id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh", "labels": {"gender": "male"}},
]


class CreateAgent(BaseModel):
    agent: dict
    message: str = "Created"


class SaveVersion(BaseModel):
    agent: dict
    message: str = ""
    source: str = "human"
    base_version: Optional[int] = None  # version the edit started from


def _issues(agent: dict) -> list[dict]:
    return [i.to_dict() for i in validate_agent(agent)]


def _with_issues(agent_id: str, record: dict) -> dict:
    return {"id": agent_id, **record, "issues": _issues(record["agent"])}


def _http_error(e: Exception) -> HTTPException:
    if isinstance(e, store.NotFound):
        return HTTPException(404, str(e))
    if isinstance(e, store.Conflict):
        return HTTPException(409, str(e))
    return HTTPException(400, str(e))


# ---- call-request validation -------------------------------------------------
def _start_rejection(request: dict) -> Optional[JSONResponse]:
    """Return an error response if a /start request names an agent that can't run."""
    try:
        agent, _, _ = store.resolve_call_agent(request.get("body") or {})
    except (store.NotFound, ValueError) as e:
        err = _http_error(e)
        return JSONResponse({"detail": err.detail}, status_code=err.status_code)
    if agent is None:
        return None  # the bot falls back to its default agent
    issues = _issues(agent)
    if any(i["severity"] == "error" for i in issues):
        return JSONResponse({"detail": "Agent has errors.", "issues": issues}, status_code=422)
    return None


class StartValidationMiddleware:
    """Validates the agent in POST /start before the runner's own route sees it.

    /start belongs to the Pipecat runner, and the bot only builds the agent after
    the WebRTC connection is up. Without this check, an invalid agent gets a
    session id, then fails inside the bot and the client waits for a call that
    never starts.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/start":
            return await self.app(scope, receive, send)

        chunks, more = [], True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        raw = b"".join(chunks)

        try:
            rejection = _start_rejection(json.loads(raw or b"{}"))
        except (json.JSONDecodeError, AttributeError):
            rejection = None  # let the runner report malformed requests itself
        if rejection:
            return await rejection(scope, receive, send)

        # Hand the runner the body we already read.
        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": raw, "more_body": False}

        await self.app(scope, replay, send)


# ---- routes ------------------------------------------------------------------
def register_routes(app: FastAPI) -> None:
    """Attach the editor API to the runner's FastAPI app."""

    # Added before the runner's CORS middleware, which therefore wraps it and
    # adds CORS headers to rejections too.
    app.add_middleware(StartValidationMiddleware)

    # -- agents --
    @app.get("/api/agents")
    async def list_agents():
        return store.list_agents()

    @app.post("/api/agents", status_code=201)
    async def create_agent(req: CreateAgent):
        agent_id, record = store.create_agent(req.agent, req.message)
        return _with_issues(agent_id, record)

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str):
        try:
            return _with_issues(agent_id, store.get_version(agent_id))
        except (store.NotFound, ValueError) as e:
            raise _http_error(e)

    @app.put("/api/agents/{agent_id}")
    async def save_agent(agent_id: str, req: SaveVersion):
        # Drafts with errors are saved too, so work in progress is never lost.
        # The test call is what refuses to run an invalid agent.
        try:
            store.latest_version(agent_id)  # only existing agents get new versions
            record = store.save_version(agent_id, req.agent, req.message, req.source, req.base_version)
        except (store.NotFound, store.Conflict, ValueError) as e:
            raise _http_error(e)
        return _with_issues(agent_id, record)

    @app.delete("/api/agents/{agent_id}", status_code=204)
    async def delete_agent(agent_id: str):
        try:
            store.delete_agent(agent_id)
        except (store.NotFound, ValueError) as e:
            raise _http_error(e)
        return Response(status_code=204)

    # -- versions --
    @app.get("/api/agents/{agent_id}/versions")
    async def list_versions(agent_id: str):
        try:
            return store.list_versions(agent_id)
        except (store.NotFound, ValueError) as e:
            raise _http_error(e)

    @app.get("/api/agents/{agent_id}/versions/{version}")
    async def get_version(agent_id: str, version: int):
        try:
            return _with_issues(agent_id, store.get_version(agent_id, version))
        except (store.NotFound, ValueError) as e:
            raise _http_error(e)

    @app.post("/api/agents/{agent_id}/versions/{version}/restore")
    async def restore_version(agent_id: str, version: int):
        # Rolling back appends a copy of the old version, so history stays linear
        # and the rollback itself can be undone.
        try:
            old = store.get_version(agent_id, version)
            record = store.save_version(
                agent_id, old["agent"], f"Restored version {version}", source="restore"
            )
        except (store.NotFound, ValueError) as e:
            raise _http_error(e)
        return _with_issues(agent_id, record)

    # -- calls --
    @app.get("/api/calls")
    async def list_calls(agent_id: Optional[str] = None):
        return store.list_calls(agent_id)

    @app.get("/api/calls/{call_id}")
    async def get_call(call_id: str):
        try:
            return store.get_call(call_id)
        except (store.NotFound, ValueError) as e:
            raise _http_error(e)

    # -- tools --
    @app.post("/api/validate")
    async def validate(agent: dict):
        return {"issues": _issues(agent)}

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
