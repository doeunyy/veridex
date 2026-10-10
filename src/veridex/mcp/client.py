"""Client construction only; discovery and agent wiring remain explicit async steps."""

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection


def create_client(connections: dict[str, Connection]) -> MultiServerMCPClient:
    """Construct a client without spawning servers or making network requests.

    Callers supply adapter-native stdio or Streamable HTTP connection definitions.
    Future integration will await get_tools() and inject tools into the agent graph.
    """
    return MultiServerMCPClient(connections)
