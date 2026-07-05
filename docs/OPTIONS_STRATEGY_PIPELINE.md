# Options Strategy Pipeline (paper-only lane)

**Status:** Stage B (2026-07-05) · first strategy: `deep_itm_call` (Deep ITM Call, stock replacement)
**Lineage:** Hermes discovery candidate **#339** (`hermes_discovery_candidates`, status `APPROVED_RESEARCH_ONLY`)
**Law of the lane:** model → paper → validate → operator decision. No live path exists in code; a met
validation gate is a report, never a switch.

## Path: model → paper → validate → 2FA desk

```
Hermes discovery candidate (APPROVED_RESEARCH_ONLY)
  └─ config/strategies/<strategy>.yaml          strategy config (paper_only, manual_review_only,
     │                                          execution.live_allowed: false, validation_gate)
  └─ scripts/lib/options_pipeline/<gen>.py      generator: read-only chain analysis → config gates
     │                                          → scored paper proposals (flags disclosed, never hidden)
  └─ scripts/options_strategy_scanner.py        winner scanner: holdings + watchlist buy/strong_buy
     │                                          underlyings → top-N per run → desk queue
  └─ options_desk_enterprise.sync_approval_queue
     │                                          SAME options_approval_queue as covered calls/CSPs,
     │                                          manual-review lane, live_eligible=false + paper block
  └─ Options tab (/v3/trading?tab=Options)      "DEEP ITM · PAPER MODEL" cards — review/ack only
  └─ scripts/lib/options_pipeline/validation.py paper outcomes → validation gate report (advisory)
  └─ OPERATOR DECISION                          gate met ⇒ "operator decision required" — any live
                                                consideration goes through the existing options desk
                                                arming + per-order 2FA path, which this pipeline
                                                never touches
```

## The triple fail-closed locks

A deep-ITM (or any future paper-model) proposal cannot leak into live execution because three
independent layers each refuse:

1. **Generator lock** — every proposal row carries `educational_paper_model=true`,
   `requires_manual_review=true`, `paper_only=true`, `execution_mode='manual_review_only'`,
   `auto_eligible=false`, and `enterprise.live_eligible=false` with an explicit paper-model block.
   `submit_to_desk_queue()` refuses to write any row missing those flags (fail-closed, test-enforced).
2. **Desk lock** — `options_desk_enterprise.resolve_approval` refuses to approve rows whose
   `live_eligible` is false ("cannot approve — enterprise blocks remain"), and
   `check_preflight_approval` refuses live submit for the same reason. The scanner additionally
   refuses to run at all if the config loses `paper_only` / `manual_review_only` /
   `live_allowed: false` (config-integrity check), or if the strategy is `PAUSED`/`KILLED`.
3. **Surface lock** — no broker submit / order / 2FA module is imported anywhere in the pipeline
   (AST-enforced forbidden-imports tests, Stage A §7), the UI renders no approve-to-live affordance
   for paper rows (actions are review-chain / pass only; "Executed manually" is hidden), and the
   API feed drops any queue row that lost its paper flags rather than rendering it as a normal
   desk proposal.

The validation module adds a fourth, advisory-side invariant: it has **no write path** to
execution flags, strategy status, or the strategy YAML (test-enforced by source inspection).

## Earnings-before-expiry: disclosed flag, not a reject (operator decision 2026-07-05)

`selection_policy.allow_earnings_before_expiry: true` in `config/strategies/deep_itm_call.yaml`.

Rationale: a deep-ITM call held as stock replacement carries the earnings event exactly the way the
replaced shares would — rejecting on earnings would make the model dishonest about the strategy it
models. Instead the condition is **surfaced as a disclosed card flag** ("⚠ earnings before expiry",
from `meta.gate_flags: earnings_before_expiry_operator_flagged`) so the reviewing operator sees it on
every affected card. `earnings_unknown` (no earnings date resolvable) is likewise a disclosed flag.
The strict-reject machinery remains in the generator and is covered by tests — flipping the config
back to `false` restores rejection with no code change.

## IV-rank context layer (2026-07-06 — advisory only, never a gate)

Daily ATM-IV snapshots (`lib/strategy_research/iv_history.py`) accrue in `options_iv_history`
(one row per symbol per day, upsert on `(symbol, snapshot_date)`; migration
`migrations/2026_07_06_options_iv_history.sql`, additive on the pre-existing 2026-06-22 table).
Capture CLI: `scripts/options_iv_snapshot.py --run --symbols-from-universe` — same eligibility
universe as the scanner (holdings equities + buy/strong_buy watchlist); ATM IV = near-the-money
(±5% of spot) contracts in the ~30-60 DTE window, averaged, defensive on missing/NaN greeks.

Suggested capture cron (NOT installed by the script — operator installs; 15:45 ET is near-close
with live quotes; an older 16:20 no-arg cron predates this layer and remains legacy-compatible):

```
45 15 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/options_iv_snapshot.py --run --symbols-from-universe >> logs/options_iv_snapshot.log 2>&1
```

`iv_history.iv_rank(symbol)` → `{atm_iv, iv_rank, percentile, verdict}`:

- **Honesty rule:** fewer than **20** stored days → `{"available": false, "reason":
  "insufficient history", "days": N}` — a rank is NEVER fabricated from thin data.
