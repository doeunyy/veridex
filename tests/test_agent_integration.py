import pytest

from veridex.agent.service import AgentService

pytestmark = pytest.mark.integration


def test_real_agent_selects_search_tool():
    service = AgentService()

    result = service.chat_with_trace(
        "According to the indexed ReAct paper, how does reasoning interact with actions?",
        session_id="integration-react",
    )

    assert result["response"]

    assert any(call["name"] == "search_evidence" for call in result["tool_calls"])

    assert result["tool_results"]
    assert all(not item["content_preview"].startswith("Error:") for item in result["tool_results"])
