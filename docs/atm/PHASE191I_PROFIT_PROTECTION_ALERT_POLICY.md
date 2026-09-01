# PHASE 191I — Profit-Protection Alert Policy

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only.** Defines when a profit-protection advisory is **actionable** (Telegram) vs
**informational** (digest/dashboard only). No routine noise.

---

## Actionable (Telegram) — only if quote is fresh AND operator action matters
- Large gain with **no broker stop** (naked).
- Large gain with a stop that **does not protect meaningful profit** (stop below entry / giveback
  ≥ 50% of unrealized gain) → maps to `URGENT_PROTECTION_REVIEW` / `large_gain_loose_stop` /
  `profit_giveback_too_high`.
- **Take-profit missing AND giveback risk exceeds threshold** on a large gain.
- Broker stop **verification failed** (from Phase 190 `protection_alerts`).

## Digest / dashboard only (no Telegram)
- Advisory is informational (`REVIEW_STOP`, `TAKE_PROFIT_ADVISORY` where the stop already protects
  profit — e.g. SNOW).
- Quote **stale** (cannot advise on live giveback).
- `NO_ACTION`.

## Mapping to current state
| Trade | Advisory | Telegram? | Why |
|---|---|---|---|
| ANY | URGENT_PROTECTION_REVIEW + loose-stop + giveback | **YES (actionable)** | big gain, stop protects nothing |
| SNOW | TAKE_PROFIT_ADVISORY | digest only | stop already locks profit; TP is optimization |
| others | NO_ACTION | none | below thresholds |

## Implementation
- Routing reuses Phase 190 `protection_alerts.py` (SIEM `alert_events` always written; Telegram
  gated by `PROTECTION_ALERTS_TELEGRAM`). Profit-protection severities map P0/P1 → Telegram when
  enabled, P2/info → SIEM/digest only.
- **Dedup:** one actionable alert per (trade, defect_type) per 6h window (existing dedup).
- Default `PROTECTION_ALERTS_TELEGRAM` remains **off** until an operator noise check; the corrected
  Phase 189/190 digest was already sent once on operator authorization.

## Guardrail
Alerts are advisory. No alert triggers an automatic stop/order change — execution remains gated to
Phase 192.
