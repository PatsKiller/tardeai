# Stance organic park — PARK_STANCE_AWAIT_ORGANIC

```
Status: ACTIVE
as_of: 2026-09-20T14:45:00-04:00
Measured at: report_organic_stance_hold.py organic=0 non_organic=2 exit=2; timers armed Mon 06:35 / 09:05 ET
Canonical repo path: docs/ops/STANCE_ORGANIC_PARK_2026-09-20.md
Authority: operator token from plan approve (maturity gap closeout)
Token: PARK_STANCE_AWAIT_ORGANIC
```

## Decision

Operator recorded **`PARK_STANCE_AWAIT_ORGANIC`** on 2026-09-20.

This closes **goal gate (1)** from the 2026-09-20 13:22 ET operator close brief
(organic exit 0 **or** explicit stance park token). It does **not** invent an organic hold
and does **not** claim Monday OBSERVED.

## Still true in the wild

| surface | value `[VERIFIED]` 2026-09-20T18:45Z |
|---|---|
| Organic report | PARTIAL · organic=0 · non_organic=2 · exit 2 |
| Holds path | `~/.local/state/tradeai/cio_telegram_stance_holds.jsonl` |
| Observe-early timer | Mon 2026-09-21 **06:35** ET → `tradeai-stance-organic-observe.service` |
| Observe timer | Mon 2026-09-21 **09:05** ET → same service |

## What closes the park to OBSERVED

A natural Mon–Fri producer hold with `source=check_investment_send` (GO / scalp / proposal),
then `python3 scripts/report_organic_stance_hold.py` exit **0**. No canary invent.
