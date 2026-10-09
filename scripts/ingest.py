import argparse
import shutil
from pathlib import Path

from veridex.config import settings
from veridex.rag.chunking import chunk_documents
from veridex.rag.ingestion import load_corpus
from veridex.rag.vectorstore import index_documents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete the existing local index before ingestion.",
    )
    args = parser.parse_args()

    index_dir = Path(settings.chroma_persist_dir).resolve()

    if args.rebuild and index_dir.exists():
        # Restrict deletion to the configured local index.
        if index_dir == Path.cwd().resolve():
            raise ValueError("Refusing to delete project root.")
        shutil.rmtree(index_dir)

    documents = load_corpus(
        manifest_path=Path("data/samples/manifest.json"),
        documents_dir=settings.documents_dir,
    )

    chunks = chunk_documents(documents)

    print(f"Parsed pages: {len(documents)}")
    print(f"Generated chunks: {len(chunks)}")

    count = index_documents(chunks)
    print(f"Indexed chunks: {count}")


if __name__ == "__main__":
    main()
