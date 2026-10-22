import json
from types import SimpleNamespace

import pytest
from agents_fakes import CONFIG, PASSAGE, factory, last_human, make_tools, system, tool_call
from langchain_core.messages import AIMessage

from veridex.agents.citations import cited
from veridex.agents.graph import build_graph, heuristic_choice
from veridex.agents.prompts import DATA_PROMPT, RESEARCH_PROMPT, SUMMARY_PROMPT, SUPERVISOR_PROMPT
from veridex.agents.service import MultiAgentService, SessionCapacityError
from veridex.agents.tools import shared_tools, tools_by_agent


def plan(*steps):
    """Supervisor script: the n-th supervisor call returns steps[n]."""
    state = {"n": 0}

    def choose():
        step = steps[min(state["n"], len(steps) - 1)]
        state["n"] += 1
        return step

    return choose


def research_script(choose):
    def script(provider, mode, messages):
        prompt = system(messages)
        if mode == "structured":
            return choose()
        if prompt == RESEARCH_PROMPT:
            if messages[-1].type == "tool":
                return AIMessage(
                    content="ReAct interleaves reasoning and acting [react_2022:p2:c012]."
                )
            return tool_call("search_evidence", {"query": "ReAct"})
        if prompt == DATA_PROMPT:
            if messages[-1].type == "tool":
                return AIMessage(content="There are 42 papers.")
            return tool_call("query_catalog_sql", {"sql": "SELECT COUNT(*) FROM papers"})
        return AIMessage(content=f"merged: {last_human(messages)[-120:]}")

    return script


async def run(graph, question, thread="t1"):
    return await graph.ainvoke(
        MultiAgentService.turn_input(question),
        config={"configurable": {"thread_id": thread}, "recursion_limit": 12},
    )


def graph_for(script, tools=None):
    make, calls = factory(script)
    from langgraph.checkpoint.memory import InMemorySaver

    graph = build_graph(
        tools or make_tools(), config=CONFIG, factory=make, checkpointer=InMemorySaver()
    )
    return graph, calls


@pytest.mark.asyncio
async def test_single_specialist_answer_with_citation_and_trace():
    choose = plan(
        {"next": "research", "task": "Explain ReAct", "reason": "Method question."},
        {"next": "finish", "reason": "Answered."},
    )
    graph, calls = graph_for(research_script(choose))
    state = await run(graph, "What is ReAct?")

    assert state["answer"].endswith("[react_2022:p2:c012].")
    assert [c["id"] for c in state["citations"]] == ["react_2022:p2:c012"]
    assert [e["node"] for e in state["trace"]] == [
        "supervisor",
        "research",
        "supervisor",
        "finalize",
    ]
    assert state["trace"][0]["reason"] == "Method question."
    assert [(r["agent"], r["provider"], r["rule"]) for r in state["routing"]] == [
        ("supervisor", "gemini", "classify"),
        ("research", "gemini", "single_lookup"),
        ("supervisor", "gemini", "classify"),
    ]
    assert ("gemini", "tools") in calls and ("openai", "plain") not in calls


@pytest.mark.asyncio
async def test_two_specialists_are_merged_by_openai_synthesis():
    choose = plan(
        {"next": "data", "task": "Count papers", "reason": "Count question."},
        {"next": "research", "task": "Compare ReAct", "reason": "Second part."},
        {"next": "finish", "reason": "Both parts answered."},
    )
    graph, _ = graph_for(research_script(choose))
    state = await run(graph, "How many papers are there, and compare ReAct with CoT?")

    assert [r["agent"] for r in state["results"]] == ["data", "research"]
    assert state["answer"].startswith("merged:")
    providers = {r["provider"] for r in state["routing"]}
    assert providers == {"gemini", "openai"}
    assert state["routing"][-1]["rule"] == "multi_agent_merge"
    research = next(r for r in state["routing"] if r["agent"] == "research")
    assert research["provider"] == "openai" and research["signals"]["comparison"]


