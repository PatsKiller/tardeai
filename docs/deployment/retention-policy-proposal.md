# Communications Gateway — Retention Policy (PROPOSED)

**Status:** DRAFT — PROPOSAL, operator sign-off required before any retention class is
authoritative or any scheduler is installed.

**as_of:** 2026-09-05T11:40:00Z
**Measured at:** not measured

---

## Purpose

This document proposes the **retention class table** for the Communications Gateway
Librarian (`scripts/lib/comms/librarian.py`). It is a proposal, not a policy in force.
**Every row below is `PROPOSED` and requires operator sign-off.** Until that sign-off is
recorded, the only retention behaviour that exists is the in-code heuristic
`_CLASS_HEURISTICS` `[CODE] scripts/lib/comms/librarian.py`, which is not itself an
operator-approved retention policy.

Two rules are stated up front because they are load-bearing for every row:

1. **Expiry is not deletion.** An `expires_at` horizon makes a record *eligible* for a
   lifecycle action; it does not by itself delete anything. The only destructive path is
   `execute_expiry_pass(dry_run=False)`, which writes a tombstone and a purge receipt —
   and which is **not scheduled** in this work. A row can sit expired indefinitely until an
   operator-approved scheduler runs the pass.

2. **Knowledge status is separate from retention.** Whether a communication is promoted to
   `ACCEPTED` knowledge (`propose_knowledge_candidate` / `decide_knowledge_candidate`) is an
   independent decision with its own provenance and review requirements. Retention policy
   governs the *communication* record; it never auto-promotes knowledge and never deletes
   knowledge on the strength of a retention TTL. "Accepted knowledge" appears in this table
   only to make explicit that its lifetime is not governed by a content TTL.

---

## Proposed retention class table

Each row is `PROPOSED`. The `Sign-off` column is `Operator required` on every row — there is
no row here that an agent may self-authorise.

| # | Retention class | Holds | Proposed action | Proposed content TTL | Proposed metadata TTL | Sign-off |
|---|---|---|---|---|---|---|
| 1 | `raw_payload` | Unredacted raw message payload / body | `DELETE_CONTENT_KEEP_TOMBSTONE` | 30 d | 90 d | **Operator required — PROPOSED** |
| 2 | `sanitized_body` | Redacted, safe-for-display body text | `DELETE_CONTENT_KEEP_TOMBSTONE` | 30 d | 90 d | **Operator required — PROPOSED** |
| 3 | `provider_coordinates` | Provider chat_id / message_id / delivery handles | `REDACT` | 30 d | 90 d | **Operator required — PROPOSED** |
| 4 | `approvals_tokens` | Operator approvals, auth/token audit trail | `KEEP` | 365 d | 3 y | **Operator required — PROPOSED** |
| 5 | `market_candidates` | Screened candidates, watchlist discovery rows | `COMPACT` | 365 d | 2 y | **Operator required — PROPOSED** |
| 6 | `protection_incidents` | Protection / risk incidents and their evidence | `KEEP` | 365 d | 3 y | **Operator required — PROPOSED** |
| 7 | `routine_digest` | Daily briefs, routine operational chatter | `DELETE_CONTENT_KEEP_TOMBSTONE` | 7 d | 30 d | **Operator required — PROPOSED** |
| 8 | `research_advisory` | Research theses, advisory narratives | `COMPACT` | 365 d | 2 y | **Operator required — PROPOSED** |
| 9 | `accepted_knowledge` | Knowledge promoted to `ACCEPTED` | `KEEP` | *no content TTL* | *no metadata TTL* | **Operator required — PROPOSED** |
| 10 | `debug` | Debug / diagnostic emissions | `DELETE_ALL_ALLOWED` | 7 d | 30 d | **Operator required — PROPOSED** |
| 11 | `legal_compliance` | Legal hold, compliance, tax-relevant records | `HOLD` | **separate policy — no deadline invented here** | **separate policy — no deadline invented here** | **Operator required — PROPOSED** |

### Per-row notes

- **Row 11 (`legal_compliance` / tax):** no deadline is invented here. Legal hold and
  tax-relevant retention are governed by a **separate policy** that has not been authored in
  this work, per `AGENTS.md` §7 (never invent a reason) and §17 (operator-only). The
  Librarian's `HOLD` action suspends retention and blocks all deletes regardless of TTL; the
  *duration* of that hold is an operator/legal decision, not an engineering default.

- **Row 9 (`accepted_knowledge`):** accepted knowledge is a *knowledge* record, not a
  communication. Its lifetime is not a retention TTL. It is listed here only to state that
  retention never deletes it and never conflates knowledge promotion with retention.

- **`COMPACT` and `REDACT` are destructive-content actions, not deletes.** They rewrite the
  record (drop the narrative / redact fields) while preserving the tombstone and the
  purge receipt. A "purge receipt" is recorded for these actions exactly as it is for
  `DELETE_*`.

---

## What the purge receipt records

Every destructive lifecycle action — `KEEP`, `COMPACT`, `REDACT`,
`DELETE_CONTENT_KEEP_TOMBSTONE`, `DELETE_ALL_ALLOWED`, `HOLD` — writes a
`PurgeReceipt@v1` receipt `[CODE] scripts/lib/comms/librarian.py` carrying:

- `decision_id`, `action`, `retention_class`
- affected `event_ids` / `artifact_ids`
- `content_hashes` of the affected content
- `tombstone` flag (true only when a tombstone was actually written)
- `decided_by`, `policy_version`, `decided_at`
- `dry_run` and `note`

The dry-run expiry path (`execute_expiry_pass(dry_run=True)`) emits a **"would-delete"**
receipt (with `tombstone=false`, `dry_run=true`) and **deletes nothing**. This makes intent
auditable even when nothing was destroyed.

---

## Operator-gated items (propose and stop)

The following are **operator-only** and are intentionally *not* done in this work
(`AGENTS.md` §17):

1. **Retention class table approval.** Every row above requires explicit operator sign-off
   before any TTL or action becomes authoritative. Until then, `_CLASS_HEURISTICS` remains a
   code heuristic, not policy.

2. **Retention scheduling.** No cron or systemd entry for `execute_expiry_pass` has been
   created. Installing any scheduler is operator-only and must be proposed separately, with a
   lane-registry row and an `output_signal` before it is installed (`AGENTS.md` §9.3).

3. **DB migration.** Durable DB persistence of purge receipts requires a new
   `communication_purge_receipts` table. No migration is applied here; the code falls back to
   the in-memory store when the table is absent, and the migration itself is operator-owned.

**Nothing in this document authorises deletion.** A proposal marked `PROPOSED` is not an
approval, and "expiry is not deletion" (§ Purpose) applies to every row above.
