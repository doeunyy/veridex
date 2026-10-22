"""Supervisor pattern: supervisor -> one specialist -> supervisor ... -> finalize.

Routing between nodes reads only state fields (`next`, `hops`, `results`), so every
transition is visible in the trace. A failing specialist is recorded in `results`
with status=error and the supervisor decides what to do next; the graph never crashes.
"""

import re
from collections.abc import Callable
from time import monotonic

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from veridex.agents.citations import cited
from veridex.agents.prompts import SUPERVISOR_PROMPT, SYNTHESIS_PROMPT
from veridex.agents.state import WORKERS, Next, SupervisorState, WorkerName
from veridex.agents.workers import run_worker
from veridex.config import Settings, settings
from veridex.llm.providers import Provider
from veridex.llm.router import Signals, analyze_query, invoke_with_fallback, route

HISTORY_MESSAGES = 6
_RESULT_PREVIEW = 800
_DATA_HINT = re.compile(
    r"\b(how many|count|number of|list|which papers|who wrote|authors?|published|"
    r"per (?:year|topic)|catalog)\b|몇\s*편|몇\s*개|목록|저자|연도별|주제별",
    re.IGNORECASE,
)
_SUMMARY_HINT = re.compile(
    r"\b(summari[sz]e|summary|overview|tl;?dr|outline)\b|요약|정리해", re.IGNORECASE
)
_GREETING = re.compile(r"^\s*(hi|hello|hey|thanks?|thank you|안녕|고마워|감사)\b", re.IGNORECASE)


class SupervisorChoice(BaseModel):
    next: Next = Field(description="research, summary, data, or finish")
    task: str = Field(default="", description="Self-contained instruction for the specialist.")
    reason: str = Field(description="One sentence the user sees explaining the choice.")
    direct_answer: str = Field(
        default="", description="Only for greetings or capability questions."
    )


def _history(state: SupervisorState) -> list[AnyMessage]:
    """Earlier turns only (the current question is passed separately)."""
    messages = [m for m in state.get("messages", []) if m.type in ("human", "ai")]
    return messages[:-1][-HISTORY_MESSAGES:]


def heuristic_choice(question: str, results: list[dict]) -> SupervisorChoice:
    """Deterministic routing used when the supervisor model is unavailable."""
    done = {r["agent"] for r in results if r["status"] == "ok"}
    if done:
        return SupervisorChoice(next="finish", reason="Fallback rule: a specialist has answered.")
    if _GREETING.match(question) and len(question) < 40:
        return SupervisorChoice(
            next="finish",
            reason="Fallback rule: greeting.",
            direct_answer="Hi! Ask me about LLM agents, RAG or evaluation research.",
        )
    tried = {r["agent"] for r in results}
    for agent, pattern in (("data", _DATA_HINT), ("summary", _SUMMARY_HINT)):
        if agent not in tried and pattern.search(question):
            return SupervisorChoice(
                next=agent,
                task=question,
                reason=f"Fallback rule: {agent} keywords in the question.",
            )
    if "research" not in tried:
        return SupervisorChoice(next="research", task=question, reason="Fallback rule: default.")
    return SupervisorChoice(next="finish", reason="Fallback rule: no specialist left to try.")


