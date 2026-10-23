"""Read-only, manifest-approved access to the Corpus v3 PDF papers."""

import asyncio
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import PurePosixPath
from threading import Lock
from typing import Annotated

import pymupdf
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from veridex.config import settings
from veridex.rag.v3.manifest import Paper

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DOCUMENTS = 100
MAX_PDF_PAGES = 1000
MAX_READ_PAGES = 10
MAX_TEXT_CHARS = 20_000
_PDF_LOCK = Lock()
_READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_COMPONENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\Z")
_SENSITIVE = {
    "secret",
    "secrets",
    "credential",
    "credentials",
    "password",
    "passwords",
    "token",
    "tokens",
    "private",
    "id_rsa",
    "id_ed25519",
    "env",
}


class WorkspaceDocument(BaseModel):
    document_id: str = Field(description="Stable relative PDF filename within the approved corpus.")
    paper_id: str = Field(description="Citation ID, also the search_evidence document_id filter.")
    title: str
    topic: str
    year: int
    source_url: str
    license: str
    format: str = "pdf"
    size_bytes: int
    page_count: int


class DocumentList(BaseModel):
    documents: list[WorkspaceDocument]


class DocumentPage(BaseModel):
    page: int = Field(description="One-based PDF page number.")
    text: str


class DocumentRead(BaseModel):
    document: WorkspaceDocument
    pages: list[DocumentPage]
    truncated: bool = Field(description="True if requested text exceeded max_chars.")


def _identifier(document_id: str) -> tuple[str, ...]:
    parts = tuple(document_id.split("/"))
    if (
        any(not _COMPONENT.fullmatch(part) for part in parts)
        or PurePosixPath(document_id).suffix.lower() != ".pdf"
        or any(
            part.lower() in _SENSITIVE
            or PurePosixPath(part).stem.lower() in _SENSITIVE
            or set(re.split(r"[_.-]", part.lower())) & _SENSITIVE
            for part in parts
        )
    ):
        raise ToolError("Invalid document identifier: use an approved relative PDF filename.")
    return parts


def _catalog() -> dict[str, Paper]:
    # This metadata path is administrator-configured, never supplied by MCP callers.
    path = settings.corpus_manifest_path
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ToolError("Workspace document catalog exceeds the size limit.")
    entries = json.loads(path.read_text(encoding="utf-8"))["papers"]
    if len(entries) > MAX_DOCUMENTS:
        raise ToolError("Workspace document catalog exceeds the document limit.")
    catalog = {}
    for item in entries:
        entry = Paper.model_validate(item)
        try:
            _identifier(entry.filename)
        except ToolError:
            continue
        if entry.filename in catalog:
            raise ToolError("Workspace document catalog contains duplicate identifiers.")
        catalog[entry.filename] = entry
    return catalog


@contextmanager
def _open_pdf(document_id: str):
    parts = _identifier(document_id)
    # The configured root is the trust boundary. Descendant symlinks are never followed,
    # including during open: directory descriptors avoid check-then-open path races.
    root = settings.documents_dir.resolve(strict=True)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        for component in parts[:-1]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ToolError("Document must be a regular PDF file without hard links.")
        if info.st_size > MAX_FILE_BYTES:
            raise ToolError("Document exceeds the file-size limit.")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ToolError("Document exceeds the file-size limit.")
        # Parse checked bytes instead of reopening a caller-supplied filesystem path.
        with _PDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass or not 1 <= pdf.page_count <= MAX_PDF_PAGES:
                raise ToolError("Document is encrypted or exceeds the PDF page-count limit.")
            yield pdf, len(data)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _metadata(entry: Paper, size: int, pages: int) -> WorkspaceDocument:
    return WorkspaceDocument(
        document_id=entry.filename,
        paper_id=entry.doc_id,
        title=entry.title,
        topic=entry.topic,
        year=entry.year,
        source_url=entry.abs_url,
        license=entry.license,
        size_bytes=size,
        page_count=pages,
    )


def _list_documents() -> DocumentList:
    documents = []
    for document_id, entry in sorted(_catalog().items()):
        try:
            with _open_pdf(document_id) as (pdf, size):
                documents.append(_metadata(entry, size, pdf.page_count))
        except (OSError, ValueError, RuntimeError, ToolError):
            # Unavailable, unsafe, oversized, or malformed files are not listed.
            continue
    return DocumentList(documents=documents)


def _read_document(
    document_id: str, start_page: int, end_page: int | None, max_chars: int
) -> DocumentRead:
    _identifier(document_id)
    entry = _catalog().get(document_id)
    if entry is None:
        raise ToolError("Document is not in the approved catalog.")
    if end_page is not None and (end_page < start_page or end_page - start_page >= MAX_READ_PAGES):
        raise ToolError("Page range must be ordered and contain at most 10 pages.")
    with _open_pdf(document_id) as (pdf, size):
        last = (
            end_page
            if end_page is not None
            else min(pdf.page_count, start_page + MAX_READ_PAGES - 1)
        )
        if start_page > pdf.page_count or last > pdf.page_count:
            raise ToolError("Requested page range is outside this document.")
        pages = []
        remaining = max_chars
        truncated = False
        for index in range(start_page - 1, last):
            # Match Phase 01 extraction, but load only requested pages.
            text = pdf[index].get_text("text").strip()
            if len(text) > remaining:
                pages.append(DocumentPage(page=index + 1, text=text[:remaining]))
                truncated = True
                break
            pages.append(DocumentPage(page=index + 1, text=text))
            remaining -= len(text)
        return DocumentRead(
            document=_metadata(entry, size, pdf.page_count), pages=pages, truncated=truncated
        )


async def _safe_call(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except ToolError:
        raise
    except Exception:  # noqa: BLE001 — hide host paths and parser details at the tool boundary
        raise ToolError("Workspace document is unavailable or could not be read safely.") from None


def create_server() -> FastMCP:
    """Construct a server without accessing the filesystem."""
    server = FastMCP(name="Veridex Workspace")

    @server.tool(annotations=_READ_ONLY)
    async def list_documents() -> DocumentList:
        """List available, manifest-approved PDF research documents and relative identifiers."""
        return await _safe_call(_list_documents)

    @server.tool(annotations=_READ_ONLY)
    async def read_document(
        document_id: Annotated[str, Field(strict=True, min_length=1, max_length=256)],
        start_page: Annotated[int, Field(strict=True, ge=1)] = 1,
        end_page: Annotated[int | None, Field(strict=True, ge=1)] = None,
        max_chars: Annotated[int, Field(strict=True, ge=1, le=MAX_TEXT_CHARS)] = 12_000,
    ) -> DocumentRead:
        """Read up to 10 PDF pages with a bounded text response.

        Pages are one-based. Omitted end_page selects up to 10 pages from start_page.
        Use a document_id from list_documents. Text is capped by max_chars.
        """
        return await _safe_call(_read_document, document_id, start_page, end_page, max_chars)

    return server


if __name__ == "__main__":
    import sys

    # PyMuPDF defaults to STDOUT; keep parser diagnostics off the JSON-RPC stream.
    pymupdf.set_messages(stream=sys.stderr)
    create_server().run(transport="stdio")
