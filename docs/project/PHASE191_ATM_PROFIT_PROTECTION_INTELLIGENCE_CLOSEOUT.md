# PHASE 191 — ATM Profit-Protection Intelligence — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~10:50–11:15 ET · Alpaca **paper** only · Live endpoint blocked
**Advisory only — no stops moved, no take-profit orders created, no broker orders modified.**

---

## What shipped
- **191B/D** `profit_protection_advisory.py` — TradeAI scoring model; computes the full
  profit-protection audit on fresh quotes, scores stop **quality** (lock/giveback), persists
  advisories to `atm_profit_protection_advisories`.
- **191E** `hermes_profit_protection_check.py` + 5 finding types — Hermes second opinion
  (loose-stop / giveback / no-TP / metadata-missing).
- **191F** `GET /api/v2/atm/profit-protection-advisory` — inline panel data (TradeAI + Hermes
  side-by-side, advisory-only decision buttons). Live on next server restart.
- **191H** closed-loop learning design + capture surface.
- **191I** actionable-vs-digest alert policy.
- Migration `migrations/2026_06_02_phase191_profit_protection.sql`.

## Required closeout fields
- **Phase 191 complete:** ✅ YES
- **ANY advisory generated:** ✅ YES — `URGENT_PROTECTION_REVIEW` (loose stop, ~100% giveback, no TP)
- **SNOW advisory generated:** ✅ YES — `TAKE_PROFIT_ADVISORY` (stop already locks profit)
- **Open trades reviewed:** 6
- **Take-profit missing count:** 6
- **Stop-quality advisory count:** 1 (ANY)
- **Trailing-eligible count:** 0
- **Profit-lock advisory count:** 1 (ANY)
- **Inline ATM advisory visible:** endpoint added; **visible on next server restart** (UI panel next build)
- **Hermes rule added:** ✅ YES (`hermes_profit_protection_check.py`, +5 finding types)
- **TradeAI scoring model added:** ✅ YES (`profit_protection_advisory.py`)
- **SIEM/Telegram policy updated:** ✅ YES (191I — actionable vs digest)
- **No stops modified:** ✅ YES · **No orders placed:** ✅ YES
- **Live trading:** ZERO · **Live endpoint blocked:** YES · **GO/WAIT mutation:** ZERO ·
  **Strategy mutation:** ZERO · **Level 7:** PROHIBITED
- **Next recommended gate:** **Phase 192 — operator-approved paper stop/take-profit adjustment
  workflow** (propose → show why → explicit operator click → modify the Alpaca **paper** order;
  then wire the 191H close reconciler to measure accepted/ignored + profit-left-on-table).

## Operator takeaways
1. **ANY needs attention** — +20% gain, stop locks nothing; operator review to lock profit / set TP.
2. **SNOW is protected** — stop already locks ~$143; only take-profit optimization remains.
3. The system now says **what to do and why**, with a Hermes second opinion, and correctly ranks
   stop **quality** (not just gain size).

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no stops moved/cancelled,
no take-profit orders created, no strategy configs changed, no GO/WAIT logic changed, Level 7 not
enabled, Claude Code auto-update not run. DB writes limited to a new advisory table, Hermes findings,
and a CHECK-constraint extension.
