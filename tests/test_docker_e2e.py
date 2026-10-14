"""Explicit opt-in TCP checks against the mounted offline Docker fixture only."""

import concurrent.futures
import json
import os
import socket
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration
URL = "http://127.0.0.1:18846"
MEASUREMENTS = {"http": []}


@pytest.fixture(scope="module")
def client():
    if os.environ.get("VERIDEX_RUN_DOCKER_E2E") != "1":
        pytest.skip("Requires explicitly started offline local Docker fixture")
    with httpx.Client(base_url=URL, timeout=90, trust_env=False) as value:
        for _ in range(180):
            try:
                if value.get("/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("Offline container did not become ready")
        status = value.get("/__verification").json()
        assert status["offline"] is True
        assert status["servers"] == ["evidence", "web_search", "workspace"]
        assert sorted(status["tools"]) == [
            "list_documents",
            "read_document",
            "search_evidence",
            "search_web",
        ]
        MEASUREMENTS["initial_pids"] = status["children"]
        assert len(status["children"]) == 3
        assert status["index_separate"]
        yield value
        MEASUREMENTS["final"] = value.get("/__verification").json()
        root = Path(".artifacts/e2e-host")
        root.mkdir(parents=True, exist_ok=True)
        (root / "idle.json").write_text(json.dumps(MEASUREMENTS, sort_keys=True, indent=2) + "\n")


def chat(client, query, session):
    started = time.monotonic()
    response = client.post("/chat", json={"query": query, "session_id": session})
    MEASUREMENTS["http"].append(
        {
            "query": query,
            "session": session,
            "status": response.status_code,
            "body": response.json(),
            "seconds": round(time.monotonic() - started, 4),
        }
    )
    return response


def wait(client, predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = client.get("/__verification").json()
        if predicate(status):
            return status
        time.sleep(0.03)
    raise AssertionError("Fixture condition did not complete")


def control(client, **values):
    assert client.post("/__verification/control", json=values).status_code == 200


def test_health_ready_and_schema(client):
    limits = client.get("/__verification").json()["limits"]
    assert (limits["api_max_active_requests"], limits["api_max_waiting_requests"]) == (1, 0)
    assert (limits["agent_max_tool_calls"], limits["agent_max_model_calls"]) == (8, 6)
    assert limits["agent_max_completion_tokens"] == 4096
    assert (limits["provider_timeout_seconds"], limits["provider_max_retries"]) == (30, 0)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    response = chat(client, "greeting", "greeting")
    assert response.status_code == 200
    assert response.json() == {"response": "Hello offline."}


@pytest.mark.parametrize(
    "query,names",
    [
        ("evidence", ["search_evidence"]),
        ("web", ["search_web"]),
        ("workspace", ["list_documents"]),
        ("read", ["list_documents", "read_document"]),
        ("evidence-web", ["search_evidence", "search_web"]),
        ("workspace-evidence", ["list_documents", "search_evidence"]),
        ("insufficient", ["search_evidence"]),
        ("tool-error", ["search_web"]),
        ("pdf-error", ["read_document"]),
    ],
)
def test_real_mcp_traces(client, query, names):
    response = chat(client, query, query)
    assert response.status_code == 200 and set(response.json()) == {"response"}
    trace = client.get("/__verification").json()["traces"][-1]
    assert [c["name"] for c in trace["calls"]] == names
    assert [r["name"] for r in trace["results"]] == names
    assert all(r["completed"] for r in trace["results"])
    if query in {"tool-error", "pdf-error"}:
        assert trace["results"][-1]["status"] == "error"
        assert response.json() == {"response": "Controlled tool error; no verified evidence."}
    else:
        assert all(r["status"] == "success" for r in trace["results"])
    evidence = [r for r in trace["results"] if r["name"] == "search_evidence"]
    if evidence and query != "insufficient":
        first = evidence[0]["passages"][0]
        assert first["chunk_id"] == "rag_long_context_2024_p1_c00000"
        assert first["paper_id"] == "rag_long_context_2024" and first["page"] == 1
        assert abs(first["distance"]) < 1e-6
    if query == "insufficient":
        assert evidence[0]["passages"] == []
        assert response.json() == {"response": "Insufficient evidence; no verified answer."}
    for result in trace["results"]:
        if result["name"] == "search_web" and result["status"] == "success":
            assert result["urls"] == ["https://offline.example.test/rag"]
        if result["name"] == "list_documents":
            assert (
                len(result["documents"]) == 5 and "rag_long_context_2024.pdf" in result["documents"]
            )
        if result["name"] == "read_document" and result["status"] == "success":
            assert result["paper_id"] == "rag_long_context_2024" and result["pages"] == [3]
            assert result["page_characters"] == [1000]


def test_error_recovery_and_memory_isolation(client):
    assert chat(client, "web", "tool-error").status_code == 200
    trace = client.get("/__verification").json()["traces"][-1]
    assert trace["results"][0]["status"] == "success"
    assert chat(client, "remember-alpha", "memory-a").status_code == 200
    assert chat(client, "recall", "memory-a").json() == {"response": 'History: ["remember-alpha"]'}
    assert chat(client, "recall", "memory-b").json() == {"response": "History: []"}
    status = client.get("/__verification").json()
    assert status["children"] == MEASUREMENTS["initial_pids"]
    assert all(v["balanced"] for v in status["sessions"].values())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": "x"},
        {"query": 1, "session_id": "s"},
        {"query": "x", "session_id": 1},
        {"query": " ", "session_id": "s"},
        {"query": "x", "session_id": " "},
        {"query": "x" * 10001, "session_id": "s"},
        {"query": "x", "session_id": "s" * 129},
        {"query": "x", "session_id": "s", "secret": "PRIVATE-SENTINEL"},
    ],
)
def test_strict_validation(client, body):
    response = client.post("/chat", json=body)
    assert response.status_code == 422 and response.json() == {"detail": "Invalid request."}
    assert "PRIVATE-SENTINEL" not in response.text


