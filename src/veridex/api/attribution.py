"""Public corpus notice derived from the Corpus v3 manifest (CC BY 4.0 / CC0 attribution)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from veridex.rag.v3.manifest import load_manifest

NOTICE = (
    "Veridex indexes and serves text from the papers below under their stated licenses. "
    "Text was extracted and split into passages for retrieval; no other changes were made. "
    "Copyright remains with the authors."
)


class PaperAttribution(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    doc_id: str
    title: str
    authors: list[str]
    year: int
    license: str
    license_url: str
    source_url: str


class CorpusAttribution(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    corpus: str
    description: str
    notice: str
    papers: list[PaperAttribution]


def load_attribution(manifest_path: Path | None) -> CorpusAttribution | None:
    """None when no corpus manifest is deployed (e.g. a bare API test app)."""
    if manifest_path is None or not manifest_path.is_file():
        return None
    manifest = load_manifest(manifest_path)
    return CorpusAttribution(
        corpus=manifest.corpus,
        description=manifest.description,
        notice=NOTICE,
        papers=[
            PaperAttribution(
                doc_id=p.doc_id,
                title=p.title,
                authors=list(p.authors),
                year=p.year,
                license=p.license,
                license_url=p.license_url,
                source_url=p.abs_url,
            )
            for p in manifest.papers
        ],
    )


def render_notice(manifest_path: Path) -> str:
    """CORPUS_LICENSE_NOTICE.md: attribution for every paper shipped in the image."""
    notice = load_attribution(manifest_path)
    lines = [
        "# Corpus v3 attribution and license notice",
        "",
        notice.description,
        "",
        notice.notice,
        (
            "Generated from `data/corpus_v3/papers.json` by "
            "`uv run python scripts/corpus_v3.py notice`."
        ),
        "",
        "| Paper | Authors | Year | License | Source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for paper in notice.papers:
        authors = ", ".join(paper.authors[:6]) + (" et al." if len(paper.authors) > 6 else "")
        lines.append(
            f"| {paper.title} | {authors} | {paper.year} | "
            f"[{paper.license}]({paper.license_url}) | <{paper.source_url}> |"
        )
    return "\n".join(lines) + "\n"
