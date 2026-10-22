from time import monotonic

from langchain_core.messages import AIMessage

from veridex.config import Settings
from veridex.evaluation.run import summarize
from veridex.llm import usage
from veridex.llm.router import Signals, route


def test_cost_uses_input_and_output_prices():
    calls = usage.start_turn()
    response = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200},
    )
    usage.record("research", "openai", "gpt-6.1-sol", response, monotonic(), ok=True)
    usage.record(
        "supervisor", "gemini", "gemini-3.8-flash", {"raw": response}, monotonic(), ok=True
    )
    usage.record("research", "openai", "gpt-6.1-sol", None, monotonic(), ok=False)
    assert [c["input_tokens"] for c in calls] == [1000, 1000, 0]
    expected = (1000 * 2.0 + 200 * 10.0 + 1000 * 0.75 + 200 * 3.75) / 1_000_000
    assert usage.cost_usd(calls) == round(expected, 6)


def test_forced_provider_is_explained():
    config = Settings(
        _env_file=None, openai_api_key="sk", google_api_key="g", router_force_provider="openai"
    )
    decision = route("supervisor", Signals(), config)
    assert decision.provider == "openai" and decision.rule == "classify"
    assert "Evaluation override" in decision.reason


def test_summary_statistics():
    assert summarize([None]) == {"n": 0}
    stats = summarize([1, 2, 3, 4, 10, None])
    assert stats["n"] == 5 and stats["median"] == 3 and stats["p90"] == 10
