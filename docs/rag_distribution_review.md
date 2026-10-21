# Corpus licensing decision — Step 4.7e

Reviewed 2026-10-12. This supersedes the earlier conditional distribution review.
Only rights/attribution decision documents were updated. No remote PDFs were fetched,
no artifact was changed, and no publication or deployment is authorized. Exact local
SHA-256 values and full author lists remain in [rag_attribution.json](v1/rag_attribution.json).
The JSON is an inventory, not a rights grant or a complete packaged NOTICE file.

## Decision and exact-file disposition

The current bundle remains blocked by **RAG 2020**. No officially authorized
CC-licensed version of that same paper was verified in the sources searched. This
is a bounded search conclusion, not proof that none exists anywhere. Recommend
replacing just that paper with the ACL-published Li et al. 2024 paper below, after
approved download and exact-file inspection. Alternatively, obtain applicable
rights-holder permission for the current RAG file, extracted text and intended
remote use; that would avoid any corpus change. No permission request was sent.

| Exact local file | Identity/license evidence | Disposition |
| --- | --- | --- |
| `rag_2020.pdf` | 19 pages, printed arXiv 2005.11401v4, 12 April 2021. No in-file reuse license located. Metadata records later Quartz/AppendMode processing. | Blocked: permission or licensed replacement required. |
| `react_2022.pdf` | 33 pages, printed arXiv 2210.03629v3, 10 March 2023, ICLR camera-ready. [Version-specific submission record](https://arxiv.org/abs/2210.03629v3) identifies the submitted PDF and links [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Local title/authors/version match; no conflicting local notice found. | Retain covered paper content with attribution, license and modification notices. Canonical remote-byte comparison has not been performed. |
| `self_rag_2023.pdf` | 30 pages, printed arXiv 2310.11511v1, 17 October 2023. [Version-specific submission record](https://arxiv.org/abs/2310.11511v1) identifies the PDF and links CC BY 4.0. Local title/authors/version match; no conflicting local notice found. | Same retention conditions as ReAct. |
| `netmhcpan_2020.pdf` | Six-page publisher article, DOI 10.1093/nar/gkaa379. Exact local PDF page 1 expressly grants CC BY-NC 4.0; [publisher-supplied PMC article](https://pmc.ncbi.nlm.nih.gov/articles/PMC7319546/) corroborates it. © The Author(s) 2020, OUP on behalf of Nucleic Acids Research. | Retain for compliant noncommercial coursework use with attribution. Commercial use requires permission or replacement. |
| `mixmhc2pred_2023.pdf` | 31-page publisher article, DOI 10.1016/j.immuni.2023.03.009. Exact local PDF page 2 expressly grants CC BY-NC 4.0, © 2023 The Authors, Elsevier Inc. | Retain under the same noncommercial conditions. Pages 19–31 are integral STAR+METHODS through e13, not an appended independent supplement. Publisher HTML was unavailable; the in-file notice is the evidence. |

The arXiv licenses attach to identified submissions and their linked paper files,
rather than a generic website footer. Matching local work/version identity supports
application to the paper. It does not certify canonical remote byte identity or
exclude every undocumented local alteration. CC permits adaptations with conditions;
byte identity is not itself a CC requirement. If release policy requires canonical
byte attestation, approve a separate version-pinned fetch/hash comparison; none was
performed here. No license notice was found inside ReAct/Self-RAG themselves.

Local notice and caption text review found no separately credited reproduction
exclusion in the four retained files. This is not comprehensive clearance of every
embedded third-party excerpt. ReAct contains benchmark/environment/Wikipedia
examples; Self-RAG includes retrieved-passage/training examples. Retain supplied
credits and do not claim independent rights to underlying sources. Bioinformatics
papers cite external datasets, structures and software; article licenses do not
independently license those resources. MixMHC2pred page 15 links external supplemental
information, which is not included or cleared. ReAct/Self-RAG appendices and integral
MixMHC2pred methods belong to the identified articles. No external datasets, code,
slides, posters or supplement downloads are proposed. Any subsequently identified
express exclusion must be resolved before publication.

## Original RAG paper and same-paper source search

**Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks**, Lewis et al.,
NeurIPS 2020. Authors: Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni,
Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Wen-tau Yih,
Tim Rocktäschel, Sebastian Riedel and Douwe Kiela. The manifest points to arXiv
2005.11401; the local file identifies v4.

| Official source inspected (HTML only) | Conclusion |
| --- | --- |
| [arXiv v4](https://arxiv.org/abs/2005.11401v4) | Links the [arXiv nonexclusive distribution grant](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html). This grants arXiv rights, not a CC downstream grant to us. |
| [NeurIPS proceedings](https://proceedings.neurips.cc/paper/2020/hash/6b493230-Abstract.html) and [copyright FAQ](https://neurips.cc/FAQ/Copyright) | Hosts the paper; authors retain copyright and license NeurIPS. That evidence alone does not authorize our redistribution. |
| [Meta author-affiliated record](https://ai.meta.com/research/publications/retrieval-augmented-generation-for-knowledge-intensive-nlp-tasks/) | Identifies the same work/authors and a download. No applicable CC grant found on the inspected record; download not fetched. |
| [UCL Discovery 10100504](https://discovery.ucl.ac.uk/id/eprint/10100504/) | Names `2005.11401v1.pdf`, 837 kB. UI labels it Published Version; additional information calls it an author accepted manuscript and refers reuse to publisher terms. No CC grant established. |

UCL differs from the local file by recorded version and reported manuscript status.
Exact text/layout/byte differences are unverified because downloads were prohibited.
It is not a cleared replacement. Search results claiming CC for unrelated papers
with similar titles, papers merely citing Lewis et al., and a third-party directory
were not accepted. Code licenses are not paper licenses; open access is not a reuse
grant. There is no verified same-paper CC PDF for which this review can provide
licensed attribution or a file comparison.

## Proposed one-paper replacement

1. **Preferred:** Zhuowan Li, Cheng Li, Mingyang Zhang, Qiaozhu Mei and Michael
   Bendersky (2024), *Retrieval Augmented Generation or Long-Context LLMs? A
   Comprehensive Study and Hybrid Approach*. EMNLP Industry Track, pp. 881–893;
   DOI **10.18653/v1/2024.emnlp-industry.66**.
   [Official article/PDF record](https://aclanthology.org/2024.emnlp-industry.66/).
   Named PDF: `https://aclanthology.org/2024.emnlp-industry.66.pdf`.
   Covers RAG/long-context comparison, cost and self-routing. Preserves the RAG
   theme but does not supply evidence for the original paper's specific claims.
2. **Alternative:** Niu et al. (2024), *RAGTruth: A Hallucination Corpus for
   Developing Trustworthy Retrieval-Augmented Language Models*, ACL long papers;
   DOI **10.18653/v1/2024.acl-long.585**.
   [Official article/PDF record](https://aclanthology.org/2024.acl-long.585/).
   Named PDF: `https://aclanthology.org/2024.acl-long.585.pdf`.
   Focuses on factuality evaluation; propose its paper only, not its dataset.

Both are ACL-published 2024 papers. [ACL's copyright policy](https://aclanthology.org/faq/copyright/)
explicitly licenses ACL materials published from 2016 under CC BY 4.0, including
reproduction/distribution. Named official PDF records plus that publisher policy
provide concrete file-source evidence, not a license inferred from open access.
The policy excludes third-party materials. Neither candidate PDF was fetched:
hashes, embedded notices and exclusions still require approved download/inspection.
Credit all authors, title, publisher/year/DOI, source, license and changes; preserve
additional supplied notices. Neither candidate is claimed fully cleared yet.

## Notice delivery and noncommercial conditions

For the new image/bundle, prepare a human-readable `CORPUS_NOTICE`, attribution JSON,
and applicable CC BY / CC BY-NC 4.0 license texts. Include authors, title/version,
source URI, copyright notices, license links, supplied disclaimers and changes;
never invent missing notices or imply endorsement. Disclose extraction/chunking.
If old RAG is retained with permission, disclose its two parenthesis substitutions
in `rag_2020_p3_c00012`. That repair must not be applied to unrelated replacement text.

Make equivalent notices accessible to service recipients: proposed public
`/attribution` page with a discoverable link, such as an HTTP `Link` header, plus
source/title/page attribution for retrieved evidence. Delivery is **planned, not
implemented**. Preserve `/chat` JSON exactly `{"response":"..."}`. Ship notices
with distributed images/indexes; Chroma contains source text, so removing PDFs alone
does not resolve rights. Do not impose restrictions or technical measures contrary
to the applicable CC license on licensed content.

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en) restricts
use to purposes not primarily directed toward commercial advantage or monetary
compensation. Recommend an unmonetized noncommercial coursework demo with a defined
grading expiry. Paid hosting alone does not decide purpose. Confirm actual use and
recipients: educational intent and private registry storage are not automatic
exemptions. Commercial expansion needs permission/replacement for both NC papers.
Compliant covered CC reuse does not automatically require a separate rights-holder
grant. User acceptance of conditions cannot supply missing copyright permission.

## Migration procedure — only after approval

1. Approve the preferred candidate and fetch only its named official PDF into a new
   staging directory. Record final URL, timestamp, SHA-256, version, license evidence
   and inspected notices; resolve express exclusions before ingestion. Never
   overwrite original, recovered or bundled artifacts.
2. Create a new five-paper manifest/version. Retain four current IDs/hashes; replace
   `rag_2020` with truthful ID **`rag_long_context_2024`** and filename
   `rag_long_context_2024.pdf`. Alternative selection gets its own truthful ID.
   Never reuse old RAG IDs/citations for another work. Retain old artifacts for rollback.
3. Pin parser/chunker versions, parameters, normalization rules and ordering; record
   source hashes and recipe. Reproduce retained chunk IDs only for unchanged chunks;
   generate new document/page/chunk-index IDs for the replacement and check collisions.
   Reject unexpected controls; do not propagate the old targeted repair. Recalculate
   expected counts: 523 retained chunks plus new replacement chunks if the other
   four papers' chunking stays unchanged. **615 is not a new-corpus requirement.**
4. Recommend re-embedding **all five** approved papers using explicitly requested
   `text-embedding-3-small`, dimensions **1536**, after separate paid-call approval.
   Existing dimension 1536 does not verify historical model identity. Mixing old/new
   vectors solely because dimensions match is unsafe. Calculate an offline token/cost
   estimate first and approve a dollar ceiling. Record requested/provider-reported
   model, dimensions, SDK/chunker versions and run provenance; hash finite FLOAT32
   vectors. A provider alias does not guarantee future identical output; preserve
   vectors for reproducible replay. No paid request is authorized now.
5. Build Chroma through its public API into a new directory with locked dependencies.
   Validate manifest/files, IDs, metadata/pages, actual count, dimensions, checksums,
   SQLite/FTS5 integrity, `$contains`, native self-queries and semantic retrieval
   questions. Update tests genuinely tied to old content/counts. Verify other-paper
   retrieval, Workspace attribution, real MCP routing, two-turn memory and HTTP schema.
6. Export a new locally validated bundle/version/provenance/digest with notices. Run
   Linux/amd64 Docker TCP and ordinary regression tests. Review build selections for
   renamed PDF files and pin the new bundle digest. Do not replace the existing
   `veridex-rag-v1-local`; remote publication requires separate approval.

Local ingestion can be deterministic; provider outputs cannot be promised identical
on future runs. If applicable original RAG permission is obtained, no rebuild is
needed for licensing. Historical model uncertainty could be documented for coursework;
a model-pinned rebuild is recommended when replacement already requires embeddings.

## Outstanding approval gate

| Decision/action | Evidence or authorization required |
| --- | --- |
| RAG resolution | Approve Li et al. replacement and its official PDF download/review, or provide applicable rights-holder permission for the current file/extracted text/intended remote use. |
| NC retention | Confirm genuinely noncommercial coursework use, recipients, no monetization and grading expiry; fulfill attribution conditions. |
| File/scope checks | Inspect candidate exclusions; optionally approve canonical ReAct/Self-RAG fetch/hash comparison if release provenance policy requires it. Separate supplements/datasets remain excluded. |
| Rebuild/paid calls | Approve new staging corpus/index; separately approve pinned model, estimated provider cost and ceiling. |
| Notice delivery | Approve subsequent packaging/service changes to ship notices and provide discoverable attribution without changing `/chat` JSON. |
| Release/cloud | After local validation/rights gates, separately authorize registry publication, GCP resources, secrets/IAM and public grading invocation. All remain unauthorized. |

**Conclusion:** a concrete conditional replacement path is established, but the
current bundle is not cleared for remote publication. Step 4.8 is not yet ready for
deployment authorization. No migration, paid call or cloud action occurred here.