@pytest.mark.asyncio
async def test_failed_worker_does_not_crash_the_graph():
    def script(provider, mode, messages):
        if mode == "structured":
            return choose()
        raise TimeoutError("provider down")

    choose = plan(
        {"next": "research", "task": "x", "reason": "r"},
        {"next": "finish", "reason": "Research failed; stop."},
    )
    graph, calls = graph_for(script)
    state = await run(graph, "What is ReAct?")

    assert state["results"][0]["status"] == "error"
    assert state["results"][0]["error"] == "TimeoutError"
    assert "could not produce a verified answer" in state["answer"]
    assert ("gemini", "tools") in calls and ("openai", "tools") in calls  # fallback tried


@pytest.mark.asyncio
async def test_tool_failure_becomes_error_message_and_answer_continues():
    choose = plan(
        {"next": "research", "task": "x", "reason": "r"}, {"next": "finish", "reason": "ok"}
    )
    graph, _ = graph_for(research_script(choose), tools=make_tools(fail={"search_evidence"}))
    state = await run(graph, "What is ReAct?")

    result = state["results"][0]
    assert result["status"] == "ok"
    assert result["tool_calls"][0]["status"] == "error"
    assert state["citations"] == []  # failed tool output is never cited


@pytest.mark.asyncio
async def test_supervisor_model_failure_uses_heuristic_routing():
    def script(provider, mode, messages):
        if mode == "structured":
            return RuntimeError("no structured output")
        return research_script(lambda: None)(provider, mode, messages)

    graph, _ = graph_for(script)
    state = await run(graph, "How many papers are in the catalog?")

    assert [r["agent"] for r in state["results"]] == ["data"]
    assert "Fallback rule" in state["trace"][0]["reason"]
    assert state["answer"] == "There are 42 papers."


@pytest.mark.asyncio
async def test_hop_limit_and_repeat_guard_end_the_turn():
    choose = plan({"next": "research", "task": "x", "reason": "again"})
    graph, _ = graph_for(research_script(choose))
    state = await run(graph, "What is ReAct?")

    assert [r["agent"] for r in state["results"]] == ["research"]
    assert state["trace"][-2]["next"] == "finish"
    assert "already answered" in state["trace"][-2]["reason"]


@pytest.mark.asyncio
async def test_data_agent_escalates_to_openai_after_sql_error():
    def script(provider, mode, messages):
        if mode == "structured":
            return choose()
        tools = [m for m in messages if m.type == "tool"]
        if not tools:
            return tool_call("query_catalog_sql", {"sql": "SELECT bad"})
        if len(tools) == 1:
            return tool_call("query_catalog_sql", {"sql": "SELECT 1"}, "call-2")
        return AIMessage(content=f"answered by {provider}")

    choose = plan({"next": "data", "task": "x", "reason": "r"}, {"next": "finish", "reason": "ok"})
    graph, _ = graph_for(script, tools=make_tools(fail={"query_catalog_sql"}))
    state = await run(graph, "How many papers?")

    rules = [(r["provider"], r["rule"]) for r in state["routing"] if r["agent"] == "data"]
    assert rules == [("gemini", "structured_lookup"), ("openai", "sql_repair")]
    assert state["answer"] == "answered by openai"


@pytest.mark.asyncio
async def test_greeting_is_answered_directly():
    choose = plan({"next": "finish", "reason": "Greeting.", "direct_answer": "Hello!"})
    graph, _ = graph_for(research_script(choose))
    state = await run(graph, "hi")
    assert state["answer"] == "Hello!" and state["results"] == []


@pytest.mark.asyncio
async def test_multi_turn_history_and_per_turn_reset():
    seen = []

    def script(provider, mode, messages):
        if mode == "structured":
            seen.append([m.content for m in messages[1:-1]])
            return {"next": "finish", "reason": "r", "direct_answer": f"turn {len(seen)}"}
        raise AssertionError

    graph, _ = graph_for(script)
    await run(graph, "first question")
    state = await run(graph, "second question")

    assert seen[1] == ["first question", "turn 1"]
    assert state["results"] == [] and len(state["trace"]) == 2
    assert [m.content for m in state["messages"]] == [
        "first question",
        "turn 1",
        "second question",
        "turn 2",
    ]


