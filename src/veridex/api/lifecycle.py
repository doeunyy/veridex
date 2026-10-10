"""Same-task MCP ownership and a shared shutdown budget.

Cancellation cannot interrupt synchronous PDF/Chroma worker threads. The SDK
closes STDIO and terminates children on exit; at the deadline cancellation forces
process cleanup instead of waiting for thread completion. History repair is best
effort if a task ignores cancellation or the process is externally killed.
"""

import asyncio
from contextlib import asynccontextmanager, nullcontext

import anyio

from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.mcp.client import MCPClientError

SHUTDOWN_TIMEOUT = 8.0
DRAIN_TIMEOUT = 0.5
REPAIR_TIMEOUT = 1.5
PRODUCTION_SERVERS = {"evidence", "web_search", "workspace"}


async def drain_requests(application):
    """Cancel once, allowing AgentService to repair interrupted tool rounds."""
    tasks = set(application.state.chat_tasks)
    if not tasks:
        return
    _, pending = await asyncio.wait(tasks, timeout=DRAIN_TIMEOUT)
    for task in pending:
        task.cancel()
    if pending:
        _, pending = await asyncio.wait(pending, timeout=REPAIR_TIMEOUT)
    if pending:
        # Do not claim successful cleanup for a cancellation-resistant turn.
        raise MCPClientError("Agent requests did not stop within the shutdown budget.")


def agent_lifespan(*, injected_service=None, service_factory=None):
    factory = service_factory or open_mcp_agent_service

    @asynccontextmanager
    async def lifespan(application):
        if application.state.lifecycle_started:
            raise RuntimeError("Application lifespan has already started.")
        application.state.lifecycle_started = True
        application.state.agent_service = None
        try:
            # This scope must precede SDK scope entry, and stay in the same task.
            with anyio.CancelScope() as shutdown_scope:
                context = (
                    nullcontext(injected_service) if injected_service is not None else factory()
                )
                async with context as service:
                    if injected_service is None:
                        if set(service.registry.servers) != PRODUCTION_SERVERS:
                            raise MCPClientError(
                                "The API requires all three production MCP servers."
                            )
                        if not service.is_usable:
                            raise MCPClientError("Agent service is unavailable.")
                    application.state.agent_service = service
                    try:
                        yield
                    finally:
                        application.state.shutting_down = True
                        application.state.agent_service = None
                        shutdown_scope.deadline = anyio.current_time() + SHUTDOWN_TIMEOUT
                        await drain_requests(application)
            if shutdown_scope.cancel_called:
                raise MCPClientError("Agent shutdown exceeded its total deadline.")
        except Exception:  # noqa: BLE001 — redact startup and teardown details
            raise MCPClientError("Agent application lifecycle failed.") from None
        finally:
            application.state.agent_service = None
            application.state.shutting_down = True

    return lifespan
