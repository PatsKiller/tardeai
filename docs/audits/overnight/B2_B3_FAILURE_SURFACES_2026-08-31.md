# B2 + B3 — Failure surfaces (2026-08-31)

**Authority:** `READ_ONLY_ADVISORY` · `AGENTS.md` §9.1  
**as_of:** 2026-08-31  
**Branch:** `fix/overnight-b2-b3-failure-surfaces`  
**Supersedes open PR #733** for `aegis_overnight` (same mechanism; this package
adds the other three silent-success sites plus B2 diagnostics).

---

## B2 — Opaque failure summaries

### What the record showed

| path | `pipeline_runs.summary` (live) |
|---|---|
| health-recovery **success** | `{"note": "health recovery rc=orchestrator_yfinance_rate_limit; rate_limit_hits=32", ...}` |
| orchestrator **failure** | `{"errors": "2"}` |

Successful recovery rows already carried `rc=` and `rate_limit_hits=`. Failing
rows stored only the SystemExit code. A yfinance rate-limit death, an argparse
exit, and a scoring crash were indistinguishable.

### Fix

`scripts/trade_ai_orchestrator.py`:

- `_err` accumulates stage errors.
- `format_failure_diagnostic(...)` builds the same shape the recovery note uses.
- `_enrich_opaque_exit` turns a bare `2` into `rc=exit_2; rate_limit_hits=N; ...`
  before `PipelineRun.run_fail` records it.
- `write_failure_run_summary` writes `run_summary.json` with
  `status=FAILED`, `rate_limit_hits`, `reason_codes`, and
  `published_dashboard=False` — a surface, not a log line.

### What becomes legible

Once failure rows carry the diagnostic, the same classifier the health agent
already uses (`orchestrator_yfinance_rate_limit` vs `orchestrator_stage_fail`
vs argparse) can read **the orchestrator's own row** instead of only the
recovery note that papered over it. Underlying failures that were collapsed
into `"2"` — rate-limit storms, underfilled universes (`UNIVERSE_TOO_SMALL`,
`FINVIZ_AUTH_*`), and stage exceptions — are named on the row.

---

## B3 — Success claims made conditional

### 1. `aegis_overnight`

**Defect:** `PHASE FAILED: morning_brief_delivery` (and `delivered: False`
payloads that never raised) still ended `AEGIS OVERNIGHT COMPLETE` with
`Briefs: 15` from the **synthesis** count.

**Requires for COMPLETE:** no phase with `phase_status in {FAILED, TIMEOUT}`
and no `NO_EFFECT` whose reason is outside `BENIGN_NO_EFFECT`
(`already_sent`, `semantic_duplicate`).

**Digest count:** `N delivered / M generated`, with the delivery cause when
N=0.

### 2. `portfolio_orchestrator`

**Defect:** `Bundle send failed` printed, then `_report_stage_failures`
printed `all pipeline stages completed` because the send was not a stage
failure.

**Requires for "all pipeline stages completed":** `_STAGE_FAILURES` empty —
and Bundle send now calls `_stage_failed("morning_command_bundle", ...)`.

### 3. `cio_command_center` (~1620)

**Defect:** bare `except` served the unrendered product and still stamped
`canonical_cio_source = "cio.operator_product.current"`.

**Requires for `canonical_cio_source`:** `command_center_view(...)` returned
successfully. Render failure and missing product omit the stamp and surface
`render_error` / `loaded: False`.

### 4. `trade_ai_orchestrator` run-health branch

**Defect:** `RUN_FAILED — 0 symbols` only printed a warning, then published
HTML dashboard, PDF, and `dashboard_live.html`.

**Requires for publishing dashboard / PDF / dashboard_live:**
`_publish_artifacts` true — set false when health status is not healthy/partial
and `--allow-underfilled` is absent. Failure writes the B2 diagnostic and
returns it as the process exit string.

---

## Tests + CI

- `tests/test_overnight_b2_b3_failure_surfaces.py` (new)
- Registered in `scripts/run_cio_hardening_ci.py` gate
  `overnight_b2_b3_failure_surfaces`

## Rails

- No broker · no secrets · failures reach a surface · dry-run/tests quote output
- One PR; merge when CI green; **no deploy** (wave instruction)
