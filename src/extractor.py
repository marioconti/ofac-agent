"""
Stage 2 of the pipeline: the Strands agent. It reads ONE observation of prose
and returns the structured `Observation` (fields only — no judgement).

This is the only stage that uses the LLM. Extraction runs at temperature 0 for
reproducibility.

IMPORTANT (isolation): a Strands Agent is stateful — it keeps the conversation
history across calls. Reusing one agent for all 80 observations would resend
every prior observation on each call (cost balloons, context can overflow) and
let one case's data bleed into the next. So we build a FRESH agent per
observation: history is empty each time, `accumulated_usage` is exactly that
observation's usage, and one failure never affects another.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from strands import Agent
from strands.models.anthropic import AnthropicModel

from .schema import Observation

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

_SYSTEM_PROMPT = (
    "You extract structured fields from a single compliance screening note that "
    "reports one OFAC-SDN name match. Read the note and fill in the fields for the "
    "bank client and for the OFAC subject. Rules: do NOT judge or classify the "
    "match; do NOT invent data — use null when a field is absent; normalize dates "
    "to ISO (YYYY-MM-DD, or just the year when only the year is given); resolve "
    "abbreviated Spanish months (SEP, AGO, MAY, DIC...). The client and OFAC data "
    "may appear mixed and in any order."
)


def make_model(model_id: str = DEFAULT_MODEL) -> AnthropicModel:
    """Build the model/client once; reuse it across observations."""
    return AnthropicModel(
        client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
        model_id=model_id,
        max_tokens=1024,
        params={"temperature": 0},
    )


def extract_one(raw_text: str, model: AnthropicModel):
    """Extract one observation with a FRESH, isolated agent. Returns (Observation, metrics)."""
    agent = Agent(model=model, system_prompt=_SYSTEM_PROMPT, callback_handler=None)
    result = agent(raw_text, structured_output_model=Observation)
    return result.structured_output, result.metrics


if __name__ == "__main__":
    # Manual check: extract a couple of observations with fresh agents.
    # Run from the repo root:  python -m src.extractor
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    from .loader import load_observations

    obs = load_observations("input/observaciones-ejemplo.pdf")
    by_number = {n: raw for n, raw in obs}
    model = make_model()

    for target in (1, 5):  # Obs 1 (borderline) and Obs 5 (the 97%-score trap)
        data, metrics = extract_one(by_number[target], model)
        usage = metrics.accumulated_usage
        print(f"\n===== Obs {target} =====")
        print(data.model_dump_json(indent=2))
        print(f"[tokens in={usage['inputTokens']} out={usage['outputTokens']}]")
