from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from veridex.rag.generation import answer_question, find_invalid_citations


def make_document(document_id, title, page, content, url):
    return Document(
        page_content=content,
        metadata={
            "document_id": document_id,
            "title": title,
            "page": page,
            "source_url": url,
        },
    )


@patch("veridex.rag.generation.search_documents")
def test_no_evidence_returns_fallback(mock_search):
    mock_search.return_value = []

    result = answer_question("Question without available evidence")

    assert result["sources"] == []
    assert "No relevant evidence" in result["answer"]


@patch("veridex.rag.generation.ChatOpenAI")
@patch("veridex.rag.generation.search_documents")
def test_generation_uses_retrieved_evidence(
    mock_search,
    mock_chat_model,
    monkeypatch,
):
    monkeypatch.setattr(
        "veridex.rag.generation.settings.openai_api_key",
        "test-key",
    )

    rag_document = make_document(
        "rag_2020",
        "Traditional RAG",
        2,
        "RAG combines parametric and non-parametric memory.",
        "https://example.com/rag",
    )

    self_rag_document = make_document(
        "self_rag_2023",
        "Self-RAG",
        3,
        "Self-RAG uses reflection tokens for adaptive retrieval.",
        "https://example.com/self-rag",
    )

    mock_search.return_value = [
        (rag_document, 0.4),
        (self_rag_document, 0.5),
    ]

    fake_model = MagicMock()
    fake_model.invoke.return_value.content = (
        "Traditional RAG uses external memory [S1]. Self-RAG adds adaptive retrieval [S2]."
    )
    mock_chat_model.return_value = fake_model

    result = answer_question(
        "Compare traditional RAG and Self-RAG",
        top_k=2,
    )

    assert "[S1]" in result["answer"]
    assert "[S2]" in result["answer"]

    assert len(result["sources"]) == 2
    assert result["sources"][0]["label"] == "S1"
    assert result["sources"][1]["label"] == "S2"

    assert result["sources"][0]["document_id"] == "rag_2020"
    assert result["sources"][1]["document_id"] == "self_rag_2023"

    messages = fake_model.invoke.call_args.args[0]
    prompt_text = messages[1].content

    assert "RAG combines parametric" in prompt_text
    assert "Self-RAG uses reflection tokens" in prompt_text
    assert "[S1]" in prompt_text
    assert "[S2]" in prompt_text


def test_invalid_citation_detection():
    sources = [
        {"label": "S1"},
        {"label": "S2"},
    ]

    answer = "First claim [S1]. Unsupported reference [S9]."

    invalid = find_invalid_citations(answer, sources)

    assert invalid == {"[S9]"}


def test_valid_citations():
    sources = [
        {"label": "S1"},
        {"label": "S2"},
    ]

    answer = "Traditional RAG [S1] differs from Self-RAG [S2]."

    assert find_invalid_citations(answer, sources) == set()
