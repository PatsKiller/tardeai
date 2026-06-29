# SEC / Form 4 — Momentum Catalyst Context

_SEC/Form 4 as a **supporting evidence** source for momentum_scalp. Implemented in
`scripts/run_sec_form4_momentum_context.py` (scheduled wrapper) + `scripts/sec_form4_source_maturity.py`
(context classifier + maturity scorer); covered by `tests/test_sec_form4_momentum_context.py`._

## What it is — and is NOT

SEC/Form 4 is **not** a real-time scalp trigger. It is a supporting catalyst/insider-context source: a
recent **open-market insider BUY** (transaction code `P`) contributes the Social Scout `catalyst_evidence`
pillar **only when recent + relevant**. It can **never**:

* create GO by itself,
* bypass route policy / risk / liquidity / TTL / validation gates,
* satisfy `social_velocity` (that needs social evidence),
* trigger a trade or any broker write.

A SEC-only candidate (no verified news catalyst) stays social-only → **never GO**, always not_tradeable.

## Source (reused)

`sec_data_ingest.py` already ingests Form 4 from the free SEC EDGAR API into the `sec_form4` table
(`symbol, filer_relation, transaction_type, shares, price, total_value, filing_date, sec_url,
quality_score`). This hardening adds the **momentum-context** layer + scheduling + maturity + health.

## Context wrapper

```bash
python3 scripts/run_sec_form4_momentum_context.py --dry-run   # report only (default)
python3 scripts/run_sec_form4_momentum_context.py --apply     # refresh Form 4 + write context artifact
```

For the recent micro-float momentum symbols (from `trade_ai_scans`), it refreshes Form 4 (reusing
`sec_data_ingest.ingest_form4`) and derives per-symbol context: `direction` (insider_buy/sell/none),
`recent_insider_buy`, `catalyst_relevant`, `confidence` (≤0.6 — never trigger-grade), `latest_filing_date`,
`evidence_url` (SEC URL), and a `source_trace_id` (`secf4-<date>-<symbol>` lineage; **no raw blobs**).
Output persists to `data/runtime/sec_form4_momentum_context_latest.json`. Read-only / source-ingestion only.

## Schedule (cron)

```cron
45 5 * * 1-5  run_sec_form4_momentum_context.py --apply     # pre-market
15 9 * * 1-5  run_sec_form4_momentum_context.py --apply     # near the open
```

Idempotent, flock-locked, parseable JSON logs (`logs/sec_form4_momentum_context.log`).

## Catalyst-evidence relevance rule

`sec_form4_source_maturity.classify_insider_context` marks a row catalyst-relevant only when it is an
open-market **buy** within `CATALYST_RELEVANT_DAYS` (7). Stale buys and sell-only filings do **not**
qualify. The pillar evaluator (`social_scout_pillars._pillar_catalyst_evidence`) accepts a flagged recent
insider buy (`sec_form4_insider_buy=True`, `sec_form4_age_days ≤ 7`) as `catalyst_evidence`.

## Maturity: 3.0 → 4.5-ready

`sec_form4_source_maturity.score_source` requires **all** of: configured · scheduled · tested · monitored ·
traceable · integrated · safe-fail → **4.5**. **5.0** requires live in-window observation of fresh
coverage + downstream use — not claimed before observation. Current: **4.5-ready** (latest filing
freshness + live cadence observation pending).

## Health

`health_agent.collect_momentum_scalp_multi_source_health` flags `sec_form4_context_stale` (schedule-aware,
05:45–09:15 ET window — no off-hours floods) and **auto-remediates** by re-running the context wrapper
(on the auto-remediation safety allowlist — source/read-only, no broker writes).

## Safety

Read-only / source-ingestion only. No live broker writes. Operator confirmation / 2FA untouched. SEC/Form 4
does not advance strategy/validation maturity — the empirical validation sample (2/30) remains the blocker.
