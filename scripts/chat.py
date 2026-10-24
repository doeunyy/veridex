"""Ask the multi-agent system from the terminal and print routing and trace.

uv run python scripts/chat.py "What is ReAct?" "How many papers per topic?"
"""

import argparse
import asyncio
import json
from uuid import uuid4

from veridex.agents.service import open_multi_agent_service


async def run(questions: list[str], show_trace: bool) -> None:
    session = uuid4().hex
    async with open_multi_agent_service() as service:
        for question in questions:
            result = await service.achat_with_trace(question, session)
            print(f"\nQ: {question}\n\n{result['response']}\n")
            for decision in result["routing"]:
                fallback = f" (fallback from {decision['fallback_from']})" * bool(
                    decision["fallback_from"]
                )
                print(
                    f"  route {decision['agent']:<10} -> {decision['provider']}/"
                    f"{decision['model']} [{decision['dimension']}:{decision['rule']}]{fallback}"
                )
            print("  sources:", ", ".join(c["id"] for c in result["citations"]) or "none")
            if show_trace:
                print(json.dumps(result["trace"], indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", nargs="+", help="Questions asked in one conversation.")
    parser.add_argument("--trace", action="store_true", help="Also print orchestration events.")
    args = parser.parse_args()
    asyncio.run(run(args.questions, args.trace))


if __name__ == "__main__":
    main()
