# Desk gap-fix closeout — Advisory/CIO accuracy + daily shadow-receipt producer

Date: 2026-08-19
Branch: `feat/desk-gap-fix`
Authority: READ_ONLY_ADVISORY (no broker / order / stop / risk / 2FA mutation)

## What changed

Five phases closed data inconsistencies, staleness, and mis-bucketing across the
Advisory Desk (`/v3/advisory`) and CIO Desk (`/v3/cio`), then wired a real
scheduled producer for the two source clocks that previously had none.

### Phase 0 — Truth clocks (unblocks TRIM accuracy)

- Holdings source clock + price as-of labeling; Finviz Aug-14 `CONFLICTED` state
  suppresses TRIM rather than acting on stale data.
- `DATA_CONFLICT` / `ACTION_SUPPRESSED` propagate to rows so a conflicted sell is
  never surfaced as actionable.

### Phase 1 — Advisory: watch + re-entry visibility

- Personal watch and re-entry counts surfaced on the Advisory Desk.
- Watch Hub opportunity slice (`watchlist_hub` class) from the DB universe,
  bounded and distinct from the personal watch.
- Re-entry decision-desk join (`reentry_decision_desk`) for re-entry opinions.
- "Run now" vs technicals stamp: a background rebuild does not refresh
  `BLOCKED`-row technicals; the UI says so explicitly.

### Phase 2 — CIO: opportunities bucketing + honest caps

- Re-entry opportunities bucketed from their true source (not mislabeled as
  watch); `watch_total` / `reentry_total` added to the payload.
- Universe & Theses: CUSIP/bond-style identifiers bucketed `BONDS_UNRESOLVED` and
  sorted last; membership painted (`HELD` / `REENTRY` / `WATCH` / `OTHER`).
- Holdings thesis painted on the Portfolio Action Book; "why" falls back to
  `why_still_held` / `thesis_state`.
- Re-entry book "Show all" instead of a silent 30-name cap; `NON_TICKER_SYMBOLS`
  filtered out of the re-entry book.

### Phase 3 — Senses/memory: NO_PRODUCER vs daily shadow receipts

- Added `FRESH_NO_PRODUCER` + `no_producer_freshness()` for sources with no daily
  timer, so an aged receipt read as informational rather than a missed job.
- Wired the producer (below), which flips SENSES/MEMORY to real
  `CURRENT` / `STALE` / `EXPIRED` classification and stamps
  `producer = "advisory_shadow_seed"`.

### Phase 4 — TRIM policy + synthesis fail-closed

- `trim_kind` classifies TRIM as `policy` (concentration), `rule` (gain), or
  `housekeeping` (remnant/sub-threshold). Remnants are `HOLD`, never a book
  TRIM/EXIT/ADD; Flash opinions skip them (`skipped_housekeeping` telemetry).
- LLM synthesis fails closed on `CONFLICTED`/stale rows: a conflicted name is
  never named as a sell or funding source.

## Daily shadow-receipt producer (new)

`scripts/advisory_shadow_seed.py` writes two observation receipts every run at
`influence = 0`:

1. Financial Senses tool-trace heartbeat → `data/cio/agent_tool_traces.jsonl`
   (`fs_provider=shadow_seed`, `fs_capability=daily_shadow_seed`).
2. Governed durable-memory admission → `data/cio/aif_memory.jsonl` +
   `aif_memory_admissions.jsonl` (`PROCEDURAL_HINT`, `CANDIDATE` — context only).

It never invokes a live FS provider, a model, or a broker mutation.
`MEMORY_BEHAVIOR_INFLUENCE` is pinned to 0 in the script and the unit.

Systemd wiring (committed under `config/systemd/user/`):

- `tradeai-advisory-shadow-seed.service` — oneshot, release-tree path,
  `Environment=MEMORY_BEHAVIOR_INFLUENCE=0`.
- `tradeai-advisory-shadow-seed.timer` — `OnCalendar=*-*-* 21:45:00`
  (immediately before the 21:50 nightly reflection).

The MEMORY clock now reads the newest admission receipt (`admitted_at`), so a
producer run moves `as_of` even when the heartbeat does not rank first in
retrieval.

## Deploy / rollback

1. Merge `feat/desk-gap-fix` to protected main (PR flow).
2. Deploy exact main (requires `release-write` grant on ms01):
   ```bash
   scripts/cio_phase2_exact_main_deploy.sh prepare
   scripts/cio_phase2_exact_main_deploy.sh promote
   ```
3. Install the producer timer (host):
   ```bash
   cp config/systemd/user/tradeai-advisory-shadow-seed.{service,timer} ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now tradeai-advisory-shadow-seed.timer
   ```
4. Rollback: `scripts/cio_phase2_exact_main_deploy.sh rollback`.

## Tests

- `tests/test_advisory_shadow_seed.py` — producer receipts, influence=0, FS
  recognition by `join_financial_senses`, MEMORY clock from admission receipt.
- `tests/test_advisory_desk_trim_policy.py` — TRIM policy/rule/housekeeping and
  synthesis fail-closed on CONFLICTED.
- `tests/test_advisory_desk_operator.py::test_no_producer_freshness_*`.
- CIO re-entry/CUSIP/non-ticker coverage in `test_cio_command_center.py`,
  `test_cio_investment_product.py`, `test_symbol_thesis_integration.py`.
