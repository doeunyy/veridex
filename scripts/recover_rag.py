"""Recover the reviewed legacy Chroma index offline; never export a deployment bundle."""

import argparse
import sys
from pathlib import Path

from veridex.rag.artifacts import ArtifactError
from veridex.rag.recovery import recover


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--reference", type=Path, default=Path(".artifacts/source-inspection.json"))
    parser.add_argument(
        "--source-quiescent",
        action="store_true",
        help="Attest no source readers/writers can start until this command finishes",
    )
    args = parser.parse_args()
    try:
        report = recover(
            project=Path.cwd(),
            reference=args.reference,
            destination=args.destination,
            source_quiescent=args.source_quiescent,
        )
    except ArtifactError as exc:
        print(f"Recovery rejected: {exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 — do not expose source text or raw native errors
        print(
            "Recovery rejected: invalid source, candidate, or offline validation failure.",
            file=sys.stderr,
        )
        return 1
    print(f"Validated recovered index: {args.destination / 'chroma'}")
    print(
        f"Preserved {report['validation']['vectors_preserved']} FLOAT32 vectors; deployment bundle not exported."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
