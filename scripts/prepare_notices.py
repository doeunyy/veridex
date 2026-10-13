"""Build image-only notices from the pinned bundle; never modify canonical artifacts."""

import json
from pathlib import Path

from veridex.api.attribution import CorpusAttribution
from veridex.deployment.runtime import BUNDLE, BUNDLE_SHA256, LOCK, SPEC, validate
from veridex.rag.artifacts import ArtifactError


def corpus_notice(metadata) -> CorpusAttribution:
    provenance = json.loads(metadata.embedding_model_provenance)
    attribution = provenance["attribution"]
    papers = []
    for entry in attribution["documents"]:
        filename = entry["filename"]
        if metadata.files[f"papers/{filename}"].sha256 != entry["sha256"]:
            raise ArtifactError("Attribution source fingerprint differs from bundled PDF.")
        papers.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "authors": entry["authors"],
                "source_url": entry["source_url"],
                "version": entry["identified_local_version"],
                "sha256": entry["sha256"],
                "license_id": entry["license_id"],
                "license_url": entry["license_url"],
                "copyright_notice": entry["copyright_notice"],
                "modifications": entry["modifications"],
                "third_party_scope": entry["third_party_review"],
            }
        )
    if len(papers) != 5 or {p["id"] for p in papers} != set(SPEC.document_ids):
        raise ArtifactError("Release attribution has incorrect document IDs.")
    return CorpusAttribution(
        corpus_version="veridex-corpus-v2",
        intended_use="Noncommercial coursework grading demo; remote publication requires separate authorization.",
        limitations=[
            "NetMHCpan and MixMHC2pred are CC BY-NC 4.0: covered reuse must be noncommercial.",
            "Article licenses do not independently license linked datasets, software, external supplements or excluded third-party material.",
            "No author endorsement is implied. PDFs are unchanged; text extraction/chunking and recorded control escaping are modifications.",
        ],
        documents=papers,
    )


def main():
    metadata = validate(BUNDLE, checksum=BUNDLE_SHA256, lock=LOCK)
    notice = corpus_notice(metadata)
    destination = Path("/opt/veridex/notices")
    destination.mkdir()
    data = notice.model_dump_json(indent=2) + "\n"
    (destination / "attribution.json").write_text(data)
    lines = [
        "Veridex Corpus v2 — Attribution and License Notices",
        notice.intended_use,
        *notice.limitations,
    ]
    for paper in notice.documents:
        lines.extend(
            [
                "",
                paper.title,
                ", ".join(paper.authors),
                paper.version,
                paper.source_url,
                paper.copyright_notice,
                f"{paper.license_id}: {paper.license_url}",
                "Modifications: " + "; ".join(paper.modifications),
                paper.third_party_scope,
            ]
        )
    (destination / "CORPUS_NOTICE.txt").write_text("\n".join(lines) + "\n")
    for identifier in ["CC-BY-4.0", "CC-BY-NC-4.0"]:
        source = Path("/app/src/veridex/deployment/notices") / (identifier + ".txt")
        (destination / source.name).write_bytes(source.read_bytes())
    for path in destination.iterdir():
        path.chmod(0o444)
    destination.chmod(0o555)


if __name__ == "__main__":
    main()
