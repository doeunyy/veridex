"""MCP boundary for restricted read-only documents; tools will be added later."""

from fastmcp import FastMCP


def create_server() -> FastMCP:
    """Construct an independent server without reading or exposing filesystem paths."""
    return FastMCP(name="Veridex Workspace")


if __name__ == "__main__":
    create_server().run(transport="stdio")
