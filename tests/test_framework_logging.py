import asyncio
import io
import json
import logging
from types import SimpleNamespace

import pytest
import uvicorn
from uvicorn.logging import DefaultFormatter

from veridex.api.app import create_app
from veridex.framework_logging import SanitizedFrameworkErrors, uvicorn_log_config
from veridex.observability import observed

SECRET = "SECRET-sentinel sk-proj-SENTINEL"


@pytest.fixture
def emitted():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(DefaultFormatter("%(levelprefix)s %(message)s", use_colors=False))
    handler.addFilter(SanitizedFrameworkErrors())
    logger = logging.getLogger("veridex.test.framework")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield logger, stream
    logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)


@pytest.fixture
def restore_uvicorn_logging():
    names = ["uvicorn", "uvicorn.error", "uvicorn.access"]
    loggers = {name: logging.getLogger(name) for name in names}
    saved = {
        name: (log.handlers[:], log.filters[:], log.level, log.propagate)
        for name, log in loggers.items()
    }
    yield
    for name, (handlers, filters, level, propagate) in saved.items():
        log = logging.getLogger(name)
        log.handlers[:] = handlers
        log.filters[:] = filters
        log.setLevel(level)
        log.propagate = propagate


def chained_cancellation():
    try:
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            raise asyncio.CancelledError
    except asyncio.CancelledError as exc:
        return exc


def test_unfiltered_traceback_would_expose_chained_text():
    exc = chained_cancellation()
    assert SECRET in logging.Formatter().formatException((type(exc), exc, exc.__traceback__))


def test_chained_exception_is_reduced_to_class_only_event(emitted):
    logger, stream = emitted
    exc = chained_cancellation()
    logger.error("Exception in ASGI application\n", exc_info=exc)
    output = stream.getvalue()
    assert SECRET not in output and "Traceback" not in output and "RuntimeError" not in output
    assert output.startswith("ERROR:")
    assert json.loads(output.split(None, 1)[1]) == {
        "classification": "asgi_application",
        "event": "framework_error",
        "exception_class": "CancelledError",
    }


@pytest.mark.parametrize(
    "emit, classification, exception",
    [
        (lambda log, e: log.error(e), "unclassified", "Exception"),
        (lambda log, e: log.warning("Invalid HTTP request: %s", e), "unclassified", "Exception"),
        (
            lambda log, e: log.error("Exception in 'lifespan' protocol\n", exc_info=e),
            "lifespan_protocol",
            "Exception",
        ),
        (
            lambda log, e: log.error(f"Traceback (most recent call last):\n  {e!s}"),
            "traceback_text",
            None,
        ),
        (lambda log, e: log.error(f"Error loading ASGI app. {e}"), "unclassified", None),
    ],
)
def test_framework_error_variants_are_sanitized(emitted, emit, classification, exception):
    logger, stream = emitted
    secret_class = type("SECRET-class", (OSError,), {})
    emit(logger, secret_class(SECRET))
    output = stream.getvalue()
    assert "SECRET" not in output and "Traceback" not in output
    event = json.loads(output.split(None, 1)[1])
    assert event.pop("exception_class", None) == exception
    assert event == {"classification": classification, "event": "framework_error"}


def test_unformattable_exception_cannot_break_or_leak(emitted):
    logger, stream = emitted

    class Hostile(Exception):
        def __str__(self):
            raise RuntimeError(SECRET)

        def __repr__(self):
            raise RuntimeError(SECRET)

    logger.error("ASGI callable should return None, but returned '%s'.", Hostile())
    logger.error({SECRET: 1})
    output = stream.getvalue()
    assert "SECRET" not in output
    assert [json.loads(line.split(None, 1)[1])["event"] for line in output.splitlines()] == [
        "framework_error",
        "framework_error",
    ]


