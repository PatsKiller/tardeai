# Overnight F4 — Search health + degradation into research output

**Wave:** Overnight F4  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0`  
**Branch:** `fix/overnight-f4-search-health`  
**Deploy:** none  
**Overlap:** does **not** rewrite F1/F2 `cio_residual_web` policy/census; thin call sites only (`attach_degradation` / `forward_stamp` / `narrative_suffix`).

---

## Finding

`scripts/lib/search_health.py` already probes SearXNG and returns an `impaired`
record when fewer than `MIN_HEALTHY_ENGINES` actually served results. The live
residual-web transport stamped `search_pool*` onto its response — and
**`run_hop` dropped those keys**, so the hop result, CC binding, and narrative
never said the pool was thinner than it looked.

Measured failure this programme exists to remove (2026-08-30): ten results, all
from one engine, peers CAPTCHA-suspended / rate-limited, research output silent.

AGENTS.md §12: *"When the engine pool is degraded, the research output says so."*

---

## Monitor (dry + live as_of)

Dry (no HTTP probe) — monitor lane collects:

```
$ python3 -m scripts.lib.search_health_degradation
# dry=true, probe=false → lane search-providers, budgets present,
# per_source=[] when no durable search_health.json (never invents CAPTCHA)
```

Live probe quoted 2026-08-31T05:27Z (read-only GET to local SearXNG; no paid
provider; **no write** to production durable status in this tranche). An earlier
probe in the same minute saw bing+brave healthy; a repeat saw brave drop to
"too many requests" — exactly the thinner-looking-full failure mode:

```
impaired                 → true   (only bing serving; MIN_HEALTHY_ENGINES=2)
search_thinner_than_full → true
serving_engines          → bing
unresponsive_engines     → brave: too many requests
                           duckduckgo: CAPTCHA
                           startpage: Suspended: CAPTCHA
search_captcha_suspended → [duckduckgo, startpage]
```

Per-source state always names measured CAPTCHA suspensions. When
`impaired=True`, `search_thinner_than_full=True` and the narrative suffix states
the answer is thinner than a full result set.

---

## Change this tranche

| File | Change |
|------|--------|
| `scripts/lib/search_health_degradation.py` | **New** — durable status reader/writer, per-source report, `attach_degradation` / `forward_stamp` / `narrative_suffix` / `dry_report`. Never invents CAPTCHA data. |
| `scripts/lib/cio_residual_web.py` | Thin hooks: live transport → `attach_degradation(probe=True, persist=True)`; `run_hop` + `cc_binding` → `forward_stamp`; narrative → `narrative_suffix`. |
| `tests/test_overnight_f4_search_health.py` | Dry monitor, per-source CAPTCHA, durable round-trip, stamp survives `run_hop`, no invent on stub. |
| `scripts/run_cio_hardening_ci.py` | Allowlist gate `overnight_f4_search_health`. |
| This audit note | Evidence. |

Existing monitor `scripts/lib/search_health.py` is **reused**, not replaced.

---

## Rails (verified by tests)

| Rail | How |
|------|-----|
| Monitor runs dry | `collect_search_health(probe=False)` + `dry_report(probe=False)` |
| Per-source state | `per_source_state` / `search_sources` from measured pool only |
| CAPTCHA-suspended surfaced | `search_captcha_suspended` + note + narrative suffix |
| thinner ≠ full | `search_thinner_than_full` iff `impaired`; narrative says so |
| Never invent CAPTCHA | Missing/corrupt durable → empty sources, `impaired=None` |
| Stamp survives hop | `forward_stamp` in `run_hop` / `cc_binding` |
| Durable path | `…/data/runtime/search_health.json` under `production_state_root` |

---

## What F4 deliberately does **not** do

- Does not re-census or re-bind Brave callers (WAVE F1+F2).
- Does not change search budget flock/ledger (WAVE F3).
- Does not install cron, promote CURRENT, or spend a paid search credit.
- Does not invent CAPTCHA rows when the monitor has not measured them.

---

## Reproduction

```bash
python3 -m scripts.lib.search_health_degradation          # dry
python3 -c "
from scripts.lib.search_health import pool_health
from scripts.lib.search_health_degradation import degradation_stamp
import json
print(json.dumps(degradation_stamp(pool=pool_health()), indent=2))
"
python3 -m pytest -q tests/test_overnight_f4_search_health.py
```
