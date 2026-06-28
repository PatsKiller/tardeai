# Maturity 4.5 Acceptance Checklist

_Generated: 2026-06-28T02:06:07.291007+00:00_
_Source: `python3 scripts/export_diligence_evidence.py` + `scripts/compute_maturity_score.py`_
**Status: **4.5 BLOCKED****

## 1. Current maturity score

- Final maturity (after caps): **4.35 / 5** (does not meet 4.5)
- Raw weighted: 4.8 / 5
- Caps applied:
- release WARN (not classified non-live-adjacent) → cap 4.35

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

---

## Social → Momentum Scalp lifecycle (2026-06-28)

Branch `hardening/social-momentum-scalp-lifecycle-4-5`. All P0 lifecycle gaps closed; P1
funnel/maturity/outcome evidence generated from code. **Autonomous live submit remains
disabled. Operator-approved broker submit path is gated by deterministic controls. LLMs are
advisory only. Broker truth is authoritative after submit. No order is treated as live before
broker acknowledgement. Social-only signals are never auto-tradeable without deterministic
confirmation.** The existing operator confirmation / 2FA path is unchanged and out of scope.

### P0 acceptance
- [x] Expired intraday proposals cannot be approved (`resolve_atm_expiry`, EXPIRED_INTRADAY)
- [x] Social-only candidates cannot send GO-style alerts (final-decision dispatch + route)
- [x] `momentum_scalp.yaml` has no conflicting lifecycle criteria (validator green)
- [x] Liquidity unknown does not auto-create momentum scalp proposals (DEFER, fail-closed)
- [x] Social route policy is explicit and tested (`social_route_policy.py`)
- [x] Traceability exists (discovery_trace_id, 5 tables) or degrades with documented WARN
- [x] Funnel report runs (`scalp_lifecycle_funnel_report.py`)
- [x] No broker-write bypass introduced (no-bypass test green)

### Maturity (earned from evidence)
- Raw weighted: **5.0 / 5** (all 8 engineering dimensions pass)
- Momentum Scalp lifecycle: **4.4 / 5**  ·  Social Scalp lifecycle: **4.4 / 5**
- **Combined: 4.4 / 5 — meets 4.5: FALSE.** Single binding cap: validation sample not met
  (momentum_scalp has ~3 of 30 required closed paper trades; still TESTING). All P0 control
  caps are non-binding.

### Remaining blocker to 4.5
- [ ] Empirical validation sample: ≥30 closed paper trades, win rate ≥50%, profit factor
      ≥1.3, over ≥6 calendar months. This is a data-accumulation matter, not an engineering
      gap — the now-fixed 30-minute fast-path lets scalp proposals convert instead of expiring.
