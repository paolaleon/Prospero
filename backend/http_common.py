#
# Helpers shared by the HTTP modules (api.py, call_guard.py).
#

from fastapi import HTTPException

import store
from agent_builder import validate_agent


def issues_json(agent: dict) -> list[dict]:
    """An agent's validation issues, ready to return as JSON."""
    return [i.to_dict() for i in validate_agent(agent)]


def http_error(e: Exception) -> HTTPException:
    """The HTTP error for a store exception: 404 not found, 409 conflict, else 400."""
    if isinstance(e, store.NotFound):
        return HTTPException(404, str(e))
    if isinstance(e, store.Conflict):
        return HTTPException(409, str(e))
    return HTTPException(400, str(e))
