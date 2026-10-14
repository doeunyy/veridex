"""Opt-in development tools for protocol checks, outside production factories."""

import sys
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def register_protocol_smoke_tool(server: FastMCP) -> None:
    """Register a deterministic echo tool only when explicitly requested."""

    @server.tool
    def protocol_echo(text: Annotated[str, Field(strict=True, min_length=1)]) -> str:
        """Echo a nonempty string to verify MCP argument and result transport."""
        print("Veridex protocol smoke: echo invoked", file=sys.stderr, flush=True)
        return f"echo: {text}"
