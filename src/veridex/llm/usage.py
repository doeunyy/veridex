"""Per-turn token usage, model latency and estimated cost.

Prices are USD per 1M tokens, recorded on 2026-10-22:
- gemini-3.8-flash: $0.75 input / $3.75 output (Google AI pricing page, paid tier,
  through 2026-12-31).
- gpt-6.1-sol: $2.00 input / $10.00 output (third-party price lists; the OpenAI page
  was not reachable from the build machine, so confirm on the OpenAI dashboard).
- text-embedding-3-small: $0.02 input (OpenAI pricing page).
"""

from contextvars import ContextVar
from time import monotonic

PRICES_PER_MILLION = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gpt-6.1-sol": (2.00, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
}

_CALLS: ContextVar[list[dict] | None] = ContextVar("veridex_model_calls", default=None)


def start_turn() -> list[dict]:
    """Collect model calls made by this task and every task it spawns."""
    calls: list[dict] = []
    _CALLS.set(calls)
    return calls


def tokens(response) -> tuple[int, int]:
    if isinstance(response, dict) and "raw" in response:  # structured output, include_raw=True
        response = response["raw"]
    usage = getattr(response, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def record(agent: str, provider: str, model: str, response, started: float, ok: bool) -> None:
    calls = _CALLS.get()
    if calls is None:
        return
    input_tokens, output_tokens = tokens(response) if ok else (0, 0)
    calls.append(
        {
            "agent": agent,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": round((monotonic() - started) * 1000),
            "ok": ok,
        }
    )


def cost_usd(calls: list[dict]) -> float:
    total = 0.0
    for call in calls:
        price_in, price_out = PRICES_PER_MILLION.get(call["model"], (0.0, 0.0))
        total += call["input_tokens"] * price_in + call["output_tokens"] * price_out
    return round(total / 1_000_000, 6)
