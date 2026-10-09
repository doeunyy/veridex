from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from veridex.agent.prompts import AGENT_SYSTEM_PROMPT
from veridex.agent.state import AgentState
from veridex.agent.tools import search_evidence
from veridex.config import settings


def build_agent_graph(
    tools=None,
    model=None,
    checkpointer=None,
):
    """Build a stateful LangGraph tool-calling agent."""
    if tools is None:
        tools = [search_evidence]

    if model is None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

        model = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )

    bound_model = model.bind_tools(tools)

    def agent_node(state: AgentState):
        messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            *state["messages"],
        ]

        response = bound_model.invoke(messages)

        return {"messages": [response]}

    builder = StateGraph(AgentState)

    builder.add_node("agent", agent_node)
    builder.add_node(
        "tools",
        ToolNode(tools, handle_tool_errors=True),
    )

    builder.add_edge(START, "agent")

    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": END},
    )

    builder.add_edge("tools", "agent")

    if checkpointer is None:
        checkpointer = InMemorySaver()

    return builder.compile(checkpointer=checkpointer)
