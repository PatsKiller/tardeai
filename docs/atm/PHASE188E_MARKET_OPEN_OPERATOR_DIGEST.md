# PHASE 188E — Market-Open Operator Digest

Status:      HISTORICAL
as_of:       2026-06-02T08:17:52-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~08:25 ET (premarket) · Alpaca **paper** only · Live endpoint blocked

---

## Status line

| Item | Status |
|---|---|
| ELMT | **HELD** — stale quote, revalidation deferred to open (gate working correctly) |
| SNOW profit-protection needed | **YES** — but mark is stale; act at open, operator-reviewed |
| ANY profit-protection needed | **YES (higher priority)** — naked +$507, no stop |
| Trades executed premarket today | **0** |
| Operator action needed | **YES — 3 items (ANY, SNOW, TMHC) at the open** |

## Open-position risk summary

| id | Sym | Unreal P&L | Stop | Target | Family | Status |
|---|---|---|---|---|---|---|
| 48 | ANY | +$507.58 | ❌ none | ❌ none | unknown | 🔴 naked, high gain |
| 43 | SNOW | +$348.78* | ❌ none | ❌ none | unknown | 🔴 naked, high gain (stale mark) |
| 28 | NWG | +$26.46 | ✅ 15.05 | ✅ 17.42 | income | 🟢 covered |
| 33 | CMCSA | +$9.60 | ✅ 23.61 | ✅ 27.34 | income | 🟢 covered |
| 31 | AGNC | +$5.86 | ✅ 9.71 | ✅ 11.24 | income | 🟢 covered |
| 47 | TMHC | −$1.62 | ⚠️ 68.02 (no broker order) | ✅ 78.77 | swing | 🟡 verify broker stop |

\* stale mark (yesterday's close).

## Counts

- Open positions reviewed: **6**
- Hard-stop active (broker order present): **3** (NWG, AGNC, CMCSA)
- Trailing active: **0**
- Trailing-eligible right now: **0** (deep positions have no risk basis; rest below tier)
- Take-profit missing: **2** (SNOW, ANY) — plus TMHC broker-stop unverified
- Naked (no stop at all): **2** (SNOW, ANY)

## Telegram alert — conditions MET (payload prepared, NOT auto-sent)

> Alert conditions satisfied: stop/profit-protection missing on two high-gain positions + a
> system defect (sync-onboarding metadata gap). Payload below is ready; not auto-sent pending
> operator confirmation.

```
🟠 ATM Paper — Market-Open Action Needed (2026-06-02)
• ANY  +$507  NAKED (no stop) — assign protective stop at open [P1]
• SNOW +$348* NAKED (no stop/TP), +18% stale mark — confirm live, set TP+stop [P2]
• TMHC  stop $68.02 has NO broker order — verify/place [P3]
• ELMT: held, stale quote, awaiting live data (gate OK)
Defect: alpaca_sync positions onboard with no strategy/stop/target metadata.
0 trades premarket. Paper-only. Live endpoint blocked. No mutations made.
```