def test_malformed_json_and_oversized_bodies(client):
    response = client.post("/chat", content="{", headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and response.json() == {"detail": "Invalid request."}
    for data in [b"x" * 65537, iter([b"x" * 40000, b"x" * 30000])]:
        response = client.post("/chat", content=data)
        assert response.status_code == 413 and response.json() == {
            "detail": "Request body is too large."
        }


def test_unavailable_and_safe_internal_failure(client):
    response = chat(client, "model-error", "failure")
    assert response.status_code == 500 and response.json() == {"detail": "Agent request failed."}
    control(client, unavailable=True)
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        response = chat(client, "greeting", "unavailable")
        assert response.status_code == 503 and response.json() == {
            "detail": "Agent service is unavailable."
        }
    finally:
        control(client, unavailable=False)


def test_overload_queue_and_deadline(client):
    control(client, active=1, waiting=1, timeout=4, queue=1)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(chat, client, "slow-model", "load-active")
            wait(client, lambda s: s["active"] == 1)
            second = pool.submit(chat, client, "slow-model", "load-queued")
            wait(client, lambda s: s["waiting"] == 1)
            response = chat(client, "greeting", "load-rejected")
            assert response.status_code == 429 and response.json() == {
                "detail": "Too many requests."
            }
            assert response.headers["retry-after"] == "1"
            assert (
                client.get("/health").status_code == 200 and client.get("/ready").status_code == 200
            )
            assert second.result().json() == {"detail": "Request queue wait timed out."}
            assert first.result().json() == {"detail": "Request deadline exceeded."}
        wait(client, lambda s: s["active"] == s["waiting"] == 0)
    finally:
        control(client, active=4, waiting=8, timeout=60, queue=30)


def test_total_deadline_includes_queue(client):
    control(client, active=1, waiting=1, timeout=2, queue=30)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(chat, client, "slow-model", "total-active")
            wait(client, lambda s: s["active"] == 1)
            started = time.monotonic()
            second = pool.submit(chat, client, "slow-model", "total-queued")
            assert first.result().status_code == 504
            assert second.result().json() == {"detail": "Request deadline exceeded."}
            assert time.monotonic() - started < 3.5
        wait(client, lambda s: s["active"] == s["waiting"] == 0)
    finally:
        control(client, active=4, waiting=8, timeout=60, queue=30)


def test_tool_deadline_repairs_history(client):
    control(client, timeout=3)
    try:
        response = chat(client, "slow-tool", "tool-timeout")
        assert response.status_code == 504 and response.json() == {
            "detail": "Request deadline exceeded."
        }
        status = wait(client, lambda s: "tool-timeout" in s["sessions"])
        assert status["sessions"]["tool-timeout"]["balanced"]
        assert status["sessions"]["tool-timeout"]["interrupted"] == 1
        assert chat(client, "greeting", "tool-timeout").status_code == 200
    finally:
        control(client, timeout=60)


def test_tcp_disconnect_cancels_and_repairs(client):
    control(client, timeout=15)
    body = json.dumps({"query": "slow-tool", "session_id": "disconnect"}).encode()
    previous = len(client.get("/__verification").json()["provider_events"])
    with socket.create_connection(("127.0.0.1", 18846), timeout=5) as connection:
        connection.sendall(
            b"POST /chat HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        wait(
            client,
            lambda s: any(
                e["kind"] == "web-start" and e.get("query") == "web-slow"
                for e in s["provider_events"][previous:]
            ),
        )
    try:
        status = wait(
            client, lambda s: "cancelled:disconnect" in s["events"] and s["active"] == 0, timeout=2
        )
        assert status["sessions"]["disconnect"]["balanced"]
        assert status["sessions"]["disconnect"]["interrupted"] == 1
        assert chat(client, "greeting", "disconnect").status_code == 200
    finally:
        control(client, timeout=3)
        wait(client, lambda s: s["active"] == 0, timeout=18)
        control(client, timeout=60)


def test_session_serialization_and_cross_session_concurrency(client):
    before = client.get("/__verification").json()["events"].count("brief-model-entered")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(chat, client, "brief-model", "serial")
        wait(client, lambda s: s["events"].count("brief-model-entered") > before)
        second = pool.submit(chat, client, "recall", "serial")
        started = time.monotonic()
        other = pool.submit(chat, client, "greeting", "parallel")
        assert other.result().json() == {"response": "Hello offline."}
        assert time.monotonic() - started < 0.9
        assert not first.done()
        assert first.result().status_code == 200
        assert second.result().json() == {"response": 'History: ["brief-model"]'}
    assert client.get("/__verification").json()["children"] == MEASUREMENTS["initial_pids"]


def test_invalid_tcp_header_is_safe(client):
    with socket.create_connection(("127.0.0.1", 18846), timeout=5) as connection:
        connection.sendall(
            b"POST /chat HTTP/1.1\r\nHost: localhost\r\nContent-Length: PRIVATE-SENTINEL\r\n\r\n"
        )
        response = connection.recv(4096)
    assert b"400 Bad Request" in response
    assert b"PRIVATE-SENTINEL" not in response


def test_tool_and_model_budgets_inside_container(client):
    assert chat(client, "tool-budget", "tool-budget").status_code == 200
    trace = client.get("/__verification").json()["traces"][-1]
    assert trace["error"] == "tool_call_limit"
    assert len(trace["calls"]) == 9
    assert all(not result["completed"] for result in trace["results"])
    assert "No final answer is verified" in trace["response"]
    assert client.get("/__verification").json()["sessions"]["tool-budget"]["balanced"]
    control(client, models=2)
    try:
        assert chat(client, "model-budget", "model-budget").status_code == 200
        trace = client.get("/__verification").json()["traces"][-1]
        assert trace["error"] == "model_call_limit"
        assert sum(result["completed"] for result in trace["results"]) == 2
    finally:
        control(client, models=6)
    assert chat(client, "greeting", "tool-budget").json() == {"response": "Hello offline."}


def test_default_concurrency_rejects_waiting_work(client):
    control(client, active=1, waiting=0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(chat, client, "brief-model", "default-capacity")
        wait(client, lambda s: s["active"] == 1)
        response = chat(client, "greeting", "default-rejected")
        assert response.status_code == 429 and response.json() == {"detail": "Too many requests."}
        assert first.result().status_code == 200


def test_completed_turn_retention_and_checkpoint_compaction(client):
    for i in range(7):
        assert chat(client, f"retain-{i}", "retention").status_code == 200
    state = client.get("/__verification").json()
    assert state["sessions"]["retention"]["humans"] == [f"retain-{i}" for i in range(1, 7)]
    assert state["checkpoint_counts"]["retention"] == 1
    assert chat(client, "recall", "retention").json() == {
        "response": "History: " + json.dumps([f"retain-{i}" for i in range(1, 7)])
    }


def test_session_capacity_and_idle_expiry(client):
    retained = client.get("/__verification").json()["retained_sessions"]
    control(client, sessions=len(retained))
    try:
        response = chat(client, "greeting", "no-session-slot")
        assert response.status_code == 429
        assert response.json() == {"detail": "Session capacity exhausted."}
        assert client.get("/__verification").json()["retained_sessions"] == retained
        control(client, advance_ttl=1801)
        assert chat(client, "greeting", "after-expiry").status_code == 200
        state = client.get("/__verification").json()
        assert state["retained_sessions"] == ["after-expiry"]
        assert state["checkpoint_counts"] == {"after-expiry": 1}
    finally:
        control(client, sessions=128)


def test_v2_notice_delivery_and_citation_metadata(client):
    notice = client.get("/attribution")
    assert notice.status_code == 200
    data = notice.json()
    assert data["corpus_version"] == "veridex-corpus-v2"
    assert {d["id"] for d in data["documents"]} == {
        "rag_long_context_2024",
        "react_2022",
        "self_rag_2023",
        "netmhcpan_2020",
        "mixmhc2pred_2023",
    }
    acl = next(d for d in data["documents"] if d["id"] == "rag_long_context_2024")
    assert acl["authors"] == [
        "Zhuowan Li",
        "Cheng Li",
        "Mingyang Zhang",
        "Qiaozhu Mei",
        "Michael Bendersky",
    ]
    assert acl["license_id"] == "CC-BY-4.0"
    assert acl["sha256"] == "90407fd3c2bcf11d52868f0aaee3d39d6a9919351c89636555a641950531a070"
    assert any("noncommercial" in value for value in data["limitations"])
    assert client.post("/attribution", json={}).status_code == 405
    response = chat(client, "evidence", "v2-citation")
    assert set(response.json()) == {"response"}
    assert response.headers["link"] == '</attribution>; rel="describedby"'
    passage = client.get("/__verification").json()["traces"][-1]["results"][0]["passages"][0]
    assert passage["paper_id"] == acl["id"]
    assert passage["title"] == acl["title"]
    assert passage["source_url"] == acl["source_url"]
