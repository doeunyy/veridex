import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from veridex.agent.state import AgentState
from veridex.agent.tools import search_evidence
from veridex.rag import vectorstore
from veridex.rag.retrieval import search_documents


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(vectorstore, "_stores", {})
    monkeypatch.setattr(vectorstore, "_index_identities", {})
    monkeypatch.setattr(vectorstore.settings, "chroma_persist_dir", tmp_path / "index")
    monkeypatch.setattr(vectorstore, "get_embeddings", lambda: LocalEmbeddings())


class LocalEmbeddings(Embeddings):
    """Deterministic local vectors: exercise real Chroma without an API or corpus."""

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [float(len(text)), 1.0, 2.0]


def test_parallel_first_retrieval_initializes_once(isolated_store, monkeypatch):
    workers = 6
    barrier = Barrier(workers)
    entered = Event()
    release = Event()
    calls_lock = Lock()
    calls = []
    store = MagicMock()
    store.similarity_search_with_score.return_value = []

    def construct(**kwargs):
        with calls_lock:
            calls.append(kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return store

    monkeypatch.setattr(vectorstore, "Chroma", construct)

    def retrieve(index):
        barrier.wait(timeout=5)
        return search_documents(f"query {index}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(retrieve, index) for index in range(workers)]
        try:
            assert entered.wait(timeout=5)
            assert not any(future.done() for future in futures)
        finally:
            release.set()
        assert [future.result(timeout=5) for future in futures] == [[]] * workers

    assert len(calls) == 1
    assert store.similarity_search_with_score.call_count == workers
    assert vectorstore.get_vector_store() is store


def test_failed_constructor_is_not_cached(isolated_store, monkeypatch):
    store = MagicMock()
    constructor = MagicMock(side_effect=[RuntimeError("startup failed"), store])
    monkeypatch.setattr(vectorstore, "Chroma", constructor)
    with pytest.raises(RuntimeError, match="startup failed"):
        vectorstore.get_vector_store()
    assert vectorstore.get_vector_store() is store
    assert constructor.call_count == 2


@pytest.mark.parametrize(
    "setting",
    ["chroma_persist_dir", "chroma_collection", "openai_embedding_model", "openai_api_key"],
)
def test_configuration_switch_does_not_reuse_wrong_store(isolated_store, monkeypatch, setting):
    constructor = MagicMock(side_effect=[MagicMock(), MagicMock()])
    monkeypatch.setattr(vectorstore, "Chroma", constructor)
    old_value = getattr(vectorstore.settings, setting)
    first = vectorstore.get_vector_store()
    new_value = str(old_value) + "-other"
    monkeypatch.setattr(vectorstore.settings, setting, new_value)
    second = vectorstore.get_vector_store()
    assert second is not first
    monkeypatch.setattr(vectorstore.settings, setting, old_value)
    assert vectorstore.get_vector_store() is first
    assert constructor.call_count == 2


def test_real_chroma_parallel_cold_start_and_six_tools(isolated_store):
    # All six threads enter get_vector_store together, using the real constructor.
    barrier = Barrier(6)

    def open_store(_):
        barrier.wait(timeout=5)
        return vectorstore.get_vector_store()

    with ThreadPoolExecutor(max_workers=6) as executor:
        stores = list(executor.map(open_store, range(6)))
    assert all(store is stores[0] for store in stores)

    documents = [
        Document(
            page_content=f"Evidence for {name}",
            metadata={
                "document_id": name,
                "chunk_id": name,
                "title": name,
                "page": 1,
                "source_url": "https://example.com/paper",
            },
        )
        for name in ("RAG", "Self-RAG", "ReAct")
    ]
    assert vectorstore.index_documents(documents) == 3
    node = ToolNode([search_evidence], handle_tool_errors=True)
    calls = [
        {
            "name": "search_evidence",
            "args": {"query": f"comparison {index}", "top_k": 3},
            "id": str(index),
            "type": "tool_call",
        }
        for index in range(6)
    ]
    graph = StateGraph(AgentState)
    graph.add_node("tools", node)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    result = graph.compile().invoke({"messages": [AIMessage(content="", tool_calls=calls)]})
    result["messages"] = result["messages"][1:]
    assert len(result["messages"]) == 6

    for message in result["messages"]:
        assert message.status == "success", message.content
        passages = json.loads(message.content)["passages"]
        assert {passage["document_id"] for passage in passages} == {"RAG", "Self-RAG", "ReAct"}


def test_replaced_index_requires_restart_and_rebuild_is_guarded(isolated_store):
    store = vectorstore.get_vector_store()
    index_dir = vectorstore.settings.chroma_persist_dir
    with pytest.raises(RuntimeError, match="fresh process"):
        vectorstore.assert_index_not_in_use(index_dir)
    # Rename only a temporary test index; leave the real corpus/index untouched.
    index_dir.rename(index_dir.with_name("old-index"))
    index_dir.mkdir()
    with pytest.raises(RuntimeError, match="deleted or replaced"):
        vectorstore.get_vector_store()
    assert store is not None


def test_fresh_process_rebuild_guard_allows_unopened_path(isolated_store):
    vectorstore.assert_index_not_in_use(vectorstore.settings.chroma_persist_dir)


def test_rebuild_script_refuses_deletion_of_open_index(isolated_store, monkeypatch):
    import runpy
    import sys
    from pathlib import Path

    vectorstore.get_vector_store()
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--rebuild"])
    remove = MagicMock()
    monkeypatch.setattr("shutil.rmtree", remove)
    script = Path(__file__).resolve().parents[1] / "scripts" / "ingest.py"
    with pytest.raises(RuntimeError, match="fresh process"):
        runpy.run_path(str(script), run_name="__main__")
    remove.assert_not_called()
