from pathlib import Path

from veridex.config import settings
from veridex.rag.ingestion import load_corpus
from collections import Counter


def main():
    documents = load_corpus(
        manifest_path=Path("data/samples/manifest.json"),
        documents_dir=settings.documents_dir,
    )

    print(f"Total extracted pages: {len(documents)}")

    for document in documents[:5]:
        print("-" * 60)
        print("Title:", document.metadata["title"])
        print("Page:", document.metadata["page"])
        print("Characters:", len(document.page_content))
        print("Preview:", document.page_content[:300])
        
    page_counts = Counter(
        doc.metadata["document_id"]
        for doc in documents
    )

    print("\nPages per document:")
    for document_id, count in page_counts.items():
        print(f"  {document_id}: {count} pages")


if __name__ == "__main__":
    main()
