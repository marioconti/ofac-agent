"""
Token, cost and time accounting.

The brief asks for the run's cost and timing to be visible, so this is a first-class
part of the pipeline rather than something bolted on at the end: every extraction
reports its tokens here, and the run summary reads its totals from this object.

Prices are per million tokens, as published by Anthropic. They live in one table so
that switching models is a one-line change and the reported cost stays honest.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

# USD per million tokens: (input, output).
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}

# Used when the model is unknown, so an unpriced model reports 0 instead of crashing
# a run. The summary flags it rather than quietly printing a wrong number.
UNKNOWN_PRICE = (0.0, 0.0)


def price_of(model_id: str) -> tuple[float, float]:
    return PRICES_PER_MTOK.get(model_id, UNKNOWN_PRICE)


def cost_of(model_id: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = price_of(model_id)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


@dataclass
class RunCost:
    """Accumulates usage across a whole run."""

    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    started_at: float = 0.0

    def start(self) -> None:
        self.started_at = time.perf_counter()

    def add(self, input_tokens: int, output_tokens: int) -> float:
        """Record one model call. Returns the cost of that single call."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1
        return cost_of(self.model_id, input_tokens, output_tokens)

    @property
    def total_cost(self) -> float:
        return cost_of(self.model_id, self.input_tokens, self.output_tokens)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at if self.started_at else 0.0

    @property
    def is_priced(self) -> bool:
        return self.model_id in PRICES_PER_MTOK


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"
