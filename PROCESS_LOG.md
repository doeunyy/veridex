# Veridex — CSCI 599 Assignment 1 Process Log

## Development Progress

### Phase 00 — Project Foundation

**Implementation**

- Initialized the repository with a lightweight branching strategy and PR template.
- Configured Python 3.13, uv, dependencies, environment settings, and project structure.
- Prepared a five-paper research corpus, document manifest, and initial evaluation questions.

**Verification**

- Validated environment configuration and core dependencies with smoke tests.
- Confirmed that the development environment was ready for RAG implementation.

### Phase 01 — Core RAG Pipeline

**Implementation**

- Implemented PDF parsing, metadata extraction, and recursive document chunking.
- Integrated OpenAI embeddings and persistent Chroma vector indexing.
- Added semantic retrieval, document filtering, and LLM-based answer generation with source citations.
- Implemented citation-label validation.

**Verification**

- Extracted 119 pages from five research PDFs.
- Passed 20 unit tests and 3 integration tests.
- Manually verified single-document retrieval, cross-document comparisons, and insufficient-evidence handling.

**Limitations**

- PDF layout extraction and character-based chunking may disrupt reading order or sentence boundaries.
- Semantic retrieval may favor particular documents in comparison queries.
- Citation-label validation does not establish factual support for individual claims.

### Phase 02 — LangGraph Agent & Memory

**Implementation**

- Implemented a MessagesState-based LangGraph agent with evidence-grounded prompting, LLM-driven tool selection, conditional routing, and iterative `search_evidence` execution.
- Added session memory with `InMemorySaver` and `thread_id`, an AgentService interface with tracing, an interactive CLI, and Mermaid graph visualization.
- Reproduced a concurrent Chroma initialization race and added lock-protected, configuration-aware caching and index lifecycle safeguards without deleting or rebuilding the existing index.

**Verification**

- Passed 42 unit tests, including 10 Chroma regression cases; four integration tests passed during development (as recorded in my development reports).
- Manually verified direct responses, source-cited retrieval, multi-step comparisons, session memory/isolation, and insufficient-evidence handling (as recorded in my development reports); unit tests also cover mocked tool-error handling.
- The previously failing three-paper comparison completed with six successful tool calls and normal termination after the fix (as recorded in my development reports).
- Passed Ruff lint and formatting checks and confirmed ignore rules for secrets, PDFs, indexes, and private notes.

**Limitations**

- Memory is process-local, and LLM tool selection and call counts may vary between runs.
- Chroma initialization locking is process-local; concurrent rebuilding across processes remains unsupported.
- Citations do not establish claim-level factual support, and real API failure recovery is not exhaustively tested.
- MCP integration and Cloud Run deployment remain future work.

### Phase 03 — MCP Integration

**Implementation**

- Implemented three independent MCP servers exposing `search_evidence`, `search_web`, `list_documents`, and `read_document`; reused the existing RAG pipeline and restricted Workspace access to manifest-approved PDFs.
- Added dynamic tool discovery, a persistent multi-server registry, structured results, and session-bound LangChain adapters.
- Integrated the real MCP tools into the existing LangGraph architecture through an asynchronous AgentService and dedicated CLI, with LLM-driven routing, cross-server chaining, session memory/isolation, and source-preserving traces.
- Added interruption recovery using error ToolMessages, subprocess lifecycle checks, and sanitized Evidence error handling without fabricating successful tool execution.

**Verification**

- Passed 225 ordinary tests, including real STDIO protocol, multi-server Agent, filesystem security, cancellation/recovery, and Phase 01–02 regression coverage; nine opt-in integrations were deselected in the final run.
- Selected live integrations verified indexed retrieval, Tavily search, Evidence/Web orchestration, Workspace listing/reading, multi-turn memory, and session isolation; exact tool sequences in automated protocol tests use scripted models.
- Passed Ruff lint/format and Git whitespace checks. The security audit found no configured-credential or common credential-pattern matches in 95 reachable Git blobs and confirmed exclusions for secrets, PDFs, indexes, and private notes.

**Limitations**

- Memory and locks remain process-local; session/history growth and search-text sizes lack deployment-level budgets. Cancelled synchronous PDF/retrieval workers can continue, and failed MCP children are not automatically restarted.
- Prompt grounding and source metadata do not establish claim-level factual support or guarantee prompt-injection resistance.
- Cloud Run deployment remains Phase 04 work: ingress/lifecycle handling, durable checkpoints, corpus/index provisioning, authentication, resource limits, and shutdown within the platform grace period are still required.

