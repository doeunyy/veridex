"""Content-free events; context is task-local and never derived from caller identifiers."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import monotonic
from uuid import uuid4

_CORRELATION = ContextVar("veridex_correlation", default=None)
_LOG = logging.getLogger("uvicorn.error.veridex")
_SERVERS = {"evidence", "workspace", "catalog", "tavily"}
_TOOLS = {
    "search_evidence",
    "list_documents",
    "read_document",
    "describe_catalog",
    "query_catalog_sql",
    "tavily_search",
    "tavily_extract",
}
_EXCEPTIONS = {
    "CancelledError",
    "TimeoutError",
    "RuntimeError",
    "ValueError",
    "TypeError",
    "MCPClientError",
    "ToolException",
    "AgentBudgetExceeded",
    "SessionCapacityError",
    "GraphRecursionError",
    "APITimeoutError",
    "APIConnectionError",
    "AuthenticationError",
    "RateLimitError",
    "BadRequestError",
    "PermissionDeniedError",
}


def correlation_id():
    return _CORRELATION.get()


def exception_class(exception):
    """Allowlisted class name only; never the message or arbitrary custom class names."""
    name = type(exception).__name__
    return name if name in _EXCEPTIONS else "Exception"


@contextmanager
def turn_context():
    token = _CORRELATION.set(uuid4().hex)
    try:
        yield
    finally:
        _CORRELATION.reset(token)


@contextmanager
def execution(component, *, server=None, tool=None):
    if component not in {"chat", "agent", "model", "mcp_tool"}:
        raise ValueError("Unknown event component")
    fields = {"component": component, "correlation_id": correlation_id()}
    if server in _SERVERS:
        fields["server"] = server
    if tool in _TOOLS:
        fields["tool"] = tool

    def emit(outcome, exception=None):
        event = {
            **fields,
            "event": f"{component}_{outcome}",
            "duration_ms": round((monotonic() - started) * 1000, 3),
        }
        if exception is not None:
            event["exception_class"] = exception_class(exception)
        _LOG.info(json.dumps(event, sort_keys=True))

    protocol_failed = False

    def fail_protocol():
        nonlocal protocol_failed
        protocol_failed = True

    started = monotonic()
    emit("started")
    try:
        yield fail_protocol
    except BaseException as exc:
        emit("failed", exc)
        raise
    else:
        if protocol_failed:
            emit("failed")
        else:
            emit("completed")


def observed(component):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            with execution(component) as fail_protocol:
                result = await function(*args, **kwargs)
                if (
                    component == "agent"
                    and isinstance(result, dict)
                    and result.get("status") == "error"
                ):
                    fail_protocol()
                return result

        return wrapped

    return decorate
