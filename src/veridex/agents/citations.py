"""Collect sources from tool results and keep the ones an answer actually cites."""

import json
import re

from langchain_core.messages import ToolMessage

# Matches IDs in [a:p1:c000] and in grouped forms such as [a:p1:c000, b:p2:c003].
_CHUNK_REF = re.compile(r"\b([a-z0-9_]+_\d{4}:p\d+:c\d+)\b")
_PAGE_REF = re.compile(r"\[([a-z0-9_]+_\d{4}) p\.(\d+)\]")
_SNIPPET = 280


def _payload(message: ToolMessage) -> dict | None:
    artifact = message.artifact
    if isinstance(artifact, dict) and isinstance(artifact.get("structured_content"), dict):
        return artifact["structured_content"]
    content = message.content
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def collect_sources(message: ToolMessage, sources: dict[str, dict]) -> None:
    """Add corpus chunks, read pages and web results from one tool result."""
    if message.status == "error":
        return
    payload = _payload(message)
    if not payload:
        return
    for passage in payload.get("passages", []):
        sources[passage["chunk_id"]] = {
            "kind": "corpus",
            "id": passage["chunk_id"],
            "document_id": passage["document_id"],
            "title": passage["title"],
            "page": passage["page"],
            "url": passage["source_url"],
            "snippet": passage["content"][:_SNIPPET],
        }
    document = payload.get("document")
    if isinstance(document, dict):
        for page in payload.get("pages", []):
            key = f"{document['paper_id']} p.{page['page']}"
            sources[key] = {
                "kind": "page",
                "id": key,
                "document_id": document["paper_id"],
                "title": document["title"],
                "page": page["page"],
                "url": document["source_url"],
                "snippet": page["text"][:_SNIPPET],
            }
    for result in payload.get("results", []):
        if isinstance(result, dict) and result.get("url"):
            sources[result["url"]] = {
                "kind": "web",
                "id": result["url"],
                "title": result.get("title") or result["url"],
                "url": result["url"],
                "snippet": (result.get("content") or "")[:_SNIPPET],
            }


def cited(answer: str, sources: dict[str, dict]) -> list[dict]:
    """Sources referenced in the answer, in order of first mention, without duplicates."""
    found: list[str] = []
    for match in _CHUNK_REF.finditer(answer):
        found.append(match.group(1))
    for match in _PAGE_REF.finditer(answer):
        found.append(f"{match.group(1)} p.{match.group(2)}")
    for key, source in sources.items():
        if source["kind"] == "web" and key in answer:
            found.append(key)
    ordered = sorted(dict.fromkeys(found), key=lambda key: _position(answer, key))
    return [sources[key] for key in ordered if key in sources]


def _position(answer: str, key: str) -> int:
    index = answer.find(key)
    return index if index >= 0 else len(answer)
