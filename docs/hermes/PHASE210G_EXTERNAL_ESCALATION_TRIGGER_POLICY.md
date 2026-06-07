# Phase 210G — External Escalation Trigger Policy (2026-06-07)

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
