#
# CallRecorder — builds one call's record: transcript, transitions, refusals,
# fallbacks, where it ended and what it collected (format in store.save_call).
#
# Used by voice calls (bot.py), which save the record when the call ends, and by
# test replays (regression/), which keep it to check against the test.
#

from datetime import datetime
from typing import Optional

from loguru import logger

import store
from agent_builder.builder import BUILT_IN_FALLBACK


class CallRecorder:
    """Collects one call's timeline and writes it to the store when the call ends."""

    def __init__(self, agent: dict, agent_id, version, source: str):
        self.record = {
            "id": store.new_call_id(),
            "source": source,
            "agent_id": agent_id,
            "agent_version": version,
            "agent": agent,
            "started_at": store.now(),
            "ended_at": None,
            "ended_by": None,
            "final_node": agent["initial_node"],
            "collected": {},
            "events": [],
        }
        # What the call consumed (usage.py), when it's being metered.
        self.usage: Optional[dict] = None
        self.speech = False  # voice calls also pay for speech-to-text, by time

    @property
    def call_id(self) -> str:
        return self.record["id"]

    def add(self, type: str, **fields) -> dict:
        event = {"t": store.now(), "type": type, **fields}
        self.record["events"].append(event)
        return event

    def transition(self, from_node: str, function: str, to_node: str, args: dict) -> dict:
        self.record["final_node"] = to_node
        self.record["collected"].update(args)
        return self.add("transition", from_node=from_node, function=function, to_node=to_node, args=args)

    def fallback(self, from_node: str, reason: str, to_node: str) -> dict:
        # The call got stuck and was moved on (D-16): that's where it now is.
        self.record["final_node"] = to_node
        return self.add("fallback", from_node=from_node, reason=reason, to_node=to_node)

    def refusal(self, node: str, function: str, args: dict, problems: list) -> dict:
        # A transition the LLM tried without the data it requires. Repeated
        # refusals in one node are a sign its instructions need work.
        return self.add("refused", node=node, function=function, args=args, problems=problems)

    def finish(self) -> dict:
        # The built-in fallback ends the call too.
        end_nodes = {n["name"] for n in self.record["agent"]["nodes"] if n.get("end")} | {BUILT_IN_FALLBACK}
        self.record["ended_at"] = store.now()
        self.record["ended_by"] = "agent" if self.record["final_node"] in end_nodes else "caller"
        if self.usage is not None:
            if self.speech:
                started = datetime.fromisoformat(self.record["started_at"])
                ended = datetime.fromisoformat(self.record["ended_at"])
                self.usage["stt"] = {"seconds": round((ended - started).total_seconds(), 1)}
            self.record["usage"] = self.usage
        return self.record

    def save(self) -> None:
        store.save_call(self.finish())
        logger.info(f"Recorded call {self.call_id} ({len(self.record['events'])} events)")
