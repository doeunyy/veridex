"""Public corpus notices only: no provider traces, document text or internal paths."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PaperAttribution(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    title: str
    authors: list[str] = Field(min_length=1)
    source_url: str
    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_id: Literal["CC-BY-4.0", "CC-BY-NC-4.0"]
    license_url: str
    copyright_notice: str
    modifications: list[str]
    third_party_scope: str


class CorpusAttribution(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    corpus_version: str
    intended_use: str
    limitations: list[str]
    documents: list[PaperAttribution] = Field(min_length=5, max_length=5)


def load_attribution(path: Path | None) -> CorpusAttribution | None:
    if path is None:
        return None
    return CorpusAttribution.model_validate(json.loads(path.read_bytes()))
