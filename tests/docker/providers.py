"""Test-only provider replacements. Production server tool implementations stay real."""

import asyncio
import json
import os
import sqlite3
import struct
from contextlib import closing


def event(kind, **values):
    descriptor = os.open(
        "/verification-report/events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600
    )
    try:
        os.write(descriptor, (json.dumps({"kind": kind, **values}) + "\n").encode())
    finally:
        os.close(descriptor)


def install(role):
    if role == "evidence":
        from langchain_core.embeddings import Embeddings

        from veridex.rag import embeddings

        class ExistingVector(Embeddings):
            def embed_query(self, text):
                event("embedding-query", query=text)
                with closing(
                    sqlite3.connect(
                        "file:/opt/veridex/rag/chroma/chroma.sqlite3?mode=ro&immutable=1", uri=True
                    )
                ) as db:
                    vector = db.execute(
                        "SELECT vector FROM embeddings_queue WHERE id='rag_2020_p3_c00012'"
                    ).fetchone()[0]
                return list(struct.unpack("<1536f", vector))

            def embed_documents(self, texts):
                raise AssertionError("Offline verification must never ingest or embed documents")

        embeddings.get_embeddings = lambda: ExistingVector()
    if role == "web_search":
        import tavily

        class OfflineTavily:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def search(self, *, query, **kwargs):
                event("web-start", query=query)
                if query == "web-error":
                    raise RuntimeError("PRIVATE-SENTINEL secret /sensitive/path")
                if query == "web-slow":
                    try:
                        await asyncio.sleep(120)
                    except asyncio.CancelledError:
                        event("web-cancelled", query=query)
                        raise
                return {
                    "results": [
                        {
                            "title": "Offline RAG fixture",
                            "url": "https://offline.example.test/rag",
                            "content": "Deterministic provider fixture, not live web evidence.",
                        }
                    ]
                }

        tavily.AsyncTavilyClient = OfflineTavily
