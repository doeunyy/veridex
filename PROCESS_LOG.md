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

_To be completed._

### Phase 03 — MCP Integration

_To be completed._

### Phase 04 — Cloud Deployment & QA

_To be completed._

---

## Chronological Development Narrative

_TODO — Write a 200–300-word chronological narrative covering the complete development process._

## AI Tools & Prompts

_TODO — Document AI tools and versions, specific development prompts, and how AI-generated suggestions were used and verified._

## Personal Lessons Learned

_TODO — Add 2–3 sentences reflecting on personal learning and verification._
