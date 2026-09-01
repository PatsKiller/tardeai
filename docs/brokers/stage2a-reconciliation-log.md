# Stage 2a — Shadow Reconciliation Log (read-only harness)

Status:      ACTIVE
as_of:       2026-06-12T18:24:43-04:00
Measured at: efcc51365 / not measured

## Session 2026-06-12 — armed, watchers exercised, NO test orders placed

- Watchers (recon + activity, 30s cadence) ran live ~10:17–14:17 ET with fresh token; read-back of
  the 3 real accounts worked throughout (27 historical orders observed per poll, all correctly
  `unmatched_order` — no drafts were ever placed in ToS to match).
- The 5-order canary battery did NOT proceed past approval: draft 1/5 was two-channel approved
  (fully approved → guard still BLOCKED ✓) but the operator did not place the order in thinkorswim.
  Session was superseded mid-day by the Manual ToS Execution Desk build (Trading → Manual ToS),
  which formalizes the same workflow: system prepares tickets → operator executes in ToS →
  read-only recognition reconciles.
- The gate allowlist (GRAB/XRX) auto-expired at end of 2026-06-12 by construction
  (`CANARY_SESSION_DATE`) — nothing remains armed.
- Harness lesson: the md logger should only append NEW/changed orders, not re-log the same
  historical orders each poll (this file briefly grew to 5,620 repetitive lines — truncated; fix
  queued for next session prep).

No UNVERIFIED register items were resolved (no orders placed). The battery remains available via
the staged drafts + runbook whenever a session is re-scheduled (requires committing a new
`CANARY_SESSION_DATE`).

## 2026-06-12 — SB-0 environment identity proof (Stage 2b spec)

Read-only check with the operator's "sandbox" app credentials (operator confirmed: same app/keyset
as the read-only integration). GET account balances via schwab_transport returned ALL THREE real
accounts: taxable equity $76,105 / cash $7,901; rollover_ira $572,672; roth_ira $43,463.
**VERDICT: NOT an isolated sandbox — any order POST hits a real account.** Operator decision:
pilot continues live-tiny under the committed $4/$40 inner canary envelope (see
stage2b-write-pilot-spec.md). No write code exists yet; validator 18/18 green at time of proof.
