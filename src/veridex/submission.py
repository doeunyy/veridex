"""Explicit source-only or private coursework archive plans; no runtime changes."""

import hashlib
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from veridex.deployment.runtime import BUNDLE_SHA256, SPEC
from veridex.rag.artifacts import ArtifactError, validate_bundle

PREFIX = "submission_artifacts/veridex-rag-v2-local"
VECTOR_DIR = "chroma/d3bcc165-69e4-4140-b0b7-f0682afdb815"
BUNDLE_FILES = frozenset(
    {"bundle.json", "manifest.json", "chroma/chroma.sqlite3"}
    | {f"papers/{identifier}.pdf" for identifier in SPEC.document_ids}
    | {
        f"{VECTOR_DIR}/{name}"
        for name in ("header.bin", "data_level0.bin", "length.bin", "link_lists.bin")
    }
)
ROOT_FILES = frozenset(
    {
        ".dockerignore",
        ".env.example",
        ".gitignore",
        ".python-version",
        "Dockerfile",
        "README.md",
        "PROCESS_LOG.md",
        "pyproject.toml",
        "uv.lock",
        "CORPUS_LICENSE_NOTICE.md",
    }
)
REQUIRED = frozenset(
    {
        "README.md",
        "PROCESS_LOG.md",
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "scripts/serve_api.py",
        "scripts/container_entrypoint.py",
        "src/veridex/mcp/servers/evidence.py",
        "src/veridex/mcp/servers/web_search.py",
        "src/veridex/mcp/servers/workspace.py",
        "docs/rag_attribution_v2.json",
        "src/veridex/deployment/notices/CC-BY-4.0.txt",
        "src/veridex/deployment/notices/CC-BY-NC-4.0.txt",
    }
)
CREDENTIAL = re.compile(
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|tvly-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
)


def source_path(name: str) -> bool:
    p = PurePosixPath(name)
    if not p.parts or p.is_absolute() or str(p) != name or ".." in p.parts or "\\" in name:
        return False
    if any(part in {"node_modules", "__pycache__", "venv", "build", "dist"} for part in p.parts):
        return False
    if any(part.startswith(".") for part in p.parts) and name not in ROOT_FILES:
        return name == ".github/pull_request_template.md" or (
            p.parts[:2] == (".github", "workflows") and len(p.parts) == 3 and p.suffix == ".yml"
        )
    if p.name in {"credentials.json", "service-account.json", "development_notes.md"}:
        return False
    return (
        name in ROOT_FILES
        or (p.parts[0] in {"src", "scripts", "tests"} and p.suffix == ".py")
        or (p.parts[0] == "docs" and len(p.parts) == 2 and p.suffix in {".md", ".mmd", ".json"})
        or (p.parts[:2] == ("docs", "v1") and len(p.parts) == 3 and p.suffix in {".md", ".json"})
        or (
            p.parts[:4] == ("src", "veridex", "deployment", "notices")
            and p.name in {"CC-BY-4.0.txt", "CC-BY-NC-4.0.txt"}
        )
        or name in {"data/samples/manifest.json", "data/samples/eval_questions.json"}
    )


def check_source(files: dict[str, bytes]) -> None:
    if not REQUIRED <= files.keys():
        raise ArtifactError("Required submission source files are missing.")
    for name, data in files.items():
        if not source_path(name):
            raise ArtifactError("Unapproved source-package path.")
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            raise ArtifactError("Binary content is not approved source.") from None
        if "\0" in text:
            raise ArtifactError("Binary content is not approved source.")
        for match in CREDENTIAL.finditer(text):
            if (name, match.group()) != (
                "tests/test_mcp_web_search.py",
                "tvly-" + "test-secret-never-log",
            ):
                raise ArtifactError("Credential-like material in submission source.")


@dataclass(frozen=True)
class ArchivePlan:
    files: dict[str, bytes]
    commit: str
    timestamp: int
    mode: str


def read_git_source(root: Path, ref: str) -> tuple[dict[str, bytes], str, int]:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])

    # Resolve once; all reads use this frozen commit, never the working directory.
    commit = git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
    files = {}
    for row in git("ls-tree", "-rz", commit).split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ArtifactError("Symlinks and submodules are not approved submission source.")
        files[name.decode()] = git("cat-file", "blob", oid)
    return files, commit, int(git("show", "-s", "--format=%ct", commit))


