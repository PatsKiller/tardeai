# Options Desk — operator contract (skim)

> **Status: HISTORICAL (superseded 2026-09-26 by docs/options-module.md).** Kept for the record; do not treat as current. Current proposal flow: `docs/options-module.md` ("Current flow (2026-09-26)").

```
Status: HISTORICAL (superseded 2026-09-26 by docs/options-module.md)
as_of: 2026-09-24T12:25:00-04:00
Authority: companion skim only
Canonical SoT: plan-options-desk-holdings-strategies-20260924.md
```

**Read the full plan for stages and acceptance.** Pocket card only.

Current coverage/scan contract: [Options Module](options-module.md) and
[October 5 capacity and acceptance record](ops/OPTIONS_SCAN_CAPACITY_2026-10-05.md).
The historical requirements below are retained verbatim.

## Asks (P1–P8)

1. CC/CSP/puts/spreads + Schwab + Path B · **latest holdings** · propose only when gates+edge clear  
2. Open-leg P&L / margins / sell-hold-roll  
3–4. CIO fluent + opines (real CIO path)  
5. Goals ↔ security / sector / industry / strategy (no auto-mint)  
6. **BUY_READY + ENTRY_NEAR institutional packet** — equity + options + compare + CIO verdict + Path B  
7. Holdings funnel — named drops; silent omit = defect  
8. **P8** — PE for thesis; IV/ATR/expected-move/Greeks for structure (PE ≠ strike picker)

## Litmus

- **V BUY_READY** — alt or WRONG_STRATEGY_CLASS honesty  
- **AXTI ENTRY_NEAR** — elevated ATR prefers citing defined-risk options; formerly-held noted  

## Stages

| Stage | Status |
|---|---|
| 1 funnel + latest holdings | CLOSED |
| 1B open-leg | CLOSED on PR #1215 |
| 1C CIO fluency/goals | WIRED |
| 1D packet + P8 | WIRED local (push pending) |
| 2 / 2G / 3 | Your call |

## Hard rules

No new strategies · no IV widen · no invented margin · no auto-mint goals · no fake specialists · Path B 2FA · not every holding gets an options play.

## Links

SoT · PR https://github.com/PatsKiller/tardeai/pull/1215 · Drive plan `1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z`
