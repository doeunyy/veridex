import argparse

from veridex.rag.generation import answer_question


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    result = answer_question(args.query, top_k=args.top_k)

    print("\nANSWER")
    print("=" * 60)
    print(result["answer"])

    print("\nSOURCES")
    print("=" * 60)

    for source in result["sources"]:
        print(f"[{source['label']}] {source['title']} (PDF page {source['page']})")
        print(source["source_url"])


if __name__ == "__main__":
    main()
