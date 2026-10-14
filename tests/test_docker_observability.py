"""Opt-in checks of sanitized events from the mounted offline TCP fixture."""

import json
import os
import subprocess

import pytest
from test_docker_e2e import client, control  # noqa: F401 — shared offline fixture

pytestmark = pytest.mark.integration


def logs():
    result = subprocess.run(
        ["docker", "logs", os.environ["VERIDEX_OBSERVABILITY_CONTAINER"]],
        capture_output=True,
        text=True,
        check=True,
    )
    text = result.stdout + result.stderr
    events = []
    for line in text.splitlines():
        start = line.find('{"component":')
        if start >= 0:
            events.append(json.loads(line[start:]))
    return text, events


def test_real_dispatch_and_sanitized_failure_logs(client):  # noqa: F811
    for query in ["evidence-web", "tool-error", "model-error"]:
        r = client.post(
            "/chat", json={"query": query, "session_id": "PRIVATE-SENTINEL-session" + query}
        )
        assert r.status_code == (500 if query == "model-error" else 200)
        if query == "model-error":
            assert r.json() == {"detail": "Agent request failed."}
    text, events = logs()
    assert "PRIVATE-SENTINEL" not in text
    assert "credential /sensitive/path" not in text
    # Framework errors, including disconnect cancellation, are class-only events.
    assert "Traceback" not in text
    assert "Exception in ASGI application" not in text
    framework = [
        json.loads(line[line.find("{") :])
        for line in text.splitlines()
        if "framework_error" in line
    ]
    assert all(
        set(e) <= {"classification", "event", "exception_class"} and e["event"] == "framework_error"
        for e in framework
    )
    assert events
    allowed = {
        "component",
        "event",
        "correlation_id",
        "duration_ms",
        "server",
        "tool",
        "exception_class",
    }
    assert all(set(e) <= allowed for e in events)
    assert any(e["event"] == "mcp_tool_failed" and e.get("tool") == "search_web" for e in events)
    assert any(
        e["event"] == "model_failed" and e.get("exception_class") == "RuntimeError" for e in events
    )
    ids = {e["correlation_id"] for e in events if e["event"] == "chat_started"}
    assert None not in ids
    for identifier in ids:
        turn = [e for e in events if e["correlation_id"] == identifier]
        assert sum(e["event"] == "chat_started" for e in turn) == 1
    assert any(
        {
            e.get("tool")
            for e in events
            if e["correlation_id"] == i and e["event"] == "mcp_tool_completed"
        }
        >= {"search_evidence", "search_web"}
        for i in ids
    )


def test_concurrent_turn_log_contexts(client):  # noqa: F811
    import concurrent.futures

    control(client, active=2)
    before = len(logs()[1])
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda i: client.post(
                        "/chat",
                        json={
                            "query": "brief-model",
                            "session_id": f"PRIVATE-SENTINEL-concurrent-{i}",
                        },
                    ),
                    range(2),
                )
            )
        assert all(r.status_code == 200 for r in responses)
    finally:
        control(client, active=1)
    emitted = logs()[1][before:]
    starts = [e for e in emitted if e["event"] == "chat_started"]
    ids = {e["correlation_id"] for e in starts}
    assert len(ids) == 2
    for i in ids:
        assert [e["event"] for e in emitted if e["correlation_id"] == i] == [
            "chat_started",
            "agent_started",
            "model_started",
            "model_completed",
            "agent_completed",
            "chat_completed",
        ]