### Phase 04 — Cloud Deployment & QA

**Implementation**

- Added a FastAPI service exposing the required `POST /chat` contract (`{"query", "session_id"}` → `{"response"}`), with `/health`, `/ready`, and `/attribution`. The MCP registry and agent are owned by the application lifespan, and startup refuses to serve unless all three servers and exactly four tools are discovered.
- Hardened request handling: strict schemas, a 65,536-byte body limit, one active request with no queue, a 180-second total deadline, disconnect cancellation, and safe status mapping that never exposes provider details. Added per-turn limits (8 tool calls, 6 model calls, 64,000 context characters, 4,096 completion tokens) and session limits (128 sessions, 30-minute idle expiry, 6 retained turns).
- Built a multi-stage, non-root linux/amd64 Docker image that bundles a digest-validated corpus and index and copies it to private instance-local storage at startup.
- Migrated to the licensed Corpus v2 (586 chunks), replacing a paper without a verified reuse license with the CC BY 4.0 EMNLP 2024 RAG-versus-long-context paper. Notices are served at `/attribution` and shipped in the image.
- Added sanitized observability: per-turn correlation IDs (independent of session IDs) and chat, agent, model, and MCP dispatch events that carry only durations, allowlisted server and tool names, and normalized exception classes. After a review found that Uvicorn could print raw chained exception text, added a log filter that reduces framework errors to class-only events.
- Provisioned private Google Cloud resources in `us-west1`: a private Artifact Registry repository, Secret Manager secrets referenced by numeric version, a dedicated runtime service account, and a USD 5 monthly budget alert. Deployed the IAM-private Cloud Run service `veridex-staging` (Gen2, 1 vCPU / 2 GiB, concurrency 1, min 0 / max 1 instances).
- Released changes as zero-traffic revisions that were tagged, health-checked, and tested before shifting traffic. The serving revision is now `veridex-staging-mcp-log-35bbef6` (image digest `sha256:8657fdec…a391`, provider timeout 45 s); `veridex-staging-timeout45` remains available for rollback.

**Verification**

- Latest offline results: 497 ordinary tests passed (47 integration tests deselected); 33 Docker TCP end-to-end and 2 Docker observability tests passed against the built image; Ruff and `git diff --check` passed. With the filter disabled, 8 of the 11 new framework-logging tests failed, confirming they detect the problem.
- Live private-staging tests (each run once, individually approved): direct answer, same-session memory, and session isolation passed. Evidence retrieval was a partial pass (citations correct, but the Self-Route mechanism was missing). Workspace chaining, Evidence plus Web in one turn, web search, and safe failure on a missing document all passed, with the real MCP calls logged under one correlation ID per turn.
- Public activation preserved revision, traffic and scaling. One anonymous chat smoke test returned HTTP 200 with the exact JSON contract in 2.805 seconds; logs recorded one completed model call and no MCP dispatch or error events for that turn.
- The first web-search test returned HTTP 500 on the uninstrumented revision. Logs showed no instance replacement or web-tool error, so the cause remains unconfirmed; the retry on the instrumented revision passed.
- Earlier image verification matched runtime files to `fc73f1a`, without proving build provenance. The subsequent SDK logging safeguard passed four malformed-response cases and Docker validation. The current image was built from `35bbef6`; one live Workspace turn verified two model calls and one successful listing call before promotion. All 75 protected corpus and artifact records remained unchanged throughout.

**Limitations**

- Session memory exists only inside one instance and is lost when it scales to zero, is replaced, or is redeployed. Cold starts take about 30–40 seconds.
- Anonymous session IDs are not authenticated, so callers using the same ID share history.
- A provider timeout still produces HTTP 500 rather than a graceful limit message.
- Tool arguments and results are deliberately not logged, so dependent chaining is supported by strong circumstantial evidence rather than captured data flow.
- Public grading access is enabled through a service-level `allUsers` Invoker grant. Revocation is planned for December 14, 2026, but is not scheduled.

---

## Chronological Development Narrative