- **Verdict bands:** rank < 30 `extrinsic_cheap` ("extrinsic cheap") · 30-70 `normal` ·
  > 70 `extrinsic_rich` ("extrinsic rich — pay-up warning").
- **Wiring:** `deep_itm_call_analysis` output carries `iv_context`; the generator applies a
  **bounded edge-score modifier** (×1.1 cheap / ×0.9 rich / ×1.0 otherwise-or-unavailable,
  clamped 0-100) and, when rich, the disclosed card flag `iv_rich_pay_up_warning`. The
  modifier only re-ranks — no candidate is ever rejected on IV. Scanner `winner_summary`
  includes `iv_context` per winner; the paper-model card block renders one line
  ("IV rank 23% — extrinsic cheap": teal cheap / amber rich / dim "IV history building — N/20 days").

## Scanner cron (suggested — NOT installed)

The scanner never installs its own schedule; the operator does, explicitly:

```
15 10 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/options_strategy_scanner.py --run --strategy deep_itm_call >> logs/options_strategy_scanner.log 2>&1
```

Default invocation is `--dry-run` (prints, writes nothing). Weekends/holidays degrade honestly:
chains report per-underlying reasons ("weekend — no chain", liquidity unquotable) instead of
fabricating quotes.

## Validation gate (advisory)

Ledger: `options_paper_outcomes` (migration `migrations/2026_07_05_options_paper_outcomes.sql`,
additive + idempotent). One row per closed paper trade, upsert on `proposal_id` (lineage back to
`options_approval_queue` and, through `meta.discovery_ref`, to discovery #339).

- Record: `validation.record_outcome(proposal_id, outcome=win|loss|scratch, pnl, entry_debit,
  exit_value, pnl_r, opened_at, closed_at, exit_reason, notes, meta)` — refuses contradictory
  input (a "win" with negative pnl).
- Report: `validation.validation_status("deep_itm_call")` or
  `.venv/bin/python scripts/options_validation_status.py --json`
- Gate (from the YAML's `validation_gate`, all must pass): **≥30 closed paper trades ·
  win rate ≥55% (wins/(wins+losses), scratches neutral) · profit factor ≥1.3 ·
  ≥3 calendar months · human approval required**.
- Verdict text is exactly one of: `gate not met — …` or
  `gate met — operator decision required (human_approval_required; nothing is auto-enabled)`.
- Optional advisory mirror: `--sync-registry` writes `trades_taken` + a
  `metadata.paper_validation` blob onto `strategy_registry` — never lifecycle/eligibility columns.

Surfaces: `GET /api/v2/options/validation` powers the Options-tab "Strategy Validation" strip;
each queued paper card carries a `paper validation n/30` chip.

## How a new strategy joins the lane

1. **Discovery** — a Hermes discovery candidate reaches an operator-approved research status
   (e.g. `APPROVED_RESEARCH_ONLY`). Research-only approval is a prerequisite, not a trade approval.
2. **Config** — add `config/strategies/<strategy_id>.yaml` with `paper_only: true`,
   `execution_mode: manual_review_only`, `execution.live_allowed: false`, a `discovery_ref`
   block, selection gates, and a `validation_gate`. The standard loader
   (`strategy_config_loader.py`) picks it up and registers it.
3. **Generator** — add `scripts/lib/options_pipeline/<strategy>_generator.py` following
   `deep_itm_generator.py`: read-only chain analysis, config-driven gates with honest
   reject/flag reasons, proposal rows in the desk's queue shape, fail-closed queue writer.
   Extend the forbidden-imports test list with the new file.
4. **Scanner** — add the strategy to `SUPPORTED_STRATEGIES` in
   `scripts/options_strategy_scanner.py` (and `validation.py` for outcome tracking); winners
   flow into the same `options_approval_queue` manual-review lane.
5. **Validate** — paper outcomes accrue in `options_paper_outcomes`; the strategy shows up in
   the validation strip. Live consideration only after the gate is met **and** the operator
   decides — through the desk's existing arming + per-order 2FA path, never through this pipeline.

## File map

| Piece | Path |
| --- | --- |
| Strategy config | `config/strategies/deep_itm_call.yaml` |
| Generator | `scripts/lib/options_pipeline/deep_itm_generator.py` |
| Scanner CLI | `scripts/options_strategy_scanner.py` |
| Validation ledger/report | `scripts/lib/options_pipeline/validation.py` |
| Validation CLI | `scripts/options_validation_status.py` |
| IV-rank history/rank | `scripts/lib/strategy_research/iv_history.py` |
| IV snapshot CLI | `scripts/options_iv_snapshot.py` |
| Migrations | `migrations/2026_07_05_options_paper_outcomes.sql` · `migrations/2026_07_06_options_iv_history.sql` |
| API | `/api/v2/options/proposals` (merged paper rows) · `/api/v2/options/validation` |
| UI | `OptionsHub.tsx` (validation strip) · `OptionProposalCardV4.tsx` (paper card block + IV line) |
| Tests | `tests/test_options_pipeline_deep_itm.py` · `tests/test_options_pipeline_validation.py` · `tests/test_options_iv_rank.py` |
