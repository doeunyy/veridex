import asyncio
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest
from fastmcp import Client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_mcp_protocol import ROOT

from veridex.mcp.servers import workspace

TEXTS = ["Research evidence page one.", "Second page of research.", "Third page."]


def make_pdf(path, texts=TEXTS):
    with pymupdf.open() as pdf:
        for text in texts:
            page = pdf.new_page()
            if text:
                page.insert_text((72, 72), text)
        pdf.save(path)


def catalog_entry(filename):
    return {
        "id": Path(filename).stem,
        "filename": filename,
        "title": "Approved research",
        "domain": "nlp",
        "year": 2026,
        "source_url": "https://example.com/paper?x=1#section",
    }


def write_catalog(path, names):
    path.write_text(json.dumps({"documents": [catalog_entry(name) for name in names]}))


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "papers"
    root.mkdir()
    make_pdf(root / "paper.pdf")
    manifest = tmp_path / "manifest.json"
    write_catalog(manifest, ["paper.pdf"])
    monkeypatch.setattr(workspace.settings, "documents_dir", root)
    monkeypatch.setattr(workspace.settings, "workspace_manifest_path", manifest)
    return root, manifest


@pytest.mark.asyncio
async def test_listing_metadata_and_schema(corpus):
    root, _ = corpus
    async with Client(workspace.create_server()) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["list_documents", "read_document"]
        assert tools[0].inputSchema == {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        schema = tools[1].inputSchema
        assert schema["required"] == ["document_id"]
        assert schema["properties"]["start_page"] == {"type": "integer", "minimum": 1, "default": 1}
        assert schema["properties"]["max_chars"] == {
            "type": "integer",
            "minimum": 1,
            "maximum": 20000,
            "default": 12000,
        }
        result = await client.call_tool("list_documents", {})
        assert result.structured_content == {
            "documents": [
                {
                    "document_id": "paper.pdf",
                    "paper_id": "paper",
                    "title": "Approved research",
                    "domain": "nlp",
                    "year": 2026,
                    "source_url": "https://example.com/paper?x=1#section",
                    "format": "pdf",
                    "size_bytes": (root / "paper.pdf").stat().st_size,
                    "page_count": 3,
                }
            ]
        }
        assert str(root) not in str(result)


@pytest.mark.asyncio
async def test_reads_ranges_truncation_and_no_writes(corpus):
    root, manifest = corpus
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "paper.pdf", manifest)
    }
    async with Client(workspace.create_server()) as client:
        for _ in range(2):
            full = await client.call_tool("read_document", {"document_id": "paper.pdf"})
            assert full.structured_content["pages"] == [
                {"page": index + 1, "text": text} for index, text in enumerate(TEXTS)
            ]
            assert not full.structured_content["truncated"]
        ranged = await client.call_tool(
            "read_document",
            {
                "document_id": "paper.pdf",
                "start_page": 2,
                "end_page": 2,
            },
        )
        assert ranged.structured_content["pages"] == [{"page": 2, "text": TEXTS[1]}]
        truncated = await client.call_tool(
            "read_document",
            {
                "document_id": "paper.pdf",
                "max_chars": 5,
            },
        )
        assert truncated.structured_content["truncated"]
        assert truncated.structured_content["pages"] == [{"page": 1, "text": TEXTS[0][:5]}]
        multi = await client.call_tool(
            "read_document",
            {
                "document_id": "paper.pdf",
                "max_chars": len(TEXTS[0]) + 2,
            },
        )
        assert (
            sum(len(page["text"]) for page in multi.structured_content["pages"])
            == len(TEXTS[0]) + 2
        )
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before


