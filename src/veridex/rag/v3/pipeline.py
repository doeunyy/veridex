"""LCEL ingestion: PDF pages -> body text -> token chunks with citation metadata.

No provider client is created here; the output feeds the offline cost plan and the
separately approved embedding build.
"""

import math
import re
from pathlib import Path

import pymupdf
import tiktoken
from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_text_splitters import RecursiveCharacterTextSplitter

from veridex.rag.v3 import EMBEDDING_MODEL, PRICE_USD_PER_MILLION_TOKENS
from veridex.rag.v3.manifest import Manifest, Paper

ENCODING = "cl100k_base"
CHUNK_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 60
# References are long lists of other papers' titles that dominate similarity search
# without answering anything. A heading line alone on a line marks where they begin.
_BACK_MATTER = re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE)
_MIN_BODY_PAGES = 2


def load_pages(item: tuple[Paper, Path]) -> list[Document]:
    """One Document per non-empty page, carrying everything a citation needs."""
    paper, pdf_path = item
    pages = []
    with pymupdf.open(pdf_path) as pdf:
        for number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(
                    Document(
                        page_content=text,
                        metadata={
                            "document_id": paper.doc_id,
                            "arxiv_id": paper.arxiv_id,
                            "title": paper.title,
                            "year": paper.year,
                            "topic": paper.topic,
                            "license": paper.license,
                            "source_url": paper.abs_url,
                            "page": number,
                            "page_count": len(pdf),
                        },
                    )
                )
    if not pages:
        raise ValueError(f"No extractable text in {pdf_path.name}.")
    return pages


def strip_back_matter(pages: list[Document]) -> list[Document]:
    """Keep the body: drop everything from the first references heading onward.

    Appendices after the references are dropped too; the body answers the questions
    the corpus is built for, and keeping appendices would let a few very long papers
    dominate the index. Headings on the first pages are ignored (tables of contents).
    """
    kept = []
    for page in pages:
        match = _BACK_MATTER.search(page.page_content)
        if match and page.metadata["page"] > _MIN_BODY_PAGES:
            body = page.page_content[: match.start()].strip()
            if body:
                kept.append(Document(page_content=body, metadata=dict(page.metadata)))
            return kept
        kept.append(page)
    return kept


def make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=ENCODING,
        chunk_size=CHUNK_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        add_start_index=True,
    )


def assign_chunk_ids(chunks: list[Document]) -> list[Document]:
    """Stable, human-readable IDs: <document_id>:p<page>:c<index within document>."""
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_id"] = (
            f"{chunk.metadata['document_id']}:p{chunk.metadata['page']}:c{index:03d}"
        )
    return chunks


def build_ingestion_chain(splitter: RecursiveCharacterTextSplitter | None = None) -> Runnable:
    """(paper, pdf path) -> chunks. Pages never merge, so every chunk has one page."""
    splitter = splitter or make_splitter()
    return (
        RunnableLambda(load_pages, name="load_pages")
        | RunnableLambda(strip_back_matter, name="strip_back_matter")
        | RunnableLambda(splitter.split_documents, name="split")
        | RunnableLambda(assign_chunk_ids, name="assign_chunk_ids")
    )


def ingest(manifest: Manifest, papers_dir: Path, chain: Runnable | None = None) -> list[Document]:
    chain = chain or build_ingestion_chain()
    items = [(paper, papers_dir / paper.filename) for paper in manifest.papers]
    missing = [path.name for _, path in items if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing PDFs (run download first): {missing}")
    chunks = [chunk for batch in chain.batch(items) for chunk in batch]
    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk IDs.")
    return chunks


def embedding_plan(chunks: list[Document], batch_size: int) -> dict:
    """Exact token count with the embedding tokenizer, before any paid request."""
    encoder = tiktoken.get_encoding(ENCODING)
    tokens = [len(encoder.encode(c.page_content, disallowed_special=())) for c in chunks]
    per_document: dict[str, dict] = {}
    for chunk, count in zip(chunks, tokens, strict=True):
        stats = per_document.setdefault(
            chunk.metadata["document_id"],
            {"chunks": 0, "tokens": 0, "page_count": chunk.metadata["page_count"], "pages": set()},
        )
        stats["chunks"] += 1
        stats["tokens"] += count
        stats["pages"].add(chunk.metadata["page"])
    for stats in per_document.values():
        stats["body_pages"] = len(stats.pop("pages"))
    total = sum(tokens)
    return {
        "model": EMBEDDING_MODEL,
        "encoding": ENCODING,
        "chunking": {
            "chunk_tokens": CHUNK_TOKENS,
            "overlap_tokens": CHUNK_OVERLAP_TOKENS,
            "back_matter": "dropped from first references heading",
        },
        "documents": len(per_document),
        "chunks": len(chunks),
        "tokens": total,
        "largest_chunk_tokens": max(tokens, default=0),
        "batch_size": batch_size,
        "requests": math.ceil(len(chunks) / batch_size),
        "price_usd_per_million_tokens": PRICE_USD_PER_MILLION_TOKENS,
        "estimated_usd": round(total * PRICE_USD_PER_MILLION_TOKENS / 1_000_000, 6),
        "per_document": dict(sorted(per_document.items())),
    }
