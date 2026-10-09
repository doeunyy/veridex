from langchain_core.messages import HumanMessage

from veridex.agent.graph import build_agent_graph


class AgentService:
    """Session-based interface for the Veridex agent."""

    def __init__(self, graph=None):
        self.graph = graph if graph is not None else build_agent_graph()

    def chat(self, query: str, session_id: str) -> str:
        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if not session_id.strip():
            raise ValueError("Session ID cannot be empty.")

        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 12,
        }

        result = self.graph.invoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )

        final_message = result["messages"][-1]

        if not isinstance(final_message.content, str):
            raise TypeError("Expected a text-only agent response.")

        return final_message.content

    def get_history(self, session_id: str):
        config = {
            "configurable": {"thread_id": session_id}
        }

        snapshot = self.graph.get_state(config)

        return snapshot.values.get("messages", [])
