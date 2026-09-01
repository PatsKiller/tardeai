# Synthetic Stops for Fractional Positions (2026-06-21)

Status:      HISTORICAL
as_of:       2026-06-21T22:21:37-04:00
Measured at: efcc51365 / not measured

## Problem
Schwab REJECTS a resting STOP order on a fractional share quantity (policy 2025-05-21: fractional orders
must use Market-Day / Limit-Day / Limit-GTC). So fractional holdings — e.g. TDG 0.7169, NOC 1.2262,
LMT 1.4059, LHX 2.5176 — cannot be protected by a broker-side stop. The whole-share floor (committed
1fa50334) protects the integer part but leaves the fraction (and, for sub-1-share positions, everything)
uncovered.

## Solution — software-monitored stop → Market-Day sell-all
Schwab DOES accept a Market-Day sell of the full fractional qty. So a synthetic stop:
1. **arm** — store a stop LEVEL for the full position (advisory; nothing placed at the broker).
2. **watch** — `unified_stop_supervisor` (every ~3 min, RTH) compares live price to the level.
3. **fire** — on breach it builds a MARKET-DAY sell-all intent and REQUESTS per-order 2FA (Telegram +
   email + web typed-ticker). It does NOT auto-submit — the operator approves through the existing
   protective-stop/confirm flow, exactly like every other live order. (Auto-fire without per-order
   approval is intentionally NOT implemented — would need an explicit operator decision.)

## Pieces
- `scripts/brokers/protective_stop_pilot.py` — MARKET (`SELL_ALL`) order kind → Schwab Market-DAY sell of
  the full qty (committed 57a3fa43).
- `scripts/synthetic_stop_monitor.py` (new) — `synthetic_stops` table + `arm` / `cancel` / `list_stops` /
  `check_and_trigger(dry_run)`. Live price from Schwab quote → enrichment-cache fallback; a missing price
  NEVER triggers (fail-closed). One active stop per (symbol, account); re-arm supersedes.
- `scripts/unified_stop_supervisor.py` — best-effort hook in `run_cycle`: `check_and_trigger(dry_run=dry_run
  or not in_hours)` so breaches only fire during RTH in apply mode; reported under `synthetic_stops`.
- `scripts/api_v2.py` — `POST /api/v2/holdings/synthetic-stop` (arm), `POST .../synthetic-stop/cancel`,
  `GET /api/v2/holdings/synthetic-stops?status=armed|all|triggered|canceled`.

## Safety
Arming places NOTHING at the broker. A breach only REQUESTS 2FA — the operator's per-order approval is the
gate that actually submits the market sell, identical to every other live Schwab order. Fail-closed on a
missing price. Whole-share positions should still use a real broker STOP (open-trades card); this is
specifically the fractional path.

## Verified
Table create, arm, live-price fetch (real Schwab quote), correct breach logic (price>stop → ok;
price<=stop → would_trigger), cancel, and all three HTTP endpoints. Monitor wired + reported in the
supervisor cycle.

## Candidates (fractional Schwab positions wanting this — 2026-06-21)
Sub-1-share (no broker stop possible): TDG 0.7169. Small fractional (whole-stop leaves a meaningful slice):
NOC 1.2262, LMT 1.4059, LHX 2.5176. Large fractional (whole-share stop ≈ full coverage): PFLT, CSWC, RTX,
LDOS, NEE.

## Remaining
Card UI to arm/show synthetic stops on fractional positions (engine + API are ready to wire).
