# Local RAG candidate distribution review

Reviewed 2026-10-10 against the five manifest-listed local PDFs and their exact
SHA-256 fingerprints recorded in `bundle.json`. This review grants no distribution
approval. The bundle is local/internal only; remote image publication is blocked
pending authorization for the intended recipients and use.

| Paper / PDF | Available license evidence | Redistribution review status |
| --- | --- | --- |
| `rag_2020` / `rag_2020.pdf` | Local PDF identifies arXiv v4, but contains no license notice. [arXiv v4](https://arxiv.org/abs/2005.11401v4) links the [arXiv nonexclusive license](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html). | That grant to arXiv does not establish downstream permission for this bundle. Additional authorization required. Local PDF metadata also indicates later modification; exact-file scope requires review. |
| `react_2022` / `react_2022.pdf` | Local PDF identifies v3; [arXiv](https://arxiv.org/abs/2210.03629v3) links [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). No license notice found inside the PDF. | Repository license evidence found; verify exact-file applicability and retain required attribution, license link, and applicable notices before distribution. Not yet authorized. |
| `self_rag_2023` / `self_rag_2023.pdf` | Local PDF identifies v1; [arXiv](https://arxiv.org/abs/2310.11511v1) links [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). No license notice found inside the PDF. | Same attribution/exact-file applicability review as ReAct; not yet authorized. |
| `netmhcpan_2020` / `netmhcpan_2020.pdf` | PDF page 1 expressly identifies [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) and noncommercial reuse with citation. | Noncommercial use and attribution conditions must be satisfied; authorization for intended deployment/distribution remains pending. |
| `mixmhc2pred_2023` / `mixmhc2pred_2023.pdf` | PDF page 2 expressly identifies [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). The local 31-page file includes additional material. | Verify supplementary-material and third-party scope, attribution, and noncommercial conditions before approval. |

Publisher web verification was unavailable for PMC (browser challenge) and
ScienceDirect (retrieval failure); the biomedical evidence above is from the actual
local PDFs. Public possession/access alone was not treated as distribution rights.
CC licenses may not cover third-party material or every right needed for a planned
use. The index contains source text as well as vectors; the rights review also
applies to distribution of Chroma contents, not only PDFs.

The manifest carries titles and source URLs but is not a complete distribution
attribution package. Before remote publication, finish the rights review and prepare
required notices/attribution for the chosen use. A private registry is still a remote
publication and has not been approved. No authorization is inferred from this step.

Embedding-model identity remains unresolved. Linux/amd64 container compatibility
was subsequently verified in Step 4.5/4.6 under local emulation; native Cloud Run
performance remains unmeasured. `unverified-legacy-model` is an explicit uncertainty
marker, never a claim that old vectors came from the current configured model.

[Step 4.7b](deployment_approval_checklist.md) distinguishes CC license conditions
from missing permission. Compliant reuse of covered CC-licensed material does not
automatically require a separate rights-holder grant. RAG's downstream permission
remains unestablished; conditional corpus replacement is proposed, not performed.
