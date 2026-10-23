# Veridex v2

Multi-agent research assistant over 42 papers on LLM agents, retrieval-augmented
generation and LLM evaluation. A LangGraph supervisor routes each turn to Research,
Summary or Data agents; every model call is routed between OpenAI and Gemini by an
inspectable cost/capability router; answers stream over Server-Sent Events to a vanilla
HTML/JS page with routing decisions, an orchestration trace and source-linked citations.

**Live:** <https://veridex-v2-596419356898.us-west1.run.app>
(Cloud Run, GCP project `veridex-v2`, `us-west1`)

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | orchestration diagram, state schema, agents and tools, routing table, RAG pipeline, MCP tool sharing, durable state |
| [docs/evaluation.md](docs/evaluation.md) | RAGAS scores, latency (cold and warm), cost per query, provider comparison |
| [docs/corpus_v3.md](docs/corpus_v3.md) | paper list, licensing, chunking, rebuild commands |
| [PROCESS_LOG.md](PROCESS_LOG.md) | AI tools used, development and verification narrative |
| [CORPUS_LICENSE_NOTICE.md](CORPUS_LICENSE_NOTICE.md) | attribution for every paper in the corpus |

Assignment 1 (v1.0.1) is preserved under [docs/v1](docs/v1/README_v1.md), the
`v1.0.1` tag and the `release/v1.x` branch; its Cloud Run service is unchanged.

## What it does

| Ask | Handled by | Tools |
| --- | --- | --- |
| "How does Self-RAG decide when to retrieve?" | Research | corpus search (`search_evidence`) and Tavily web search |
| "What are the latest LLM-as-a-judge benchmarks?" | Research | Tavily Remote MCP plus the corpus |
| "Summarize the RAPTOR paper." | Summary | `list_documents`, `read_document`, `search_evidence` |
| "How many papers per topic? Who wrote ReAct?" | Data | SQL over a read-only paper catalog |
| Multi-part requests | several agents in turn, merged by the synthesizer | |

Each answer shows which agent ran, which provider and model handled each call and why
(`dimension:rule`, reason and signals on hover), the trace of supervisor decisions and
tool calls, and numbered citations linked to the source chunk (paper, page, arXiv URL).

## Requirements

| Requirement | Used for | Access and cost (checked 2026-10-22) |
| --- | --- | --- |
| Python 3.13 and [uv](https://docs.astral.sh/uv/) | local development | free |
| OpenAI API key | `gpt-6.1-sol` (reasoning, synthesis, SQL repair, RAGAS judge) and `text-embedding-3-small` | paid; about $2 / $10 per 1M input / output tokens (third-party price lists, confirm on the OpenAI dashboard); embeddings $0.02 per 1M |
| Google AI (Gemini) API key | `gemini-3.8-flash` (supervisor, lookups, long-context summaries, SQL) | paid tier $0.75 / $3.75 per 1M tokens through 2026-12-31; a free tier exists with rate limits |
| Tavily API key | Tavily Remote MCP web search | free plan with monthly credits |
| Google Cloud project with billing | Cloud Run, Cloud Build, Artifact Registry, Firestore, Secret Manager | USC Google Cloud education credit covers eligible usage; Cloud Run scales to zero |

Model IDs were verified against each provider's `/models` endpoint on 2026-10-21.
Measured cost per query and the full breakdown are in [docs/evaluation.md](docs/evaluation.md).

## Run locally

```bash
uv sync
cp .env.example .env
```

Fill in `OPENAI_API_KEY`, `GOOGLE_API_KEY` and `TAVILY_API_KEY` in `.env`. Then build the
corpus bundle (download is free; embedding costs about $0.012):

```bash
uv run python scripts/corpus_v3.py download
uv run python scripts/corpus_v3.py plan
uv run python scripts/corpus_v3.py build --max-usd 0.05
uv run python scripts/corpus_v3.py catalog
uv run python scripts/check_bundle.py
```

Start the API and open <http://localhost:8080>:

```bash
uv run python scripts/serve_api.py
```

Or ask from the terminal (same conversation for all questions):

```bash
uv run python scripts/chat.py "What is ReAct?" "How does Reflexion build on it?" --trace
```

Locally, conversations are stored in SQLite (`STATE_BACKEND=sqlite`); on Cloud Run in
Firestore.

### Tests

```bash
uv run ruff check .
uv run pytest -q
```

The offline suite needs no API keys: models are scripted fakes, and MCP tests run real
STDIO servers with a local stand-in for Tavily.

## API

| Method and path | Purpose |
| --- | --- |
| `GET /` | chat UI (static HTML, CSS, JS) |
| `POST /api/chat/stream` | one turn as SSE: `route`, `trace`, `token`, `citations`, `done`, `error` |
| `POST /chat` | the same turn as JSON `{"response": "..."}` |
| `GET /api/info` | agents, their MCP tools, shared tools, models, state backend |
| `GET /attribution` | corpus papers, authors and licenses |
| `GET /health`, `GET /ready` | liveness, and readiness after all MCP servers connected |

Request body for both chat routes: `{"query": "...", "session_id": "..."}`. Requests are
limited per instance (body size, 4 active and 4 waiting turns, 240 s deadline).

## Deploy to a fresh GCP project

Prerequisites: `gcloud` authenticated as a project owner, billing enabled, `uv`, and the
corpus bundle built as above.

```bash
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-west1
export CLOUD_RUN_SERVICE=veridex-v2
bash deploy/cloud_run.sh bootstrap
bash deploy/cloud_run.sh deploy
```

`bootstrap` enables the APIs, creates the Artifact Registry repository `veridex`, the
Firestore database, the runtime service account (`roles/datastore.user`), Cloud Build
permissions, and the secrets `openai-api-key`, `gemini-api-key` and `tavily-api-key`
(it prompts for each value without echoing it). `deploy` checks the bundle, builds the
image with Cloud Build, deploys Cloud Run (2 GiB, 2 vCPU, concurrency 10, timeout 300 s,
0–3 instances, `--allow-unauthenticated`) with the keys from Secret Manager and
`STATE_BACKEND=firestore`, then calls `/health`, `/ready` and `/api/info`.
`bash deploy/cloud_run.sh verify` repeats the checks.

The image is a multi-stage `python:3.13-slim` build from the exact pins in
`requirements.txt`, runs as a non-root user and contains the Corpus v3 PDFs, Chroma
index and paper catalog (verified at build time). No credentials are in the image or
the repository; `.env` is git- and docker-ignored.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/veridex/agents` | supervisor graph, workers, prompts, tool assignment, citations, service |
| `src/veridex/llm` | providers, router, usage and cost |
| `src/veridex/mcp` | MCP client registry and the evidence, workspace and catalog servers |
| `src/veridex/rag/v3` | corpus manifest, download, LCEL ingestion, Chroma build |
| `src/veridex/data` | read-only SQLite paper catalog |
| `src/veridex/state` | Firestore, SQLite and memory conversation stores |
| `src/veridex/api`, `src/veridex/web/static` | FastAPI app, SSE endpoint and the UI |
| `src/veridex/evaluation`, `eval/` | evaluation harness, question set and results |
| `deploy/cloud_run.sh`, `Dockerfile` | deployment |
