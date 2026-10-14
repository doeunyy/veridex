import argparse

from veridex.rag.retrieval import search_documents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--document-id", default=None)
    args = parser.parse_args()

    results = search_documents(
        query=args.query,
        top_k=args.top_k,
        document_id=args.document_id,
    )

    for rank, (doc, distance) in enumerate(results, start=1):
        print(f"\n{'=' * 60}")
        print(f"Rank: {rank}")
        print(f"Distance: {distance:.4f}")
        print(f"Title: {doc.metadata['title']}")
        print(f"Page: {doc.metadata['page']}")
        print(f"Chunk ID: {doc.metadata['chunk_id']}")
        print(f"Source: {doc.metadata['source_url']}")
        print(f"\n{doc.page_content[:500]}")


if __name__ == "__main__":
    main()
