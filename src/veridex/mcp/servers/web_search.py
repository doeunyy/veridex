"""MCP boundary for Tavily search; tools will be added later."""

from fastmcp import FastMCP


def create_server() -> FastMCP:
    """Construct an independent server without creating a Tavily client."""
    return FastMCP(name="Veridex Web Search")


if __name__ == "__main__":
    create_server().run(transport="stdio")
