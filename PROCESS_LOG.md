# Process log — Veridex v2 (Assignment 2)

## AI tools used

Claude Code (Claude Opus 5.5) planned, implemented and tested most of the code under my review; I made design decisions, ran the paid steps and signed every commit. At runtime: OpenAI `gpt-6.1-sol` and `text-embedding-3-small`, Google `gemini-3.8-flash`, and `gpt-6.1-sol` as the RAGAS judge.

## Development narrative

I expanded Assignment 1's single-agent RAG system into a Supervisor with three specialized agents, hybrid LLM routing, and 42 papers. Five development branches covered corpus, multi-agent core, streaming UI, deployment, and evaluation. A unified manifest synchronized the RAG index, SQLite catalog, and license notices; routing decisions remained inspectable. Unsupported GPT-6 temperature settings broke agent calls, `.gcloudignore` excluded deployment data, and oversized Tavily extracts caused OpenAI timeouts. Sequential web searches took 176 seconds; I revised the prompt for batched tool calls, reducing latency to 70 seconds.

## Verification narrative

Beyond 480+ offline tests, I tested STDIO MCP servers with a Tavily stand-in and live queries using three API keys. I verified Firestore persistence via REST and confirmed conversation continuity after deploying a new Cloud Run revision. I measured cold-start latency after the instance count reached zero. CI exposed an import-order failure masked by ruff's local cache; I now lint with `--no-cache`.

## What I learned

I verified every arXiv license myself before packaging papers, since AI tools could not establish redistribution rights. Limited budgets taught me to measure per-call costs. Instrumentation showed Gemini's default reasoning-token usage, not retrieval (~1 s), dominated latency and cost. Per-rule thinking budgets halved time to first token without degrading RAGAS scores.