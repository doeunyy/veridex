"""Source-only submission archive of a frozen Git commit; no corpus, index, or secrets."""

import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from veridex.rag.artifacts import ArtifactError

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
        "requirements.txt",
        ".gcloudignore",
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
        "requirements.txt",
        ".env.example",
        "deploy/cloud_run.sh",
        "scripts/serve_api.py",
        "scripts/check_bundle.py",
        "src/veridex/agents/graph.py",
        "src/veridex/mcp/servers/evidence.py",
        "src/veridex/mcp/servers/workspace.py",
        "src/veridex/mcp/servers/catalog.py",
        "data/corpus_v3/papers.json",
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
        or (
            p.parts[:4] == ("src", "veridex", "web", "static")
            and len(p.parts) == 5
            and p.suffix in {".html", ".css", ".js"}
        )
        or (p.parts[0] == "docs" and len(p.parts) == 2 and p.suffix in {".md", ".mmd", ".json"})
        or (p.parts[:2] == ("docs", "v1") and len(p.parts) == 3 and p.suffix in {".md", ".json"})
        or (p.parts[0] == "deploy" and len(p.parts) == 2 and p.suffix == ".sh")
        or name
        in {
            "data/samples/manifest.json",
            "data/samples/eval_questions.json",
            "data/corpus_v3/papers.json",
        }
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
                "tests/test_mcp_multi_server.py",
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


def plan_archive(source: dict[str, bytes], *, commit: str, timestamp: int) -> ArchivePlan:
    check_source(source)
    return ArchivePlan(dict(source), commit, timestamp, "source-only")


def write_archive(plan: ArchivePlan, output: Path) -> None:
    """Explicit write only; never overwrite an existing archive or include directory contents."""
    if output.suffix != ".zip" or output.exists():
        raise ArtifactError("A new ZIP output path is required; existing archives are immutable.")
    check_source(plan.files)
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
