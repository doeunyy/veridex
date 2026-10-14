"""Export the reviewed recovered index as a local/internal-only deployment candidate."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from veridex.rag import recovery
from veridex.rag.artifacts import (
    ArtifactError,
    assert_idle,
    digest,
    package_bundle,
    read_file,
    records,
    relative_path,
    source_files,
    tree,
    validate_bundle,
)

RECOVERY_SHA256 = "e5bc1f7d240960c44ced003c44e1f97fb465896d401ff9fe76c9942ac1271c7b"
PDF_RIGHTS = {
    "rag_2020": {
        "evidence": "https://arxiv.org/abs/2005.11401v4",
        "license": "arXiv nonexclusive distribution license",
        "status": "No downstream redistribution permission established; local PDF has no license notice",
    },
    "react_2022": {
        "evidence": "https://arxiv.org/abs/2210.03629v3",
        "license": "CC BY 4.0 (arXiv license link)",
        "status": "Attribution and exact-file applicability review pending",
    },
    "self_rag_2023": {
        "evidence": "https://arxiv.org/abs/2310.11511v1",
        "license": "CC BY 4.0 (arXiv license link)",
        "status": "Attribution and exact-file applicability review pending",
    },
    "netmhcpan_2020": {
        "evidence": "local PDF page 1",
        "license": "CC BY-NC 4.0",
        "status": "Noncommercial/attribution conditions; deployment authorization pending",
    },
    "mixmhc2pred_2023": {
        "evidence": "local PDF page 2",
        "license": "CC BY-NC 4.0",
        "status": "Noncommercial/attribution and supplementary-material scope review pending",
    },
}


def export(
    *, project: Path, destination: Path, snapshot_version: str, source_quiescent: bool
) -> str:
    if not source_quiescent:
        raise ArtifactError("Stop readers/writers and attest source quiescence.")
    project = project.absolute()
    destination = destination.absolute()
    allowed = project / ".artifacts/versions"
    if (
        destination == allowed
        or not destination.is_relative_to(allowed)
        or destination.resolve() != destination
        or project.resolve() != project
    ):
        raise ArtifactError(
            "Local bundle must be under the safe ignored .artifacts/versions directory."
        )
    relative_path(snapshot_version)
    if "/" in snapshot_version:
        raise ArtifactError("Snapshot version must be one component.")
    if destination.exists() or destination.is_symlink():
        raise ArtifactError("Bundle already exists; never overwrite it.")
    candidate = project / ".artifacts/recovery/veridex-rag-recovered-v1"
    # Missing candidates must never trigger recovery/reconstruction during export.
    provenance = read_file(candidate, "provenance.json")
    if digest(provenance) != RECOVERY_SHA256:
        raise ArtifactError("Recovered provenance differs from the reviewed trusted digest.")
    assert_idle(candidate / "chroma")
    candidate_before = records(candidate, tree(candidate))
    report = recovery.recover(
        project=project,
        reference=project / ".artifacts/source-inspection.json",
        destination=candidate,
        source_quiescent=True,
    )
    before = recovery.fingerprint(project, report["source_files"])
    provenance_record = {
        "embedding_model_identity": report["embedding_model_identity"],
        "recovery_provenance_sha256": RECOVERY_SHA256,
        "source_inspection_sha256": report["source_inspection_sha256"],
        "source_files": report["source_files"],
        "normalization": report["normalization"],
        "recovered_files": report["recovered_files"],
        "distribution": "LOCAL/INTERNAL ONLY; remote image publication BLOCKED pending authorization",
        "pdf_rights_review": PDF_RIGHTS,
        "linux_amd64_compatibility": "UNVERIFIED; requires native container validation",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".export-", dir=destination.parent) as scratch:
        temporary = Path(scratch)
        staged = temporary / "bundle"
        checksum = package_bundle(
            manifest=project / "data/samples/manifest.json",
            papers=project / "data/papers",
            index=candidate / "chroma",
            destination=staged,
            snapshot_version=snapshot_version,
            lock_file=project / "uv.lock",
            expected=recovery.SPEC,
            source_quiescent=True,
            embedding_model_provenance=json.dumps(provenance_record, sort_keys=True),
        )
        # Compare every approved source vector/text/metadata through native Chroma.
        source = temporary / "original-copy"
        source.mkdir()
        for name in tree(project / "data/index"):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(project / "data/index", name))
            if (
                digest(target.read_bytes())
                != report["source_files"][f"data/index/{name}"]["sha256"]
            ):
                raise ArtifactError("Original source changed during verification copying.")
        payload = temporary / "records.json"
        payload.write_bytes(recovery.canonical(recovery.extract(source)))
        recovery.verify(staged / "chroma", payload, temporary, project)
        metadata = validate_bundle(
            staged,
            expected=recovery.SPEC,
            metadata_sha256=checksum,
            lock_file=project / "uv.lock",
            probe=True,
        )
        expected_files = source_files(
            project / "data/samples/manifest.json",
            project / "data/papers",
            candidate / "chroma",
            recovery.SPEC,
        )
        if any(
            metadata.files[name].sha256 != digest(path.read_bytes())
            for name, path in expected_files.items()
        ):
            raise ArtifactError("Final bundle differs from source checksums.")
        assert_idle(candidate / "chroma")
        assert_idle(project / "data/index")
        if (
            records(candidate, tree(candidate)) != candidate_before
            or recovery.fingerprint(project, report["source_files"]) != before
        ):
            raise ArtifactError("Original or recovered source changed during export.")
        if destination.exists() or destination.is_symlink():
            raise ArtifactError("Bundle destination appeared during export; never overwrite it.")
        staged.rename(destination)
    return checksum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--snapshot-version", required=True)
    parser.add_argument("--source-quiescent", action="store_true")
    args = parser.parse_args()
    try:
        checksum = export(
            project=Path.cwd(),
            destination=args.destination,
            snapshot_version=args.snapshot_version,
            source_quiescent=args.source_quiescent,
        )
    except ArtifactError as exc:
        print(f"Local export rejected: {exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 — do not expose document contents or native errors
        print("Local export rejected: invalid or incomplete source/candidate.", file=sys.stderr)
        return 1
    print(f"Validated local/internal bundle: {args.destination}")
    print(f"bundle.json SHA-256: {checksum}")
    print("Remote publication BLOCKED; embedding model and Linux/amd64 compatibility unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
