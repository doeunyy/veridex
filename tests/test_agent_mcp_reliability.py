import asyncio
import json
import os
import signal

import pytest
from langchain_core.messages import AIMessage
from test_agent_mcp import ScriptedModel, call, request
from test_mcp_multi_server import SOURCE_URL, is_alive, process_ids
from test_mcp_multi_server import (
    connections as connections,  # noqa: PLC0414 — re-export pytest fixture
)

from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.mcp.client import MCPClientError


@pytest.fixture
def observed_connections(connections, tmp_path):
    """Observe test providers while running the unchanged production server entry points."""
    configs, pid_log, _ = connections
    bootstrap = configs["evidence"]["args"][0]
    control = tmp_path / "control"
    control.mkdir()
    observer = tmp_path / "observer.py"
    observer.write_text("""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys
from threading import Lock
import time

role = sys.argv[1]
control = Path(os.environ["TEST_CONTROL_DIR"])
real_run_module = runpy.run_module
lock = Lock()
active = 0

def event(phase, query):
    global active
    with lock:
        active += 1 if phase == "start" else -1
        record = {"phase": phase, "query": query, "active": active, "pid": os.getpid()}
        with (control / f"{role}.jsonl").open("a") as log:
            log.write(json.dumps(record) + "\\n")
    if phase == "start":
        (control / f"{role}.{query}.started").touch()

async def wait_async(path):
    async with asyncio.timeout(5):
        while not path.exists():
            await asyncio.sleep(0.005)

def wait_sync(path):
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Controlled provider deadline")
        time.sleep(0.005)

def run_server(module, **kwargs):
    if role == "evidence":
        from veridex.rag import retrieval
        original = retrieval.search_documents
        def retrieve(query, **arguments):
            event("start", query)
            try:
                if query == "parallel":
                    wait_sync(control / "web_search.parallel.started")
                elif query == "slow":
                    wait_sync(control / "release")
                elif query.startswith("serial"):
                    time.sleep(0.05)
                return original(query=query, **arguments)
            finally:
                event("end", query)
        retrieval.search_documents = retrieve
    elif role == "web_search":
        import tavily
        original = tavily.AsyncTavilyClient
        class ObservedTavily(original):
            async def search(self, query, **arguments):
                event("start", query)
                try:
                    if query == "parallel":
                        await wait_async(control / "evidence.parallel.started")
                    return await super().search(query=query, **arguments)
                finally:
                    event("end", query)
        tavily.AsyncTavilyClient = ObservedTavily
    return real_run_module(module, **kwargs)

runpy.run_module = run_server
runpy.run_path(os.environ["TEST_PROVIDER_BOOTSTRAP"], run_name="__main__")
""")
    for role, config in configs.items():
        config["args"] = [str(observer), role]
        config["env"]["TEST_PROVIDER_BOOTSTRAP"] = bootstrap
        config["env"]["TEST_CONTROL_DIR"] = str(control)
    return configs, pid_log, control


async def wait_for_file(path):
    async with asyncio.timeout(10):
        while not path.exists():
            await asyncio.sleep(0.01)


def events(control, role):
    path = control / f"{role}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def assert_balanced_history(messages):
    calls = {
        item["id"] for message in messages if message.type == "ai" for item in message.tool_calls
    }
    replies = {message.tool_call_id for message in messages if message.type == "tool"}
    assert calls == replies


