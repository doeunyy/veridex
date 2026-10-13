# Step 4.8.1c — Block A verification and remaining provisioning preflight

Verified 2026-10-12 using the USC account `<OPERATOR_ACCOUNT>`, project
`zeta-store-511505-i7`, region `us-west1`, and linked USD billing account
`<BILLING_ACCOUNT_ID>`. No cloud mutation was performed. Block A was authorized,
but all three APIs were already listed as enabled; no enablement command was needed.

## Read-only results

| Check | Result |
| --- | --- |
| IAM API | `iam.googleapis.com` enabled |
| Secret Manager API | `secretmanager.googleapis.com` enabled; secret listing succeeds |
| Billing Budgets API | `billingbudgets.googleapis.com` enabled; budget listing succeeds on recheck |
| Artifact Registry, us-west1 | No repositories; `veridex` available |
| Runtime service-account name | `veridex-runtime` absent; only the existing Compute default account was listed |
| Secret names | No secrets; both `veridex-openai-api-key` and `veridex-tavily-api-key` available |
| Billing budgets | Successful billing-account list returned `[]`; no duplicate budget |
| Project permission introspection | `resourcemanager.projects.get`, `billing.resourcebudgets.read`, `billing.resourcebudgets.write` all returned |
| Billing-account permission introspection | `billing.accounts.get`, `billing.accounts.getIamPolicy`, `billing.budgets.create`, `billing.budgets.list` all returned |
| Intended default email recipient | Billing policy lists `user:<OPERATOR_ACCOUNT>` under `roles/billing.admin`; no Billing Account User bindings returned |

The first budget list returned `SERVICE_DISABLED` despite the enabled-service list.
Its enable-and-retry prompt was explicitly declined. A subsequent read-only list
succeeded without a mutation, consistent with API propagation delay. This was not
an IAM denial. Permission checks used read-only `testIamPermissions` operations;
no policy bindings were changed. Tokens were captured only in memory and not printed
or saved. The SDK policy command returned INVALID_ARGUMENT; an official REST GET
retrieved the recipient policy successfully. Email delivery has not been tested.

[Google's budget guidance](https://docs.cloud.google.com/billing/docs/how-to/budgets)
confirms single-project budgets are supported and project billing-budget permissions
can suffice. Account-level create/list authority was independently verified here.
[Default email recipients](https://docs.cloud.google.com/billing/docs/how-to/budgets-notification-recipients)
are Billing Account Administrators and Users. The USC administrator is the intended
recipient; no notification channel, test email, or budget has been created.

## Review of Blocks B–E and next approval

The commands in [Step 4.8.1b](gcp_provisioning_review_481b.md) remain PREPARED BUT
NOT EXECUTED. B names a private Docker repository only. C creates a dedicated
runtime identity without keys or roles. D depends on C and creates empty secret
shells plus two secret-scoped accessor bindings; it adds no values or versions.
E is independently executable after approval: one monthly USD $5 budget filtered
to `projects/<PROJECT_NUMBER>`, all services, excluding credits, with actual-spend
thresholds of 50%, 80%, and 100% ($2.50/$4/$5), default role-based email enabled.
No duplicate, permission, currency, or recipient blocker remains for E.

**Next single block requiring explicit approval: Block E.** Approval should include
its gross-usage/exclude-all-credits basis and default billing-role recipients.
Creating alerts is not itself a compute/storage usage charge. Alerts can be delayed
and are not a hard spending cap; provider charges are separate. No spending-cap
support is inferred from this verification.

Recommended order: E → B → C → D, with a separate approval for each block and fresh
read-only collision checks immediately before creation. Preserve the budget through
later publication/deployment and cleanup. Secret version insertion, registry push,
private Run deployment, live-provider verification, and public grading access each
remain separate future gates. No runtime billing permissions are needed.

All prior cleanup commands also remain unexecuted and require separate approval.
Do not remove the existing Compute default account or pre-existing API enablement.
No images, corpus artifacts, secrets, IAM bindings, or Run services were changed.
