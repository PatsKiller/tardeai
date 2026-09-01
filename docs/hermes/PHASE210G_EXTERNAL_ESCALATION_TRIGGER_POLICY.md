# Phase 210G — External Escalation Trigger Policy (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T13:38:00-04:00
Measured at: efcc51365 / not measured

## Triggers
TradeAI vs Hermes score delta > 8; Hermes flags stop/protection defect; weak evidence + high portfolio
impact; repeated operator/Hermes disagreement; new strategy underperforming; high-$ position with profit-
giveback risk; defense/income/retirement/tax-sensitive topic; momentum catalyst with high social/news
volatility; source-credibility conflict; high-LLM local failure/timeout; model uncertainty above threshold.

## Priority
- **P0** — must escalate before recommendation (stop/protection defect; high-$ giveback; tax/SSDI/IRMAA-critical).
- **P1** — escalate overnight (sharp disagreement; weak-evidence/high-impact).
- **P2** — queue for weekly research (strategy underperformance; source conflicts).
- **P3** — no external escalation (routine, strong-evidence, low-impact).

## Output (structured)
recommendation · evidence list · dissenting view · confidence · risk flags · learning candidate · operator action.

## Routing by topic
- Claude: retirement/tax/SSDI/IRMAA, policy/legal, final high-stakes challenge.
- ChatGPT: code/design review, synthesis, alternative reasoning.
- Grok: market/social/news narrative, sentiment/catalyst, momentum.
- Consensus panel: sharp internal disagreement + high importance.

> Governance: see EXTERNAL_LLM_USAGE_POLICY_20260607.md (limited criteria, per-call operator approval, data-class restrictions, prohibited uses).

---
## Journal/Backtest-specific escalation triggers (2026-06-07)
- Backtest weak strategy (PF<1 / low WR, sufficient n) on a live/proposed strategy → ChatGPT (design) / Claude (retire).
- Recurring journal mistake pattern across N trades, or tax/retirement-sensitive lesson → Claude / ChatGPT.
- Edge-comparison large profit-left-on-table on a high-$ position → Claude (P0 giveback).
- Entry-grade decay on an active strategy → ChatGPT / Grok (narrative).
See HERMES_JOURNAL_BACKTEST_INTERNAL_EXTERNAL_MAPPING_20260607.md. Operator-gated; no auto-escalation.
