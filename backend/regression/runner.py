#
# Runs one test against an agent: several replays, each checked.
#
# An LLM doesn't answer the same way twice, so one passing replay proves
# little. A test is replayed a few times and reports how many passed.
#

import asyncio
from typing import Awaitable, Callable, Optional

from loguru import logger

import pricing
import store
from usage import empty_llm

from . import grader
from .grader import MEDICAL_SAFETY_CHECK, grade_with_openai
from .replay import replay as replay_text
from .scenario import evaluate

DEFAULT_REPEATS = 3
MAX_REPEATS = 5

# Replays running at once, across every test being run, to stay within the
# LLM's rate limits.
_slots = asyncio.Semaphore(6)

Replay = Callable[..., Awaitable[dict]]
Grade = Callable[[dict, list[str], dict], Awaitable[list[dict]]]  # (record, checks, llm usage to add to)


async def run(
    agent: dict,
    test: dict,
    repeats: int = DEFAULT_REPEATS,
    agent_id: Optional[str] = None,
    version: Optional[int] = None,
    replay: Replay = replay_text,
    grade: Grade = grade_with_openai,
) -> dict:
    """{"at", "agent_version", "passed", "total", "cost", "runs": [...]}, one run per replay.

    Each run carries its usage and estimated cost: the replay's LLM calls, and
    the grader's (D-19)."""
    checks = [MEDICAL_SAFETY_CHECK, *test["expect"].get("checks", [])]

    async def once() -> dict:
        grading = empty_llm()
        async with _slots:
            try:
                record = await replay(agent, test["caller_turns"], agent_id=agent_id, version=version)
                grades = await grade(record, checks, grading)
            except Exception as e:
                logger.exception("Replay failed")
                return {"passed": False, "error": str(e), "events": [], "results": [], "cost": None}
        results = evaluate(test, record, grades)
        replay_llm = (record.get("usage") or {}).get("llm") or empty_llm()
        replay_cost = pricing.llm_cost(replay_llm, pricing.agent_model(agent))
        grader_cost = pricing.llm_cost(grading, grader.model())
        return {
            "passed": all(r["passed"] for r in results),
            "error": None,
            "final_node": record["final_node"],
            "collected": record["collected"],
            "unused_turns": record.get("unused_turns", 0),
            "events": record["events"],
            "results": results,
            "usage": {"replay": replay_llm, "grader": grading},
            "cost": {
                "replay": replay_cost,
                "grader": grader_cost,
                "total": (replay_cost or 0) + (grader_cost or 0),
                "complete": replay_cost is not None and grader_cost is not None,
            },
        }

    runs = await asyncio.gather(*(once() for _ in range(repeats)))
    return {
        "at": store.now(),
        "agent_version": version,
        "passed": sum(1 for r in runs if r["passed"]),
        "total": repeats,
        "cost": sum((r["cost"] or {}).get("total", 0) for r in runs),
        "runs": runs,
    }
