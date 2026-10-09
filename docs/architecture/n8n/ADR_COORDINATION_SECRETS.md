# ADR: coordination secrets for the n8n lab

```
Status:      ACCEPTED 2026-10-08 (operator decision: "one scoped key may live in n8n")
as_of:       2026-10-08T12:00:00-04:00
Measured at: origin/main e6eee00a2 (served CURRENT == main) / lab compose docker-compose.n8n.yml as read 2026-10-08
Supersedes:  the PROPOSED text of 2026-10-07, kept verbatim below under "Superseded"
Policy:      AGENTS.md §23.5 (ACTIVE 2.0.0, ratified 2026-10-08; amended by 3.0.0 ACTIVE 2026-10-09, see "Addendum — AGENTS.md 3.0.0"; 4.0.0 ACTIVE 2026-10-09 adds no credential)
```

## Decision

n8n holds **exactly one credential**: the relay bearer, `TRADEAI_N8N_RELAY_BEARER`, stored as a single
n8n Header-Auth credential and presented only to `tradeai-n8n-run-relay.service` on the docker bridge
(`172.19.0.1:18092`, pending the operator's permission to bind it). The bearer can do one thing: ask the
relay to request a run of a lane in `config/n8n_run_allowlist.json` in `dry_run` or `live` mode. The gateway
HMAC key for that path, `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` (caller `n8n-relay`, scope `coordination_run`),
is read by the relay from the rendered tmpfs env (`/run/user/1000/tradeai/env`) and **never enters n8n**;
the existing `TRADEAI_N8N_GATEWAY_HMAC_KEY` (caller `tradeai-dispatch`, scope `coordination_read`) is
unchanged. Both values are minted in Bitwarden Secrets Manager (project `trade-ai-prod`), delivered by
`scripts/secrets/render_env.py`, named in `config/secret_registry.yaml` with `max_age_days: 7`, and rotated
weekly by `scripts/secrets/rotation_daemon.py` once that daemon is scheduled (it is unscheduled today —
`10-eligibility-and-secrets-20261007.md` §6; scheduling it is a `cron` grant and is not part of this ADR).
Rotation of the bearer is two-step: the relay accepts the current and the previous bearer for one overlap
window (`TRADEAI_N8N_RELAY_BEARER_PREVIOUS`, same pattern as `TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS`),
the operator updates the n8n credential, the previous value is removed. No other credential of any kind —
provider, broker, database, messaging, n8n API key — may exist in n8n; adding one is an AGENTS.md §17
decision.

## Preconditions (all must hold before the credential is created)

1. **Execution data on success is not retained.** `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`,
   `EXECUTIONS_DATA_SAVE_ON_ERROR=all`, `EXECUTIONS_DATA_PRUNE=true`, `EXECUTIONS_DATA_MAX_AGE=168` in the
   running compose file (measured 2026-10-07: `SAVE_ON_SUCCESS=all`, no prune). Diff proposed in
   `docs/implementation/n8n-parallel/proposals/n8n-lab-hardening-compose-diff-20261008.md`.
2. **Owner MFA is on** for the single owner account (`bakeoff-n8n@m8m.lab`, measured MFA off 2026-10-07).
3. **The n8n database role is not a superuser** (`n8n_app` from
   `docs/implementation/n8n-parallel/proposals/init/01-n8n-app-role.sh`, applied on a fresh volume on
   recreate; the official image makes `POSTGRES_USER` a superuser).
4. `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, `N8N_COMMUNITY_PACKAGES_ENABLED=false`, `N8N_PYTHON_ENABLED=false`
   and the `NODES_EXCLUDE` list (executeCommand, executeCommandTool, ssh, ftp, emailSend*, localFileTrigger)
   stay as they are today — measured present on 2026-10-08.
5. Both key names exist in Bitwarden SM and appear (hash only) in the rendered
   `/run/user/1000/tradeai/env.manifest.json` before any unit that reads them is enabled.

## Threat model (unchanged)

The caller is an untrusted process that can reach the relay (from the container) or 127.0.0.1 (on the host).
Loopback is not an identity. Headers `X-Forwarded-For`, `X-Real-Ip`, and `Forwarded` are ignored. A stolen
bearer must not place an order, mint a grant, satisfy 2FA, promote a release, bid, send, or open a DOF SQL
path — which holds only because the allowlist cannot contain such a command (tested against
`FORBIDDEN_ROUTE_TOKENS` and the `data_source_authority.json` writers) and because the gateway never spawns.
Logs, receipts and n8n execution records must not contain the HMAC seed, the bearer, a provider key, a
broker credential, a database URL, or a TOTP secret.

## Key handling

The HMAC seeds live in Bitwarden SM. The relay and the dispatcher read them from the rendered environment at
start; neither is an n8n credential. Rotation keeps the previous key on `*_PREVIOUS` only for the overlap
window. A claim lives at most 300 seconds with 5 seconds of clock skew. The nonce is consumed only after
the MAC matches. Scope is per caller: `coordination_read` for `tradeai-dispatch`, `coordination_run` for
`n8n-relay`. Project is `trade-ai` or `nyc-dof-auction` and must match the event. The lane must be on the
allowlist for its scope. The method and path allowlist is `GET /healthz` and `POST /v1/coordination`; the
route allowlist is `coordination/event`, `coordination/status`, `coordination/run`. The relay accepts only
`POST /run` and `GET /status`, caps the body at 1 KiB, and refuses anything else by name.

## Consequences

- n8n becomes the scheduler-of-record for allowlisted lanes without holding any authority: a bearer can
  only ask; the ledger `runs` row and the host-side executor decide, and the `RunReceipt@v1` is the evidence.
- One more secret to rotate weekly, two more SM keys, one more `*_PREVIOUS` overlap, and a rotation daemon
  that must finally be scheduled. The bearer's blast radius on theft is "an allowlisted lane runs early, under
  its own lock, and leaves a receipt saying so".
- The n8n database may hold the encrypted credential row; with `SAVE_ON_SUCCESS=none` it holds no successful
  execution input. Error executions are kept 168 h and may contain the request body (lane id, mode,
  idempotency key) — never the bearer, which lives in the credential table, not the node parameters.
- The lab's `docs/AGENTS.md` sentence "No stored credentials" becomes false by one; the lab doc is the
  operator's and is updated by the operator when the credential is created.
- `durable=false` on the gateway receipt and "no claim of exactly-once delivery outside the sqlite file"
  remain true; the ledger `runs` table uses the idempotency key as its primary key so a retried trigger
  cannot become a second run.

## Rejected

- **A seed or an opaque reference carried in a workflow (the 2026-10-07 bootstrap).** n8n stores
  execution input; a reference in a node parameter is a bearer in the n8n database with every execution.
  The accepted design puts the only secret in n8n's encrypted credential table, where it is not copied per
  execution, and makes non-retention of successful executions a precondition rather than a hope.
- **Zero credentials with a host-side dispatcher polling n8n.** Rejected by the operator's rapid-deployment
  directive: 71 lanes need n8n to initiate on its own schedule; a poller makes cron the scheduler again.
- **The gateway HMAC key as the n8n credential (10-07 "decision 1" shape).** Rejected: the HMAC key signs
  claims for every caller sharing it; a bearer valid only at the relay is narrower, and the key never leaves
  the host.
- **A provider, database or messaging credential in n8n for "broader routing".** Rejected: routing breadth
  is delivered by server-side templates and named routing policies (AGENTS.md §23.4), not by keys.

## Tests that exist

Unknown method, encoded path, proxy header without a signature, oversized body, invalid UTF-8, old and new
key overlap, crash before commit, two connections racing one nonce, and a reference that cannot change lane.
All of those are local to the gateway. The relay, the `coordination/run` operation and the executor get
their own tests in workstream B's PR (bearer, body cap, forbidden path; scope, allowlist, idempotent replay,
enum-covered refusals; fake runner, lock skip, timeout, receipt). None of them has run inside n8n yet.

## What remains false

`durable=false` on the gateway receipt. No claim of exactly-once delivery outside the sqlite file. The relay
is not installed and the bearer does not exist until the preconditions above are measured true. No DOF
role exists (proposal: `docs/implementation/n8n-parallel/proposals/dof-reader-role-20261008.sql.md`).

## Addendum — AGENTS.md 3.0.0 (ACTIVE 2026-10-09, `APPROVE_AGENTS_POLICY_3_0_0 1547 a0984546181d316f92931c7b87218b55b3b836d9`)

- **A second credential, the bridge token, is allowed only after AGENTS.md §23.10's preconditions are
  each measured true with a receipt** (P2–P9, P11–P13, P15–P22). It authenticates AI requests at the
  governed bridge's Agent endpoint and nothing else; it is rendered from Bitwarden SM, rotated weekly with a
  `_PREVIOUS` overlap, and caller identity is bound to it server-side. The relay bearer stays the only
  credential for run requests. Any third credential remains a defect and a §17 decision.
- **Owner MFA is waived (operator decision 2026-10-09).** The n8n editor listens on 127.0.0.1 only and is
  reached through an SSH tunnel over Tailscale. The waiver replaces the "owner MFA on" precondition above for
  both credentials. **It does not extend to the database role:** `DB_POSTGRESDB_USER=n8n_app` with
  `rolsuper=f` remains a precondition for the bridge token (§23.10 P13).
- Evidence: `docs/implementation/n8n-parallel/audits/guardrail-audit-c-policy-n8n-20261009.md` (G1, G7,
  G11, G12) and the proposal `docs/implementation/n8n-parallel/proposals/agents-3-0-0-governed-n8n-agents-20261009.md`.

---

## Superseded — the PROPOSED text of 2026-10-07 (kept verbatim; no longer the decision)

Status: proposed. Not installed. The pilot stays BLOCKED_POLICY until an operator accepts a bootstrap that never places a seed in n8n.

### Threat model

The caller is an untrusted process that can reach 127.0.0.1. Loopback is not an identity. Headers `X-Forwarded-For`, `X-Real-Ip`, and `Forwarded` are ignored. A stolen bearer must not place an order, mint a grant, satisfy 2FA, promote a release, bid, or open a DOF SQL path. Logs and execution records must not contain the HMAC seed, a provider key, a broker credential, a database URL, or a TOTP secret.

### Key handling

The seed lives in Bitwarden. The source-side process reads it from the environment at start. It is not an n8n credential. Rotation keeps the previous key on `TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS` only for the overlap window. A claim lives at most 300 seconds with 5 seconds of clock skew. The nonce is consumed only after the MAC matches. Scope is `coordination_read`. Project is `trade-ai` or `nyc-dof-auction` and must match the event. The lane must be on the allowlist. The method and path allowlist is `GET /healthz` and `POST /v1/coordination`. The event carries the source SHA the server expects.

### Bootstrap that stays inside the policy

The source-side dispatcher signs the claim and does not hand the seed to n8n. If n8n must correlate an event, the dispatcher issues an opaque reference. The ledger stores only the hash. The reference is bound to one project, one lane, one idempotency key, and an expiry. Redeeming it cannot mint a broader claim and cannot call a forbidden route; those routes are refused before the claim is treated as authority.

This is still not an install. n8n stores execution input. Putting the reference into a workflow would copy a bearer into that store. Until a reviewed design shows the execution record does not retain it, no workflow is created and no secret-bearing node is added.

### Tests that exist

Unknown method, encoded path, proxy header without a signature, oversized body, invalid UTF-8, old and new key overlap, crash before commit, two connections racing one nonce, and a reference that cannot change lane. All of those are local. None of them ran inside n8n.

### What remains false

`durable=false` on the gateway receipt. No claim of exactly-once delivery outside the sqlite file. No n8n credential. No DOF role.

## Addendum — AGENTS.md 4.0.0 (ACTIVE 2026-10-09, `APPROVE_AGENTS_POLICY_4_0_0`)

- No credential is added or changed. The one live-lane exception (`trade-ai-scalp-live`, §23.3) runs on
  the host under the existing relay bearer; the Finviz key stays behind the data broker on the host and
  never enters n8n.
