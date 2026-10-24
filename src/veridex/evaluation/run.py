"""Run the fixed question set and score it.

answers  — run every question through the real multi-agent service in-process
           (routed, or with every agent forced onto one provider for comparison)
ragas    — score answers with RAGAS (faithfulness, answer relevancy,
           context precision, context recall)
latency  — time the deployed Cloud Run service over SSE (TTFT, total, cold/warm)
"""

import asyncio
import json
import math
import time
from pathlib import Path
from statistics import mean, median
from uuid import uuid4

import httpx

from veridex.config import Settings, settings

QUESTIONS = Path("eval/questions_v3.json")
RESULTS = Path("eval/results")
CORPUS_CATEGORIES = {"rag", "summary", "data"}


def load_questions(path: Path = QUESTIONS, categories: set[str] | None = None) -> list[dict]:
    questions = json.loads(path.read_text())["questions"]
    return [q for q in questions if categories is None or q["category"] in categories]


async def run_answers(
    questions: list[dict], out: Path, *, force_provider: str | None = None, factory=None
) -> list[dict]:
    """One fresh session per question so answers do not depend on each other."""
    from veridex.agents.service import open_multi_agent_service

    config = settings.model_copy(
        update={"router_force_provider": force_provider, "state_backend": "memory"}
    )
    rows = []
    out.parent.mkdir(parents=True, exist_ok=True)
    async with open_multi_agent_service(config=config, factory=factory) as service:
        for question in questions:
            started = time.monotonic()
            done, error = None, None
            try:
                async for event, data in service.astream_turn(
                    question["question"], f"eval-{uuid4().hex}", include_contexts=True
                ):
                    if event == "done":
                        done = data
            except Exception as exc:  # noqa: BLE001 — record and continue the batch
                error = type(exc).__name__
            row = {
                "id": question["id"],
                "category": question["category"],
                "mode": force_provider or "routed",
                "wall_ms": round((time.monotonic() - started) * 1000),
                "error": error,
                **(done or {}),
            }
            rows.append(row)
            with out.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"{question['id']}: {row['wall_ms'] / 1000:.1f}s "
                f"${row.get('cost_usd', 0):.4f} {error or ''}",
                flush=True,
            )
    return rows


def read_jsonl(path: Path) -> list[dict]:
    # Split on "\n" only: answers can contain U+2028 and other characters splitlines() treats
    # as line breaks, which JSON leaves unescaped inside strings.
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def ragas_scores(
    answers: list[dict],
    questions: list[dict],
    *,
    judge: Settings | None = None,
    raise_exceptions: bool = False,
):
    """Per-question RAGAS scores. Reference-based metrics only where a reference exists."""
    from veridex.evaluation.ragas_compat import import_ragas

    import_ragas()
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )
    from ragas.run_config import RunConfig

    judge = judge or settings
    # GPT-6 reasoning models only accept the default temperature.
    llm = LangchainLLMWrapper(
        ChatOpenAI(model=judge.openai_model, api_key=judge.openai_api_key, timeout=180),
        bypass_temperature=True,
    )
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=judge.openai_embedding_model, api_key=judge.openai_api_key)
    )
    by_id = {q["id"]: q for q in questions}
    scored = [a for a in answers if a.get("response") and a["id"] in by_id]

    def sample(answer):
        question = by_id[answer["id"]]
        return SingleTurnSample(
            user_input=question["question"],
            response=answer["response"],
            retrieved_contexts=[c["text"] for c in answer.get("contexts", [])] or [""],
            reference=question.get("reference") or None,
        )

    with_reference = [a for a in scored if by_id[a["id"]].get("reference")]
    without_reference = [a for a in scored if not by_id[a["id"]].get("reference")]
    config = RunConfig(timeout=180, max_workers=4)
    results: dict[str, dict] = {a["id"]: {} for a in scored}
    for group, metrics in (
        (
            with_reference,
            [
                Faithfulness(),
                ResponseRelevancy(),
                LLMContextPrecisionWithReference(),
                LLMContextRecall(),
            ],
        ),
        (without_reference, [Faithfulness(), ResponseRelevancy()]),
    ):
        if not group:
            continue
        dataset = EvaluationDataset(samples=[sample(a) for a in group])
        frame = evaluate(
            dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
            run_config=config,
            raise_exceptions=raise_exceptions,
        ).to_pandas()
        for answer, (_, row) in zip(group, frame.iterrows(), strict=True):
            for metric in metrics:
                value = row.get(metric.name)
                results[answer["id"]][metric.name] = (
                    None
                    if value is None or (isinstance(value, float) and math.isnan(value))
                    else float(value)
                )
    return results


async def time_deployed(url: str, questions: list[dict], *, label: str) -> list[dict]:
    """Client-side TTFT/total over SSE plus the server's own timing breakdown."""
    rows = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
        for question in questions:
            started = time.monotonic()
            first_byte = first_token = None
            done: dict = {}
            event = None
            async with client.stream(
                "POST",
                f"{url.rstrip('/')}/api/chat/stream",
                json={"query": question["question"], "session_id": f"lat-{uuid4().hex}"},
            ) as response:
                async for line in response.aiter_lines():
                    first_byte = first_byte or time.monotonic()
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        if event == "token" and first_token is None:
                            first_token = time.monotonic()
                        if event == "done":
                            done = json.loads(line[5:])
            row = {
                "id": question["id"],
                "category": question["category"],
                "label": label,
                "client_first_byte_ms": _ms(first_byte, started),
                "client_ttft_ms": _ms(first_token, started),
                "client_total_ms": _ms(time.monotonic(), started),
                "server_ttft_ms": done.get("ttft_ms"),
                "server_total_ms": done.get("total_ms"),
                "retrieval_ms": done.get("timing", {}).get("retrieval_ms"),
                "llm_ms": done.get("timing", {}).get("llm_ms"),
                "cost_usd": done.get("cost_usd"),
                "providers": sorted({c["provider"] for c in done.get("usage", [])}),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
    return rows


def summarize(values: list[float | None]) -> dict:
    present = [v for v in values if v is not None]
    if not present:
        return {"n": 0}
    ordered = sorted(present)
    p90 = ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]
    return {"n": len(present), "mean": mean(present), "median": median(present), "p90": p90}


def _ms(end, start):
    return None if end is None else round((end - start) * 1000)


def run(coro):
    return asyncio.run(coro)