def test_each_agent_has_distinct_prompt_and_tools():
    tools = tools_by_agent([t for group in make_tools().values() for t in group])
    names = {agent: {t.name for t in group} for agent, group in tools.items()}
    assert names["research"] == {"search_evidence", "tavily_search", "tavily_extract"}
    assert names["data"] == {"describe_catalog", "query_catalog_sql", "list_documents"}
    assert len({RESEARCH_PROMPT, SUMMARY_PROMPT, DATA_PROMPT, SUPERVISOR_PROMPT}) == 4
    assert shared_tools() == {
        "list_documents": ["summary", "data"],
        "search_evidence": ["research", "summary"],
    }
    with pytest.raises(ValueError, match="missing MCP tools"):
        tools_by_agent(make_tools()["research"])


def test_heuristic_routing_rules():
    assert heuristic_choice("Summarize the RAPTOR paper", []).next == "summary"
    assert heuristic_choice("몇 편의 논문이 있어?", []).next == "data"
    assert heuristic_choice("How does Self-RAG work?", []).next == "research"
    assert heuristic_choice("hello", []).next == "finish"


def test_only_cited_sources_are_returned_in_order():
    sources = {
        "a_2022:p1:c000": {"kind": "corpus", "id": "a_2022:p1:c000"},
        "b_2023:p3:c010": {"kind": "corpus", "id": "b_2023:p3:c010"},
        "https://x.org/y": {"kind": "web", "id": "https://x.org/y"},
    }
    answer = "See [b_2023:p3:c010] and [web](https://x.org/y), plus [fake_2020:p1:c000]."
    assert [s["id"] for s in cited(answer, sources)] == ["b_2023:p3:c010", "https://x.org/y"]
    grouped = "Both [a_2022:p1:c000, b_2023:p3:c010] agree."
    assert [s["id"] for s in cited(grouped, sources)] == ["a_2022:p1:c000", "b_2023:p3:c010"]


@pytest.mark.asyncio
async def test_tool_budget_and_large_results_are_bounded():
    seen = []

    def script(provider, mode, messages):
        if mode == "structured":
            return choose()
        tools = [m for m in messages if m.type == "tool"]
        seen.append([m.content for m in tools])
        if not tools:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_evidence", "args": {"query": str(i)}, "id": f"c{i}"}
                    for i in range(4)
                ],
            )
        return AIMessage(content="done [react_2022:p2:c012]")

    choose = plan(
        {"next": "research", "task": "x", "reason": "r"}, {"next": "finish", "reason": "ok"}
    )
    make, _ = factory(script)
    config = CONFIG.model_copy(
        update={"worker_max_tool_calls": 2, "worker_max_tool_result_characters": 1000}
    )
    huge = make_tools()
    from langchain_core.tools import StructuredTool

    def big(query: str) -> str:
        return json.dumps({"passages": [PASSAGE], "padding": "x" * 5000})

    huge["research"][0] = StructuredTool.from_function(
        func=big, name="search_evidence", description="search"
    )
    huge["summary"][2] = huge["research"][0]
    from langgraph.checkpoint.memory import InMemorySaver

    graph = build_graph(huge, config=config, factory=make, checkpointer=InMemorySaver())
    state = await run(graph, "What is ReAct?")

    contents = seen[-1]
    assert len(contents) == 4
    assert all(len(c) <= 1000 + len("\n[truncated]") for c in contents[:2])
    assert (
        contents[2:] == ["Tool call budget reached. Answer with the evidence you already have."] * 2
    )
    assert [c["id"] for c in state["citations"]] == ["react_2022:p2:c012"]  # full artifact kept


@pytest.mark.asyncio
async def test_service_runs_turns_and_limits_sessions():
    choose = plan({"next": "finish", "reason": "r", "direct_answer": "hello"})
    make, _ = factory(research_script(choose))
    registry = SimpleNamespace(
        is_active=True, tools=[t for group in make_tools().values() for t in group]
    )
    config = CONFIG.model_copy(update={"agent_max_sessions": 1})
    service = MultiAgentService(registry, config=config, factory=make)

    result = await service.achat_with_trace("hi", "s1")
    assert result["response"] == "hello" and result["agents"] == []
    assert service.describe()["shared_tools"]["search_evidence"] == ["research", "summary"]
    with pytest.raises(SessionCapacityError):
        await service.achat("hi", "s2")
    with pytest.raises(ValueError):
        await service.achat(" ", "s1")