@pytest.mark.asyncio
async def test_blank_pages_and_default_page_cap(corpus):
    root, _ = corpus
    (root / "paper.pdf").unlink()
    make_pdf(root / "paper.pdf", [""] + [f"Page {i}" for i in range(2, 13)])
    async with Client(workspace.create_server()) as client:
        result = await client.call_tool("read_document", {"document_id": "paper.pdf"})
        assert len(result.structured_content["pages"]) == 10
        assert result.structured_content["pages"][0] == {"page": 1, "text": ""}
        assert result.structured_content["document"]["page_count"] == 12
        last = await client.call_tool(
            "read_document", {"document_id": "paper.pdf", "start_page": 11}
        )
        assert [page["page"] for page in last.structured_content["pages"]] == [11, 12]


INVALID_IDS = [
    "",
    " ",
    "../paper.pdf",
    "sub/../../paper.pdf",
    "/etc/passwd",
    "/tmp/paper.pdf",
    "C:\\paper.pdf",
    "sub\\paper.pdf",
    "./paper.pdf",
    "sub//paper.pdf",
    "paper.pdf/",
    ".hidden.pdf",
    ".private/paper.pdf",
    "credentials.pdf",
    "api-secret.pdf",
    "id_rsa.pdf",
    "notes.txt",
    "notes.md",
    "paper.PDF.exe",
    "paper.pdf\x00",
    "%2e%2e/paper.pdf",
    "paper.pdf",  # handled separately as a directory fixture below
]


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id", INVALID_IDS[:-1])
async def test_unsafe_identifiers_rejected_without_file_access(corpus, monkeypatch, document_id):
    open_file = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr(workspace, "_open_pdf", open_file)
    async with Client(workspace.create_server()) as client:
        result = await client.call_tool(
            "read_document", {"document_id": document_id}, raise_on_error=False
        )
        assert result.is_error
    open_file.assert_not_called()


INVALID_ARGUMENTS = [
    {},
    {"document_id": 123},
    {"document_id": "x" * 257},
    *[{"document_id": "paper.pdf", "start_page": value} for value in (0, -1, True, "1", 1.5)],
    *[{"document_id": "paper.pdf", "end_page": value} for value in (0, True, "2", 1.5)],
    *[{"document_id": "paper.pdf", "max_chars": value} for value in (0, 20001, True, "5", 1.5)],
    {"document_id": "paper.pdf", "start_page": 3, "end_page": 2},
    {"document_id": "paper.pdf", "end_page": 11},
    {"document_id": "paper.pdf", "start_page": 4},
    {"document_id": "paper.pdf", "end_page": 4},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", INVALID_ARGUMENTS)
async def test_invalid_arguments_and_ranges(corpus, arguments):
    async with Client(workspace.create_server()) as client:
        result = await client.call_tool("read_document", arguments, raise_on_error=False)
        assert result.is_error
        assert not (await client.call_tool("read_document", {"document_id": "paper.pdf"})).is_error


@pytest.mark.asyncio
async def test_listing_filters_unsafe_missing_unapproved_files(corpus):
    root, manifest = corpus
    make_pdf(root / "unapproved.pdf")
    make_pdf(root / ".hidden.pdf")
    make_pdf(root / "credentials.pdf")
    (root / "notes.txt").write_text("Sensitive notes")
    (root / "broken.pdf").write_bytes(b"not a PDF")
    (root / "directory.pdf").mkdir()
    (root / "oversized.pdf").write_bytes(b"x" * (workspace.MAX_FILE_BYTES + 1))
    (root / "escape.pdf").symlink_to(manifest)
    write_catalog(
        manifest,
        [
            "paper.pdf",
            ".hidden.pdf",
            "credentials.pdf",
            "notes.txt",
            "broken.pdf",
            "directory.pdf",
            "oversized.pdf",
            "escape.pdf",
            "missing.pdf",
            "../outside.pdf",
        ],
    )
    async with Client(workspace.create_server()) as client:
        result = await client.call_tool("list_documents", {})
        assert [item["document_id"] for item in result.structured_content["documents"]] == [
            "paper.pdf"
        ]
        assert (
            await client.call_tool(
                "read_document", {"document_id": "unapproved.pdf"}, raise_on_error=False
            )
        ).is_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "directory",
        "file-symlink",
        "directory-symlink",
        "hard-link",
        "fifo",
        "oversized",
        "malformed",
        "encrypted",
    ],
)
async def test_unsafe_approved_files_fail_and_recover(corpus, tmp_path, kind, caplog):
    root, manifest = corpus
    filename = "bad.pdf"
    path = root / filename
    if kind == "directory":
        path.mkdir()
    elif kind == "file-symlink":
        outside = tmp_path / "outside.pdf"
        make_pdf(outside)
        path.symlink_to(outside)
    elif kind == "directory-symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        make_pdf(outside / "bad.pdf")
        (root / "linked").symlink_to(outside, target_is_directory=True)
        filename = "linked/bad.pdf"
    elif kind == "hard-link":
        os.link(root / "paper.pdf", path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "oversized":
        with path.open("wb") as stream:
            stream.truncate(workspace.MAX_FILE_BYTES + 1)
    elif kind == "malformed":
        path.write_bytes(b"invalid PDF")
    elif kind == "encrypted":
        with pymupdf.open(root / "paper.pdf") as pdf:
            pdf.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="test", owner_pw="test")
    write_catalog(manifest, ["paper.pdf", filename])
    async with Client(workspace.create_server()) as client:
        async with asyncio.timeout(3):
            result = await client.call_tool(
                "read_document", {"document_id": filename}, raise_on_error=False
            )
        assert result.is_error
        assert str(tmp_path) not in str(result) + caplog.text
        # The hard-link fixture also makes paper.pdf ineligible until the link is removed.
        if kind == "hard-link":
            path.unlink()
        assert not (await client.call_tool("read_document", {"document_id": "paper.pdf"})).is_error


