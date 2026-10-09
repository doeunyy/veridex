from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from veridex.agent.graph import build_agent_graph
from veridex.agent.service import AgentService


@tool
def unused_tool(query: str) -> str:
    """Return placeholder test data."""
    return query


def test_session_memory_and_isolation():
    model = MagicMock()
    bound_model = MagicMock()

    model.bind_tools.return_value = bound_model
    bound_model.invoke.side_effect = [
        AIMessage(content="First answer."),
        AIMessage(content="Second answer."),
        AIMessage(content="Other session answer."),
    ]

    graph = build_agent_graph(
        tools=[unused_tool],
        model=model,
    )

    service = AgentService(graph=graph)

    service.chat(
        "Explain Self-RAG.",
        session_id="session-a",
    )

    service.chat(
        "What are its benefits?",
        session_id="session-a",
    )

    service.chat(
        "Hello.",
        session_id="session-b",
    )

    history_a = service.get_history("session-a")
    history_b = service.get_history("session-b")

    assert len(history_a) == 4
    assert len(history_b) == 2

    assert history_a[0].content == "Explain Self-RAG."
    assert history_a[2].content == "What are its benefits?"
    assert history_b[0].content == "Hello."

    # The second invocation should receive prior session context.
    second_call_messages = bound_model.invoke.call_args_list[1].args[0]

    assert any(message.content == "Explain Self-RAG." for message in second_call_messages)

    assert any(message.content == "First answer." for message in second_call_messages)
