"""Specialist agents: a bounded tool loop with a routed model and distinct tools/prompt."""

import re
from collections.abc import Callable
from time import monotonic

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from veridex.agents.citations import collect_sources
from veridex.agents.prompts import WORKER_PROMPTS
from veridex.agents.state import WorkerName, announce
from veridex.agents.tools import canonical_name
from veridex.config import Settings
from veridex.llm.providers import Provider
from veridex.llm.router import RoutingDecision, Signals, analyze_query, invoke_with_fallback, route

_DOC_ID = re.compile(r"\b[a-z0-9_]+_20\d\d\b")
_TOOL_ERROR = "Tool failed. No usable evidence was returned; do not cite this result."
_BUDGET = "Tool call budget reached. Answer with the evidence you already have."


def worker_signals(agent: WorkerName, question: str, task: str) -> Signals:
    signals = analyze_query(f"{question}\n{task}")
    if agent == "summary":
        named = len(set(_DOC_ID.findall(f"{question} {task}")))
        documents = max(1, named, 2 if signals.comparison else 1)
        return Signals(**{**signals.__dict__, "documents": documents})
    return signals


async def run_worker(
    agent: WorkerName,
    *,
    task: str,
    question: str,
    history: list[AnyMessage],
    tools: list[BaseTool],
    config: Settings,
    factory: Callable[[Provider], BaseChatModel] | None = None,
) -> dict:
    """Run one specialist to completion. Failures are returned, never raised.

    Returns a WorkerResult: agent, status, answer, sources, tool_calls, routing, error.
    """
    started = monotonic()
    by_name = {tool.name: tool for tool in tools}
    decision = route(agent, worker_signals(agent, question, task), config)
    routing: list[dict] = []
    tool_calls: list[dict] = []
    sources: dict[str, dict] = {}
    messages: list[AnyMessage] = [
        SystemMessage(content=WORKER_PROMPTS[agent]),
        *history,
        HumanMessage(content=f"User question: {question}\n\nYour task: {task}"),
    ]
    try:
        for round_number in range(config.worker_max_tool_rounds + 1):
            final_round = round_number == config.worker_max_tool_rounds
            if final_round:
                messages.append(HumanMessage(content="Tool budget reached. Answer now."))
            response, used = await invoke_with_fallback(
                decision,
                messages,
                prepare=(lambda m: m) if final_round else (lambda m: m.bind_tools(tools)),
                factory=factory,
                config=config,
            )
            _record(routing, used)
            messages.append(response)
            if final_round or not getattr(response, "tool_calls", None):
                return _result(agent, response, sources, tool_calls, routing, started)
            failed = False
            for call in response.tool_calls:
                tool_ms = 0
                if len(tool_calls) >= config.worker_max_tool_calls:
                    message = ToolMessage(
                        content=_BUDGET, name=call["name"], tool_call_id=call["id"], status="error"
                    )
                else:
                    tool_started = monotonic()
                    message = await _call_tool(by_name, call)
                    tool_ms = round((monotonic() - tool_started) * 1000)
                    collect_sources(message, sources)
                    message = _bounded(message, config.worker_max_tool_result_characters)
                failed |= message.status == "error"
                messages.append(message)
                tool_calls.append(
                    {
                        "agent": agent,
                        "tool": canonical_name(call["name"]),
                        "args": {k: str(v)[:200] for k, v in call["args"].items()},
                        "status": message.status,
                        "duration_ms": tool_ms,
                    }
                )
            if agent == "data" and failed and not decision.signals.escalate:
                escalated = Signals(**{**decision.signals.__dict__, "escalate": True})
                decision = route("data", escalated, config)
        raise AssertionError("unreachable")  # pragma: no cover
    except Exception as exc:  # noqa: BLE001 — a failed worker must not crash the graph
        return {
            "agent": agent,
            "status": "error",
            "answer": "",
            "error": type(exc).__name__,
            "sources": sources,
            "tool_calls": tool_calls,
            "routing": routing,
            "duration_ms": round((monotonic() - started) * 1000),
        }


async def _call_tool(by_name: dict[str, BaseTool], call: dict) -> ToolMessage:
    tool = by_name.get(call["name"])
    if tool is None:
        return ToolMessage(
            content="Unknown tool for this agent.",
            name=call["name"],
            tool_call_id=call["id"],
            status="error",
        )
    try:
        return await tool.ainvoke({**call, "type": "tool_call"})
    except Exception:  # noqa: BLE001 — tool failures become error ToolMessages
        return ToolMessage(
            content=_TOOL_ERROR, name=call["name"], tool_call_id=call["id"], status="error"
        )


def _bounded(message: ToolMessage, limit: int) -> ToolMessage:
    """Cap what the model reads (web extracts can be huge); sources keep the full artifact."""
    content = message.content
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    if len(content) <= limit:
        return message
    clipped = content[:limit] + "\n[truncated]"
    return message.model_copy(update={"content": clipped})


def _record(routing: list[dict], used: RoutingDecision) -> None:
    entry = used.as_dict()
    if not routing or routing[-1] != entry:
        routing.append(entry)
        announce("route", entry)


def _text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        ).strip()
    return str(content).strip()


def _result(agent, response, sources, tool_calls, routing, started) -> dict:
    return {
        "agent": agent,
        "status": "ok",
        "answer": _text(response),
        "error": None,
        "sources": sources,
        "tool_calls": tool_calls,
        "routing": routing,
        "duration_ms": round((monotonic() - started) * 1000),
    }
