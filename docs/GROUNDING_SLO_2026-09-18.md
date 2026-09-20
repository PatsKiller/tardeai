# Agent number-grounding SLO — 2026-09-18 breach and closure

```
Status: CLOSED (live SLO PASS)
as_of: 2026-09-19T20:34:54-04:00
Measured at: dev tree 170532178 (= origin/main after #1095), live trade_ai DB, 7-day window
Authority: READ_ONLY_ADVISORY — operator ratifies floors; agent does not loosen enforce
Canonical: docs/GROUNDING_SLO_2026-09-18.md
Config: config/agent_number_grounding_slo.json (AgentNumberGroundingSLO@v1, status PROPOSED)
```

## The 2026-09-18 breach

The 7-day Grounding SLO failed with a **0.22 soft_unsupported token share** against the
**0.15** floor. `risk_agent` carried **172 of 219** total breaches (0.913 soft share),
emitting uncited numeric metrics — stop losses, VaR, position sizes and R:R multiples —
that no supplied passage backed.

Two distinct defects produced that number:

1. **Real ungrounded output.** `risk_agent` stated R/ATR multiples that were never placed
   in its supplied context, so the checker could not match them to a source passage.
2. **Report double-count.** `summarize()` tallied verdicts into the same `Counter` keyspace
   as its own `soft_unsupported` metric, so a row whose verdict *was* `soft_unsupported`
   incremented the metric twice. Bare 0–1 decimals (`0.85`, `0.95`) — stated confidence
   scores, not market facts — were also counted as unsupported figures.

## Remediation as landed

| # | Change | PR | Evidence |
|---|---|---|---|
| 1 | Put allowed R/ATR multiples into `risk_agent` supplied context so the checker can ground them | #1078 | `scripts/process_watchlist_agent_jobs.py:865` |
| 2 | Prefix verdict tallies `v:<verdict>`; separate `soft_flag` metric; exempt confidence-shaped tokens; track legacy rows as `stale_grounded_residual` rather than inflating soft share | #1087 | `scripts/report_agent_number_grounding.py` `_confidence_shaped_token()` |

**Pre-emit completion gate (already wired, not new work).** `apply_number_grounding()` is
imported at `scripts/process_watchlist_agent_jobs.py:45` and runs at line 3075 — *before*
emission. Any answer carrying unverified figures is demoted to `RESEARCH_MORE`
(line 3077 logs the demotion and the offending tokens) and the full receipt is persisted
to `full_result.number_grounding` at line 3118. There is no emission path that skips it.

## Verification (Stage 1 acceptance)

```
$ python3 scripts/report_agent_number_grounding.py --days 7 --json --check-slo
```

```json
{
  "schema": "AgentNumberGroundingSLOEval@v1",
  "results": 998,
  "min_results_for_slo": 20,
  "ungrounded_share": 0.0,
  "soft_unsupported_share": 0.003,
  "breaches": [],
  "verdict": "PASS",
  "ok": true
}
```

Per agent, 7-day window:

| agent | results | soft | soft share | ungrounded | stale_grounded_residual |
|---|---|---|---|---|---|
| maria | 651 | 2 | 0.003 | 0 | 23 |
| risk_agent | 173 | 1 | 0.006 | 0 | 157 |
| steph | 155 | 0 | 0.000 | 0 | 26 |
| tax_agent | 19 | 0 | 0.000 | 0 | 9 |

**`risk_agent` moved from 0.913 soft share to 0.006** — below the 0.15 floor, and below
the 0.05 ungrounded floor at 0.0. Overall share 0.003 vs the 0.15 floor. `breaches: []`.

## Honesty note on `stale_grounded_residual`

`risk_agent` still shows **157** residual rows: historical results written with
`verdict=grounded` that nonetheless listed unsupported tokens. They are reported
separately and deliberately **not** counted toward the soft share, because the
figures were unsupported under the old checker but the rows predate the current gate.
They age out of the 7-day window on their own. This is a reporting decision, not a
suppression: the count stays visible in every run so the residual cannot go dark.

## Standing risk

`slo_status` is **PROPOSED**, not ratified. The floors in
`config/agent_number_grounding_slo.json` are advisory until the operator ratifies them.
The SLO exits 0 and reports UNKNOWN when results fall below `min_results_for_slo` (20) —
it does not invent green on thin windows.
