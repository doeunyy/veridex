"""Read-only SQLite catalog of Corpus v3 papers, queried by the Data agent with SQL.

The catalog is built from the same manifest as the vector index, so the Data agent
and the Research agent always describe the same corpus.
"""

import sqlite3
from pathlib import Path

from veridex.rag.v3.manifest import Manifest

DEFAULT_MAX_ROWS = 50
TIMEOUT_SECONDS = 2.0
# Abort runaway statements (e.g. huge cross joins) after this many SQLite VM steps.
MAX_VM_STEPS = 5_000_000
_STEPS_PER_TICK = 1000

SCHEMA = """
CREATE TABLE papers (
    doc_id TEXT PRIMARY KEY,      -- citation id, e.g. react_2022
    arxiv_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    year INTEGER NOT NULL,        -- year of first arXiv submission
    topic TEXT NOT NULL,          -- rag_retrieval | agent_reasoning_tools | multi_agent_systems | evaluation
    first_author TEXT NOT NULL,
    author_count INTEGER NOT NULL,
    primary_category TEXT NOT NULL,
    license TEXT NOT NULL,
    abs_url TEXT NOT NULL,
    page_count INTEGER NOT NULL,  -- pages in the PDF
    body_pages INTEGER NOT NULL,  -- pages indexed (before the references)
    chunk_count INTEGER NOT NULL, -- chunks in the vector index
    token_count INTEGER NOT NULL  -- embedded tokens
);
CREATE TABLE authors (
    doc_id TEXT NOT NULL REFERENCES papers(doc_id),
    position INTEGER NOT NULL,    -- 1 = first author
    name TEXT NOT NULL,
    PRIMARY KEY (doc_id, position)
);
CREATE TABLE categories (
    doc_id TEXT NOT NULL REFERENCES papers(doc_id),
    category TEXT NOT NULL,       -- arXiv category, e.g. cs.CL
    PRIMARY KEY (doc_id, category)
);
"""

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}


class CatalogQueryError(ValueError):
    """A query the catalog refuses; the message is safe to show the model."""


def build_catalog(manifest: Manifest, stats: dict[str, dict], db_path: Path) -> int:
    """Write a fresh catalog. `stats` is the plan's per_document section."""
    missing = {p.doc_id for p in manifest.papers} - set(stats)
    if missing:
        raise ValueError(f"No chunk statistics for {sorted(missing)}.")
    staging = db_path.with_suffix(".building")
    staging.unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(staging) as connection:
        connection.executescript(SCHEMA)
        for paper in manifest.papers:
            row = stats[paper.doc_id]
            connection.execute(
                "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    paper.doc_id,
                    paper.arxiv_id,
                    paper.title,
                    paper.year,
                    paper.topic,
                    paper.first_author,
                    len(paper.authors),
                    paper.categories[0],
                    paper.license,
                    paper.abs_url,
                    row["page_count"],
                    row["body_pages"],
                    row["chunks"],
                    row["tokens"],
                ),
            )
            connection.executemany(
                "INSERT INTO authors VALUES (?,?,?)",
                [(paper.doc_id, i, name) for i, name in enumerate(paper.authors, start=1)],
            )
            connection.executemany(
                "INSERT INTO categories VALUES (?,?)",
                [(paper.doc_id, category) for category in dict.fromkeys(paper.categories)],
            )
    connection.close()
    staging.replace(db_path)
    return len(manifest.papers)


def describe_schema() -> str:
    """The schema text given to the Data agent so it can write correct SQL."""
    return SCHEMA.strip()


def _authorize(action, *_):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def query_catalog(db_path: Path, sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> dict:
    """Run one SELECT against a read-only connection; anything else is refused.

    Returns columns, at most `max_rows` rows and whether more rows existed.
    """
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise CatalogQueryError("Empty query.")
    if not sqlite3.complete_statement(statement + ";") or ";" in statement:
        raise CatalogQueryError("Exactly one SQL statement is allowed.")
    if not db_path.is_file():
        raise FileNotFoundError(f"Catalog not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=TIMEOUT_SECONDS)
    budget = [MAX_VM_STEPS // _STEPS_PER_TICK]

    def tick() -> int:
        budget[0] -= 1
        return 1 if budget[0] < 0 else 0  # non-zero aborts the running statement

    try:
        connection.set_authorizer(_authorize)
        connection.set_progress_handler(tick, _STEPS_PER_TICK)
        try:
            cursor = connection.execute(statement)
            if cursor.description is None:
                raise CatalogQueryError("Only SELECT queries are allowed.")
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as exc:
            if budget[0] < 0:
                raise CatalogQueryError("Query exceeded the work limit.") from None
            raise CatalogQueryError(f"Query rejected: {exc}") from None
        return {
            "columns": [column[0] for column in cursor.description],
            "rows": [list(row) for row in rows[:max_rows]],
            "truncated": len(rows) > max_rows,
        }
    finally:
        connection.close()
