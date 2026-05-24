# POST-AUDIT-OPS-1 — Remaining Backend Audit Defects

**Status:** FIXED — 5/5 workstreams closed

The earlier Google Drive diagnostic reports were superseded by these fixes. A-5 final review remains blocked until after 2026-05-22. Live trading remains disabled. No trades/orders were created by these remediation phases.

## Scorecard

| Workstream | Commit | Original Root Cause | Final Result | Safety |
|---|---|---|---|---|
| REGIME-CRON-1 | `03baf9d` | save_*() defaulted dry_run=True; callers never passed False | Snapshot fresh; run log recording | No strategy activation, no rotation auto-apply, no trades/orders |
| AGENT-WORKER-1 | `00a6967` | fused_signals.overall_signal schema mismatch; actual column direction | 125 stuck jobs recovered; queue processing restored | No fake completions, no trades/orders |
| LLM-FIX-1 | `50c0846` | Phantom table reference; real LLM output existed but was not extracted | 109 actionable outcomes populated | No fake LLM verdicts |
| COUNT-TRUTH-1 | `d8ef77f` | Scope drift / ambiguous count labels | Scope-specific labels added to PaperGovernance, PaperJournal, CIODashboard | No data manipulation |
| ATTR-1 | `442c46b` | yfinance MultiIndex broke benchmark price fetch | Alpha +1.02%; all metrics populated from real 1604-day price history | No fake attribution data |

## Corrected Findings

- **Regime**: Root cause was a Python parameter bug, not a missing cron or wrong write target. `save_snapshot(conn, snapshot)` defaulted to `dry_run=True` — the classifier ran daily but never wrote. Fixed by passing `dry_run=False`. Transaction recovery and run-log recording added.

- **Agent**: "Worker not running" was a misdiagnosis. The agent worker is cron-triggered batch processing (not a daemon). The actual issue was `fused_signals.overall_signal` column didn't exist (actual: `direction`), which poisoned DB transactions and left 125 jobs stuck in "processing" forever. Fixed with column correction + transaction recovery.

- **Overnight LLM**: "Template fallback / table not found" was wrong. The `overnight_recovery_verdicts` table never existed — it was a phantom name in the diagnostic. The real pipeline uses `deep_overnight_llm_results` (1116 real LLM verdicts from gemma3-overnight). The gap was that `overnight_actionable_outcomes` had no populator. Fixed by creating `extract_overnight_actionable_outcomes.py` (109 outcomes extracted).

- **Counts**: Different pages used different WHERE filters — expected behavior, not a bug. Fixed by adding scope-specific labels (Paper Open/Closed, All-Time Decisions, Pending Review, etc.).

- **Attribution**: "No benchmark tables" was misleading. Attribution uses JSON files (`performance_attribution.json`), not DB tables. The root cause was yfinance >= 0.2.x returning MultiIndex columns, silently breaking the benchmark price extraction. Fixed by flattening with `iloc[:, 0]`. SPY/ITA/AGG now cached (1604 days), alpha = +1.02%.

## Reports

Original diagnostic reports (pre-fix) are preserved with supersession notes.
Current truth report: `doc_recon1_truth_report.md`
Closure memo: `post_audit_ops1_5_of_5_closure_memo.md`
