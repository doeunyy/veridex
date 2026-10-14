"""Fail closed before starting the existing API runner; no ingestion/provider calls."""

import sys


def main() -> int:
    try:
        from veridex.deployment.runtime import bootstrap

        bootstrap()
    except Exception:  # noqa: BLE001 — omit credentials, source text, and internal paths
        print(
            "Container bootstrap failed: bundle integrity, dependencies, or storage permissions invalid.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
