"""MCP boundary for the existing Chroma retrieval pipeline."""

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from veridex.rag.retrieval import search_documents


class EvidencePassage(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    page: int = Field(description="One-based PDF page number.")
    source_url: str
    content: str
    distance: float | None = Field(description="Chroma retrieval distance, not confidence.")


class EvidenceResult(BaseModel):
    query: str
    passages: list[EvidencePassage]


def create_server() -> FastMCP:
    """Construct a server without opening Chroma or loading embeddings."""
    server = FastMCP(name="Veridex Evidence")

    @server.tool
    async def search_evidence(
        query: Annotated[str, Field(strict=True, min_length=1)],
        top_k: Annotated[int, Field(strict=True, ge=1, le=10)] = 5,
        document_id: Annotated[str | None, Field(strict=True)] = None,
    ) -> EvidenceResult:
        """Search indexed research papers for evidence, optionally filtering by document ID.

        Unknown document IDs return no passages. Distance is Chroma distance, not confidence.
        """
        if not query.strip():
            raise ValueError("Search query cannot be empty.")
        results = await asyncio.to_thread(
            search_documents, query=query, top_k=top_k, document_id=document_id
        )
        return EvidenceResult(
            query=query,
            passages=[
                EvidencePassage(
                    document_id=document.metadata["document_id"],
                    chunk_id=document.metadata["chunk_id"],
                    title=document.metadata["title"],
                    page=document.metadata["page"],
                    source_url=document.metadata["source_url"],
                    content=document.page_content,
                    distance=distance,
                )
                for document, distance in results
            ],
        )

    return server


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-smoke", action="store_true")
    args = parser.parse_args()
    server = create_server()
    if args.protocol_smoke:
        from veridex.mcp.dev_tools import register_protocol_smoke_tool

        register_protocol_smoke_tool(server)
    server.run(transport="stdio")
