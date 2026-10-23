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
#   /api/agents/{id}/tests[/{test_id}]     regression tests: list, create (from a call), edit, delete
#   /api/agents/{id}/tests/{test_id}/run   replay a test against a version or the draft
#   /api/calls[/{id}]                      recorded calls
#   /api/validate                          structured errors/warnings for a draft agent
#   /api/voices                            ElevenLabs voices for the voice picker
#   /api/copilot                           one ProsperO turn, streamed as server-sent events
#
# register_routes also installs the call guard (call_guard.py), which refuses
# call requests for agents with errors before the runner accepts them.
#

import json
import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel

import prospero
import regression
import store
from call_guard import StartValidationMiddleware
from http_common import http_error, issues_json

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


class CreateTest(BaseModel):
    call_id: Optional[str] = None  # make the test from this call
    name: Optional[str] = None     # or write it out
    caller_turns: Optional[list] = None
    expect: Optional[dict] = None


class EditTest(BaseModel):
    name: Optional[str] = None
    caller_turns: Optional[list] = None
    expect: Optional[dict] = None


class RunTest(BaseModel):
    agent: Optional[dict] = None  # an unsaved draft; the latest version if omitted
    repeats: int = regression.runner.DEFAULT_REPEATS


class CopilotTurn(BaseModel):
    agent: Optional[dict] = None  # the agent as it stands; none for a brand-new one
    history: list[dict] = []      # earlier messages: [{"role": "user"|"assistant", "content": "..."}]
    message: str


def _with_issues(agent_id: str, record: dict) -> dict:
    return {"id": agent_id, **record, "issues": issues_json(record["agent"])}


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
        try:
            agent_id, record = store.create_agent(req.agent, req.message)
        except ValueError as e:
            raise http_error(e)
        return _with_issues(agent_id, record)

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str):
        try:
            return _with_issues(agent_id, store.get_version(agent_id))
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

    @app.put("/api/agents/{agent_id}")
    async def save_agent(agent_id: str, req: SaveVersion):
        # Drafts with errors are saved too, so work in progress is never lost.
        # The test call is what refuses to run an invalid agent.
        try:
            store.latest_version(agent_id)  # only existing agents get new versions
            record = store.save_version(agent_id, req.agent, req.message, req.source, req.base_version)
        except (store.NotFound, store.Conflict, ValueError) as e:
            raise http_error(e)
        return _with_issues(agent_id, record)

    @app.delete("/api/agents/{agent_id}", status_code=204)
    async def delete_agent(agent_id: str):
        try:
            store.delete_agent(agent_id)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)
        return Response(status_code=204)

    # -- versions --
    @app.get("/api/agents/{agent_id}/versions")
    async def list_versions(agent_id: str):
        try:
            return store.list_versions(agent_id)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

    @app.get("/api/agents/{agent_id}/versions/{version}")
    async def get_version(agent_id: str, version: int):
        try:
            return _with_issues(agent_id, store.get_version(agent_id, version))
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

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
            raise http_error(e)
        return _with_issues(agent_id, record)

    # -- regression tests (AD-18) --
    @app.get("/api/agents/{agent_id}/tests")
    async def list_tests(agent_id: str):
        try:
            return store.list_tests(agent_id)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

    @app.post("/api/agents/{agent_id}/tests", status_code=201)
    async def create_test(agent_id: str, req: CreateTest):
        try:
            if req.call_id:
                call = store.get_call(req.call_id)
                if call.get("agent_id") != agent_id:
                    raise ValueError("That call was made with another agent.")
                test = regression.from_call(call)
            else:
                fields = req.model_dump(exclude_none=True, exclude={"call_id"})
                fields.setdefault("expect", {})
                base = {"id": store.new_test_id(), "created_at": store.now(), "from_call": None, "last_run": None}
                test = regression.clean(fields, base)
                if "name" not in test or "caller_turns" not in test:
                    raise ValueError("A test needs a name and what the caller says.")
            return store.save_test(agent_id, test)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

    @app.put("/api/agents/{agent_id}/tests/{test_id}")
    async def edit_test(agent_id: str, test_id: str, req: EditTest):
        try:
            test = regression.clean(req.model_dump(exclude_none=True), store.get_test(agent_id, test_id))
            return store.save_test(agent_id, test)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

    @app.delete("/api/agents/{agent_id}/tests/{test_id}", status_code=204)
    async def delete_test(agent_id: str, test_id: str):
        try:
            store.delete_test(agent_id, test_id)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)
        return Response(status_code=204)

    @app.post("/api/agents/{agent_id}/tests/{test_id}/run")
    async def run_test(agent_id: str, test_id: str, req: RunTest):
        try:
            test = store.get_test(agent_id, test_id)
            if req.agent is not None:
                agent, version = req.agent, None
            else:
                record = store.get_version(agent_id)
                agent, version = record["agent"], record["version"]
        except (store.NotFound, ValueError) as e:
            raise http_error(e)
        if not 1 <= req.repeats <= regression.runner.MAX_REPEATS:
            raise HTTPException(400, f"Repeats must be between 1 and {regression.runner.MAX_REPEATS}.")
        # Same rule as a call: an agent with errors doesn't run (AD-2).
        issues = issues_json(agent)
        if any(i["severity"] == "error" for i in issues):
            return JSONResponse({"detail": "Agent has errors.", "issues": issues}, status_code=422)

        result = await regression.run(agent, test, req.repeats, agent_id=agent_id, version=version)
        # The latest result is kept on the test, so the list shows it.
        test["last_run"] = {k: result[k] for k in ("at", "agent_version", "passed", "total")}
        store.save_test(agent_id, test)
        return result

    # -- calls --
    @app.get("/api/calls")
    async def list_calls(agent_id: Optional[str] = None):
        return store.list_calls(agent_id)

    @app.get("/api/calls/{call_id}")
    async def get_call(call_id: str):
        try:
            return store.get_call(call_id)
        except (store.NotFound, ValueError) as e:
            raise http_error(e)

    # -- ProsperO --
    complete = None  # the OpenAI client is created on first use

    @app.post("/api/copilot")
    async def copilot(turn: CopilotTurn):
        nonlocal complete
        complete = complete or prospero.openai_complete()

        async def events():
            async for event in prospero.run_turn(turn.agent, turn.history, turn.message, complete):
                yield f"data: {json.dumps(event)}\n\n"

        # Server-sent events: the editor draws each edit as it arrives.
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    # -- tools --
    @app.post("/api/validate")
    async def validate(agent: dict):
        return {"issues": issues_json(agent)}

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
