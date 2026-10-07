# Phase 1D — features on the installed n8n

Instance: `n8nio/n8n:2.43.0`, digest `sha256:c6a3a0461d1d3ffc16d849adf57606c2b028667ade70cce2faa2ff094734873c`, Community image, UI bound to `127.0.0.1:5678`. Database counts at 2026-10-07T00:49:34Z: 4 workflows, 0 credentials, 0 API keys, 0 webhooks, 0 installed packages, 0 variables, 66 executions, 1 user.

Unauthenticated `GET /rest/settings` returned HTTP 200 in public mode. It reported `communityNodesEnabled` false, SAML login false, LDAP login false, OIDC login false, and `enterprise.saml`, `enterprise.ldap`, and `enterprise.oidc` false. It did not include `planName`. An earlier authenticated settings read on this same instance, recorded in `/home/johnclaw/m8m-bakeoff-lab/docs/N8N.md`, listed the remaining enterprise flags false, including external secrets, source control, variables, sharing, log streaming, audit logs, and debug-in-editor. That longer list was not re-fetched this pass. Label for the longer list: OBSERVED_LAB, earlier same day. Do not treat a Free Registered checkbox as on.

`GET /api/v1/openapi.yml` returned 200 without a key. `GET /api/v1/workflows` returned 401. No API key was created.

The first pilot uses none of the rows marked NOT_USED or BLOCKED_POLICY.

| Feature | On this version | Paid edition required | Needed by a first pilot | Boundary | If it fails | Lab result |
|---|---|---|---|---|---|---|
| Schedule trigger | Yes | No | Later, only as a shadow clock | Cron stays the live clock | A missed n8n tick does not stop cron | OBSERVED_LAB. Two monitors are active on a 5-minute schedule. |
| Webhook | Node present | No | No | Localhost only. Bench path is inactive. | Inactive workflows do not register the path | OBSERVED_LAB. Webhook rows: 0. |
| Wait and human review | Wait node is in the image | Some review tooling is enterprise. Not demonstrated. | No. The approval pilot cannot become an approval. | No grant, no 2FA | An unattended wait is not a decision | NOT_MEASURED |
| Execute Workflow | Node present | No | No | Sub-workflows would still be shadow | Not used | NOT_USED |
| HTTP Request | Yes | No | Read-only health is already the lab use | GETs of build-meta and DOF run-scope only | Non-200 stops that workflow | OBSERVED_LAB. Both monitors are active. |
| Pagination, batching, retries | Supported by the node, not configured here | No | No | Not an API gateway | Not used | NOT_USED |
| Error Trigger | Node present | No | No | Records in n8n only. No send. | Bench workflow is inactive | OBSERVED_LAB on 2026-10-06, then deactivated. Not a delivery receipt. |
| Public API and CLI | API path is on. CLI exists in the image and was not used to change workflows. | No | No | Zero keys. 401 without a key. | Closed | OBSERVED_LAB this pass |
| Postgres node | In the image | No | No | Must not receive the production DSN | Not used | 0 credentials. n8n's own database is a different Postgres, port not published. |
| Gmail, Telegram, Drive, GitHub nodes | In the image | No | No | A credential would be a second secret store | Blocked | BLOCKED_POLICY |
| AI Agent and tool calling | LangChain package is in the image and on no workflow | No for the node. Not approved for this program. | No | Would bypass the governed model gateway if given a provider key | Not enabled | NOT_USED |
| DeepSeek, OpenRouter, Ollama chat nodes | Direct nodes or HTTP would be possible | No | No | Direct provider credentials are forbidden | Blocked | BLOCKED_POLICY. Bridge on `127.0.0.1:8766` is not reachable as host loopback from the container. |
| Embeddings, vector store, chat memory | In the image | No | No | Not institutional memory | Not used | NOT_USED |
| AI evaluation and tracing | Evaluation node is in the image | No | No | Not a cost ledger | Not used | NOT_USED |
| Data tables | Node present | No | No | Not a second ledger | Not used | NOT_USED this pass (no table was created) |
| Workflow history and export | Instance history and JSON export work without paid Git | Paid source control is a different feature | Exports can be reviewed in git later | A git commit of JSON is not n8n's paid environments feature | Not a rollback of cron | OBSERVED_LAB for the existing monitor exports in the lab tree |
| Task runners and Code node | JavaScript runner only | No | Prefer no code in the first pilot | Python is disabled and the image has no Python runner | Python execution throws | OBSERVED_LAB. `N8N_PYTHON_ENABLED=false`. |
| Metrics, logging, security audit | Executions are stored. Log streaming was false on the earlier settings read. | Log streaming and audit logs are enterprise on that earlier read | An external check is still missing | n8n's own log cannot see a run it never started | No alert destination was created this pass | Executions: 66. Alert destination: not remeasured; earlier same day it was 0. |
| Queue mode | Documented for Community. Not installed. | Multi-main is not included | No. Five low-frequency pilots do not justify Redis. | Would add Redis, a main, and workers, and still dies with the host | Not installed | OBSERVED_LAB. Containers are `m8m-n8n` and `m8m-n8n-db` only. No Redis. |
| MCP client or server | Shipped catalog is not a connection | No | No | Prefer off | Not adopted | NOT_USED. No API key and no credential. |
| Credentials | Native encrypted database | External secret stores are enterprise and do not list Bitwarden | No secret is allowed in n8n | Second store, conflicts with Bitwarden-only | Blocked | OBSERVED_LAB. 0 credentials. |
| Users, MFA, SSO | One owner. SSO flags false this pass. | SSO is enterprise | No | Localhost UI is not authorization | Not expanded | OBSERVED_LAB |
| Projects and sharing | Not in the unauthenticated settings body | Team projects and sharing were off on the earlier read | DOF must not share a project with Trade AI if both ever run here | Community has no project wall | Separate instance, or stop | NOT a reason to put DOF workflows on this instance |
| Source control inside n8n | Not a Community feature on the earlier read | Yes | No. Reviewed JSON in git is the substitute. | Do not describe a git commit as n8n Git | n/a | BLOCKED as a product feature. Git review remains available outside n8n. |
| External secrets | Enterprise, no Bitwarden provider | Yes | Cannot satisfy the Bitwarden rule | Not a workaround | Blocked | BLOCKED_POLICY |

Excluded nodes remain Execute Command, SSH, FTP, email send (including tool variants), and Local File Trigger. `NODES_EXCLUDE` is a JSON array. Community package install is off. Those constraints were not loosened.

## Correction 2026-10-07T02:14Z

The 00:49Z counts above stay as that read. A later count on the same containers: 4 workflows, 0 credentials, 0 API keys, 0 rows in `webhook_entity`, 0 variables, 0 installed packages, 0 installed nodes, 1 project, 1 user, and 100 execution rows. Those rows are 48 successes for `n8n-monitor-trade-ai`, 48 successes for `n8n-monitor-dof`, 2 successes and 1 error for `n8n-bench-nodes`, and 1 success for `n8n-bench-error`. The inactive bench workflow still contains a webhook node with path `n8n-bench-nodes`. That node is not a registered webhook row. `GET /healthz` returned `{"status":"ok"}`. Workflow `updatedAt` values were unchanged by a workflow-only export. The full install read is `08-install-and-doc-audit.md`.
