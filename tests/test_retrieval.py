from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from veridex.rag.retrieval import search_documents


@pytest.fixture
def mock_vector_store():
    """Replace the real Chroma vector store with a mock."""
    with patch("veridex.rag.retrieval.get_vector_store") as mock_get_store:
        store = MagicMock()
        mock_get_store.return_value = store
        yield store


def test_search_returns_ranked_documents(mock_vector_store):
    document = Document(
        page_content="RAG uses external non-parametric memory.",
        metadata={
            "document_id": "rag_2020",
            "page": 2,
            "chunk_id": "rag_2020_p2_c00001",
        },
    )

    mock_vector_store.similarity_search_with_score.return_value = [(document, 0.42)]

    results = search_documents(
        query="How does RAG use external knowledge?",
        top_k=3,
    )

    assert len(results) == 1
    assert results[0][0].metadata["document_id"] == "rag_2020"
    assert results[0][1] == 0.42

    mock_vector_store.similarity_search_with_score.assert_called_once_with(
        query="How does RAG use external knowledge?",
        k=3,
        filter=None,
    )


def test_document_filter(mock_vector_store):
    mock_vector_store.similarity_search_with_score.return_value = []

    search_documents(
        query="What does the model predict?",
        top_k=5,
        document_id="mixmhc2pred_2023",
    )

    mock_vector_store.similarity_search_with_score.assert_called_once_with(
        query="What does the model predict?",
        k=5,
        filter={"document_id": "mixmhc2pred_2023"},
    )


@pytest.mark.parametrize("query", ["", "   ", "\n"])
def test_empty_query_rejected(query):
    with pytest.raises(ValueError, match="empty"):
        search_documents(query)


@pytest.mark.parametrize("top_k", [0, -1, -5])
def test_invalid_top_k_rejected(top_k):
    with pytest.raises(ValueError, match="positive"):
        search_documents("What is RAG?", top_k=top_k)
