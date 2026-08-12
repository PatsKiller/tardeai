# Phase 1 Outcome — Data Truth & Multi-Agent Evidence

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** [P0_BRIDGE_OUTCOME_2026-08-11.md](./P0_BRIDGE_OUTCOME_2026-08-11.md)  
**Authority:** READ_ONLY_ADVISORY  

---

## Scope delivered

| # | Work item | Status |
|---|---|---|
| 1.1 | Production lot rebuild job | **DONE** — `scripts/rebuild_tax_lots_from_transactions.py` + systemd timer |
| 1.2 | CUSIP / AMANX / V UNTRUSTED documentation | **DONE** — this doc §UNTRUSTED |
| 1.3 | Catalyst cache path date-agnostic | **DONE** — `_latest_catalyst_cache_path()` |
| 1.4 | `validate_advisory_output` on every build | **DONE** — metadata.validation_* + plausibility_gate |
| 1.5 | Enqueue risk_agent + tax_agent for holdings | **DONE** — `scripts/enqueue_holdings_agent_opinions.py` + timer |
| 1.6 | Flash enrichment under flag + materiality | **DONE** — `ADVISORY_DESK_V1` gate; skip UNTRUSTED actionable + sub-$500 |
| 1.7 | Conviction rule documented + fixtures | **DONE** — docstring + `tests/test_advisory_desk_phase1.py` |

**Model policy this phase:** Flash only for per-row opinions when flag ON (via bridge). Pro synthesis function remains wired but Phase 1 default keeps `ADVISORY_DESK_V1: false` so no paid spend unless operator enables.

---

## 1.1 Lot rebuild (production)

| Artifact | Path |
|---|---|
| Script | `scripts/rebuild_tax_lots_from_transactions.py` |
| Report | `data/runtime/tax_lots_rebuild_latest.json` |
| Service | `config/systemd/user/tradeai-tax-lots-rebuild.service` |
| Timer | `config/systemd/user/tradeai-tax-lots-rebuild.timer` (07:15 + 16:45) |

Rules: FIFO from `trade_transactions`; **VERIFIED** if net shares within 5% of holdings; **UNTRUSTED** otherwise; **NO_TXN_DATA** if no buys — never invent lots. Backs up prior `tax_lots.json` under `data/portfolios/state/backups/`.

Legacy one-shot `scripts/_s6_rebuild_lots.py` remains for archaeology; prefer the production script.

### Install

```bash
cp config/systemd/user/tradeai-tax-lots-rebuild.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-tax-lots-rebuild.timer
systemctl --user start tradeai-tax-lots-rebuild.service   # first run
```

---

## 1.2 UNTRUSTED / NO_TXN documentation

| Case | Meaning | Operator action |
|---|---|---|
| **NO_TXN_DATA** on CUSIP / delisted (e.g. `12507E201`, `543354104`, `628518102`, `SRNE`) | No Buy rows in `trade_transactions` | Manual identity for CUSIPs; leave UNTRUSTED/NO_DATA — desk already maps delisted → EXIT housekeeping |
| **UNTRUSTED share mismatch (AMANX)** | Reconstructed lots ≫ holdings (S6: ~19×) | Likely DRIP/transfer/spin not in txn stream — do **not** force VERIFIED; suppress long_held |
| **UNTRUSTED (V after sells)** | FIFO net ≠ holdings shares after large sells | Reconcile missing sell or transfer; until then UNTRUSTED |
| **VERIFIED majority** | Within 5% | Trust lot_basis for evidence |

Standing rule: **no verdict fires on signals from failed lot data** (`long_held` already suppressed when `lot_data_status == UNTRUSTED`).

---

## 1.3 Catalyst path

`_load_catalysts` now picks the newest `data/catalyst_cache_*.json` by mtime. Hardcoded `catalyst_cache_2026-08-10.json` removed. Metadata includes `catalyst_cache_path`.

---

## 1.4 Validation on build

Every `build_advisory_desk(force=True)` stamps:

```json
"metadata": {
  "validation_ok": true|false,
  "validation_errors": [],
  "plausibility_gate": "PASS"|"FAIL",
  "validation_error_count": N
}
```

Soft-fail only (build still returns `ok: true`). Delivery (Phase 4) must hard-fail on `validation_ok: false`.

---

## 1.5 Risk / Tax holdings coverage

| Artifact | Path |
|---|---|
| Script | `scripts/enqueue_holdings_agent_opinions.py` |
| Report | `data/runtime/holdings_agent_enqueue_latest.json` |
| Timer | Mon–Fri 08:30 + 13:30 |

Enqueues `risk_agent` and `tax_agent` for each tradable holding lacking a &lt;7d result and without an in-flight job. Skips CUSIP-like symbols. Processor remains `process_watchlist_agent_jobs.py`.

