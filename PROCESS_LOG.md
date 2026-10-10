# Veridex — CSCI 599 Assignment 1 Process Log

> Work in Progress — This document will be finalized before assignment submission.

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

- Passed 42 unit tests, including 10 Chroma regression cases; four integration tests passed during development (user-reported).
- Manually verified direct responses, source-cited retrieval, multi-step comparisons, session memory/isolation, and insufficient-evidence handling (user-reported); unit tests also cover mocked tool-error handling.
- The previously failing three-paper comparison completed with six successful tool calls and normal termination after the fix (user-reported).
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

_To be completed._

---

## Chronological Development Narrative

_TODO — Write a 200–300-word chronological narrative covering the complete development process._

## AI Tools & Prompts

_TODO — Document AI tools and versions, specific development prompts, and how AI-generated suggestions were used and verified._

## Personal Lessons Learned

_TODO — Add 2–3 sentences reflecting on personal learning and verification._
