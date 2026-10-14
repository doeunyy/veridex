"""Source-only submission contract; never reads or packages external corpus files."""

import ast
import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SHA256 = "7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb"
ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    ".python-version",
    "Dockerfile",
    "PROCESS_LOG.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
}
REQUIRED = ROOT_FILES | {
    "scripts/serve_api.py",
    "scripts/container_entrypoint.py",
    "scripts/check_container.py",
    "scripts/prepare_notices.py",
    "scripts/rebuild_corpus_v2.py",
    "src/veridex/api/app.py",
    "src/veridex/agent/mcp_service.py",
    "src/veridex/framework_logging.py",
    "src/veridex/deployment/runtime.py",
    "src/veridex/deployment/notices/CC-BY-4.0.txt",
    "src/veridex/deployment/notices/CC-BY-NC-4.0.txt",
    "src/veridex/mcp/client.py",
    "src/veridex/mcp/servers/evidence.py",
    "src/veridex/mcp/servers/web_search.py",
    "src/veridex/mcp/servers/workspace.py",
    "docs/agent_graph.mmd",
    "docs/corpus_v2.md",
    "docs/docker_local.md",
    "docs/rag_attribution_v2.json",
    "data/samples/manifest.json",
    "tests/test_mcp_malformed_responses.py",
    "tests/test_submission_packaging.py",
}


def validate_source_names(names):
    """Fail on unreviewed paths rather than silently filtering unsafe archive entries."""
    for name in names:
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert name == path.as_posix() and "\\" not in name
        assert path.name.lower() not in {"credentials.json", "service-account.json"}
        assert (
            not any(part.startswith(".") for part in path.parts)
            or name in ROOT_FILES
            or (name == ".github/pull_request_template.md")
        )
        allowed = (
            name in ROOT_FILES
            or name == ".github/pull_request_template.md"
            or (path.parts[0] in {"src", "scripts", "tests"} and path.suffix == ".py")
            or (
                path.parts[:4] == ("src", "veridex", "deployment", "notices")
                and path.name in {"CC-BY-4.0.txt", "CC-BY-NC-4.0.txt"}
            )
            or (
                path.parts[0] == "docs"
                and len(path.parts) == 2
                and path.suffix in {".md", ".mmd", ".json"}
                and path.name != "development_notes.md"
            )
            or name in {"data/samples/manifest.json", "data/samples/eval_questions.json"}
        )
        assert allowed, f"Unapproved source-package path: {name}"


@pytest.fixture(scope="module")
def source_names():
    if not (ROOT / ".git").exists():
        # Extracted source packages have no Git inventory. Inspect their source
        # directories, excluding only bytecode generated while running these tests.
        names = {name for name in ROOT_FILES if (ROOT / name).is_file()}
        for directory in ["src", "scripts", "tests", "docs", "data/samples", ".github"]:
            names.update(
                p.relative_to(ROOT).as_posix()
                for p in (ROOT / directory).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            )
        return names
    # Read-only Git inventory includes pending tests without adding them to the index.
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return {
        name
        for raw in result.stdout.split(b"\0")
        if raw and (ROOT / (name := raw.decode())).exists()
    }


def test_reviewed_source_inventory_contains_runtime_and_submission_files(source_names):
    validate_source_names(source_names)
    assert REQUIRED <= source_names
    for name in source_names:
        path = ROOT / name
        assert not path.is_symlink() and path.is_file()
        assert path.stat().st_size < 2_000_000
    assert all((ROOT / name).stat().st_size for name in REQUIRED)


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.production",
        ".git/config",
        ".aws/credentials",
        ".agents/private.md",
        ".codex/config.toml",
        ".venv/bin/python",
        "src/veridex/__pycache__/app.pyc",
        "tests/.pytest_cache/state.json",
        "credentials.json",
        "service-account.json",
        "docs/credentials.json",
        "docs/service-account.json",
        "scripts/private.key",
        "docs/development_notes.md",
        "data/papers/react_2022.pdf",
        "data/index/chroma.sqlite3",
        ".artifacts/versions/veridex-rag-v2-local/bundle.json",
        ".docker-artifacts/report.json",
        "logs/server.log",
        "../README.md",
        "/README.md",
        "docs/../README.md",
        "docs\\corpus_v2.md",
        "main.py",
    ],
)
def test_sensitive_generated_and_unsafe_package_paths_rejected(name):
    with pytest.raises(AssertionError):
        validate_source_names({name})


def test_empty_scaffold_removed_and_existing_entrypoints_preserved():
    assert not (ROOT / "main.py").exists()
    runner = ast.parse((ROOT / "scripts/serve_api.py").read_text())
    calls = [node for node in ast.walk(runner) if isinstance(node, ast.Call)]
    uvicorn_call = next(
        node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "run"
    )
    assert ast.literal_eval(uvicorn_call.args[0]) == "veridex.api.app:app"
    keywords = {kw.arg: kw.value for kw in uvicorn_call.keywords}
    assert ast.literal_eval(keywords["workers"]) == 1
    assert ast.literal_eval(keywords["host"]) == "0.0.0.0"
    dockerfile = (ROOT / "Dockerfile").read_text()
    entrypoint = next(line for line in dockerfile.splitlines() if line.startswith("ENTRYPOINT "))
    assert json.loads(entrypoint.removeprefix("ENTRYPOINT ")) == [
        "/opt/venv/bin/python",
        "/app/scripts/container_entrypoint.py",
    ]
    assert '"/app/scripts/serve_api.py"' in (ROOT / "src/veridex/deployment/runtime.py").read_text()


def test_external_corpus_dependency_and_named_context_are_documented():
    for name in ["README.md", "docs/corpus_v2.md", "docs/docker_local.md"]:
        text = (ROOT / name).read_text()
        assert BUNDLE_SHA256 in text
        assert "external" in text.lower() and "source ZIP" in text
        assert "bundle.json" in text and "manifest.json" in text and "chroma/" in text
        assert "rag" in text and "named" in text and "586" in text
        assert "scripts/ingest.py" in text and "v1" in text.lower()
    docker_doc = (ROOT / "docs/docker_local.md").read_text()
    assert '--bundle "$RAG_BUNDLE_DIR"' in docker_doc
    assert '--build-context "rag=$RAG_BUNDLE_DIR"' in docker_doc
    assert "no build step re-ingests or re-embeds" in docker_doc
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert BUNDLE_SHA256 in dockerfile and "COPY --from=rag /chroma/" in dockerfile
    assert "/papers/rag_long_context_2024.pdf" in dockerfile


def test_sensitive_sources_are_excluded_from_default_docker_context():
    exclusions = set((ROOT / ".dockerignore").read_text().splitlines())
    assert {".env", ".env.*", ".git", "data", ".artifacts", ".docker-artifacts", "docs"} <= (
        exclusions
    )
    assert "!.env.example" in exclusions


def test_submission_docs_parse_and_local_links_resolve():
    parser = MarkdownIt("commonmark")
    for name in ["README.md", "docs/corpus_v2.md", "docs/docker_local.md"]:
        path = ROOT / name
        text = path.read_text()
        assert "[TO CONFIRM]" not in text
        tokens = parser.parse(text)
        for token in tokens:
            for child in token.children or []:
                if child.type != "link_open":
                    continue
                href = child.attrGet("href")
                if "://" in href or href.startswith("#"):
                    continue
                assert (path.parent / href.split("#", 1)[0]).is_file(), href
        assert text.count("```") % 2 == 0
