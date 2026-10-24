"""Validated paper list; the single source of truth for the corpus and the catalog."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MANIFEST = Path("data/corpus_v3/papers.json")

# Only licenses that allow redistributing the PDF inside the container image.
REDISTRIBUTABLE_LICENSES = {
    "CC-BY-4.0": "http://creativecommons.org/licenses/by/4.0/",
    "CC0-1.0": "http://creativecommons.org/publicdomain/zero/1.0/",
}
Topic = Literal["rag_retrieval", "agent_reasoning_tools", "multi_agent_systems", "evaluation"]


class Paper(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(pattern=r"^[a-z0-9_]+_\d{4}$")
    arxiv_id: str = Field(pattern=r"^\d{4}\.\d{4,5}$")
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    year: int = Field(ge=2000, le=2100)
    topic: Topic
    categories: list[str] = Field(min_length=1)
    license: str
    license_url: str
    abs_url: str
    pdf_url: str

    @model_validator(mode="after")
    def _check(self):
        if REDISTRIBUTABLE_LICENSES.get(self.license) != self.license_url:
            raise ValueError(f"{self.doc_id}: license is not redistributable or mismatched.")
        if self.abs_url != f"https://arxiv.org/abs/{self.arxiv_id}":
            raise ValueError(f"{self.doc_id}: abs_url does not match arxiv_id.")
        if self.pdf_url != f"https://arxiv.org/pdf/{self.arxiv_id}":
            raise ValueError(f"{self.doc_id}: pdf_url does not match arxiv_id.")
        if not self.doc_id.endswith(f"_{self.year}"):
            raise ValueError(f"{self.doc_id}: doc_id must end with the year.")
        return self

    @property
    def filename(self) -> str:
        return f"{self.doc_id}.pdf"

    @property
    def first_author(self) -> str:
        return self.authors[0]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus: Literal["veridex-corpus-v3"]
    description: str
    papers: list[Paper] = Field(min_length=30, max_length=50)

    @model_validator(mode="after")
    def _unique(self):
        for field in ("doc_id", "arxiv_id"):
            values = [getattr(paper, field) for paper in self.papers]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {field} in manifest.")
        return self

    def by_id(self) -> dict[str, Paper]:
        return {paper.doc_id: paper for paper in self.papers}


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    return Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