@pytest.mark.asyncio
async def test_nested_approved_and_internal_symlink_rejected(corpus):
    root, manifest = corpus
    (root / "nested").mkdir()
    make_pdf(root / "nested/paper.pdf")
    (root / "alias.pdf").symlink_to(root / "paper.pdf")
    write_catalog(manifest, ["paper.pdf", "nested/paper.pdf", "alias.pdf"])
    async with Client(workspace.create_server()) as client:
        result = await client.call_tool("list_documents", {})
        assert [item["document_id"] for item in result.structured_content["documents"]] == [
            "nested/paper.pdf",
            "paper.pdf",
        ]
        assert not (
            await client.call_tool("read_document", {"document_id": "nested/paper.pdf"})
        ).is_error
        assert (
            await client.call_tool(
                "read_document", {"document_id": "alias.pdf"}, raise_on_error=False
            )
        ).is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "invalid", "too-large", "too-many", "duplicate"])
async def test_catalog_errors_are_safe(corpus, monkeypatch, kind):
    root, manifest = corpus
    if kind == "missing":
        manifest.unlink()
    elif kind == "invalid":
        manifest.write_text("not JSON")
    elif kind == "too-large":
        monkeypatch.setattr(workspace, "MAX_MANIFEST_BYTES", 1)
    elif kind == "too-many":
        monkeypatch.setattr(workspace, "MAX_DOCUMENTS", 0)
    else:
        write_catalog(manifest, ["paper.pdf", "paper.pdf"])
    async with Client(workspace.create_server()) as client:
        failed = await client.call_tool("list_documents", {}, raise_on_error=False)
        assert failed.is_error
        assert str(root.parent) not in str(failed)


@pytest.mark.asyncio
async def test_empty_catalog_and_pdf_page_limit(corpus, monkeypatch):
    _, manifest = corpus
    write_catalog(manifest, [])
    async with Client(workspace.create_server()) as client:
        assert (await client.call_tool("list_documents", {})).structured_content == {
            "documents": []
        }
        write_catalog(manifest, ["paper.pdf"])
        monkeypatch.setattr(workspace, "MAX_PDF_PAGES", 2)
        assert (
            await client.call_tool(
                "read_document", {"document_id": "paper.pdf"}, raise_on_error=False
            )
        ).is_error
        assert (await client.call_tool("list_documents", {})).structured_content == {
            "documents": []
        }


