from pathlib import Path

import pytest

from veridex.config import settings
from veridex.rag.retrieval import search_documents

pytestmark = pytest.mark.integration


def test_vector_index_exists():
    index_dir = Path(settings.chroma_persist_dir)

    assert index_dir.exists()
    assert any(index_dir.iterdir())


def test_retrieval_across_documents():
    results = search_documents(
        "Compare NetMHCIIpan and MixMHC2pred approaches.",
        top_k=10,
    )

    document_ids = {document.metadata["document_id"] for document, _ in results}

    assert "netmhcpan_2020" in document_ids
    assert "mixmhc2pred_2023" in document_ids


def test_filtered_retrieval():
    results = search_documents(
        "What is MixMHC2pred used for?",
        top_k=5,
        document_id="mixmhc2pred_2023",
    )

    assert len(results) > 0

    for document, _ in results:
        assert document.metadata["document_id"] == "mixmhc2pred_2023"
        assert document.metadata["source_url"]
        assert document.metadata["page"] >= 1
