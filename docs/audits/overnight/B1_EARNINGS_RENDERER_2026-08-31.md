# WAVE B1 — Earnings renderer

**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**Branch:** `fix/cio-gap-earnings-b1`  
**Repo:** PatsKiller/tardeai  
**Deploy:** not in this tranche

---

## Break named

**Count-only brief line + holdings-blind OP collect fallback.**

`earnings_dates.json` (and live overlay/OP rebuild) already carried dated
events, but `morning_text` only emitted:

```text
Earnings (D): N upcoming
```

with no symbol/date/scope lines — so the brief earnings surface read as empty
of events. Separately, `build_operator_product`'s fallback called
`collect_earnings_events(root=root)` without holdings, so every row was labeled
`scope=watch` even for held names. Collector also missed the persistent-state
copy when the checkout root had no local `earnings_dates.json`.

---

## Rails honored

| Rail | How |
|------|-----|
| READ_ONLY_ADVISORY | Display/projection only; no orders/stops/broker |
| MBI=0 | No memory-behavior influence change |
| No invented analysis | Commentary stays `UNAVAILABLE` without a transcript row; brief lists dates only |
| No secrets / no PR #736 / no hooks / no notify-on | Code + tests + this audit only |
| STORE SET none | Dry-run / `persist=False` only against RO data |

---

## What changed (exclusive file set)

1. **`scripts/lib/cio_investment_product.py`**
   - `_earnings_dates_path`: checkout root first, then
     `GOOD_PERSISTENT_ROOT/.../earnings_dates.json`, then hub legacy path.
   - `collect_earnings_events` uses that resolver (still Class D; still no fake dates).

2. **`scripts/lib/cio_operator_product.py`**
   - Fallback collect passes `holdings_payload` + watch symbols so held names
     rank first and `scope` is honest.

3. **`scripts/lib/cio_operator_renderers.py`**
   - New `earnings_lines()` — lists `SYMBOL · YYYY-MM-DD · Nd · scope`.
   - Empty + `DATA_UNAVAILABLE` is named, not omitted.
   - `morning_text` uses `earnings_lines`.
   - `command_center_view` carries `earnings_quality`.

4. **`tests/test_cio_gap_earnings_b1.py`** + CI allowlist entry in
   `scripts/check_test_coverage.py`.

---

## Dry-run snippet (pinned hub data root, persist=False)

```text
earnings_n 10 quality OK
scopes ['held', 'watch']
--- earnings_lines ---
Earnings (D): 10 upcoming
- NOC · 2026-10-20 · 50d · held
- RTX · 2026-10-20 · 50d · held
- BAH · 2026-10-23 · 53d · held
- V · 2026-10-27 · 57d · held
- CSWC · 2026-11-02 · 63d · held
```

(Quoted from local prove against
`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` after the fix.)

---

## Out of scope

- Deploy / promote  
- Gap-register edits  
- Transcript commentary wiring beyond existing UNAVAILABLE  
- Notify-on / Telegram enablement  
- Persisting OP/brief stores from this tranche  
