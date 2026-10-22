"""Polite, resumable arXiv PDF download with a SHA-256 lock file."""

import hashlib
import json
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from veridex.rag.v3.manifest import Manifest

USER_AGENT = "veridex-corpus-v3/2.0 (coursework corpus builder)"
# arXiv asks automated clients to wait at least 3 seconds between requests.
REQUEST_INTERVAL_SECONDS = 3.0
MAX_PDF_BYTES = 40 * 1024 * 1024
LOCK_FILE = "downloads.json"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError(f"PDF larger than {MAX_PDF_BYTES} bytes: {url}")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_papers(
    manifest: Manifest,
    papers_dir: Path,
    *,
    fetch: Callable[[str], bytes] = _fetch,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict[str, dict]:
    """Download missing PDFs; files already recorded in the lock must still match it."""
    papers_dir.mkdir(parents=True, exist_ok=True)
    lock_path = papers_dir / LOCK_FILE
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    unknown = set(lock) - {paper.doc_id for paper in manifest.papers}
    if unknown:
        raise ValueError(f"Lock lists papers not in the manifest: {sorted(unknown)}")
    first_request = True
    for paper in manifest.papers:
        target = papers_dir / paper.filename
        if paper.doc_id in lock and target.exists():
            if sha256(target.read_bytes()) != lock[paper.doc_id]["sha256"]:
                raise ValueError(f"{target.name} differs from its recorded SHA-256.")
            continue
        if not first_request:
            sleep(REQUEST_INTERVAL_SECONDS)
        first_request = False
        data = fetch(paper.pdf_url)
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"{paper.pdf_url} did not return a PDF.")
        temporary = target.with_suffix(".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        lock[paper.doc_id] = {
            "arxiv_id": paper.arxiv_id,
            "url": paper.pdf_url,
            "bytes": len(data),
            "sha256": sha256(data),
        }
        # Persist after every file so an interrupted run resumes without refetching.
        lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
        log(f"downloaded {paper.doc_id} ({len(data):,} bytes)")
    return lock
