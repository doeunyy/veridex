# Corpus v3

Corpus v3 is the v2 (Assignment 2) RAG corpus: 42 arXiv papers on LLM agents,
retrieval-augmented generation and evaluation. The paper list in
[`data/corpus_v3/papers.json`](../data/corpus_v3/papers.json) is the single source of truth
for both the Chroma index and the Data agent's SQLite catalog.

| Topic | Papers |
| --- | --- |
| `rag_retrieval` | 9 |
| `agent_reasoning_tools` | 11 |
| `multi_agent_systems` | 10 |
| `evaluation` | 12 |

## Licensing

Only papers whose arXiv license is CC BY 4.0 or CC0 1.0 are included, so the PDFs
and the index built from them can ship inside the container image. Licenses were
read from arXiv OAI-PMH metadata on 2026-10-21 and are validated by
`veridex.rag.v3.manifest`. Well-known papers under arXiv's default non-exclusive
license (for example the original RAG paper, DPR, Toolformer and MT-Bench) are
deliberately excluded; the Research agent covers them through live web search.

## Pipeline

The ingestion pipeline is a LangChain LCEL chain
(`veridex.rag.v3.pipeline.build_ingestion_chain`):

1. **Load**: PyMuPDF extracts text page by page; each page carries the paper's
   `document_id`, title, year, topic, license, arXiv URL and page number.
2. **Strip back matter**: everything from the first standalone `References` /
   `Bibliography` heading (after page 2) is dropped, including appendices. This keeps
   citation lists out of retrieval and stops a few very long papers from dominating.
3. **Split**: `RecursiveCharacterTextSplitter.from_tiktoken_encoder` with 400-token
   chunks and 60-token overlap (`cl100k_base`). Pages are split independently, so every
   chunk cites exactly one page.
4. **Identify**: chunk IDs are `<document_id>:p<page>:c<index>`, for example
   `react_2022:p4:c012`. The UI and citations link back to these IDs.
5. **Embed and store**: `text-embedding-3-small` (1,536 dimensions) into the Chroma
   collection `veridex_corpus_v3` with cosine distance.

## Rebuilding

```bash
uv run python scripts/corpus_v3.py download
uv run python scripts/corpus_v3.py plan
uv run python scripts/corpus_v3.py build --max-usd 0.05
uv run python scripts/corpus_v3.py catalog
```

`download` is resumable and records every PDF's SHA-256 in
`.artifacts/corpus_v3/papers/downloads.json`. `plan` makes no API calls: it writes the
exact chunks and an embedding cost estimate. `build` embeds exactly the planned
chunks, refuses to run above `--max-usd`, and never overwrites an existing index.
`catalog` writes `.artifacts/corpus_v3/catalog.db`. All outputs live under the ignored
`.artifacts/corpus_v3/` directory.

Current plan: 1,855 chunks, 610,627 tokens, about $0.012 to embed.
