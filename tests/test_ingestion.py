from pathlib import Path

import pymupdf
import pytest

from veridex.rag.ingestion import load_pdf


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal PDF for testing."""
    path = tmp_path / "sample.pdf"

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text(
            (72, 72),
            "Retrieval-augmented generation uses external knowledge.",
        )
        pdf.save(path)

    return path


@pytest.fixture
def sample_metadata() -> dict:
    return {
        "id": "test_paper",
        "title": "Test Research Paper",
        "domain": "nlp",
        "year": 2026,
        "filename": "sample.pdf",
        "source_url": "https://example.com/paper",
    }


def test_pdf_extraction(sample_pdf, sample_metadata):
    documents = load_pdf(sample_pdf, sample_metadata)

    assert len(documents) == 1
    assert "external knowledge" in documents[0].page_content


def test_pdf_metadata(sample_pdf, sample_metadata):
    documents = load_pdf(sample_pdf, sample_metadata)
    metadata = documents[0].metadata

    assert metadata["document_id"] == "test_paper"
    assert metadata["title"] == "Test Research Paper"
    assert metadata["page"] == 1
    assert metadata["source_url"] == "https://example.com/paper"


def test_missing_pdf(sample_metadata, tmp_path):
    missing_path = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        load_pdf(missing_path, sample_metadata)
