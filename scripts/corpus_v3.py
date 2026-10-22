"""Build Corpus v3: download -> plan (free, offline) -> build (paid, needs --max-usd).

uv run python scripts/corpus_v3.py download
uv run python scripts/corpus_v3.py plan
uv run python scripts/corpus_v3.py build --max-usd 0.05
uv run python scripts/corpus_v3.py catalog
"""

import argparse
import json
from pathlib import Path

from veridex.rag.v3.manifest import DEFAULT_MANIFEST, load_manifest

ROOT = Path(".artifacts/corpus_v3")
BATCH_SIZE = 100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download", help="Fetch missing arXiv PDFs and record SHA-256s.")
    commands.add_parser("plan", help="Chunk the PDFs and estimate embedding cost (no API).")
    build = commands.add_parser("build", help="Embed the planned chunks into a new Chroma index.")
    build.add_argument("--max-usd", type=float, required=True, help="Refuse above this estimate.")
    commands.add_parser("catalog", help="Write the SQLite paper catalog from the plan (no API).")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    papers_dir, plan_dir, index_dir = (args.root / n for n in ("papers", "plan", "chroma"))

    if args.command == "download":
        from veridex.rag.v3.download import download_papers

        lock = download_papers(manifest, papers_dir)
        print(f"{len(lock)} PDFs in {papers_dir}")
    elif args.command == "plan":
        from veridex.rag.v3.index import write_plan
        from veridex.rag.v3.pipeline import embedding_plan, ingest

        chunks = ingest(manifest, papers_dir)
        plan = embedding_plan(chunks, BATCH_SIZE)
        write_plan(chunks, plan, plan_dir)
        summary = {k: plan[k] for k in ("documents", "chunks", "tokens", "requests")}
        print(json.dumps(summary | {"estimated_usd": plan["estimated_usd"]}, indent=2))
    elif args.command == "catalog":
        from veridex.data.catalog import build_catalog

        plan = json.loads((plan_dir / "plan.json").read_text())
        count = build_catalog(manifest, plan["per_document"], args.root / "catalog.db")
        print(f"{count} papers in {args.root / 'catalog.db'}")
    else:
        from veridex.rag.embeddings import get_embeddings
        from veridex.rag.v3.index import build_index

        result = build_index(plan_dir, index_dir, get_embeddings(), max_usd=args.max_usd)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
