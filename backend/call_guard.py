#
# Call guard — refuses call requests for agents that can't run.
#
# POST /start belongs to the Pipecat runner, which accepts any body and only
# hands it to the bot once the WebRTC connection is up. The bot is the first
# place the agent gets built, so an invalid agent used to get a session id,
# fail inside the bot, and leave the client waiting for a call that never
# starts. This middleware checks the agent first, with the same rules as the
# editor, and answers 422 (with the issues) or 404 before a session exists.
# Valid requests reach the runner unchanged.
#

import json
from typing import Optional

from fastapi.responses import JSONResponse

import store
from http_common import http_error, issues_json


def start_rejection(request: dict) -> Optional[JSONResponse]:
    """The error response for a /start request whose agent can't run, else None."""
    try:
        agent, _, _ = store.resolve_call_agent(request.get("body") or {})
    except (store.NotFound, ValueError) as e:
        err = http_error(e)
        return JSONResponse({"detail": err.detail}, status_code=err.status_code)
    if agent is None:
        return None  # the bot falls back to its default agent
    issues = issues_json(agent)
    if any(i["severity"] == "error" for i in issues):
        return JSONResponse({"detail": "Agent has errors.", "issues": issues}, status_code=422)
    return None


class StartValidationMiddleware:
    """ASGI middleware: validates the agent in POST /start before the runner sees it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/start":
            return await self.app(scope, receive, send)

        # The body can arrive in several chunks; read all of it.
        chunks, more = [], True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        raw = b"".join(chunks)

        try:
            rejection = start_rejection(json.loads(raw or b"{}"))
        except (json.JSONDecodeError, AttributeError):
            rejection = None  # not a JSON object: let the runner report it itself
        if rejection:
            return await rejection(scope, receive, send)

        # The body has been consumed, so hand the runner a copy of it.
        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": raw, "more_body": False}

        await self.app(scope, replay, send)
