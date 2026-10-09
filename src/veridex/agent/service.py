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
    
    def chat_with_trace(self, query: str, session_id: str) -> dict:
        """Run an agent turn and return the final answer with tool calls."""
        if not query.strip() or not session_id.strip():
            raise ValueError("Query and session_id are required.")

        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 12,
        }

        previous = self.graph.get_state(config)
        previous_ids = {
            msg.id
            for msg in previous.values.get("messages", [])
            if msg.id is not None
        }

        result = self.graph.invoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )

        new_messages = [
            msg
            for msg in result["messages"]
            if msg.id not in previous_ids
        ]

        tool_calls = []
        tool_results = []

        for msg in new_messages:
            if msg.type == "ai":
                for call in getattr(msg, "tool_calls", []) or []:
                    tool_calls.append(
                        {
                            "name": call["name"],
                            "args": call["args"],
                        }
                    )

            elif msg.type == "tool":
                tool_results.append(
                    {
                        "name": msg.name,
                        "tool_call_id": msg.tool_call_id,
                        "content_preview": str(msg.content)[:300],
                    }
                )

        return {
            "response": result["messages"][-1].content,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
        }

