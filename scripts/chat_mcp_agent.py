"""Run the MCP-enabled async agent while retaining all three server sessions."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from veridex.agent.mcp_service import open_mcp_agent_service


async def run(args):
    connections = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
    async with open_mcp_agent_service(connections) as service:
        queries = iter(args.query) if args.query else None
        if queries is None:
            print(f"Veridex MCP Agent — session {args.session_id}; type 'exit' to quit.")
        while True:
            try:
                query = (
                    next(queries)
                    if queries is not None
                    else await asyncio.to_thread(input, "You: ")
                )
            except (StopIteration, EOFError):
                break
            if query.strip().lower() in {"exit", "quit"}:
                break
            if not query.strip():
                continue
            try:
                trace = await service.achat_with_trace(query, args.session_id)
                print(
                    json.dumps(trace, ensure_ascii=False, indent=2)
                    if args.trace
                    else trace["response"]
                )
                if trace["status"] == "error" and queries is not None:
                    return 1
            except Exception:  # noqa: BLE001 — never print raw provider/connection exceptions
                print("Agent request failed; no verified answer was produced.", file=sys.stderr)
                if queries is not None:
                    return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default="mcp-demo")
    parser.add_argument(
        "--query", action="append", help="Run a query; repeat for a multi-turn session"
    )
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--config", type=Path, help="Adapter-native connection JSON")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001 — protect secrets in startup errors as well
        print(
            "MCP agent startup failed; check credentials and server configuration.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
