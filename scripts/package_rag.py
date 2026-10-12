"""Export or validate a versioned offline RAG bundle; no ingestion or provider calls."""

import argparse
import sys
from pathlib import Path

from veridex.rag.artifacts import ArtifactError, ArtifactSpec, package_bundle, validate_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["package", "validate"])
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path("data/samples/manifest.json"))
    parser.add_argument("--papers", type=Path, default=Path("data/papers"))
    parser.add_argument("--index", type=Path, default=Path("data/index"))
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--snapshot-version")
    parser.add_argument("--embedding-model", help="Attested indexing model; required for export")
    parser.add_argument("--source-quiescent", action="store_true")
    parser.add_argument(
        "--metadata-sha256", help="Trusted bundle.json digest required for validation"
    )
    parser.add_argument("--runtime-probe", action="store_true")
    args = parser.parse_args()
    spec = ArtifactSpec(embedding_model=args.embedding_model or "text-embedding-3-small")
    try:
        if args.action == "package":
            if not args.snapshot_version:
                parser.error("package requires --snapshot-version")
            if not args.embedding_model:
                parser.error("package requires an explicit --embedding-model attestation")
            checksum = package_bundle(
                manifest=args.manifest,
                papers=args.papers,
                index=args.index,
                destination=args.bundle,
                snapshot_version=args.snapshot_version,
                lock_file=args.lock,
                expected=spec,
                source_quiescent=args.source_quiescent,
            )
            print(f"Validated snapshot published; bundle.json SHA-256: {checksum}")
        else:
            if not args.metadata_sha256:
                parser.error("validate requires a trusted --metadata-sha256")
            metadata = validate_bundle(
                args.bundle,
                expected=spec,
                metadata_sha256=args.metadata_sha256,
                lock_file=args.lock,
                probe=args.runtime_probe,
            )
            print(f"Validated {metadata.snapshot_version}: {len(metadata.files)} payload files")
    except ArtifactError as exc:
        print(f"RAG artifact rejected: {exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 — parser/SQLite errors must not print document contents
        print("RAG artifact rejected: invalid or incomplete source/bundle.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
