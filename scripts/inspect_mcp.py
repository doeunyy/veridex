"""Inspect real MCP identities and dynamically discovered adapter tools."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from veridex.mcp.client import MCPClientError, connect_servers


async def inspect(connections=None, *, timeout=45):
    async with connect_servers(connections, timeout=timeout) as registry:
        return registry.inspection()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="JSON mapping of server IDs to adapter connections"
    )
    parser.add_argument("--timeout", type=float, default=45, help="Per-request deadline in seconds")
    args = parser.parse_args()
    try:
        connections = None
        if args.config:
            connections = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(connections, dict):
                raise MCPClientError("MCP connection configuration must be a JSON object.")
        report = asyncio.run(inspect(connections, timeout=args.timeout))
    except (MCPClientError, OSError, ValueError):
        print(
            "MCP inspection failed; check server configuration and availability.", file=sys.stderr
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
