#
# Pricing — turns recorded usage into an estimated cost, in USD (AD-19).
#
# The prices live in pricing.json, so they can be updated without a code
# change, and every record is re-priced when it's read.
#

import json
from pathlib import Path
from typing import Optional

from agent_builder.schema import DEFAULT_MODEL

PRICES_FILE = Path(__file__).parent / "pricing.json"


def prices() -> dict:
    return json.loads(PRICES_FILE.read_text())


def agent_model(agent: Optional[dict]) -> str:
    """The model an agent runs on: its own, or the default the runtime uses."""
    return (agent or {}).get("model") or DEFAULT_MODEL


def llm_cost(llm: dict, model: str, table: Optional[dict] = None) -> Optional[float]:
    """None when the model has no price in the table."""
    rate = (table or prices())["llm"].get(model)
    if rate is None:
        return None
    cached = min(llm.get("cached_tokens", 0), llm.get("input_tokens", 0))
    fresh = llm.get("input_tokens", 0) - cached
    return (fresh * rate["input"] + cached * rate["cached"] + llm.get("output_tokens", 0) * rate["output"]) / 1_000_000


def cost(usage: Optional[dict], model: str) -> Optional[dict]:
    """{"llm", "tts", "stt", "total", "complete"} for a record's usage; None if it has none.

    A part that wasn't used (e.g. no speech in a replay) is left out. "complete"
    is False when a part couldn't be priced (a model missing from the table);
    "total" then covers only what could.
    """
    if not usage:
        return None
    table = prices()
    out: dict = {}
    if "llm" in usage:
        out["llm"] = llm_cost(usage["llm"], model, table)
    if "tts" in usage:
        out["tts"] = usage["tts"]["characters"] / 1000 * table["tts_per_1k_characters"]
    if "stt" in usage:
        out["stt"] = usage["stt"]["seconds"] / 3600 * table["stt_per_hour"]
    out["total"] = sum(v for v in out.values() if v is not None)
    out["complete"] = all(v is not None for v in out.values())
    return out
