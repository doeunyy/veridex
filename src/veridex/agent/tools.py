import json

from langchain_core.tools import tool

from veridex.rag.retrieval import search_documents


@tool
def search_evidence(query: str, top_k: int = 5) -> str:
    """Search the indexed research papers for evidence.

    Use this tool when a question requires facts, methods,
    findings, or comparisons from the document corpus.

    Args:
        query: A precise natural-language search query.
        top_k: Number of relevant passages to retrieve (1-10).
    """
    if not query.strip():
        raise ValueError("Search query cannot be empty.")

    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10.")

    results = search_documents(query=query, top_k=top_k)

    passages = []

    for document, distance in results:
        metadata = document.metadata

        passages.append(
            {
                "document_id": metadata["document_id"],
                "chunk_id": metadata["chunk_id"],
                "title": metadata["title"],
                "page": metadata["page"],
                "source_url": metadata["source_url"],
                "distance": distance,
                "content": document.page_content,
            }
        )

    return json.dumps(
        {"query": query, "passages": passages},
        ensure_ascii=False,
    )
