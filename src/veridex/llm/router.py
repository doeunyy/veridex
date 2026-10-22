"""Hybrid cost/capability routing across OpenAI and Gemini.

Every generation call is routed by an explicit rule over observable signals, and the
resulting RoutingDecision (provider, model, dimension, rule, reason, signals) is
recorded in the trace and shown in the UI. A provider failure falls back to the other
provider and is recorded as a fallback, never as a routing decision.

Routing table (first matching rule wins):

| agent      | rule                 | provider | dimension  |
|------------|----------------------|----------|------------|
| supervisor | classify             | gemini   | cost       |
| research   | multi_step_synthesis | openai   | capability |
| research   | single_lookup        | gemini   | cost       |
| summary    | cross_document       | openai   | capability |
| summary    | long_context         | gemini   | capability |
| data       | sql_repair           | openai   | capability |
| data       | structured_lookup    | gemini   | cost       |
| synthesis  | multi_agent_merge    | openai   | capability |
"""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Literal

from langchain_core.language_models import BaseChatModel

from veridex.config import Settings, settings
from veridex.llm.providers import (
    Provider,
    ProviderUnavailable,
    create_chat_model,
    is_configured,
    model_id,
)
from veridex.observability import execution

Agent = Literal["supervisor", "research", "summary", "data", "synthesis"]
Dimension = Literal["cost", "capability"]

_COMPARISON = re.compile(
    r"\b(compare|comparison|versus|vs\.?|differ(?:ence|ent)?|trade-?offs?|contrast|"
    r"better than|outperform\w*|pros and cons)\b|비교|차이|대비|장단점|어느 쪽",
    re.IGNORECASE,
)
_RECENCY = re.compile(
    r"\b(latest|recent(?:ly)?|current(?:ly)?|today|this (?:year|month|week)|news|"
    r"state of the art|sota|20(?:2[5-9]|3\d))\b|최신|최근|요즘|현재|올해|뉴스",
    re.IGNORECASE,
)
_SEQUENCE = re.compile(r"\b(then|also|and then|step by step)\b|그리고|또한|그 다음", re.IGNORECASE)


@dataclass(frozen=True)
class Signals:
    """Observable inputs to a routing rule; all are recorded with the decision."""

    query_chars: int = 0
    comparison: bool = False
    multi_part: bool = False
    needs_web: bool = False
    documents: int = 0
    context_chars: int = 0
    escalate: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    agent: Agent
    provider: Provider
    model: str
    dimension: Dimension
    rule: str
    reason: str
    signals: Signals = field(default_factory=Signals)
    fallback_from: Provider | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def analyze_query(text: str) -> Signals:
    """Cheap, deterministic signals from the user's wording."""
    questions = text.count("?") + text.count("？")
    return Signals(
        query_chars=len(text),
        comparison=bool(_COMPARISON.search(text)),
        multi_part=questions > 1 or bool(_SEQUENCE.search(text)),
        needs_web=bool(_RECENCY.search(text)),
    )


def _rule(agent: Agent, s: Signals) -> tuple[Provider, Dimension, str, str]:
    if agent == "supervisor":
        return (
            "gemini",
            "cost",
            "classify",
            "Routing is a short classification; use the cheaper model.",
        )
    if agent == "research":
        if s.comparison or s.multi_part or s.needs_web:
            why = ", ".join(
                name
                for name, on in (
                    ("comparison", s.comparison),
                    ("multi-part question", s.multi_part),
                    ("needs live web results", s.needs_web),
                )
                if on
            )
            return (
                "openai",
                "capability",
                "multi_step_synthesis",
                f"Multi-step synthesis ({why}); use the stronger reasoning model.",
            )
        return "gemini", "cost", "single_lookup", "Single grounded lookup; use the cheaper model."
    if agent == "summary":
        if s.documents >= 2:
            return (
                "openai",
                "capability",
                "cross_document",
                f"Summary across {s.documents} papers needs cross-document reasoning.",
            )
        return (
            "gemini",
            "capability",
            "long_context",
            "Single-paper summary over long page text; use the long-context model.",
        )
    if agent == "data":
        if s.escalate:
            return (
                "openai",
                "capability",
                "sql_repair",
                "Previous SQL attempt failed; escalate to the stronger model.",
            )
        return (
            "gemini",
            "cost",
            "structured_lookup",
            "Simple SQL over a small schema; use the cheaper model.",
        )
    return (
        "openai",
        "capability",
        "multi_agent_merge",
        "Merging results from several agents needs multi-source synthesis.",
    )


def route(
    agent: Agent, signals: Signals | None = None, config: Settings | None = None
) -> RoutingDecision:
    config = config or settings
    signals = signals or Signals()
    provider, dimension, rule, reason = _rule(agent, signals)
    if not is_configured(provider, config):
        other = _other(provider)
        if not is_configured(other, config):
            raise ProviderUnavailable("No LLM provider is configured.")
        reason = f"{reason} {provider} is not configured, so {other} is used."
        provider = other
    return RoutingDecision(
        agent=agent,
        provider=provider,
        model=model_id(provider, config),
        dimension=dimension,
        rule=rule,
        reason=reason,
        signals=signals,
    )


def _other(provider: Provider) -> Provider:
    return "gemini" if provider == "openai" else "openai"


async def invoke_with_fallback(
    decision: RoutingDecision,
    messages: list,
    *,
    prepare: Callable[[BaseChatModel], object] = lambda model: model,
    factory: Callable[[Provider], BaseChatModel] | None = None,
    config: Settings | None = None,
):
    """Call the routed provider; on failure retry once on the other provider.

    `prepare` binds tools or structured output to whichever model is used.
    Returns (response, decision actually used).
    """
    config = config or settings
    factory = factory or (lambda provider: create_chat_model(provider, config))
    try:
        with execution("model"):
            return await prepare(factory(decision.provider)).ainvoke(messages), decision
    except Exception as primary:
        other = _other(decision.provider)
        if not is_configured(other, config):
            raise
        fallback = replace(
            decision,
            provider=other,
            model=model_id(other, config),
            fallback_from=decision.provider,
            reason=f"{decision.provider} failed ({type(primary).__name__}); fell back to {other}.",
        )
        with execution("model"):
            return await prepare(factory(other)).ainvoke(messages), fallback
