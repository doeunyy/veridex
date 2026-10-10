"""MCP boundary for the existing retrieval pipeline; tools will be added later."""

from fastmcp import FastMCP


def create_server() -> FastMCP:
    """Construct an independent server without opening Chroma or loading embeddings."""
    return FastMCP(name="Veridex Evidence")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-smoke", action="store_true")
    args = parser.parse_args()
    server = create_server()
    if args.protocol_smoke:
        from veridex.mcp.dev_tools import register_protocol_smoke_tool

        register_protocol_smoke_tool(server)
    server.run(transport="stdio")
