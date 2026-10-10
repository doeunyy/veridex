import asyncio
import json
import sys

import pytest
from langchain_core.messages import AIMessage
from test_agent_mcp import SCENARIOS, ScriptedModel, call, request
from test_mcp_multi_server import SOURCE_URL, is_alive, process_ids
from test_mcp_multi_server import (
    connections as connections,  # noqa: PLC0414 — re-export pytest fixture
)
from test_mcp_protocol import ROOT

from veridex.agent.mcp_service import open_mcp_agent_service


@pytest.mark.asyncio
async def test_all_scenarios_with_real_servers_and_mock_model(connections):
    configs, pid_log, _ = connections
    responses = [response for query, turns, names in SCENARIOS.values() for response in turns]
    responses.extend(
        [
            request(call("search_web", {"query": "recovery"}, call_id="web-recovery")),
            AIMessage(content="The web search recovered and returned a source."),
            request(call("search_evidence", {"query": "Self-RAG"})),
            AIMessage(content="Self-RAG uses retrieval and critique."),
            AIMessage(content="Its benefits include evidence grounding."),
            AIMessage(content="Hello, new session!"),
        ]
    )
    model = ScriptedModel(responses)
    traces = {}
    async with open_mcp_agent_service(configs, model=model, request_timeout=15) as service:
        initial_pids = process_ids(pid_log)
        assert len(initial_pids) == 3 and all(is_alive(pid) for pid in initial_pids)
        assert all(tool.response_format == "content_and_artifact" for tool in model.tools)
        for scenario, (query, turns, names) in SCENARIOS.items():
            trace = await service.achat_with_trace(query, scenario)
            traces[scenario] = trace
            assert [item["name"] for item in trace["tool_calls"]] == names
            assert sum(trace["call_counts"].values()) == len(names)
            for result in trace["tool_results"]:
                assert result["server_identity"].startswith("Veridex ")
                if scenario == "tool-failure":
                    assert result["status"] == "error"
                    assert result["structured_content"] is None
                    assert result["artifact"] is None
                else:
                    assert result["status"] == "success"
                    assert result["artifact"]["structured_content"] == result["structured_content"]
            assert process_ids(pid_log) == initial_pids
        passage = traces["evidence"]["tool_results"][0]["structured_content"]["passages"][0]
        assert passage["document_id"] == "paper" and passage["page"] == 1
        assert passage["source_url"] == SOURCE_URL and passage["distance"] == 0.37
        web = traces["web"]["tool_results"][0]["structured_content"]["results"][0]
        assert web["url"] == SOURCE_URL and web["published_date"] == "2026-10-01"
        assert traces["read-document"]["tool_results"][1]["structured_content"]["pages"][0]["text"]
        assert traces["evidence-web"]["server_call_counts"] == {"evidence": 1, "web_search": 1}
        assert traces["workspace-evidence"]["server_call_counts"] == {"workspace": 1, "evidence": 1}
        assert traces["no-tool"]["call_counts"] == {}
        assert "insufficient" in traces["insufficient"]["response"]
        assert "failed" in traces["tool-failure"]["response"]
        recovery = await service.achat_with_trace("Try web search again", "tool-failure")
        assert recovery["call_counts"] == {"search_web": 1}
        assert len(recovery["tool_results"]) == 1
        assert recovery["tool_results"][0]["status"] == "success"
        assert recovery["tool_results"][0]["server_identity"] == "Veridex Web Search"
        assert recovery["tool_results"][0]["structured_content"]["results"][0]["url"] == SOURCE_URL
        await service.achat("Explain Self-RAG", "memory")
        await service.achat("What are its benefits?", "memory")
        await service.achat("Hello", "isolated")
        history = await service.aget_history("memory")
        isolated = await service.aget_history("isolated")
        assert any(message.content == "Explain Self-RAG" for message in history)
        assert not any(message.content == "Explain Self-RAG" for message in isolated)
        assert len(history) == 6 and len(isolated) == 2
        assert process_ids(pid_log) == initial_pids
    assert all(not is_alive(pid) for pid in initial_pids)
    assert not service.registry.is_active


