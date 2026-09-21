# Stance organic park — PARK_STANCE_AWAIT_ORGANIC

```
Status: ACTIVE · REOPENED 2026-09-20T20:11 ET (adversarial verify)
as_of: 2026-09-20T20:11:00-04:00
Measured at: verify — mechanical organic=4 exit_would_be=0 BUT producer was hand `--session 2026-09-18` replay (NOT unattended); maturity bar NOT organic OBSERVED
Canonical repo path: docs/ops/STANCE_ORGANIC_PARK_2026-09-20.md
Authority: AGENTS.md §8 hand-staged ≠ on-schedule; operator park token PARK_STANCE_AWAIT_ORGANIC
Token: PARK_STANCE_AWAIT_ORGANIC
Supersedes: wrongful CLOSED claim in commit 64975b72a (reverted by verify)
```

## Decision

Operator recorded **`PARK_STANCE_AWAIT_ORGANIC`** on 2026-09-20.

This closes **goal gate (1)** from the 2026-09-20 13:22 ET operator close brief
(organic exit 0 **or** explicit stance park token). It does **not** invent an organic hold
and does **not** claim Monday OBSERVED.

**2026-09-20T20:11 ET verify:** Sunday hand `screener_go_alerts --send --session 2026-09-18`
stamped real `source=check_investment_send` rows. That satisfies the *mechanical* reporter
(source+caller only) but **not** maturity/organic OBSERVED — AGENTS.md §8: a proof staged
by hand does not satisfy a claim that something happens on schedule. Cron expression remains
`*/15 9-16 * * 1-5` (Mon–Fri). Awaiting natural Mon–Fri unattended hold.

## Still true in the wild

| surface | value `[VERIFIED]` 2026-09-20T20:12 ET |
|---|---|
| Mechanical reporter | organic=**4** · non_organic=2 · exit_would_be=0 (source+caller match) |
| Maturity organic | **NOT OBSERVED** — holds from hand `--session 2026-09-18` replay |
| Holds path | `~/.local/state/tradeai/cio_telegram_stance_holds.jsonl` |
| Producer last_run | `session=2026-09-18` `mode=send` `ran_at=2026-09-21T00:09:53Z` |
| Observe-early timer | Mon 2026-09-21 **06:35** ET → `tradeai-stance-organic-observe.service` |
| Observe timer | Mon 2026-09-21 **09:05** ET → same service |

## What closes the park to OBSERVED

A **natural Mon–Fri unattended** producer hold with `source=check_investment_send` (GO / scalp / proposal)
**without** a hand `--session` backdate, then `python3 scripts/report_organic_stance_hold.py` exit **0**.
No canary invent. Mechanical exit 0 alone is not enough if provenance is a staged replay.
