"""Source-only submission contract; never reads or packages external corpus files."""

import ast
import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gcloudignore",
    ".gitignore",
    ".python-version",
    "Dockerfile",
    "PROCESS_LOG.md",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "CORPUS_LICENSE_NOTICE.md",
}
REQUIRED = {
    "Dockerfile",
    "README.md",
    "PROCESS_LOG.md",
    "pyproject.toml",
    "requirements.txt",
    ".env.example",
    "uv.lock",
    "deploy/cloud_run.sh",
    "scripts/serve_api.py",
    "scripts/check_bundle.py",
    "src/veridex/api/app.py",
    "src/veridex/agents/service.py",
    "src/veridex/agents/graph.py",
    "src/veridex/llm/router.py",
    "src/veridex/state/store.py",
    "src/veridex/mcp/client.py",
    "src/veridex/mcp/servers/evidence.py",
    "src/veridex/mcp/servers/workspace.py",
    "src/veridex/mcp/servers/catalog.py",
    "src/veridex/web/static/index.html",
    "data/corpus_v3/papers.json",
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
            or (path.parts[:2] == (".github", "workflows") and path.suffix == ".yml")
        )
        allowed = (
            name in ROOT_FILES
            or name == ".github/pull_request_template.md"
            or (
                path.parts[:2] == (".github", "workflows")
                and len(path.parts) == 3
                and path.suffix == ".yml"
            )
            or (path.parts[0] in {"src", "scripts", "tests"} and path.suffix == ".py")
            or (
                path.parts[:4] == ("src", "veridex", "web", "static")
                and len(path.parts) == 5
                and path.suffix in {".html", ".css", ".js"}
            )
            or (path.parts[0] == "deploy" and len(path.parts) == 2 and path.suffix == ".sh")
            or (
                path.parts[0] == "docs"
                and len(path.parts) == 2
                and path.suffix in {".md", ".mmd", ".json"}
                and path.name != "development_notes.md"
            )
            or (
                path.parts[:2] == ("docs", "v1")
                and len(path.parts) == 3
                and path.suffix in {".md", ".json"}
            )
            or name
            in {
                "data/samples/manifest.json",
                "data/samples/eval_questions.json",
                "data/corpus_v3/papers.json",
            }
        )
        assert allowed, f"Unapproved source-package path: {name}"


@pytest.fixture(scope="module")
def source_names():
    if not (ROOT / ".git").exists():
        # Extracted source packages have no Git inventory. Inspect their source
        # directories, excluding only bytecode generated while running these tests.
        names = {name for name in ROOT_FILES if (ROOT / name).is_file()}
        for directory in [
            "src",
            "scripts",
            "tests",
            "docs",
            "data/samples",
            "data/corpus_v3",
            "deploy",
            ".github",
        ]:
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


def test_container_runs_the_api_as_non_root_from_pinned_requirements():
    runner = ast.parse((ROOT / "scripts/serve_api.py").read_text())
    calls = [node for node in ast.walk(runner) if isinstance(node, ast.Call)]
    uvicorn_call = next(
        node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "run"
    )
    assert ast.literal_eval(uvicorn_call.args[0]) == "veridex.api.app:app"
    keywords = {kw.arg: kw.value for kw in uvicorn_call.keywords}
    assert ast.literal_eval(keywords["host"]) == "0.0.0.0"
    dockerfile = (ROOT / "Dockerfile").read_text()
    lines = dockerfile.splitlines()
    assert sum(line.startswith("FROM python:3.13") for line in lines) == 2  # multi-stage
    assert "pip install --no-cache-dir --no-compile --prefix=/install -r requirements.txt" in (
        dockerfile
    )
    assert "USER 10001:10001" in lines
    cmd = next(line for line in lines if line.startswith("CMD "))
    assert json.loads(cmd.removeprefix("CMD ")) == ["python", "scripts/serve_api.py"]
    assert "RUN python -m compileall -q src && python scripts/check_bundle.py" in lines


def test_requirements_pin_exact_versions():
    requirements = [
        line
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line and not line.startswith(("#", " "))
    ]
    assert len(requirements) > 50
    assert all("==" in line and ">=" not in line and "~=" not in line for line in requirements)
    names = {line.split("==")[0].split("[")[0] for line in requirements}
    for package in (
        "langgraph",
        "langchain-openai",
        "langchain-google-genai",
        "fastapi",
        "chromadb",
    ):
        assert package in names


def test_sensitive_sources_are_excluded_but_the_bundle_is_uploaded():
    for name in (".dockerignore", ".gcloudignore"):
        assert (ROOT / name).is_file()
    exclusions = set((ROOT / ".dockerignore").read_text().splitlines())
    assert {".env", ".env.*", ".git", "/tests", "/docs", "/.artifacts/*", "/data/*"} <= exclusions
    assert {
        "!/.artifacts/corpus_v3/papers",
        "!/.artifacts/corpus_v3/chroma",
        "!/.artifacts/corpus_v3/catalog.db",
        "!/data/corpus_v3/papers.json",
    } <= exclusions
    # Unanchored directory patterns would also drop nested sources (src/veridex/data) in gcloud.
    for pattern in ("data", "data/*", "tests", "docs", ".artifacts/*"):
        assert pattern not in exclusions
    assert "#!include:.dockerignore" in (ROOT / ".gcloudignore").read_text()


def test_deploy_script_uses_secrets_and_bounded_scaling():
    script = (ROOT / "deploy/cloud_run.sh").read_text()
    assert "--set-secrets=" in script and "OPENAI_API_KEY=openai-api-key" in script
    assert "--max-instances=3" in script and "--timeout=300" in script
    assert "STATE_BACKEND=firestore" in script
    assert "sk-" not in script and "tvly-" not in script


def test_submission_docs_parse_and_local_links_resolve():
    parser = MarkdownIt("commonmark")
    for name in ["docs/corpus_v3.md"]:
        path = ROOT / name
        text = path.read_text()
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
