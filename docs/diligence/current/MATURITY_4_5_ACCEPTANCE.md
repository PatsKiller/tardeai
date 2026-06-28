# Maturity 4.5 Acceptance Checklist

_Generated: 2026-06-28T01:27:40.319416+00:00_
_Source: `python3 scripts/export_diligence_evidence.py` + `scripts/compute_maturity_score.py`_
**Status: **4.5 BLOCKED****

## 1. Current maturity score

- Final maturity (after caps): **3.75 / 5** (does not meet 4.5)
- Raw weighted: 4.6 / 5
- Caps applied:
- release readiness FAIL → cap 3.75

See `MATURITY_SCORE_LATEST.md` for the full line-by-line breakdown.

## 2. What is allowed

- Operator-approved Schwab/SnapTrade submit path, one order at a time, behind deterministic gates.
- Read-only inspection of readiness, reconciliation, kill switches, and audit ledger.
- LLM advisory commentary and proposal drafting (no execution authority).

## 3. What is blocked

- **Autonomous live submit remains disabled.**
- Any broker write outside the approved transport boundary.
- Marking an order live before broker acknowledgement.
- Replace-order routes (fenced everywhere but the transport, which itself fences them).

## 4. What requires operator approval

- Every live broker submit requires the existing per-order operator confirmation / two-factor
  step. **This path is immutable and out of scope for automation.**
- Enabling options execution requires both a commit flag and an operator DB arm.

## 5. What is advisory only

- **LLMs are advisory only.** They may never set policy, arm execution, approve an order, alter a
  kill switch, or unlock live eligibility.

## 6. Required release evidence

- Execution state: `OK` — autonomous live submit allowed = `False`
- Release readiness: `WARN_NON_LIVE_ADJACENT` (live-adjacent dirty files: none)
- **Release readiness must be PASS or explicitly justified WARN with no live-adjacent dirty files.**

## 7. Required test evidence

- Schwab write policy validator: **PASS**
- No-broker-write-bypass test: **PASS**
- Evidence-bound approval (like-to-like hashes), execution readiness modes, intraday window
  fail-closed, order lifecycle + reconciliation taxonomy, options hard-risk matrix, audit ledger,
  AI critique — see `TEST_EVIDENCE.md`.
- Audit ledger coverage: **WARN**

## 8. Remaining non-blocking warnings

- Regenerated diligence/runtime artifacts may show as dirty (WARN_NON_LIVE_ADJACENT). These are
  generated evidence, not live-adjacent source, and do not cap maturity.

## 9. Sign-off checklist

- [x] Autonomous live submit disabled
- [x] Per-order operator 2FA required (unchanged)
- [x] Release readiness PASS or justified WARN_NON_LIVE_ADJACENT
- [x] No live-adjacent dirty files
- [x] Schwab write policy validator green
- [x] No-broker-write-bypass test green
- [x] Audit ledger chain verified
- [ ] Maturity score ≥ 4.5 earned from evidence

**Broker truth is authoritative after submit. No order is treated as live before broker acknowledgement.**
