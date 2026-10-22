import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from veridex.config import Settings
from veridex.llm.providers import ProviderUnavailable, create_chat_model
from veridex.llm.router import Signals, analyze_query, invoke_with_fallback, route

BOTH = Settings(_env_file=None, openai_api_key="sk-test", google_api_key="g-test")


@pytest.mark.parametrize(
    ("agent", "signals", "provider", "rule"),
    [
        ("supervisor", Signals(), "gemini", "classify"),
        ("research", Signals(), "gemini", "single_lookup"),
        ("research", Signals(comparison=True), "openai", "multi_step_synthesis"),
        ("research", Signals(needs_web=True), "openai", "multi_step_synthesis"),
        ("summary", Signals(documents=1), "gemini", "long_context"),
        ("summary", Signals(documents=3), "openai", "cross_document"),
        ("data", Signals(), "gemini", "structured_lookup"),
        ("data", Signals(escalate=True), "openai", "sql_repair"),
        ("synthesis", Signals(), "openai", "multi_agent_merge"),
    ],
)
def test_routing_table(agent, signals, provider, rule):
    decision = route(agent, signals, BOTH)
    assert (decision.provider, decision.rule) == (provider, rule)
    assert decision.model == ("gpt-6.1-sol" if provider == "openai" else "gemini-3.8-flash")
    assert decision.reason and decision.as_dict()["signals"] == signals.__dict__


def test_both_providers_are_reachable_from_real_queries():
    providers = {
        route("research", analyze_query(query), BOTH).provider
        for query in (
            "What is ReAct?",
            "Compare Self-RAG and CRAG for retrieval quality.",
        )
    }
    assert providers == {"openai", "gemini"}


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("How does RAPTOR differ from GraphRAG?", "comparison"),
        ("Self-RAG와 RAPTOR를 비교해줘", "comparison"),
        ("What are the latest agent benchmarks in 2026?", "needs_web"),
        ("최근 나온 RAG 평가 방법은?", "needs_web"),
        ("What is RAGAS? How is faithfulness computed?", "multi_part"),
    ],
)
def test_query_signals(query, field):
    signals = analyze_query(query)
    assert getattr(signals, field) is True
    assert signals.query_chars == len(query)


def test_plain_question_has_no_escalating_signals():
    signals = analyze_query("What is the ReAct prompting format?")
    assert not (signals.comparison or signals.multi_part or signals.needs_web)


def test_unconfigured_provider_is_replaced_and_explained():
    only_openai = Settings(_env_file=None, openai_api_key="sk-test")
    decision = route("supervisor", Signals(), only_openai)
    assert decision.provider == "openai" and "gemini is not configured" in decision.reason
    with pytest.raises(ProviderUnavailable):
        route("supervisor", Signals(), Settings(_env_file=None))


def test_create_chat_model_requires_credentials():
    with pytest.raises(ProviderUnavailable):
        create_chat_model("gemini", Settings(_env_file=None, openai_api_key="sk"))
    assert create_chat_model("openai", BOTH).model_name == "gpt-6.1-sol"
    assert create_chat_model("gemini", BOTH).model == "gemini-3.8-flash"


class Broken(GenericFakeChatModel):
    async def ainvoke(self, *args, **kwargs):
        raise TimeoutError("provider down")


@pytest.mark.asyncio
async def test_fallback_switches_provider_and_records_it():
    models = {
        "gemini": Broken(messages=iter([])),
        "openai": GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
    }
    decision = route("supervisor", Signals(), BOTH)
    response, used = await invoke_with_fallback(
        decision, [HumanMessage(content="hi")], factory=models.__getitem__, config=BOTH
    )
    assert response.content == "ok"
    assert used.provider == "openai" and used.fallback_from == "gemini"
    assert "TimeoutError" in used.reason and used.rule == "classify"


@pytest.mark.asyncio
async def test_no_fallback_without_second_provider():
    only_gemini = Settings(_env_file=None, google_api_key="g")
    decision = route("supervisor", Signals(), only_gemini)
    with pytest.raises(TimeoutError):
        await invoke_with_fallback(
            decision,
            [HumanMessage(content="hi")],
            factory=lambda provider: Broken(messages=iter([])),
            config=only_gemini,
        )
