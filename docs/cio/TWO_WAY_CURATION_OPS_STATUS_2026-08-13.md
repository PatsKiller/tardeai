# Two-Way Watchlist Curation — Ops Status (2026-08-13)

**Authority:** READ_ONLY_ADVISORY · no orders/2FA  
**Branch:** `feat/two-way-watchlist-curation`  
**Canonical design doc:** [TWO_WAY_WATCHLIST_CURATION.md](./TWO_WAY_WATCHLIST_CURATION.md)

---

## Production state

| Check | Result |
|-------|--------|
| Schema (staging + reverse cols + audit) | Live |
| `surfaced_by` allows cio/advisory/defense | Live |
| Monitor | **ACTIVE** |
| Hermes directive staging undrained | **0** |
| Desk suggestions inbox (API + WatchpoolHub) | Live — **26** multi-desk staged |
| Desk hits 24h | **cio:12 · advisory:7 · defense:7** |
| Desk staging undrained | **0 / 0 / 0** |
| One-tap Promote | Live (`POST /api/v2/watch/directives/promote`) |
| Reverse research / outcomes on watchlist | 1115 / 111 names |
| Options edge reverse | **~278 names** via queue edge + IV rank proxies (closed paper still preferred when present) |
| Scorer reverse weights | **v9** — research 5.5% · options 4.5% · thesis 5.7% (~15.7% combined) |

---

## Operator actions

1. Open **Watchpool** → **Desk suggestions** (hard-refresh CC if needed).  
2. Filter by cio / advisory / defense.  
3. **Promote** staged symbols (advisory path; scalp firewall still applies).  
4. Health: `curl -sS http://127.0.0.1:7777/api/v2/watch/two-way-curation | python3 -m json.tool`

### Backlog clear (if monitor returns STALLED)

```bash
.venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --max 500 --stage-only
.venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --max 100 --stage-only --touch-quiet
.venv/bin/python scripts/watch_directives_monitor.py --dry-run
```

### Smoke (safe stage-only)

```bash
.venv/bin/python scripts/ops/two_way_curation_smoke.py --apply-drain --stage-only
```

### Multi-desk emit from latest snapshots + drain residual

```bash
# Preview candidates from advisory_desk_latest + defense_recommendations_latest
.venv/bin/python scripts/ops/emit_and_drain_desk_curation.py

# Emit advisory+defense + drain cio/advisory/defense (stage-only)
.venv/bin/python scripts/ops/emit_and_drain_desk_curation.py --apply
```

CIO residual staging is also auto-drained (stage-only) after reactive emit when
`CURATION_DRAIN_AFTER_EMIT=1` (default).

---

## Commits landed this session

- `30d3e05d` — SM env shell-sourceable  
- `c1d9046a` — P0–P2 closed loop  
- `bfc8f674` — Hermes staging fast drain  
- `67946947` — Desk suggestions inbox + promote  
- `db6b4825` — docs production status  
- `69f6d268` — multi-desk emit+drain + CIO residual auto-drain  
- `06d91cba` — options edge proxies + scorer v9  
- `ad305f87` — scheduled cron (options-edge + desk-emit)  

---

### Options edge + scorer (P1)

```bash
# Backfill options_edge from closed outcomes → queue edge → IV rank
.venv/bin/python scripts/ops/fold_options_edge_backfill.py --limit 500

# Scorer picks up hermes_score_weights.yaml v9 automatically
.venv/bin/python scripts/hermes_watchlist_scorer.py --once
```

### Cron (installed on MS-01)

Wrapper: `scripts/run_scheduled_two_way_curation.sh`  
Logs: `logs/two_way_curation_cron.log`, `logs/two_way_options_edge.log`, `logs/two_way_desk_emit.log`

| Schedule (ET, Mon–Fri) | Job |
|------------------------|-----|
| **15:50** | `options-edge` — after IV snapshot (15:45) |
| **16:25** | `options-edge` — after EOD options monitor |
| **10:20** | `desk-emit` — after morning defense recs (10:10) |
| **18:05** | `desk-emit` — after evening defense recs (17:50) |

```bash
# Manual
bash scripts/run_scheduled_two_way_curation.sh options-edge
bash scripts/run_scheduled_two_way_curation.sh desk-emit
bash scripts/run_scheduled_two_way_curation.sh all
crontab -l | sed -n '/two-way-curation-cron/,/END two-way/p'
```

---

## Residual / next

- ~~Organic advisory + defense staging~~ **proven**  
- ~~Options edge reverse empty~~ **populated via proxies** (~278 names)  
- ~~Scorer reverse too weak~~ **v9 ~15.7% reverse weight**  
- ~~Cron for edge + multi-desk emit~~ **installed**  
- Full promote under load can hit locks — stage-only for bulk; one-tap for intentional promotes  



