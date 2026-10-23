#
# Runs one test against an agent: several replays, each checked.
#
# An LLM doesn't answer the same way twice, so one passing replay proves
# little. A test is replayed a few times and reports how many passed.
#

import asyncio
from typing import Awaitable, Callable, Optional

from loguru import logger

import store

from .grader import MEDICAL_SAFETY_CHECK, grade_with_openai
from .replay import replay as replay_text
from .scenario import evaluate

DEFAULT_REPEATS = 3
MAX_REPEATS = 5

# Replays running at once, across every test being run, to stay within the
# LLM's rate limits.
_slots = asyncio.Semaphore(6)

Replay = Callable[..., Awaitable[dict]]
Grade = Callable[[dict, list[str]], Awaitable[list[dict]]]


async def run(
    agent: dict,
    test: dict,
    repeats: int = DEFAULT_REPEATS,
    agent_id: Optional[str] = None,
    version: Optional[int] = None,
    replay: Replay = replay_text,
    grade: Grade = grade_with_openai,
) -> dict:
    """{"at", "agent_version", "passed", "total", "runs": [...]}, one run per replay."""
    checks = [MEDICAL_SAFETY_CHECK, *test["expect"].get("checks", [])]

    async def once() -> dict:
        async with _slots:
            try:
                record = await replay(agent, test["caller_turns"], agent_id=agent_id, version=version)
                grades = await grade(record, checks)
            except Exception as e:
                logger.exception("Replay failed")
                return {"passed": False, "error": str(e), "events": [], "results": []}
        results = evaluate(test, record, grades)
        return {
            "passed": all(r["passed"] for r in results),
            "error": None,
            "final_node": record["final_node"],
            "collected": record["collected"],
            "unused_turns": record.get("unused_turns", 0),
            "events": record["events"],
            "results": results,
        }

    runs = await asyncio.gather(*(once() for _ in range(repeats)))
    return {
        "at": store.now(),
        "agent_version": version,
        "passed": sum(1 for r in runs if r["passed"]),
        "total": repeats,
        "runs": runs,
    }