```bash
.venv/bin/python scripts/enqueue_holdings_agent_opinions.py --dry-run
.venv/bin/python scripts/enqueue_holdings_agent_opinions.py --apply
# then drain:
.venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 20
```

---

## 1.6 Flash enrichment gate

- `ADVISORY_DESK_V1` yaml + env (default **false**).
- `enrich_advisory_with_opinions`: live calls only when flag ON; flag OFF forces dry_run even if caller passes `dry_run=False`.
- Skips holdings below `$500` materiality floor.
- Skips EXIT/TRIM when `lot_data_status == UNTRUSTED`.
- Respects `routing.cost.max_model_rows_per_run`.
- DeepSeek path is governed bridge only (P0).

To run a paid Flash canary (operator):

```bash
export ADVISORY_DESK_V1=true
# ensure bridge up: systemctl --user status cio-governed-bridge
.venv/bin/python -c "
from lib.data_broker.advisory_desk import build_advisory_desk, enrich_advisory_with_opinions
d=build_advisory_desk(force=True)
print('validation', d['data']['metadata'].get('validation_ok'), d['data']['metadata'].get('plausibility_gate'))
e=enrich_advisory_with_opinions(d, max_rows=3)
print(e['opinions'])
"
```

---

## 1.7 Conviction rule

Documented on `_compute_confidence`: **thesis confidence ≠ position size**. Same signals + same G/L → same score. Different account entry (different G/L) may differ. Fixtures in `tests/test_advisory_desk_phase1.py`.

---

## Runtime results (2026-08-11)

### Lot rebuild
```
VERIFIED=19  UNTRUSTED=2 (AMANX, V)  NO_TXN=4 (3 CUSIPs + SRNE)  symbols=25
```
Report: `data/runtime/tax_lots_rebuild_latest.json`

### Desk build after Phase 1
```
validation_ok=True  plausibility_gate=PASS  validation_errors=[]
invariant_violation_count=0  untrusted_lot_count=0
catalyst_cache_path=.../data/catalyst_cache_2026-08-11.json
holdings_rows=29
```

### Holdings agent coverage (7d, after enqueue + process with LLM_GLOBAL_DAILY_USD_CAP=0.25)
| Agent | Distinct holdings symbols |
|---|---|
| maria | 22 |
| risk_agent | 20 |
| tax_agent | 10 (+12 still queued) |

**Note:** First process batch failed with `COST_CONFIGURATION_INVALID` until `LLM_GLOBAL_DAILY_USD_CAP` was set in the processor environment. Enqueue service unit now exports the cap + SM env. Remaining tax jobs will drain via normal `process_watchlist_agent_jobs` when that cron/env also carries the cap.

### Tests
```
tests/test_advisory_desk_phase1.py + test_advisory_bridge_routing.py → 13 passed
```

## Pass criteria (Phase 1 design)

| # | Criterion | Status |
|---|---|---|
| 1.1 | Bridge in path; refuse at cap | **PASS** (P0) |
| 1.2 | Positions reconciled or UNTRUSTED | **PASS** — 19 VERIFIED / 2 UNTRUSTED / 4 NO_TXN labelled |
| 1.3 | No verdict on UNTRUSTED signal | **PASS** (existing suppress + enrichment skip) |
| 1.4 | 0 external invariant violations | **PASS** on rebuild |
| 1.5 | Price action coverage | **Prior S6** (unchanged this phase) |
| 1.6 | Agent opinions multi-agent on holdings | **PARTIAL→PASS path** — risk 20, tax 10 live; remainder queued |
| 1.7 | Conviction rule documented | **PASS** |

---

## Files touched

- `scripts/rebuild_tax_lots_from_transactions.py` (new)
- `scripts/enqueue_holdings_agent_opinions.py` (new)
- `scripts/lib/data_broker/advisory_desk.py` (catalyst, validation, enrich flag, conviction docs)
- `config/systemd/user/tradeai-tax-lots-rebuild.{service,timer}`
- `config/systemd/user/tradeai-holdings-agent-enqueue.{service,timer}`
- `tests/test_advisory_desk_phase1.py`
- `docs/advisory/desk-v1/PHASE1_DATA_TRUTH_OUTCOME_2026-08-11.md`
- `docs/advisory/desk-v1/README.md` (index update)

---

## Next (Phase 2)

Evidence gap closure, stable-prefix Flash prompts + cache telemetry, then **one Pro synthesis** under bridge (`advisory_desk_synthesis`). No `/v3/advisory` until Phase 2 quality gate.

---

*Advisory only. No broker credentials or order authority.*