def build_graph(
    tools: dict[WorkerName, list[BaseTool]],
    *,
    config: Settings | None = None,
    factory: Callable[[Provider], BaseChatModel] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    config = config or settings

    async def supervisor(state: SupervisorState) -> dict:
        started = monotonic()
        question = state["question"]
        results = state.get("results", [])
        hops = state.get("hops", 0)
        update: dict = {}
        if hops >= config.supervisor_max_hops:
            choice = SupervisorChoice(next="finish", reason="Reached the specialist limit.")
        else:
            decision = route("supervisor", analyze_query(question), config)
            try:
                choice, used = await invoke_with_fallback(
                    decision,
                    _supervisor_messages(state, question, results),
                    prepare=lambda model: model.with_structured_output(SupervisorChoice),
                    factory=factory,
                    config=config,
                )
                if not isinstance(choice, SupervisorChoice):
                    choice = SupervisorChoice.model_validate(choice)
                update["routing"] = [used.as_dict()]
            except Exception as exc:  # noqa: BLE001 — fall back to deterministic routing
                choice = heuristic_choice(question, results)
                choice.reason = f"{choice.reason} (supervisor model failed: {type(exc).__name__})"
            choice = _guard(choice, question, results)
        if choice.next in WORKERS:
            update["hops"] = hops + 1
        update |= {
            "next": choice.next,
            "task": choice.task or question,
            "reason": choice.reason,
            "direct_answer": choice.direct_answer if choice.next == "finish" else "",
            "trace": [
                _event(
                    "supervisor",
                    started,
                    next=choice.next,
                    reason=choice.reason,
                    task=choice.task if choice.next in WORKERS else "",
                    hop=hops + (choice.next in WORKERS),
                )
            ],
        }
        return update

    def worker_node(agent: WorkerName):
        async def node(state: SupervisorState) -> dict:
            result = await run_worker(
                agent,
                task=state.get("task") or state["question"],
                question=state["question"],
                history=_history(state),
                tools=tools[agent],
                config=config,
                factory=factory,
            )
            event = _event(
                agent,
                None,
                status=result["status"],
                error=result["error"],
                tools=[f"{c['tool']}:{c['status']}" for c in result["tool_calls"]],
                sources=len(result["sources"]),
                duration_ms=result["duration_ms"],
            )
            return {"results": [result], "routing": result["routing"], "trace": [event]}

        node.__name__ = agent
        return node

    async def finalize(state: SupervisorState) -> dict:
        started = monotonic()
        results = state.get("results", [])
        succeeded = [r for r in results if r["status"] == "ok" and r["answer"]]
        failed = [r["agent"] for r in results if r["status"] != "ok"]
        update: dict = {}
        if not results and state.get("direct_answer"):
            answer, mode = state["direct_answer"], "direct"
        elif len(succeeded) == 1:
            answer, mode = succeeded[0]["answer"], "single_agent"
        elif succeeded:
            decision = route("synthesis", Signals(), config)
            parts = "\n\n".join(f"## {r['agent']} agent\n{r['answer']}" for r in succeeded)
            if failed:
                parts += f"\n\nFailed specialists: {', '.join(failed)}."
            response, used = await invoke_with_fallback(
                decision,
                [
                    SystemMessage(content=SYNTHESIS_PROMPT),
                    HumanMessage(content=f"User question: {state['question']}\n\n{parts}"),
                ],
                factory=factory,
                config=config,
            )
            answer, mode = _content(response), "synthesis"
            update["routing"] = [used.as_dict()]
        else:
            answer, mode = _failure_message(failed), "failure"
        sources = {k: v for r in results for k, v in r["sources"].items()}
        citations = cited(answer, sources)
        update |= {
            "answer": answer,
            "citations": citations,
            "messages": [AIMessage(content=answer)],
            "trace": [_event("finalize", started, mode=mode, citations=len(citations))],
        }
        return update

    builder = StateGraph(SupervisorState)
    builder.add_node("supervisor", supervisor)
    for agent in WORKERS:
        builder.add_node(agent, worker_node(agent))
        builder.add_edge(agent, "supervisor")
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: "finalize" if state["next"] == "finish" else state["next"],
        {"research": "research", "summary": "summary", "data": "data", "finalize": "finalize"},
    )
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def _guard(choice: SupervisorChoice, question: str, results: list[dict]) -> SupervisorChoice:
    """Never re-run a specialist that already succeeded this turn."""
    succeeded = {r["agent"] for r in results if r["status"] == "ok"}
    if choice.next in succeeded:
        return SupervisorChoice(
            next="finish", reason=f"{choice.next} already answered; finishing ({choice.reason})"
        )
    if choice.next == "finish" and not results and not choice.direct_answer:
        return heuristic_choice(question, results)
    return choice


def _supervisor_messages(state, question: str, results: list[dict]) -> list[AnyMessage]:
    done = "\n".join(
        f"- {r['agent']} ({r['status']}): {r['answer'][:_RESULT_PREVIEW] or r['error']}"
        for r in results
    )
    return [
        SystemMessage(content=SUPERVISOR_PROMPT),
        *_history(state),
        HumanMessage(
            content=f"Current request: {question}\n\nResults so far this turn:\n{done or '(none)'}"
        ),
    ]


def _content(message) -> str:
    content = message.content
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content).strip()


def _failure_message(failed: list[str]) -> str:
    names = ", ".join(failed) or "the specialists"
    return (
        f"I could not produce a verified answer: {names} failed. "
        "No evidence was retrieved, so I will not guess. Please try again."
    )


def _event(node: str, started: float | None, **detail) -> dict:
    event = {"node": node, **{k: v for k, v in detail.items() if v not in (None, "", [])}}
    if started is not None:
        event["duration_ms"] = round((monotonic() - started) * 1000)
    return event
