"""Offline preparation only; never invoke an embedding provider."""

import argparse
import json
from pathlib import Path

from veridex.rag.corpus_v2 import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    args = parser.parse_args()
    plan = prepare(args.corpus, args.lock)
    print(json.dumps({"chunk_count": plan["chunk_count"], **plan["embedding_plan"]}, indent=2))


if __name__ == "__main__":
    main()
