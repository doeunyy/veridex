"""Which MCP tools each specialist may call.

Two MCP tools are deliberately shared between agents (the MCP tool-sharing
criterion): search_evidence is used by Research (to answer) and Summary (to cite
summary points), and list_documents by Summary (to pick pages) and Data (file details).
"""

import re

from langchain_core.tools import BaseTool

from veridex.agents.state import WORKERS, WorkerName

AGENT_TOOLS: dict[WorkerName, set[str]] = {
    "research": {"search_evidence", "tavily_search", "tavily_extract"},
    "summary": {"list_documents", "read_document", "search_evidence"},
    "data": {"describe_catalog", "query_catalog_sql", "list_documents"},
}
_TAVILY = re.compile(r"tavily[-_](search|extract)\Z")


def canonical_name(name: str) -> str:
    """Tavily Remote MCP has used both tavily-search and tavily_search."""
    match = _TAVILY.fullmatch(name)
    return f"tavily_{match.group(1)}" if match else name


def tools_by_agent(tools: list[BaseTool]) -> dict[WorkerName, list[BaseTool]]:
    selected = {
        agent: [tool for tool in tools if canonical_name(tool.name) in AGENT_TOOLS[agent]]
        for agent in WORKERS
    }
    for agent, chosen in selected.items():
        missing = AGENT_TOOLS[agent] - {canonical_name(tool.name) for tool in chosen}
        if missing:
            raise ValueError(f"{agent} agent is missing MCP tools: {sorted(missing)}")
    return selected


def shared_tools() -> dict[str, list[WorkerName]]:
    users: dict[str, list[WorkerName]] = {}
    for agent in WORKERS:
        for name in sorted(AGENT_TOOLS[agent]):
            users.setdefault(name, []).append(agent)
    return {name: agents for name, agents in users.items() if len(agents) > 1}
