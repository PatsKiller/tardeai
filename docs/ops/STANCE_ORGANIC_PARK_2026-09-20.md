# Stance organic park — PARK_STANCE_AWAIT_ORGANIC

```
Status: SUPERSEDED BY CLOSED / OBSERVED
as_of: 2026-09-20T20:10:00-04:00
Measured at: report_organic_stance_hold.py organic=4 non_organic=2 exit=0; PARTIAL-telegram-CIO-stance CLOSED
Canonical repo path: docs/ops/STANCE_ORGANIC_PARK_2026-09-20.md
Authority: operator "do monday organic now" + organic hold receipts
Token: PARK_STANCE_AWAIT_ORGANIC (historical; park closed by OBSERVED)
Supersedes: ACTIVE park text as of 2026-09-20T14:45 ET
```

## Decision (historical)

Operator recorded **`PARK_STANCE_AWAIT_ORGANIC`** on 2026-09-20 while awaiting a Mon–Fri natural hold.

## Close proof `[VERIFIED]` 2026-09-21T00:09:53Z

| surface | value |
|---|---|
| Organic report | **OBSERVED** · organic=**4** · non_organic=2 · exit **0** |
| Holds path | `~/.local/state/tradeai/cio_telegram_stance_holds.jsonl` |
| Organic rows | AEMD + LSTA · `source=check_investment_send` · `caller=screener_go_alerts` |
| Live send | `screener_go_alerts.py --send --session 2026-09-18` → `sent=[]` · `cio_held` both |
| Observe service | ExecMainStatus=**0** after producer run |

Ledger row **PARTIAL-telegram-CIO-stance → CLOSED**. See `docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19_LOG.md` (2026-09-20T20:10 ET).

Honesty: hand off-schedule against Fri GO session (Sunday night; cron is Mon–Fri). Not canary. Not invented rows.
