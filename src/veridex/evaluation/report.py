"""Turn eval/results/*.json(l) into the markdown tables used in docs/evaluation.md."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from veridex.evaluation.run import RESULTS, load_questions, read_jsonl, summarize

METRICS = {
    "faithfulness": "Faithfulness",
    "answer_relevancy": "Answer relevancy",
    "llm_context_precision_with_reference": "Context precision",
    "context_recall": "Context recall",
}


def _load(name: str):
    path = RESULTS / name
    if not path.exists():
        return None
    return read_jsonl(path) if path.suffix == ".jsonl" else json.loads(path.read_text())


def _fmt(value, digits=2):
    return "–" if value is None else f"{value:.{digits}f}"


def _metric_means(scores: dict, ids: list[str]) -> dict:
    out = {}
    for metric in METRICS:
        values = [scores[i].get(metric) for i in ids if i in scores]
        values = [v for v in values if v is not None]
        out[metric] = (mean(values), len(values)) if values else (None, 0)
    return out


def ragas_table(mode: str = "routed") -> str:
    scores = _load(f"ragas_{mode}.json") or {}
    questions = load_questions()
    rows = ["| Category | n | " + " | ".join(METRICS.values()) + " |", "|---|---|" + "---|" * 4]
    groups = [
        ("rag", "Corpus RAG"),
        ("compare", "Comparison / multi-step"),
        ("summary", "Summary"),
        ("data", "Data (SQL)"),
        ("web", "Web"),
    ]
    all_ids = []
    for category, label in groups:
        ids = [q["id"] for q in questions if q["category"] == category and q["id"] in scores]
        all_ids += ids
        means = _metric_means(scores, ids)
        rows.append(
            f"| {label} | {len(ids)} | " + " | ".join(_fmt(means[m][0]) for m in METRICS) + " |"
        )
    means = _metric_means(scores, all_ids)
    rows.append(
        f"| **All** | {len(all_ids)} | "
        + " | ".join(f"**{_fmt(means[m][0])}**" for m in METRICS)
        + " |"
    )
    return "\n".join(rows)


def answers_summary(mode: str = "routed") -> dict:
    answers = _load(f"answers_{mode}.jsonl") or []
    calls = [c for a in answers for c in a.get("usage", [])]
    by_provider = Counter(c["provider"] for c in calls)
    by_rule = Counter(
        (r["agent"], r["provider"], r["rule"], bool(r.get("fallback_from")))
        for a in answers
        for r in a.get("routing", [])
    )
    return {
        "answers": answers,
        "errors": [a["id"] for a in answers if a.get("error") or not a.get("response")],
        "calls": calls,
        "provider_calls": by_provider,
        "rules": by_rule,
        "cost": [a.get("cost_usd") for a in answers],
        "total_ms": [a.get("total_ms") for a in answers],
        "ttft_ms": [a.get("ttft_ms") for a in answers],
        "retrieval_ms": [a.get("timing", {}).get("retrieval_ms") for a in answers],
        "llm_ms": [a.get("timing", {}).get("llm_ms") for a in answers],
    }


def routing_table(mode: str = "routed") -> str:
    summary = answers_summary(mode)
    rows = ["| Agent | Rule | Provider | Calls (decisions) | Fallbacks |", "|---|---|---|---|---|"]
    grouped = defaultdict(lambda: [0, 0])
    for (agent, provider, rule, fallback), count in summary["rules"].items():
        key = (agent, rule, provider)
        grouped[key][0] += count
        if fallback:
            grouped[key][1] += count
    for (agent, rule, provider), (count, fallbacks) in sorted(grouped.items()):
        rows.append(f"| {agent} | `{rule}` | {provider} | {count} | {fallbacks} |")
    return "\n".join(rows)


def cost_latency_table(modes=("routed", "openai", "gemini")) -> str:
    rows = [
        "| Run | Questions | Mean cost / query | Total cost | Median total (s) | Median TTFT (s) | Median retrieval (s) | Median LLM (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode in modes:
        s = answers_summary(mode)
        if not s["answers"]:
            continue
        costs = [c for c in s["cost"] if c is not None]
        sec = lambda values: _fmt((summarize(values).get("median") or 0) / 1000, 1)
        rows.append(
            f"| {mode} | {len(s['answers'])} | ${mean(costs):.4f} | ${sum(costs):.2f} | "
            f"{sec(s['total_ms'])} | {sec(s['ttft_ms'])} | {sec(s['retrieval_ms'])} | {sec(s['llm_ms'])} |"
        )
    return "\n".join(rows)


def provider_table() -> str:
    rows = [
        "| Provider (all agents) | RAG questions | "
        + " | ".join(METRICS.values())
        + " | Mean cost / query | Median total (s) | Output tokens / query |",
        "|---|---|" + "---|" * 7,
    ]
    rag_ids = [q["id"] for q in load_questions() if q["category"] == "rag"]
    for mode in ("openai", "gemini", "routed"):
        scores = _load(f"ragas_{mode}.json") or {}
        answers = [a for a in (_load(f"answers_{mode}.jsonl") or []) if a["id"] in rag_ids]
        if not answers:
            continue
        means = _metric_means(scores, [a["id"] for a in answers])
        costs = [a.get("cost_usd") or 0 for a in answers]
        totals = summarize([a.get("total_ms") for a in answers]).get("median") or 0
        output = mean(sum(c["output_tokens"] for c in a.get("usage", [])) for a in answers)
        label = {"openai": "OpenAI gpt-6.1-sol", "gemini": "Gemini gemini-3.8-flash"}.get(
            mode, "Routed (hybrid)"
        )
        rows.append(
            f"| {label} | {len(answers)} | "
            + " | ".join(_fmt(means[m][0]) for m in METRICS)
            + f" | ${mean(costs):.4f} | {totals / 1000:.1f} | {output:,.0f} |"
        )
    return "\n".join(rows)


def latency_table() -> str:
    rows = [
        "| Label | Question | Category | First event (s) | TTFT (s) | Total (s) | Retrieval (s) | LLM (s) | Cost |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for label in ("warm", "cold"):
        for row in _load(f"latency_{label}.jsonl") or []:
            sec = lambda v: _fmt(None if v is None else v / 1000, 1)
            rows.append(
                f"| {label} | {row['id']} | {row['category']} | {sec(row['client_first_byte_ms'])} | "
                f"{sec(row['client_ttft_ms'])} | {sec(row['client_total_ms'])} | "
                f"{sec(row['retrieval_ms'])} | {sec(row['llm_ms'])} | "
                f"${(row['cost_usd'] or 0):.4f} |"
            )
    return "\n".join(rows)


def write_all(path: Path = RESULTS / "report.md") -> str:
    parts = [
        "## RAGAS (routed)",
        ragas_table("routed"),
        "## Routing decisions (routed run)",
        routing_table("routed"),
        "## Cost and latency (in-process runs)",
        cost_latency_table(),
        "## Provider comparison (corpus RAG questions)",
        provider_table(),
        "## Deployed latency",
        latency_table(),
    ]
    text = "\n\n".join(parts) + "\n"
    path.write_text(text)
    return text