@pytest.mark.asyncio
async def test_backend_observed_cross_server_concurrency_and_same_server_serialization(
    observed_connections,
):
    configs, pid_log, control = observed_connections
    model = ScriptedModel(
        [
            request(
                call("search_evidence", {"query": "parallel"}),
                call("search_web", {"query": "parallel"}),
            ),
            AIMessage(content="Both sources returned."),
            request(
                *[
                    call("search_evidence", {"query": f"serial-{i}"}, call_id=f"serial-{i}")
                    for i in range(3)
                ]
            ),
            AIMessage(content="All three searches returned."),
        ]
    )
    async with open_mcp_agent_service(configs, model=model, request_timeout=15) as service:
        pids = process_ids(pid_log)
        parallel = await service.achat_with_trace("Compare sources", "parallel")
        assert parallel["server_call_counts"] == {"evidence": 1, "web_search": 1}
        assert all(item["status"] == "success" for item in parallel["tool_results"])
        # Each backend waited for the other to enter; success proves actual RPC overlap.
        assert (control / "evidence.parallel.started").exists()
        assert (control / "web_search.parallel.started").exists()
        serial = await service.achat_with_trace("Three independent indexed searches", "serial")
        assert serial["call_counts"] == {"search_evidence": 3}
        assert all(item["status"] == "success" for item in serial["tool_results"])
        starts = [item for item in events(control, "evidence") if item["phase"] == "start"]
        assert sorted(item["query"] for item in starts if item["query"].startswith("serial")) == [
            "serial-0",
            "serial-1",
            "serial-2",
        ]
        assert all(item["active"] == 1 for item in starts)
        for item in serial["tool_results"]:
            assert item["structured_content"]["passages"][0]["source_url"] == SOURCE_URL
            assert item["server_identity"] == "Veridex Evidence"
        assert process_ids(pid_log) == pids
    assert all(not is_alive(pid) for pid in pids)


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["recursion", "cancel"])
async def test_interrupted_round_followup_over_real_stdio(observed_connections, interruption):
    configs, pid_log, control = observed_connections
    if interruption == "recursion":
        model = ScriptedModel(
            [
                request(call("list_documents", call_id="first")),
                request(call("search_evidence", {"query": "never-executed"}, call_id="unexecuted")),
                request(call("list_documents", call_id="followup")),
                AIMessage(content="Corpus available after interruption."),
            ]
        )
    else:
        model = ScriptedModel(
            [
                request(call("search_evidence", {"query": "slow"}, call_id="cancelled")),
                request(call("list_documents", call_id="followup")),
                AIMessage(content="Corpus available after cancellation."),
            ]
        )
    async with open_mcp_agent_service(
        configs,
        model=model,
        recursion_limit=3 if interruption == "recursion" else 12,
        request_timeout=15,
    ) as service:
        pids = process_ids(pid_log)
        if interruption == "recursion":
            trace = await service.achat_with_trace("Reach execution limit", "recovery")
            assert trace["error"] == "recursion_limit"
            marker = next(
                item for item in trace["tool_results"] if item["tool_call_id"] == "unexecuted"
            )
            assert marker["status"] == "error" and not marker["invocation_completed"]
            assert marker["artifact"] is None
            assert trace["call_counts"] == {"list_documents": 1}
            assert events(control, "evidence") == []
        else:
            turn = asyncio.create_task(service.achat("Start slow retrieval", "recovery"))
            await wait_for_file(control / "evidence.slow.started")
            turn.cancel()
            try:
                with pytest.raises(asyncio.CancelledError):
                    await turn
            finally:
                (control / "release").touch()
            # The synchronous test provider can finish after cancellation; its reply is not evidence.
            async with asyncio.timeout(10):
                while not any(item["phase"] == "end" for item in events(control, "evidence")):
                    await asyncio.sleep(0.01)
        history = await service.aget_history("recovery")
        assert_balanced_history(history)
        markers = [
            message
            for message in history
            if message.type == "tool" and message.additional_kwargs.get("execution_interrupted")
        ]
        assert len(markers) == 1 and markers[0].status == "error" and markers[0].artifact is None
        # Restore the normal budget after the deliberately premature recursion cutoff.
        service.recursion_limit = 12
        followup = await service.achat_with_trace(
            "What local papers are available now?", "recovery"
        )
        assert followup["status"] == "success"
        assert followup["call_counts"] == {"list_documents": 1}
        assert followup["tool_results"][0]["server_identity"] == "Veridex Workspace"
        assert all(item["status"] == "success" for item in followup["tool_results"])
        assert_balanced_history(model.messages[-1])
        assert process_ids(pid_log) == pids
    assert all(not is_alive(pid) for pid in pids)
    with pytest.raises(MCPClientError, match="closed"):
        await service.achat("Hi", "recovery")


@pytest.mark.asyncio
async def test_unexpected_child_exit_is_error_and_other_servers_remain_usable(connections):
    configs, pid_log, _ = connections
    model = ScriptedModel(
        [
            request(call("search_evidence", {"query": "Self-RAG"})),
            AIMessage(content="Evidence server failed; no verified source was returned."),
            request(call("list_documents", call_id="healthy-server")),
            AIMessage(content="The workspace is available."),
        ]
    )
    async with open_mcp_agent_service(configs, model=model, request_timeout=15) as service:
        records = dict(line.split() for line in pid_log.read_text().splitlines())
        evidence_pid = int(records["evidence"])
        os.kill(evidence_pid, signal.SIGTERM)
        async with asyncio.timeout(10):
            while is_alive(evidence_pid):
                await asyncio.sleep(0.01)
        failed = await service.achat_with_trace("Explain Self-RAG", "failed-server")
        assert failed["tool_results"][0]["status"] == "error"
        assert failed["tool_results"][0]["artifact"] is None
        assert failed["tool_results"][0]["server_identity"] == "Veridex Evidence"
        healthy = await service.achat_with_trace("List local papers", "healthy-server")
        assert healthy["tool_results"][0]["status"] == "success"
        assert healthy["server_call_counts"] == {"workspace": 1}
        assert len(process_ids(pid_log)) == 3  # No silent respawn of the failed child.
    assert all(not is_alive(pid) for pid in process_ids(pid_log))
