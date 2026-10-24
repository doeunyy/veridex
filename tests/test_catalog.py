import sqlite3

import pytest

from veridex.data.catalog import (
    CatalogQueryError,
    build_catalog,
    describe_schema,
    query_catalog,
)
from veridex.rag.v3.manifest import DEFAULT_MANIFEST, load_manifest


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    manifest = load_manifest(DEFAULT_MANIFEST)
    stats = {
        paper.doc_id: {"page_count": 20, "body_pages": 10, "chunks": 30 + i, "tokens": 9000}
        for i, paper in enumerate(manifest.papers)
    }
    path = tmp_path_factory.mktemp("catalog") / "catalog.db"
    assert build_catalog(manifest, stats, path) == len(manifest.papers)
    return path, manifest


def test_catalog_answers_structured_questions(catalog):
    path, manifest = catalog
    result = query_catalog(path, "SELECT COUNT(*) AS n FROM papers WHERE topic = 'evaluation'")
    expected = sum(p.topic == "evaluation" for p in manifest.papers)
    assert result == {"columns": ["n"], "rows": [[expected]], "truncated": False}

    joined = query_catalog(
        path,
        "SELECT p.doc_id FROM papers p JOIN authors a USING (doc_id) "
        "WHERE a.position = 1 AND a.name = 'Shunyu Yao' ORDER BY p.year;",
    )
    assert ["react_2022"] in joined["rows"]


def test_rows_are_capped(catalog):
    path, _ = catalog
    result = query_catalog(path, "SELECT doc_id FROM papers", max_rows=5)
    assert len(result["rows"]) == 5 and result["truncated"] is True


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM papers",
        "UPDATE papers SET year = 1999",
        "DROP TABLE papers",
        "PRAGMA table_info(papers)",
        "ATTACH DATABASE 'other.db' AS other",
        "SELECT 1; DELETE FROM papers",
        "",
    ],
)
def test_only_single_selects_are_allowed(catalog, sql):
    path, _ = catalog
    with pytest.raises(CatalogQueryError):
        query_catalog(path, sql)
    assert query_catalog(path, "SELECT COUNT(*) FROM papers")["rows"][0][0] > 0


def test_runaway_queries_hit_the_work_limit(catalog):
    path, _ = catalog
    with pytest.raises(CatalogQueryError, match="work limit"):
        query_catalog(path, "SELECT COUNT(*) FROM authors a, authors b, authors c")


def test_connection_is_read_only_even_without_authorizer(catalog):
    path, _ = catalog
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM papers")
    connection.close()


def test_build_requires_stats_for_every_paper(tmp_path):
    manifest = load_manifest(DEFAULT_MANIFEST)
    with pytest.raises(ValueError, match="No chunk statistics"):
        build_catalog(manifest, {}, tmp_path / "catalog.db")
    assert not (tmp_path / "catalog.db").exists()


def test_schema_text_names_every_table():
    schema = describe_schema()
    assert all(name in schema for name in ("papers", "authors", "categories"))
