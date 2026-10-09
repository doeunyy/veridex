from langchain_core.documents import Document

from veridex.rag.vectorstore import get_vector_store


def search_documents(
    query: str,
    top_k: int = 5,
    document_id: str | None = None,
) -> list[tuple[Document, float]]:
    """Search relevant document chunks with Chroma."""
    if not query.strip():
        raise ValueError("Query cannot be empty.")

    if top_k < 1:
        raise ValueError("top_k must be positive.")

    store = get_vector_store()

    filters = {"document_id": document_id} if document_id else None

    return store.similarity_search_with_score(
        query=query,
        k=top_k,
        filter=filters,
    )
