# API security and public grading limits

Step 4.7c targets the handout-compatible unauthenticated grading URL, pending
explicit deployment approval. No cloud access policy has changed. POST `/chat`
retains `query` and `session_id`, returning only `response`. No mandatory auth
header, cookie, server-issued token or extra field is introduced.

Anonymous IDs select conversations, not verified owners. Two callers choosing the
same ID share history. Distinct normal IDs are isolated by the checkpointer, but
there is no cross-user confidentiality guarantee. Random IDs reduce accidental
collisions, not unauthorized access. Use no confidential data or credentials.
Identity-scoped ownership remains a future authenticated deployment option.

Implemented controls:

- Strict nonblank strings: query <=10,000 characters, session ID <=128; no extras.
- Body <=65,536 bytes; defaults active 1 / waiting 0. Explicitly enabled queues have
  a 30-second admission deadline included in the HTTP 180-second budget.
- Agent 120s, recursion 12; eight tool calls and six generation requests per turn.
  An over-budget parallel tool round is rejected before any of its calls.
- Generation `max_completion_tokens=4096`, provider timeout 30s by default, retries 0.
  Embedding clients use the same timeout/retries 0, forwarded to the scoped Evidence child.
  `PROVIDER_TIMEOUT_SECONDS` (maximum 45) sets both; the serving Cloud Run revision uses 45s.
  Tavily retains its 20-second outer deadline and single SDK POST with no app retry loop.
- Serialized messages including system context must fit 64,000 characters before
  model invocation. This conservative cap is not an exact provider token count.
- At most 128 retained sessions. Lazy 30-minute idle expiry deletes checkpoint and
  lock records. Active/waiting turns reserve slots and cannot expire. Full capacity
  returns 429 without silently evicting an unexpired conversation.
- Retain six recent complete human turns and compact the exact default InMemorySaver
  through public APIs to the latest checkpoint/pending writes after each turn/repair,
  under its session lock. The saver instance stays the same; intermediate checkpoints
  remain during execution. Recent two-turn memory survives, older/expired history can
  be forgotten. Custom saver retention/transaction policies remain separate work.
- Cancellation repair stays in the request task. Complete-body disconnect monitoring
  begins after admission; queued disconnects are bounded by admission wait.
- Readiness is withdrawn at lifespan shutdown. The eight-second cleanup budget
  follows Uvicorn's 0.5-second drain. Agent close drains then clears default memory
  and session bookkeeping. Health/readiness use no provider calls.

Validation 422, invalid length headers 400, body 413, admission/session capacity 429,
HTTP/queue deadline 504, unavailable 503 and internal failures 500 use fixed safe
messages. Agent budget failures return the existing unverified-answer fallback;
CancelledError propagates. Successful model answers may cite/quote corpus content;
there is no automatic confidentiality/redaction guarantee for their text.

Limits are configurable and process-local. No durable rate limiter, global spend
ceiling, verified ownership, durable checkpoints or time-travel history is provided.
Output caps cannot predict exact dollars: schema/context overhead, embedding input
splitting, configured retries and sustained traffic add costs. Retained-turn limits
bound history length, not peak output bytes independently of tool-server limits.
Max one instance can be exceeded temporarily and counters reset on recycling.
Alerts are not enforced external-provider limits. Colliding IDs can contaminate or
exhaust another caller's conversation; accepting this risk is a public-demo decision.

Before public admission, approve rights/notices, anonymous privacy limitations,
provider allowance, expiry and revocation. Stage private, then use the separate
public grant. Revocation cannot recall disclosed text. Cancellation-resistant work,
synchronous PDF/Chroma threads and idle CPU throttling still need native validation.
See [approval checklist](deployment_approval_checklist.md) and
[prepared commands](cloud_run_commands.md). No cloud action is authorized here.
