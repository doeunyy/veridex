# Offline Chroma recovery workflow

This command implements the approved recovery of the reviewed Chroma 1.5.9
index. It does not ingest PDFs, load an embedding provider, replace `data/index`,
or export a deployment bundle. Run it from the repository root with the existing
locked environment (SQLite >=3.44 is required):

```sh
.venv/bin/python scripts/recover_rag.py \
  .artifacts/recovery/veridex-rag-recovered-v1 --source-quiescent
```

Stop all source readers/writers and prevent new ones from starting until the
command finishes. `--source-quiescent` is an operator attestation; `lsof` and
before/after fingerprints detect mistakes but cannot enforce a maintenance window.
Do not run against an active SQLite/HNSW directory. No checkpointing or repairing
of the source is performed. SQLite sidecars or additional index files are rejected.

The default reference is `.artifacts/source-inspection.json`, pinned in the code
to SHA-256 `7e033346ee4ff1c9dc6e408b0c3989e7ecbc7f4756a964519f13ae53afcc1f07`.
Its eleven file sizes, SHA-256 hashes, and mtimes must match. This deliberately
supports only the investigated source; a different source requires review, not
an override flag. Keep this ignored report with the original corpus for rollback.
The command records those fingerprints in the recovered provenance as well.

A verified disposable copy is read through immutable, read-only SQLite. Stored
metadata must agree with the complete FLOAT32 replay log. Public Chroma
`create_collection`/`add` calls reconstruct a distinct index with explicit vectors
and `embedding_function=None`; no internal tables are edited or repaired.

Only `rag_2020_p3_c00012` changes: offset 491 U+0000 becomes `(` and offset 502
U+0001 becomes `)`. The reviewed original and resulting text hashes are checked,
and both lengths remain 927 characters. This happens after chunking: chunk IDs,
page references, start offsets, metadata, and all 615 vectors remain unchanged.
Other PDF font control codes, including five other U+0001 occurrences, remain
unchanged. The pinned source fingerprints reject any additional unreviewed codes
or changes; an additional NUL or changed target pair is also explicitly rejected.

Validation checks all 615 vectors as little-endian FLOAT32 bytes through native
Chroma, all metadata and texts, every chunk's self-query in the top five with
near-zero distance, and exact `$contains` results for `BERTd`, `d(z)`, and `q(x)`.
The original SQLite error must be the reviewed FTS5-only failure. The candidate
must pass SQLite integrity, the official FTS5 diagnostic on a disposable copy,
and the unchanged artifact validator plus its native probe on a temporary bundle.
That temporary bundle is deleted; it is not retained or published.

Only after all checks and a final source fingerprint check does the command retain
`chroma/` and `provenance.json` in the separate ignored output directory. Provenance
records per-chunk vector, metadata, original text, and recovered text hashes,
source fingerprints, normalization, Chroma version, lockfile hash, and validation
results. Repeating the same command revalidates and reuses the existing result
without rewriting it. Modified/incomplete outputs are rejected, never replaced.
Failures remove staging copies; the untouched source is the rollback artifact.
Chroma generates new collection/segment UUIDs, so reconstruction is reproducible
in logical contents and validation, not necessarily byte-identical database files.

The historical embedding model remains **unresolved**. The validation-only model
label is `unverified-legacy-model`, not an attestation of the configured model.
Before deployment-bundle export, approve a policy for this uncertainty (trusted
historical attestation, or explicitly approved embedding regeneration). PDF
redistribution rights also remain unapproved. The recovered index was verified
locally on Darwin/arm64; Linux/amd64 native reopening with the locked dependencies
still needs verification during Docker preparation. No Docker/cloud resources
are changed by this workflow.