@pytest.mark.asyncio
async def test_concurrent_reads_and_worker_thread(corpus, monkeypatch):
    real_read = workspace._read_document
    loop_thread = threading.get_ident()
    workers = set()

    def read(*args):
        workers.add(threading.get_ident())
        assert threading.get_ident() != loop_thread
        return real_read(*args)

    monkeypatch.setattr(workspace, "_read_document", read)
    async with Client(workspace.create_server()) as client:
        results = await asyncio.gather(
            *[client.call_tool("read_document", {"document_id": "paper.pdf"}) for _ in range(4)]
        )
        assert all(result.structured_content["pages"][0]["text"] == TEXTS[0] for result in results)
    assert workers


@pytest.mark.asyncio
async def test_symlink_swap_between_lookup_and_open(corpus, monkeypatch, tmp_path):
    root, _ = corpus
    outside = tmp_path / "outside.pdf"
    make_pdf(outside, ["Outside secret"])
    actual_open = workspace.os.open

    def swap(path, flags, *args, **kwargs):
        if path == "paper.pdf":
            (root / "paper.pdf").rename(root / "saved.pdf")
            (root / "paper.pdf").symlink_to(outside)
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(workspace.os, "open", swap)
    async with Client(workspace.create_server()) as client:
        result = await client.call_tool(
            "read_document", {"document_id": "paper.pdf"}, raise_on_error=False
        )
        assert result.is_error
        assert "Outside secret" not in str(result)


@pytest.mark.asyncio
async def test_missing_corpus_root(corpus):
    root, _ = corpus
    (root / "paper.pdf").unlink()
    root.rmdir()
    async with Client(workspace.create_server()) as client:
        assert (await client.call_tool("list_documents", {})).structured_content == {
            "documents": []
        }
        assert (
            await client.call_tool(
                "read_document", {"document_id": "paper.pdf"}, raise_on_error=False
            )
        ).is_error


