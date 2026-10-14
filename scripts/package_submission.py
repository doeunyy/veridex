"""Plan a frozen Git-source submission; creating a ZIP requires explicit --write."""

import argparse
from pathlib import Path

from veridex.submission import plan_archive, read_git_source, write_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="Approved release commit or tag")
    parser.add_argument("--mode", choices=["source-only", "coursework"], default="source-only")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.write != (args.output is not None):
        parser.error("ZIP creation requires both --write and a new --output path")
    try:
        source, commit, timestamp = read_git_source(Path.cwd(), args.ref)
        plan = plan_archive(
            source, commit=commit, timestamp=timestamp, mode=args.mode, bundle=args.bundle
        )
        if args.write:
            write_archive(plan, args.output)
        print(f"Validated {plan.mode}: {len(plan.files)} files from {plan.commit}")
    except Exception:  # noqa: BLE001 — no raw file contents or exception details
        parser.exit(1, "Submission packaging stopped; no automatic fallback or rebuild.\n")


if __name__ == "__main__":
    main()
