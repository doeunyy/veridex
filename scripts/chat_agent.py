import argparse

from veridex.agent.service import AgentService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session-id",
        default="local-demo",
    )
    args = parser.parse_args()

    service = AgentService()

    print("Veridex Agent")
    print(f"Session: {args.session_id}")
    print("Type 'exit' to quit.\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if query.lower() in {"exit", "quit"}:
            break

        if not query:
            continue

        try:
            answer = service.chat(
                query=query,
                session_id=args.session_id,
            )
            print(f"\nVeridex: {answer}\n")
        except Exception as exc:  # noqa: BLE001
            # Keep the CLI running if an individual request fails.
            print(f"\nError: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
