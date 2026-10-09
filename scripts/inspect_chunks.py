from pathlib import Path

from veridex.config import settings
from veridex.rag.chunking import chunk_documents
from veridex.rag.ingestion import load_corpus


def main():
    documents = load_corpus(
        Path("data/samples/manifest.json"),
        settings.documents_dir,
    )

    chunks = chunk_documents(documents)

    print("Total pages:", len(documents))
    print("Total chunks:", len(chunks))

    for chunk in chunks[:5]:
        print("-" * 60)
        print("Chunk ID:", chunk.metadata["chunk_id"])
        print("Page:", chunk.metadata["page"])
        print("Start index:", chunk.metadata["start_index"])
        print("Length:", len(chunk.page_content))
        print("Text:", chunk.page_content[:300])


if __name__ == "__main__":
    main()
