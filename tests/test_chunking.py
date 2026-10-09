from langchain_core.documents import Document

from veridex.rag.chunking import chunk_documents


def test_chunk_size_and_metadata():
    document = Document(
        page_content="Scientific evidence requires verification. " * 100,
        metadata={
            "document_id": "test_paper",
            "page": 1,
            "title": "Test Research Paper",
            "source_url": "https://example.com/paper",
        },
    )

    chunks = chunk_documents(
        documents=[document],
        chunk_size=200,
        chunk_overlap=40,
    )

    assert len(chunks) > 1
    assert all(len(chunk.page_content) <= 200 for chunk in chunks)

    for chunk in chunks:
        assert chunk.metadata["document_id"] == "test_paper"
        assert chunk.metadata["page"] == 1
        assert chunk.metadata["source_url"] == "https://example.com/paper"
        assert chunk.metadata["chunk_id"]
        assert chunk.metadata["start_index"] >= 0


def test_chunk_ids_are_unique():
    documents = [
        Document(
            page_content=("Document A content. " * 50),
            metadata={"document_id": "paper_a", "page": 1},
        ),
        Document(
            page_content=("Document B content. " * 50),
            metadata={"document_id": "paper_b", "page": 1},
        ),
    ]

    chunks = chunk_documents(
        documents,
        chunk_size=150,
        chunk_overlap=30,
    )

    chunk_ids = [chunk.metadata["chunk_id"] for chunk in chunks]

    assert len(chunk_ids) == len(set(chunk_ids))
