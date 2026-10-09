import json
from pathlib import Path

import pymupdf
from langchain_core.documents import Document


def load_manifest(manifest_path: Path) -> list[dict]:
    """Load the document catalog."""
    with manifest_path.open(encoding="utf-8") as file:
        manifest = json.load(file)

    return manifest["documents"]


def load_pdf(pdf_path: Path, metadata: dict) -> list[Document]:
    """Extract one LangChain Document per PDF page."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    documents = []

    with pymupdf.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()

            if not text:
                continue

            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        "document_id": metadata["id"],
                        "title": metadata["title"],
                        "domain": metadata["domain"],
                        "year": metadata["year"],
                        "source_url": metadata["source_url"],
                        "page": page_number,
                        "filename": metadata["filename"],
                    },
                )
            )

    return documents


def load_corpus(
    manifest_path: Path,
    documents_dir: Path,
) -> list[Document]:
    """Load all PDFs listed in the manifest."""
    documents = []

    for item in load_manifest(manifest_path):
        pdf_path = documents_dir / item["filename"]
        documents.extend(load_pdf(pdf_path, item))

    return documents
