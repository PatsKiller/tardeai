# P1-WS2 — Event lifecycle census baseline

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0  
**Pin measured:** `852ecd47` (CURRENT)  
**Instrument:** `scripts/cio_event_lifecycle_census.py`  
**Evidence:** `docs/audits/diligence/evidence/P1_WS2_event_lifecycle_census_2026-08-30.json`  

**Do not claim 99.99%.** That KPI is Phase 9 after instrumentation + hardening. This package only measures a baseline.

---

## Stages (contract)

| Stage | Meaning (measurement) |
|-------|------------------------|
| accepted | Producer emitted / binder input observed |
| normalized | Symbol/identity/type fields usable |
| persisted | Durable store or current projection holds the row |
| processed | Downstream cognition / gates / bind / exposure attached |
| archived | Backup, EXIT spine, dated sidecar, or graph+traces retain history |
| recoverable | Row can be re-read or projection rebuild path exists |

---

## Families & producers sampled

| Family | Producers / stores |
|--------|--------------------|
| `security_holdings_exit_reentry` | `portfolio.holdings.current`, `cio.instrument_records` (HELD:/EXIT:), reentry desk + `reentry_payload_last`, identity registry, holdings backups |
| `sector_industry` | `sector.momentum.current`, `industry.momentum.current`, holdings `resolved_sectors`, wouldhavefired / sync_state sidecars |
| `catalyst_earnings` | `catalyst_graph_latest` (traces/nodes/skipped), hermes `momentum_catalysts/*.jsonl` (persistent-state fallback), `earnings_dates.json` |

Cross-cutting overlay (not a family %): `cio_lineage_completion_report` / workflow lineage → **G-LOOP-01**.

---

## Baseline table (live 2026-08-30)

| Family | accepted | normalized | persisted | processed | archived | recoverable | full_lifecycle % | processed % |
|--------|----------|------------|-----------|-----------|----------|-------------|------------------|-------------|
| security_holdings_exit_reentry | 120 | 117 | 120 | 120 | 24 | 120 | **100.0** | **100.0** |
| sector_industry | 154 | 154 | 154 | 154 | 11 | 154 | **100.0** | **100.0** |
| catalyst_earnings | 39478 | 585 | 588 | 561 | 534 | 588 | **1.49** | **1.42** |

### Headlines

| Metric | Value |
|--------|-------|
| Unweighted mean full_lifecycle % | **67.16** |
| **Event-weighted full_lifecycle %** | **2.17** |
| Unweighted mean processed % | 67.14 |
| Event-weighted processed % | **2.10** |
| Min family full_lifecycle % | **1.49** (catalyst_earnings) |
| accepted_total / recoverable_total | 39752 / 862 |
| claim_99.99 | **false** |
| Lineage overlay complete_to_checkpoint | **406 / 752 (53.99%)** |

Weighted % is the honest program signal: catalyst binder skips dominate the event volume.

---

## Drop reasons (top)

### security_holdings_exit_reentry
- `reentry_persisted_desk_only=50` — desk row without payload/EXIT spine
- `reentry_missing_price_source=9`
- `holdings_cash_skipped=5` · `holdings_symbol_not_normalized=3`
- Archive gap: only EXIT instrument records count as archived (24/120 = 20%)

### sector_industry
- `industry_archive_current_only=143` — industries have current projection, no dated archive
- `sector_not_decomposed:*` — SPCX factsheet missing; BND fixed income excluded (honest non-guess)
- Archive gap: 11/154 (7.14%) — sectors with wouldhavefired/sync sidecars only

### catalyst_earnings
- **`catalyst_graph_skip:symbol_not_registered=35928`**
- **`catalyst_graph_skip:entity_has_no_issuer=2962`**
- `hermes_persisted_daily_only=82` · `earnings_date_missing=27` · `earnings_no_dated_archive=54`
- Hermes daily files live under persistent-state (CURRENT `data/hermes` lacks `momentum_catalysts` symlink)

---

## Methodology

1. Read-only census over CURRENT (`--root`), fail-soft per store.  
2. Prefer `canonical_store_registry.resolve_store` for known store ids.  
3. Per family, materialize a symbol/row event set; mark stage booleans from store evidence.  
4. Catalyst graph **skipped** totals are folded into `accepted` without inventing per-skip rows (bounded census).  
5. `full_lifecycle_pct = recoverable / accepted`.  
6. Headlines report both unweighted family mean and event-weighted totals.  
7. No broker writes, no notify-on, no history DELETE, MBI=0.

### Limits (explicit)
- Stage marks are **evidence heuristics**, not a distributed trace spanning every cron.  
- security/sector recoverable≈100% when live+rebuild/backup paths exist — archive stages remain the honest gap.  
- Workflow lineage % is a related loop metric, not identical to event-family lifecycle.  
- Price-history DELETE/quarantine (**G-PRICE-01**) is policy-adjacent; this census does not DELETE and records quarantine-preferred stance in the gap register.

---

## Re-run

```bash
python scripts/cio_event_lifecycle_census.py --root /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
python scripts/cio_event_lifecycle_census.py --json --out docs/audits/diligence/evidence/P1_WS2_event_lifecycle_census_YYYY-MM-DD.json
```

---

## Next (not this PR)
- P9: drive catalyst `symbol_not_registered` / issuer bind toward 99.99% path.  
- P1-WS1: architecture as-built (still open on scoreboard cursor).  
- G-PRICE-01: quarantine path for corrupt prices (no DELETE).