@pytest.mark.asyncio
async def test_stdio_tools_calls_security_and_recovery(corpus, tmp_path):
    root, manifest = corpus
    outside = tmp_path / "outside.pdf"
    make_pdf(outside, ["Outside secret"])
    (root / "escape.pdf").symlink_to(outside)
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    make_pdf(root / ".hidden.pdf")
    make_pdf(root / "credentials.pdf")
    (root / "directory.pdf").mkdir()
    (root / "bad.pdf").write_bytes(b"invalid PDF")
    with (root / "oversized.pdf").open("wb") as stream:
        stream.truncate(workspace.MAX_FILE_BYTES + 1)
    (root / "notes.txt").write_text("Private note")
    write_catalog(
        manifest,
        [
            "paper.pdf",
            "escape.pdf",
            "linked/outside.pdf",
            ".hidden.pdf",
            "credentials.pdf",
            "directory.pdf",
            "bad.pdf",
            "oversized.pdf",
            "missing.pdf",
            "notes.txt",
        ],
    )
    before = hashlib.sha256((root / "paper.pdf").read_bytes()).hexdigest()
    diagnostics = tmp_path / "stderr.log"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "veridex.mcp.servers.workspace"],
        cwd=ROOT,
        env={
            "PYTHONPATH": str(ROOT / "src"),
            "DOCUMENTS_DIR": str(root),
            "WORKSPACE_MANIFEST_PATH": str(manifest),
            "OPENAI_API_KEY": "",
            "TAVILY_API_KEY": "",
        },
    )
    with diagnostics.open("w", encoding="utf-8") as errlog:
        async with (
            asyncio.timeout(30),
            stdio_client(parameters, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "Veridex Workspace"
            tools = (await session.list_tools()).tools
            assert [tool.name for tool in tools] == ["list_documents", "read_document"]
            assert all(tool.annotations.readOnlyHint for tool in tools)
            assert all(tool.annotations.destructiveHint is False for tool in tools)
            assert tools[0].inputSchema == {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
            schema = tools[1].inputSchema
            assert schema["required"] == ["document_id"]
            assert schema["additionalProperties"] is False
            assert schema["properties"]["document_id"] == {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
            }
            assert schema["properties"]["max_chars"] == {
                "type": "integer",
                "minimum": 1,
                "maximum": 20000,
                "default": 12000,
            }
            assert tools[1].outputSchema["properties"]["pages"]["type"] == "array"
            for _ in range(2):
                listed = await session.call_tool("list_documents", {})
                assert not listed.isError
                assert [doc["document_id"] for doc in listed.structuredContent["documents"]] == [
                    "paper.pdf"
                ]
                result = await session.call_tool(
                    "read_document",
                    {
                        "document_id": "paper.pdf",
                        "start_page": 2,
                        "end_page": 2,
                    },
                )
                assert not result.isError
                assert result.structuredContent["pages"] == [{"page": 2, "text": TEXTS[1]}]
                assert str(root) not in str(result)
                assert (
                    result.structuredContent["document"]["source_url"]
                    == "https://example.com/paper?x=1#section"
                )
            truncation = await session.call_tool(
                "read_document", {"document_id": "paper.pdf", "max_chars": 5}
            )
            assert truncation.structuredContent["truncated"]
            for args in INVALID_ARGUMENTS:
                assert (await session.call_tool("read_document", args)).isError
            rejected = [
                *INVALID_IDS[:-1],
                str(root / "paper.pdf"),
                "missing.pdf",
                "escape.pdf",
                "linked/outside.pdf",
                "directory.pdf",
                "oversized.pdf",
                "bad.pdf",
            ]
            for document_id in rejected:
                failed = await session.call_tool("read_document", {"document_id": document_id})
                assert failed.isError
                # Argument validation may echo its own input; filesystem errors never disclose paths.
                if document_id and len(document_id) <= 256:
                    assert str(tmp_path) not in str(failed)
                assert "Outside secret" not in str(failed)
                assert not (
                    await session.call_tool("read_document", {"document_id": "paper.pdf"})
                ).isError
            reads = await asyncio.gather(
                *[
                    session.call_tool("read_document", {"document_id": "paper.pdf"})
                    for _ in range(3)
                ]
            )
            assert all(result.structuredContent["pages"][0]["text"] == TEXTS[0] for result in reads)
            # Strictly read-only tools: unknown write tools and unexpected inputs are rejected.
            assert (await session.call_tool("write_document", {"document_id": "paper.pdf"})).isError
            assert (await session.call_tool("list_documents", {"path": str(tmp_path)})).isError
            assert not (await session.call_tool("list_documents", {})).isError
    assert hashlib.sha256((root / "paper.pdf").read_bytes()).hexdigest() == before
    stderr = diagnostics.read_text(encoding="utf-8")
    assert "Starting MCP server" in stderr
    assert str(tmp_path) not in stderr


@pytest.mark.integration
@pytest.mark.asyncio
async def test_local_research_corpus():
    # Filesystem-only integration: no OpenAI/Tavily requests or Chroma access.
    if not (
        workspace.settings.documents_dir.is_dir()
        and workspace.settings.workspace_manifest_path.is_file()
    ):
        pytest.skip("Local research corpus unavailable")
    async with Client(workspace.create_server()) as client:
        listed = await client.call_tool("list_documents", {})
        documents = listed.structured_content["documents"]
        assert documents
        for doc in documents:
            result = await client.call_tool(
                "read_document",
                {
                    "document_id": doc["document_id"],
                    "start_page": 1,
                    "end_page": 1,
                    "max_chars": 2000,
                },
            )
            assert result.structured_content["document"] == doc
            assert result.structured_content["pages"][0]["text"]
            assert len(result.structured_content["pages"][0]["text"]) <= 2000
