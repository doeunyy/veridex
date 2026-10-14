"""Offline Linux artifact audit and optional real STDIO/FastAPI smoke; no paid calls."""

import argparse
import asyncio
import json
import os
import platform
import sys
import time
from pathlib import Path


def mcp_pids():
    result = set()
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if b"veridex.mcp.servers." in path.read_bytes():
                result.add(int(path.parent.name))
        except (FileNotFoundError, PermissionError):
            pass
    return result


async def smoke():
    import httpx
    from langchain_core.messages import AIMessage

    from veridex.agent.mcp_service import open_mcp_agent_service
    from veridex.api.app import create_app
    from veridex.deployment.runtime import BUNDLE, prepare
    from veridex.mcp.client import default_connections

    index = prepare()
    os.environ["CHROMA_PERSIST_DIR"] = str(index)
    # Settings were imported above; supply explicit validated paths to production connections.
    from veridex.config import Settings

    config = Settings(
        _env_file=None,
        chroma_persist_dir=index,
        documents_dir=BUNDLE / "papers",
        workspace_manifest_path=BUNDLE / "manifest.json",
    )
    connections = default_connections(config=config)
    if any(c["command"] != sys.executable or c["cwd"] != "/app" for c in connections.values()):
        raise RuntimeError("Invalid container STDIO paths")

    class OfflineModel:
        def bind_tools(self, tools):
            if len(tools) != 4:
                raise RuntimeError("Tool discovery mismatch")
            return self

        async def ainvoke(self, messages):
            if messages[-1].type == "human":
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "list_documents",
                            "args": {},
                            "id": "offline-list",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="Offline corpus available.")

    application = create_app(
        service_factory=lambda: open_mcp_agent_service(connections, model=OfflineModel())
    )
    transport = httpx.ASGITransport(app=application)
    started = time.monotonic()
    async with httpx.AsyncClient(transport=transport, base_url="http://offline") as client:
        if (await client.get("/ready")).status_code != 503:
            raise RuntimeError("Premature readiness")
        async with application.router.lifespan_context(application):
            startup_seconds = time.monotonic() - started
            children = mcp_pids()
            if len(children) != 3:
                raise RuntimeError("Expected three persistent STDIO children")
            for endpoint in ["/health", "/ready"]:
                if (await client.get(endpoint)).status_code != 200:
                    raise RuntimeError("Health/readiness failed")
            response = await client.post(
                "/chat", json={"query": "List corpus", "session_id": "offline"}
            )
            if response.json() != {"response": "Offline corpus available."}:
                raise RuntimeError("Chat contract failed")
        if (await client.get("/ready")).status_code != 503 or mcp_pids():
            raise RuntimeError("Readiness withdrawal or child cleanup failed")
    return {
        "mcp_servers": 3,
        "discovered_tools": 4,
        "http_smoke": "passed",
        "children_cleaned_up": True,
        "startup_seconds": round(startup_seconds, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    try:
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise RuntimeError("Expected Linux/amd64")
        from veridex.deployment.runtime import BUNDLE_SHA256, audit

        report = {
            "platform": platform.platform(),
            "uid": os.getuid(),
            **audit(checksum=os.environ.get("RAG_BUNDLE_SHA256", BUNDLE_SHA256)),
        }
        if args.smoke:
            report.update(asyncio.run(smoke()))
        print(json.dumps(report, sort_keys=True))
    except Exception:  # noqa: BLE001 — native/provider errors must not leak source contents
        print(
            "Container verification failed: check Linux wheels/shared libraries, SQLite >=3.44, bundle integrity and MCP lifecycle.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