def test_lifecycle_warnings_safe_errors_and_events_pass_unchanged(emitted):
    logger, stream = emitted
    event = json.dumps({"component": "chat", "correlation_id": "c" * 32, "event": "chat_started"})
    logger.info("Started server process [%d]", 7)
    logger.info("Waiting for application startup.")
    logger.warning("Cancel %s running task(s), timeout graceful shutdown exceeded", 1)
    logger.error("Application startup failed. Exiting.")
    logging.getLogger("veridex.test.framework.veridex").info(event)
    assert stream.getvalue().splitlines() == [
        "INFO:     Started server process [7]",
        "INFO:     Waiting for application startup.",
        "WARNING:  Cancel 1 running task(s), timeout graceful shutdown exceeded",
        "ERROR:    Application startup failed. Exiting.",
        f"INFO:     {event}",
    ]


def test_log_config_extends_uvicorn_default_without_mutating_it():
    from uvicorn.config import LOGGING_CONFIG

    config = uvicorn_log_config()
    assert config["handlers"]["default"]["filters"] == ["sanitized_framework_errors"]
    assert "filters" not in config["handlers"]["access"]
    assert "filters" not in LOGGING_CONFIG["handlers"]["default"]
    assert config["loggers"] == LOGGING_CONFIG["loggers"]


@pytest.mark.asyncio
async def test_real_uvicorn_disconnect_and_framework_failure_are_safe(restore_uvicorn_logging):
    error_stream, access_stream = io.StringIO(), io.StringIO()
    config = uvicorn_log_config()
    config["handlers"]["default"]["stream"] = error_stream
    config["handlers"]["access"]["stream"] = access_stream
    started = asyncio.Event()
    cancelled = asyncio.Event()

    @observed("agent")
    async def achat(query, session_id):
        started.set()
        try:
            # Cancellation while handling a provider-like failure chains its message.
            try:
                raise RuntimeError(SECRET)
            except RuntimeError:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    api = create_app(agent_service=SimpleNamespace(achat=achat))

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/framework-failure":
            raise RuntimeError(SECRET)
        await api(scope, receive, send)

    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=0, lifespan="on", log_config=config, log_level="info"
        )
    )
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]

        async def request(raw, *, close_after=None):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(raw)
            await writer.drain()
            if close_after is not None:
                await close_after.wait()
                writer.close()
                await writer.wait_closed()
                return None
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response

        health = await request(b"GET /health HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        assert health.startswith(b"HTTP/1.1 200")
        body = json.dumps({"query": SECRET, "session_id": SECRET}).encode()
        await request(
            b"POST /chat HTTP/1.1\r\nHost: t\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body,
            close_after=started,
        )
        await asyncio.wait_for(cancelled.wait(), 5)
        failure = await request(
            b"GET /framework-failure HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n"
        )
        assert failure.startswith(b"HTTP/1.1 500") and SECRET.encode() not in failure
        for _ in range(100):
            if error_stream.getvalue().count("framework_error") >= 2:
                break
            await asyncio.sleep(0.02)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)

    errors, access = error_stream.getvalue(), access_stream.getvalue()
    assert "SECRET" not in errors + access and "Traceback" not in errors
    lines = errors.splitlines()
    framework = [json.loads(line.split(None, 1)[1]) for line in lines if "framework_error" in line]
    assert framework == [
        {
            "classification": "asgi_application",
            "event": "framework_error",
            "exception_class": "CancelledError",
        },
        {
            "classification": "asgi_application",
            "event": "framework_error",
            "exception_class": "RuntimeError",
        },
    ]
    events = [json.loads(line[line.find("{") :]) for line in lines if '{"component":' in line]
    assert [e["event"] for e in events] == [
        "chat_started",
        "agent_started",
        "agent_failed",
        "chat_failed",
    ]
    assert all(e["exception_class"] == "CancelledError" for e in events[2:])
    assert len({e["correlation_id"] for e in events}) == 1
    for expected in [
        "Started server process",
        "Waiting for application startup.",
        "Application startup complete.",
        "Shutting down",
        "Application shutdown complete.",
        "Finished server process",
    ]:
        assert expected in errors
    assert '"GET /health HTTP/1.1" 200' in access
