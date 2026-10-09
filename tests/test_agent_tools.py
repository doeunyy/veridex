import json
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from veridex.agent.tools import search_evidence


@patch("veridex.agent.tools.search_documents")
def test_search_evidence_returns_metadata(mock_search):
    document = Document(
        page_content="ReAct combines reasoning and acting.",
        metadata={
            "document_id": "react_2022",
            "chunk_id": "react_2022_p2_c00001",
            "title": "ReAct",
            "page": 2,
            "source_url": "https://example.com/react",
        },
    )
    mock_search.return_value = [(document, 0.42)]

    response = search_evidence.invoke(
        {
            "query": "How does ReAct work?",
            "top_k": 3,
        }
    )

    data = json.loads(response)

    assert data["query"] == "How does ReAct work?"
    assert len(data["passages"]) == 1

    passage = data["passages"][0]
    assert passage["document_id"] == "react_2022"
    assert passage["page"] == 2
    assert passage["distance"] == 0.42
    assert "reasoning and acting" in passage["content"]

    mock_search.assert_called_once_with(
        query="How does ReAct work?",
        top_k=3,
    )


@pytest.mark.parametrize("query", ["", " ", "\n"])
def test_search_evidence_rejects_empty_queries(query):
    with pytest.raises(ValueError, match="empty"):
        search_evidence.invoke({"query": query})


@pytest.mark.parametrize("top_k", [0, -1, 11])
def test_search_evidence_rejects_invalid_top_k(top_k):
    with pytest.raises(ValueError, match="top_k"):
        search_evidence.invoke({"query": "Self-RAG", "top_k": top_k})
