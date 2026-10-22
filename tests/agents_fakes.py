"""Deterministic chat models and tools for supervisor-graph tests (no network)."""

import json
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool

from veridex.config import Settings

CONFIG = Settings(
    _env_file=None,
    openai_api_key="sk-test",
    google_api_key="g-test",
    worker_max_tool_rounds=3,
    supervisor_max_hops=3,
    state_backend="memory",
)


class Scripted(BaseChatModel):
    """script(provider, mode, messages) -> AIMessage | dict | Exception."""

    provider: str
    script: Callable
    mode: str = "plain"

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"mode": "tools"})

    def with_structured_output(self, schema, **kwargs):
        def run(messages):
            value = self._run("structured", messages)
            return schema.model_validate(value)

        return RunnableLambda(run)

    def _run(self, mode, messages):
        value = self.script(self.provider, mode, list(messages))
        if isinstance(value, Exception):
            raise value
        return value

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._run(self.mode, messages)
        return ChatResult(generations=[ChatGeneration(message=message)])


def factory(script: Callable):
    calls: list = []

    def recorded(provider, mode, messages):
        calls.append((provider, mode))
        return script(provider, mode, messages)

    models = {p: Scripted(provider=p, script=recorded) for p in ("openai", "gemini")}
    return models.__getitem__, calls


def last_human(messages) -> str:
    return next(m.content for m in reversed(messages) if m.type == "human")


def system(messages) -> str:
    return messages[0].content


def tool_call(name: str, args: dict, call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


PASSAGE = {
    "document_id": "react_2022",
    "chunk_id": "react_2022:p2:c012",
    "title": "ReAct",
    "page": 2,
    "source_url": "https://arxiv.org/abs/2210.03629",
    "content": "ReAct interleaves reasoning traces and task-specific actions.",
    "distance": 0.2,
}


def make_tools(fail: set[str] = frozenset()) -> dict[str, list]:
    def fn(name: str, payload: Callable[[dict], dict]):
        def run(**kwargs):
            if name in fail:
                raise RuntimeError(f"{name} failed")
            return json.dumps(payload(kwargs))

        return StructuredTool.from_function(
            func=run, name=name, description=name, args_schema=_schema(name)
        )

    evidence = fn("search_evidence", lambda a: {"query": a["query"], "passages": [PASSAGE]})
    web = fn(
        "tavily_search",
        lambda a: {
            "results": [{"title": "News", "url": "https://example.com/news", "content": "x"}]
        },
    )
    extract = fn("tavily_extract", lambda a: {"results": []})
    listing = fn("list_documents", lambda a: {"documents": []})
    read = fn("read_document", lambda a: {"pages": []})
    describe = fn("describe_catalog", lambda a: {"schema_sql": "CREATE TABLE papers(...)"})
    query = fn(
        "query_catalog_sql", lambda a: {"columns": ["n"], "rows": [[42]], "truncated": False}
    )
    return {
        "research": [evidence, web, extract],
        "summary": [listing, read, evidence],
        "data": [describe, query, listing],
    }


def _schema(name: str) -> dict:
    fields = {
        "search_evidence": {"query": {"type": "string"}},
        "tavily_search": {"query": {"type": "string"}},
        "tavily_extract": {"urls": {"type": "array", "items": {"type": "string"}}},
        "list_documents": {},
        "read_document": {"document_id": {"type": "string"}},
        "describe_catalog": {},
        "query_catalog_sql": {"sql": {"type": "string"}},
    }[name]
    return {"type": "object", "properties": fields, "required": list(fields)}
