"""Evaluate Veridex v2 on eval/questions_v3.json (paid API calls; see docs/evaluation.md).

uv run python scripts/evaluate.py answers --mode routed
uv run python scripts/evaluate.py answers --mode openai --categories rag
uv run python scripts/evaluate.py ragas --mode routed
uv run python scripts/evaluate.py latency --url https://veridex-v2-596419356898.us-west1.run.app --label warm
"""

import argparse
import json

from veridex.evaluation.run import (
    RESULTS,
    load_questions,
    ragas_scores,
    read_jsonl,
    run,
    run_answers,
    time_deployed,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    answers = commands.add_parser("answers", help="Run questions through the service.")
    answers.add_argument("--mode", choices=["routed", "openai", "gemini"], default="routed")
    answers.add_argument("--categories", nargs="*", help="Subset, e.g. rag summary")
    answers.add_argument("--ids", nargs="*", help="Only these question IDs")
    scores = commands.add_parser("ragas", help="Score an answers file with RAGAS.")
    scores.add_argument("--mode", choices=["routed", "openai", "gemini"], default="routed")
    scores.add_argument("--ids", nargs="*", help="Only these question IDs")
    scores.add_argument(
        "--missing", action="store_true", help="Re-score only questions with missing values"
    )
    latency = commands.add_parser("latency", help="Time the deployed service over SSE.")
    latency.add_argument("--url", required=True)
    latency.add_argument("--label", required=True, help="e.g. warm or cold")
    latency.add_argument("--ids", nargs="*")
    args = parser.parse_args()

    categories = set(args.categories) if getattr(args, "categories", None) else None
    questions = load_questions(categories=categories)
    if getattr(args, "ids", None):
        questions = [q for q in questions if q["id"] in set(args.ids)]

    if args.command == "answers":
        out = RESULTS / f"answers_{args.mode}.jsonl"
        force = None if args.mode == "routed" else args.mode
        run(run_answers(questions, out, force_provider=force))
    elif args.command == "ragas":
        path = RESULTS / f"ragas_{args.mode}.json"
        existing = json.loads(path.read_text()) if path.exists() else {}
        answers = read_jsonl(RESULTS / f"answers_{args.mode}.jsonl")
        if args.missing:
            answers = [
                a for a in answers if a["id"] not in existing or None in existing[a["id"]].values()
            ]
        if args.ids:
            answers = [a for a in answers if a["id"] in set(args.ids)]
        result = existing | ragas_scores(answers, load_questions())
        path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    else:
        rows = run(time_deployed(args.url, questions, label=args.label))
        with (RESULTS / f"latency_{args.label}.jsonl").open("a") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