@pytest.mark.asyncio
async def test_mcp_cli_missing_credentials_is_safe(tmp_path):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "scripts/chat_mcp_agent.py"),
        "--query",
        "Hello",
        cwd=ROOT,
        env={
            "PATH": str(ROOT / ".venv/bin"),
            "PYTHONPATH": str(ROOT / "src"),
            "OPENAI_API_KEY": "",
            "TAVILY_API_KEY": "",
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(15):
        stdout, stderr = await process.communicate()
    assert process.returncode == 1
    assert not stdout
    assert b"check credentials" in stderr
    assert b"Traceback" not in stderr


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_llm_evidence_and_multiserver(tmp_path):
    from veridex.config import settings

    if not settings.openai_api_key:
        pytest.skip("OpenAI credentials unavailable")
    if not (settings.chroma_persist_dir / "chroma.sqlite3").is_file():
        pytest.skip("Existing Chroma index unavailable")
    reports = {}
    async with open_mcp_agent_service(turn_timeout=180) as service:
        evidence = await service.achat_with_trace(
            "According to the indexed Self-RAG paper, how does it use retrieval and critique? "
            "Give a short answer with the paper ID and PDF page citations.",
            "live-evidence",
        )
        reports["evidence"] = evidence
        assert evidence["status"] == "success"
        assert any(item["name"] == "search_evidence" for item in evidence["tool_calls"])
        passages = [
            passage
            for result in evidence["tool_results"]
            if result["name"] == "search_evidence" and result["status"] == "success"
            for passage in result["structured_content"]["passages"]
        ]
        assert passages and all(
            passage["source_url"] and passage["page"] >= 1 for passage in passages
        )
        if settings.tavily_api_key:
            combined = await service.achat_with_trace(
                "Compare the indexed Self-RAG paper's approach with one recent external RAG "
                "development. Ground each part in its appropriate sources and give their citations.",
                "live-comparison",
            )
            reports["evidence-web"] = combined
            assert combined["status"] == "success"
            assert {"search_evidence", "search_web"}.issubset(
                {item["name"] for item in combined["tool_calls"]}
            )
            assert any(
                result["name"] == "search_web"
                and result["status"] == "success"
                and result["structured_content"]["results"]
                for result in combined["tool_results"]
            )
    (tmp_path / "live-agent-report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2)
    )


@pytest.mark.asyncio
async def test_cli_multi_turn_trace_with_actual_servers_and_mock_model(connections, tmp_path):
    configs, pid_log, _ = connections
    config_path = tmp_path / "cli-connections.json"
    config_path.write_text(json.dumps(configs))
    launcher = tmp_path / "cli-bootstrap.py"
    launcher.write_text(
        "import runpy\n"
        "from langchain_core.messages import AIMessage\n"
        "from veridex.agent import mcp_service\n"
        "class Model:\n"
        "    def __init__(self): self.calls = 0\n"
        "    def bind_tools(self, tools):\n"
        "        assert len(tools) == 4\n"
        "        return self\n"
        "    async def ainvoke(self, messages):\n"
        "        self.calls += 1\n"
        "        if self.calls == 1: return AIMessage(content='Hello!')\n"
        "        if self.calls == 2:\n"
        "            return AIMessage(content='', tool_calls=[{'name': 'search_evidence',\n"
        "                'args': {'query': 'Self-RAG'}, 'id': 'cli-call', 'type': 'tool_call'}])\n"
        "        return AIMessage(content='Evidence [paper, PDF p.1].')\n"
        "mcp_service.ChatOpenAI = lambda **kwargs: Model()\n"
        f"runpy.run_path({str(ROOT / 'scripts/chat_mcp_agent.py')!r}, run_name='__main__')\n"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(launcher),
        "--config",
        str(config_path),
        "--trace",
        "--session-id",
        "cli-test",
        "--query",
        "Hello",
        "--query",
        "Explain Self-RAG",
        cwd=ROOT,
        env={
            "PATH": str(ROOT / ".venv/bin"),
            "PYTHONPATH": str(ROOT / "src"),
            "OPENAI_API_KEY": "fake-llm-test-key",
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(30):
        stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    decoder = json.JSONDecoder()
    first, offset = decoder.raw_decode(stdout.decode().lstrip())
    second = json.loads(stdout.decode().lstrip()[offset:].lstrip())
    assert first["response"] == "Hello!" and first["call_counts"] == {}
    assert second["call_counts"] == {"search_evidence": 1}
    assert (
        second["tool_results"][0]["structured_content"]["passages"][0]["source_url"] == SOURCE_URL
    )
    assert second["tool_results"][0]["status"] == "success"
    assert b"fake-llm-test-key" not in stdout + stderr
    pids = process_ids(pid_log)
    assert len(pids) == 3 and all(not is_alive(pid) for pid in pids)
