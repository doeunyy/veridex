from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from veridex.agent.graph import build_agent_graph


@tool
def echo_evidence(query: str) -> str:
    """Return evidence for a test query."""
    return f"Evidence found: {query}"


def make_mock_model(responses):
    model = MagicMock()
    bound_model = MagicMock()

    model.bind_tools.return_value = bound_model
    bound_model.invoke.side_effect = responses

    return model, bound_model


def test_agent_responds_without_tools():
    model, bound_model = make_mock_model([AIMessage(content="Hello! I'm Veridex.")])

    graph = build_agent_graph(
        tools=[echo_evidence],
        model=model,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="Hi!")]},
        config={"configurable": {"thread_id": "no-tool-test"}},
    )

    assert result["messages"][-1].content == ("Hello! I'm Veridex.")

    assert all(message.type != "tool" for message in result["messages"])

    bound_model.invoke.assert_called_once()


def test_agent_tool_calling_loop():
    model, bound_model = make_mock_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo_evidence",
                        "args": {"query": "Self-RAG"},
                        "id": "call_001",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Self-RAG evidence was retrieved."),
        ]
    )

    graph = build_agent_graph(
        tools=[echo_evidence],
        model=model,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="Explain Self-RAG")]},
        config={"configurable": {"thread_id": "tool-loop-test"}},
    )

    assert result["messages"][-1].content == ("Self-RAG evidence was retrieved.")

    tool_messages = [message for message in result["messages"] if message.type == "tool"]

    assert len(tool_messages) == 1
    assert "Evidence found: Self-RAG" in (tool_messages[0].content)

    assert bound_model.invoke.call_count == 2


def test_agent_multiple_tool_rounds():
    model, bound_model = make_mock_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo_evidence",
                        "args": {"query": "RAG"},
                        "id": "call_rag",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo_evidence",
                        "args": {"query": "Self-RAG"},
                        "id": "call_self_rag",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Both papers were retrieved."),
        ]
    )

    graph = build_agent_graph(
        tools=[echo_evidence],
        model=model,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="Compare RAG and Self-RAG")]},
        config={
            "configurable": {"thread_id": "multi-round-test"},
            "recursion_limit": 12,
        },
    )

    tool_messages = [message for message in result["messages"] if message.type == "tool"]

    assert len(tool_messages) == 2
    assert bound_model.invoke.call_count == 3
    assert result["messages"][-1].content == ("Both papers were retrieved.")


def test_agent_handles_tool_error():
    @tool
    def failing_tool(query: str) -> str:
        """Search documents for evidence."""
        raise RuntimeError("Simulated retrieval failure")

    model, _ = make_mock_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "failing_tool",
                        "args": {"query": "Self-RAG"},
                        "id": "call_error_001",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "I couldn't retrieve evidence due to a tool error. "
                    "I cannot provide verified citations."
                )
            ),
        ]
    )

    graph = build_agent_graph(
        tools=[failing_tool],
        model=model,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="Explain Self-RAG.")]},
        config={"configurable": {"thread_id": "tool-error-test"}},
    )

    tool_messages = [msg for msg in result["messages"] if msg.type == "tool"]

    assert len(tool_messages) == 1
    assert "Simulated retrieval failure" in str(tool_messages[0].content)

    assert "couldn't retrieve evidence" in (result["messages"][-1].content)
