# CIO Loop Continuity B1/B2/B3/D1 — Closeout 2026-08-20

**Authority:** READ_ONLY_ADVISORY  
**Phase A lineage:** already CLOSED on CURRENT (SCHD `lin_4c9d72b25d58f05a6170` ADVISORY_USED) — not rebuilt.

## Shipped

### B1 — Material financial Telegram canary (default OFF)

- Env: `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY=1` required for material-scan live Telegram
- Even `--live` + `CIO_ONLY_LIVE` stays dry without canary → `financial_lane=OFF_BY_POLICY`
- Situation notify (`CIO_SITUATION_NOTIFY`) remains a **separate** path

### B2 — Post-research desk memo regen

- Runs after reassessment/lineage attach (fail-soft)
- Stamps `lineage_id` / research_id / result_id on memo footer
- Writes `cio_desk_note_latest.md` + spine when available via `cio_dir()`

### B3 — Catalyst medium+ enqueue

- `_catalyst_medium_plus` + `should_enqueue_for_plan` elevate on research-gap / materiality bump
- `emit_research_for_plan` prefers `catalyst_map_questions` when pack present
- Still uses existing fp@v1 / TTL / de-dupe (no second queue)

### D1 — EXPIRED maturity volume

- `mature_deferred_by_age` + `observe_expired_volume` (cases + deferred dispositions)
- `GET /api/v3/maturity/expired-observe?apply=0|1`
- Learning summary exposes `expired_horizon_matured`
- **MBI / eligible_runs remain 0**

## Tests

`tests/test_cio_loop_b1_b3_d1.py` + related → **37 passed** in suite run with hermes/catalyst/outcome.

## Host enable (operator)

```bash
# B1 canary only when you want material-scan live Telegram:
export CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY=1
# plus existing CIO_ONLY_LIVE gates (AUTHORIZE_P2, INTERDICT=0)
# then: python scripts/cio_material_scan.py --live

# D1 dry observe:
curl -sS 'localhost:7777/api/v3/maturity/expired-observe?apply=0' | jq .
```

## Non-goals

- No Phase A lineage rebuild
- No bulk financial always-on
- No broker / OpenClaw main bot changes