def plan_archive(
    source: dict[str, bytes],
    *,
    commit: str,
    timestamp: int,
    mode: str = "source-only",
    bundle: Path | None = None,
) -> ArchivePlan:
    check_source(source)
    files = dict(source)
    if mode == "source-only":
        if bundle is not None:
            raise ArtifactError("Source-only mode cannot include a corpus bundle.")
    elif mode == "coursework":
        if bundle is None or "CORPUS_LICENSE_NOTICE.md" not in files:
            raise ArtifactError("Coursework mode requires the approved bundle and root notice.")
        # Capture exact immutable bytes first. Validate then recompare to reject source drift.
        paths = set()
        for p in bundle.rglob("*"):
            if p.is_symlink():
                raise ArtifactError("Bundle symlinks are forbidden.")
            if p.is_file():
                paths.add(p.relative_to(bundle).as_posix())
        if bundle.is_symlink() or paths != BUNDLE_FILES:
            raise ArtifactError("Coursework bundle inventory is not the approved twelve files.")
        captured = {name: (bundle / name).read_bytes() for name in paths}
        if hashlib.sha256(captured["bundle.json"]).hexdigest() != BUNDLE_SHA256:
            raise ArtifactError("Coursework bundle fingerprint mismatch.")
        metadata = json.loads(captured["bundle.json"])
        if hashlib.sha256(files["uv.lock"]).hexdigest() != metadata["lock_sha256"]:
            raise ArtifactError("Submission lockfile differs from the approved bundle.")
        validate_bundle(bundle, expected=SPEC, metadata_sha256=BUNDLE_SHA256, probe=False)
        for name in paths:
            if (bundle / name).read_bytes() != captured[name]:
                raise ArtifactError("Bundle changed during submission validation.")
        if (
            any(p.is_symlink() for p in bundle.rglob("*"))
            or {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
            != BUNDLE_FILES
        ):
            raise ArtifactError("Bundle inventory changed during submission validation.")
        for name, data in captured.items():
            if name != "bundle.json":
                record = metadata["files"][name]
                if (
                    len(data) != record["size"]
                    or hashlib.sha256(data).hexdigest() != record["sha256"]
                ):
                    raise ArtifactError("Coursework artifact checksum mismatch.")
            files[f"{PREFIX}/{name}"] = data
    else:
        raise ArtifactError("Unknown submission mode.")
    return ArchivePlan(files, commit, timestamp, mode)


def write_archive(plan: ArchivePlan, output: Path) -> None:
    """Explicit write only; never overwrite an existing archive or include directory contents."""
    if output.suffix != ".zip" or output.exists():
        raise ArtifactError("A new ZIP output path is required; existing archives are immutable.")
    source = {name: data for name, data in plan.files.items() if not name.startswith(PREFIX + "/")}
    check_source(source)
    corpus = {
        name.removeprefix(PREFIX + "/"): data
        for name, data in plan.files.items()
        if name.startswith(PREFIX + "/")
    }
    if plan.mode == "source-only" and corpus:
        raise ArtifactError("Source-only archives cannot contain corpus entries.")
    if plan.mode == "coursework":
        if set(corpus) != BUNDLE_FILES or "CORPUS_LICENSE_NOTICE.md" not in source:
            raise ArtifactError("Invalid coursework entry inventory.")
        if hashlib.sha256(corpus["bundle.json"]).hexdigest() != BUNDLE_SHA256:
            raise ArtifactError("Coursework bundle fingerprint mismatch.")
        metadata = json.loads(corpus["bundle.json"])
        if hashlib.sha256(source["uv.lock"]).hexdigest() != metadata["lock_sha256"]:
            raise ArtifactError("Submission lockfile differs from the approved bundle.")
        for name, data in corpus.items():
            if name != "bundle.json":
                record = metadata["files"][name]
                if (
                    hashlib.sha256(data).hexdigest() != record["sha256"]
                    or len(data) != record["size"]
                ):
                    raise ArtifactError("Coursework entry checksum mismatch.")
    elif plan.mode != "source-only":
        raise ArtifactError("Unknown submission mode.")
    date = datetime.fromtimestamp(plan.timestamp, UTC).timetuple()[:6]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        try:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, data in sorted(plan.files.items()):
                    info = zipfile.ZipInfo(name, date)
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, data, compresslevel=9)
        except BaseException:
            output.unlink(missing_ok=True)  # Only the newly created incomplete output.
            raise
