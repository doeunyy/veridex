"""Execute exactly the approved v2 embedding plan, or build/export offline afterward."""

import argparse
import json
import sys
from pathlib import Path

from veridex.rag.artifacts import ArtifactError, validate_bundle
from veridex.rag.rebuild_v2 import SPEC, build_and_export, execute_batches, frozen_inputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["embed", "build-export", "export", "validate"])
    parser.add_argument("--corpus", type=Path, default=Path(".artifacts/corpus/veridex-corpus-v2"))
    parser.add_argument(
        "--bundle", type=Path, default=Path(".artifacts/versions/veridex-rag-v2-local")
    )
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--approved-paid-plan", action="store_true")
    parser.add_argument("--metadata-sha256")
    args = parser.parse_args()
    try:
        if args.action == "embed":
            if not args.approved_paid_plan:
                parser.error("Embedding execution requires explicit paid-plan approval")
            _, chunks = frozen_inputs(args.corpus, args.lock)
            from openai import OpenAI

            from veridex.config import settings

            if not settings.openai_api_key:
                raise ArtifactError("Runtime OpenAI credential is not configured.")
            # Force the official endpoint; no model/client environment overrides or retries.
            with OpenAI(
                api_key=settings.openai_api_key,
                base_url="https://api.openai.com/v1",
                max_retries=0,
                timeout=30.0,
            ) as client:
                execute_batches(chunks, args.corpus / "embedding-run", client)
        elif args.action == "validate":
            if not args.metadata_sha256:
                parser.error("validate requires a trusted --metadata-sha256")
            metadata = validate_bundle(
                args.bundle,
                expected=SPEC,
                metadata_sha256=args.metadata_sha256,
                lock_file=args.lock,
                probe=True,
            )
            print(f"Validated {metadata.snapshot_version}: {metadata.spec.chunk_count} chunks")
        else:
            print(
                json.dumps(
                    build_and_export(
                        args.corpus, args.bundle, args.lock, build=args.action == "build-export"
                    ),
                    indent=2,
                )
            )
    except Exception as exc:  # noqa: BLE001 — journal safely and stop; never log bodies
        print(
            f"Corpus v2 operation stopped ({type(exc).__name__}); no automatic retry.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
