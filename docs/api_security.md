# API access and session ownership

The HTTP interface currently implements request limits and safe error responses.
It does not implement caller authentication or session ownership. The local runner
is for trusted development access; do not expose it publicly as a multi-user API.
No Cloud Run access policy or public-access configuration is created by this code.

Require authenticated Cloud Run invocation and restrict `roles/run.invoker` to
approved principals. IAM admission alone does not isolate conversations: every
admitted caller can currently select the same `session_id` and append to, or elicit
information from, that conversation. Random IDs reduce collisions, not this risk.
Never trust an unverified user ID header or an unverified token claim.

The minimal single-user demo option is one explicitly trusted invoker and an
ephemeral session policy. For multiple users, verify end-user identity in the
application (or a trusted authentication gateway), and derive an internal thread
key from the verified issuer/subject plus the supplied session ID. This keeps
`{"query":"...","session_id":"..."}` unchanged. A shared service-account invoker
cannot distinguish its end users; those users need a separately verified identity.

Choose the identity provider, trusted gateway/header rules if any, allowed callers,
and restart/expired-session behavior before implementing ownership. No ownership
implementation is enabled until this policy is approved. Cloud Run token forwarding
semantics must be checked before selecting which token the application verifies.

InMemorySaver and session locks remain process-local and unbounded over the lifetime
of an instance. Request caps do not cap retained conversations. Maximum instances 1
does not provide durability, ownership, or continuity across revision replacement.
Future multi-user access also needs bounded session retention and per-user quotas;
durable checkpoints and cross-instance turn coordination are separate work.

HTTP defaults: 64 KiB per chat body, 4 active requests, 8 waiting requests, 30 seconds
maximum admission wait, and 180 seconds total from ASGI entry. The 120-second agent
deadline remains unchanged. Slow uploads, admission queues, and session-lock waits
consume the HTTP budget. Client cancellation and HTTP deadlines cancel the agent
in its existing request task, allowing interrupted tool history to be repaired.
Cancellation-resistant work can delay that repair; synchronous worker threads are
not directly interruptible. The existing eight-second lifespan shutdown deadline
remains authoritative during termination. These limits exclude upstream platform
queueing and do not implement disconnect monitoring once the body has been read.

Errors return fixed messages and never echo rejected request values or provider
exceptions. Successful chat responses intentionally contain the agent's answer,
which may cite or quote corpus evidence; the application does not promise to
remove sensitive material that a model places in a successful answer.

Deployment references:
- https://docs.cloud.google.com/run/docs/authenticating/service-to-service
- https://docs.cloud.google.com/run/docs/authenticating/end-users
