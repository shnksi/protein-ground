"""Price table (USD per million tokens), checked 23 Nov 2026 against Anthropic's list prices.

Cache writes are priced at 1.25x input (5-minute TTL). The Haiku 5.5 cache-read price is
an assumption (0.1x input). These are estimates for planning; the invoice is the record.

Claude Opus 5 and Opus 4.8 are here because a server-side fallback can serve an item
asked of Opus 5.5. Without a row their tokens are unpriced and escape the spend cap. Their
cache-read price is assumed at 0.1x input, which errs on the high side.
"""

from __future__ import annotations

from dataclasses import dataclass

from proteinground.eval.agent import Episode, Usage


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.10),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01),
    "claude-opus-5": Price(input=5.00, output=25.00, cache_read=0.50),
    "claude-opus-4-8": Price(input=5.00, output=25.00, cache_read=0.50),
}


def cost_usd(model: str, usage: Usage) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        usage.input_tokens * price.input
        + usage.cache_write_tokens * price.input * 1.25
        + usage.cache_read_tokens * price.cache_read
        + usage.output_tokens * price.output
    ) / 1_000_000


def episode_cost_usd(episode: Episode) -> float | None:
    """Price each model's share of the tokens at its own rate; None if any is unpriced."""
    total = 0.0
    for model, usage in episode.usage_by_model.items():
        cost = cost_usd(model, usage)
        if cost is None:
            return None
        total += cost
    return total