With AI assistance, I developed Veridex from October 8 to 13, 2026, in five phases, each merged or reviewed through a pull request. In Phase 00, I set up the repository, Python 3.13 toolchain, and a five-paper corpus. In Phase 01, I built the RAG pipeline: PDF parsing, chunking, OpenAI embeddings, a Chroma index, and cited answer generation, with citation-label validation. In Phase 02, I wrapped retrieval in a LangGraph tool-calling agent with session memory; debugging there uncovered and fixed a concurrent Chroma initialization race. In Phase 03, I split the tools into three independent MCP servers (Evidence, Web Search with Tavily, and a read-only Workspace), added dynamic multi-server discovery, and made tool failures return safe error messages instead of fabricated results.

In Phase 04, I turned the agent into a deployable service. A FastAPI `POST /chat` endpoint gained strict validation, request and agent budgets, deadlines, and cancellation repair. A non-root Docker image bundled a digest-validated index. A licensing review led to replacing one paper and rebuilding the corpus as v2. Deployment then proceeded through small, approved gates: private Artifact Registry publication, a private Cloud Run service, and zero-traffic revisions verified through tagged URLs.

An unexplained HTTP 500 in live testing exposed a diagnostic gap. Sanitized correlation logging, followed by a framework-log hardening fix, made later live tests show which MCP tools actually ran. A configuration-only timeout increase was validated on a separate revision before traffic was shifted to it. After separate approval, I enabled public grading access and verified one anonymous chat turn; revocation remains a separately approved action.

## AI Tools & Prompts

### Tools and models

| Tool | Model / version | Where it was used |
|---|---|---|
| Claude Code (Anthropic CLI) | Claude Opus 5.5 (`claude-opus-5-5`) | I used Claude Code from Phase 04 onward for implementation, debugging, sanitized observability, framework-logging analysis, Docker and deployment validation, image publication, Cloud Run revisions and traffic, live-test execution and log analysis, and GitHub/submission documentation. |
| Codex (OpenAI) | GPT-6.1-Sol | I used Codex during Phases 00–03 for repository inspection, implementation, debugging, and testing. |
| ChatGPT (OpenAI) | GPT-6.1-Sol light | I used ChatGPT throughout Phases 00–04 for architecture planning, implementation guidance, RAG pipeline design, LangGraph and MCP integration planning, debugging, test-case design, deployment planning, and interpreting verification results. It helped me organize incremental steps with explicit validation and approval gates. |
| Other AI coding assistants, Phases 00–03 | None | I used no other AI coding assistants during Phases 00–03. I switched to Claude Code in Phase 04. |

### Example development prompts

The following are **excerpts, not complete prompts**, from my actual Phase 04 development instructions, matched to the recorded steps and labeled with the AI tools I used.

1. **ChatGPT/Claude Code — Step 4.8.4i, observability implementation:** “Add minimal structured observability that can identify the failing execution stage and whether MCP tools were actually invoked, without exposing sensitive information or changing application behavior.”
2. **ChatGPT/Claude Code — Step 4.8.4j, Docker validation:** “Validate that the updated application works in its production-like Docker environment and that sanitized observability captures actual agent/MCP execution without leaking sensitive information.”
3. **ChatGPT — Step 4.8.4a, live-testing preparation:** “Prepare a bounded, low-cost live `/chat` validation plan. Do not execute provider requests yet.”

### How AI output was used and verified

- **Gated mutations:** I split every cloud change into a read-only preflight followed by a separately approved action, then verified it afterwards against a saved snapshot (traffic, tags, IAM, revision specs).
- **Tests that prove themselves:** new tests were checked by disabling the fix (8 of 11 framework-logging tests then failed). Shell commands in the docs were parse-checked with `bash -n`, and claims about answers were checked offline against the local PDFs.
- **Provenance:** I compared file hashes inside the published image with the committed source instead of assuming they matched.
- **AI mistakes caught and disclosed:**
  - A `gcloud --set-tags` command replaced all traffic tags and removed one I had asked to keep. This was found in post-change verification; normal traffic was unaffected.
  - A shell-variable collision prevented one batch of health requests from being sent, and it was rerun cleanly.
  - An environment-variable count was misreported (19 instead of 18) and later corrected.

## Personal Lessons Learned

This project helped me understand how LangGraph agents interact with multiple MCP servers and how challenging it can be to manage asynchronous tool execution, session memory, and error handling in a real application. I also learned that a correct final answer does not necessarily prove that the intended tools were executed, which motivated me to implement structured logging and verify tool calls during Cloud Run testing. Working with AI coding assistants taught me to break complex tasks into smaller steps, review generated code carefully, and validate changes through tests instead of assuming that successful execution means everything works correctly.
