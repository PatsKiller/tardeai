# Approval / HITL authority contract — specification

```
Status:      SPECIFIED (maturity Level 1 of 5). Nothing here is built, served or active. Audit DD13 (P1, Known).
as_of:       2026-10-15
Audit:       independent due diligence 2026-10-15 (pinned e355be188) §9 "Complete HITL before adding the route"
Policy:      AGENTS.md §23.23 "Approvals" + "Broker" (n8n can request and remind, never confirm), §17, §22
Owner:       operator authority (schema approval, emergency revocation) + platform (implementation) — ROLES to confirm
Gate:        POST /approval/request MUST NOT be added to the relay, and no n8n Wait/approval node may be activated,
             until every test in §6 exists and passes and the operator accepts this contract
```

## 1. Principle

An n8n approval is a **request**. Authority is a protected host record created by an **independently verified
decision** and **consumed atomically at the effect**. A native n8n Wait-node resume URL, a webhook callback, an
`approved` branch, or a Telegram button press relayed by n8n is never authority by itself.

Two classes, never mixed (audit §9 last paragraph):

* **Operational** (e.g. "run this backfill", "accept this remediation"): host approval service, operator identity
  verified by the host (Telegram session bound to the operator id, or CC serve-proxy tailnet identity).
* **Money** (anything that could reach A1 in the threat model): **out of scope for the fabric**. Only the per-order
  operator hardware-key/TOTP assertion over the intent hash on the execution path (§22, B5). A contract version
  change can never widen an operational approval into a money one.

## 2. Records

`ApprovalRequest@v1` (host-written on `POST /approval/request`; n8n supplies only the first four fields):

| Field | Meaning |
|---|---|
| `process_id`, `step_id` | registered process step that needs the decision (closed set from `config/n8n_fabric_processes.json`) |
| `intent` | the exact action payload, canonical JSON, ≤ 4 KiB |
| `n8n_execution_id` | correlation only; never trusted for authority |
| `approval_id` | host-minted, 128-bit random |
| `intent_hash` | SHA-256 over canonical `intent` |
| `class` | `operational` (only value accepted by this contract) |
| `audience` | the host service that will consume the decision (e.g. `executor:<lane_id>`) |
| `allowed_actors` | operator principal ids permitted to decide (from host config, not from n8n) |
| `nonce` | single-use, 128-bit |
| `expires_at` | ≤ 24 h after creation; process-specific maximum in host config |
| `policy_epoch` | the effective policy/revocation epoch at creation |
| `state` | `PENDING` → `APPROVED` / `REJECTED` / `EXPIRED` / `REVOKED` → `CONSUMED` |

`ApprovalDecision@v1` (host-written by the decision surface, never by n8n): `approval_id`, `actor` (verified
principal), `decision`, `decided_at`, `intent_hash` as displayed to the actor, `factor` (`telegram_session` |
`cc_tailnet_identity`), `signature` (HMAC by a host-only decision key that no worker, lane or n8n process can read).

Storage: a dedicated SQLite file (or table set) written only by the approval service principal. Until the uid split
(threat model RR1) exists, this record is **not** protected from a uid-`johnclaw` process — which is why the route
stays closed (§0 Gate).

## 3. Flow

1. n8n `POST /approval/request` (relay → gateway scope `approval_request`, a new scope that grants nothing else) with
   `process_id`, `step_id`, `intent`, `n8n_execution_id`. Host validates, mints the record, returns `approval_ref`
   (= `approval_id`) and `expires_at`. The host — not n8n — notifies the operator through the comms gateway, showing
   `intent` rendered from the record.
2. n8n waits (Wait node timeline: remind, escalate, expire). Reminders are intents; they carry `approval_ref` only.
3. The operator decides on a host surface; the host verifies the actor and factor and writes `ApprovalDecision@v1`.
4. n8n resumes on a **signed** host event (`Event@v1`, HMAC by the gateway, audience = the workflow, bound to
   `approval_ref` and `n8n_execution_id`) or by polling `GET /approval/<ref>`; either only *tells* n8n to proceed.
5. n8n requests the effect (`POST /run` with `approval_ref`). The **executor at the effect** — not the gateway at
   admission alone — re-validates and consumes (§4).

## 4. Consumption at the effect (atomic)

In one transaction immediately before spawn: the decision exists, is `APPROVED`, signature verifies, `actor` ∈
`allowed_actors`, `audience` matches this consumer, `intent_hash` equals the hash of the run's actual argv/payload,
`expires_at` is in the future, `policy_epoch` equals the current epoch (no revocation since), `nonce` unused; then set
`CONSUMED` with `consumed_by` = run id. Any failure → `RUN_REFUSED approval:<reason>`, nothing runs. Two concurrent
consumers: exactly one wins (compare-and-set on `state`).

## 5. Ownership

| Concern | Owner (ROLE to confirm) |
|---|---|
| Contract schema approval and version bumps | operator authority |
| Emergency revocation (bump `policy_epoch`, revoke one or all `PENDING`/`APPROVED`) | operator; host CLI, works with n8n down |
| Rollout (route activation, per-process enablement) | platform, under a `config-write` grant naming the process |
| Backward compatibility | closed reader: unknown fields and unknown `state` refuse; major version negotiated, never implied |

## 6. Acceptance tests (all must fail closed **before** any effect)

| # | Case | Expected |
|---|---|---|
| H1 | forged callback / unsigned resume event | ignored; no consume |
| H2 | wrong actor (not in `allowed_actors`) | decision rejected at write |
| H3 | wrong audience (another lane consumes) | `approval:audience` refusal |
| H4 | altered payload after approval | `approval:intent_hash` refusal |
| H5 | expired approval | `approval:expired` |
| H6 | replay of a consumed approval | `approval:consumed` |
| H7 | two simultaneous consumers | exactly one `CONSUMED`; the other refused |
| H8 | revocation during the wait (epoch bump) | `approval:revoked` |
| H9 | restore of a stale approval store (backup older than the consume) | consumed/revoked state not resurrected; refuse on epoch mismatch |
| H10 | n8n `approved` branch with no host decision | `approval:missing` |
| H11 | money-class intent submitted as operational | refused at request (`class_not_permitted`) |
| H12 | approval service down | request refused; nothing proceeds (fail closed) |

## 7. Maturity

Level 1 (specified). Level 2 requires the record store, the request route behind a disabled flag and H1–H12 passing
offline. Level 3 requires one operational process using it end to end with dated receipts.
