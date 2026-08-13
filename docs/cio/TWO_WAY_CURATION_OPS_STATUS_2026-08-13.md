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
| Desk suggestions inbox (API + WatchpoolHub) | Live |
| One-tap Promote | Live (`POST /api/v2/watch/directives/promote`) |
| Reverse research / outcomes on watchlist | 1115 / 111 names |
| Options edge reverse | Wired; **0** rows (no paper outcomes yet) |

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
- multi-desk emit+drain ops + CIO residual auto-drain  

---

## Residual / next

- ~~Organic advisory + defense staging~~ **proven** via latest-snapshot emit (2026-08-13)  
- Options paper outcomes → `options_edge_score`  
- Full promote under load can hit `watchlist_items` locks — use stage-only for bulk; one-tap for intentional promotes  
- Wire `emit_and_drain_desk_curation.py` onto a daily cron after advisory/defense jobs if desired  

