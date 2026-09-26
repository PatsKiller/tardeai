---
cursor:
  subagentId: "bc-fd0624ff-5b0e-5c99-b0a9-5857e65a9274"
---

# Hermes backlog vs SentinelOne (S) — 2026-09-23

```
Status: ACTIVE
as_of: 2026-09-23T08:49:00-04:00
Measured at: GOOD_PERSISTENT_ROOT data/cio (hub-linked) + GET :7777 Hermes APIs +
             systemctl --user Hermes timers
Authority: AGENTS.md §4 evidence tags · operator Telegram/Maria claim ~08:26 ET
See also: docs/audit-s-sentinelone-memory-vs-research-20260923.md
```

## Verdict (one line)

Maria’s “500 deep → S queued, not analyzed” is **wrong for S**: CIO Hermes already **completed** `res_c3a661c21740`; “500” is the research-backlog API **page ceiling**, not S waiting in line.

## 1 · Is “500 deep” true?

| Surface | Path / call | Count `[VERIFIED]` | Notes |
|---|---|---|---|
| Hermes research backlog API | `GET /api/v2/hermes/research-backlog?status=active` | **`total: 500`** | Code hard-caps `LIMIT 500`; `total = len(items)` — ceiling, not full-table depth |
| Same payload composition | (those 500 rows) | **2 staged · 498 rejected** | Almost none are drainable work |
| Staged-only | `?status=staged` | **2** | True open librarian backlog is tiny |
| S in research_backlog items | same API | **0** | S is not in that 500 |
| CIO Hermes projection | `…/data/cio/hermes_research_projection.json` | **queued 1 · completed 666 · failed 731** | Open CIO queue ≈ 1 (NOC), not 500 |
| CIO request ledger (latest/id) | `…/hermes_research_requests.jsonl` | **queued ~20–21** (stale ages) | Not 500; S not among them |
| CIO gap requests | `…/cio_operator_gap_requests.jsonl` | **11 lines** | Includes `opr_ab7192d3b009` |
| Pending replies ledger | `…/cio_operator_pending_replies.jsonl` | **no S / no `opr_ab7192d3b009`** | mtime still 2026-09-22 |
| Hermes intelligence for S | `GET …/self-learning/drilldown?symbol=S` | **total 0** | Hub table empty for S |
| Symbol journey | `GET …/hermes/symbol-journey?symbol=S` | **`research_rows_30d: 0`**, `research_generated: []` | Matches “0 recent findings” on Hub |

**Answer:** the literal “500” appears on the Hub backlog API because of `LIMIT 500` in `scripts/api_v2.py` (`_hermes_research_backlog`). It is **not** “500 S jobs ahead of you,” and it is **not** the CIO desk Hermes queue depth.

## 2 · Where is S (`res_c3a661c21740` / `opr_ab7192d3b009`)?

| Id | Store | Status |
|---|---|---|
| `opr_ab7192d3b009` | `cio_operator_gap_requests.jsonl` | Present (desk chat `6993102664`, ts `2026-09-23T11:44:46Z`); gaps **76/77** (missing promoted research + stale quote). Forced Hermes link at `11:44:59Z`. **Not** in `cio_operator_pending_replies.jsonl`. |
| `res_c3a661c21740` | requests + projection | **`completed`** — trail: REQUESTED → CLAIMED → COMPLETED → LOOP_COMPLETED → WORKER_JOB (≈11:44–11:47Z) |
| `rr_abb8acb2f962` | `hermes_research_results.jsonl` | **`completed`** `2026-09-23T11:46:01Z`, `governed_bridge` / `deepseek-flash`, **7 findings**, classification **`INSUFFICIENT_DATA`**, stance WATCH |
| Maria / OpenClaw (~08:24 ET) | no new `res_*` | Watch directive **1278** (`hermes_enabled`) only — **no** enqueue timed to that session |

**Answer:** S’s CIO desk research is **done**, not pending/failed/missing. Maria’s “queued” referred to a different surface (Hub backlog / directive flag), not this `res_*`.

## 3 · Why it *looks* backlogged (root causes)

1. **Two Hermes products, one word** — Hub/Maria read `hermes_research_intelligence` (0 rows for S). Desk writes `hermes_research_results.jsonl` (completed, not promoted). Same morning: desk finished ~07:46 ET; Maria at ~08:26 still said “0 findings.”
2. **API ceiling misread as queue depth** — `research-backlog` returns `total: 500` at the SQL `LIMIT`; of those, 498 are already `rejected`. Not a FIFO of 500 waiting analyses for S.
3. **OpenClaw does not open a desk Hermes job** — adding S to the watchlist with `hermes_enabled` does not mint `opr_`/`res_` or join the completed desk packet; so “queued” was aspirational, not measured.

Historical CIO failure mix (projection, all symbols — context only, **not** why S waits today): **COST_CAP 346 · EXEC_LANGUAGE 274 · CIRCUIT_OPEN 40 · PROVIDER_ERROR 29** of 731 failed. Worker timer is active; bridge is running; last 24h CIO queue health showed **11 completed · 0 failed · 1 queued**.

## 4 · ETA / what unblocks S specifically

| Need | State | Unblock |
|---|---|---|
| Desk Hermes packet for S | **Already complete** (`rr_abb8acb2f962`) | No queue drain required for today’s desk ask |
| Hub / Maria “findings” > 0 | Intelligence table still **0** for S | Promote/join desk results into Hub intelligence **or** teach Maria to read CIO `hermes_research_results` / desk Sources — **propose only** (no grant invented) |
| Directional / non-INSUFFICIENT thesis | Gaps: no promoted research, stale quote, null analyst, empty catalysts | Fill house facts (quote refresh, analyst, catalysts); another Hermes run alone re-states thin evidence |
| Librarian overnight loop | Timer next ~03:45 ET | Does not place S in the 500-cap backlog list as measured |

**Next step (operator-safe):** treat S as **analyzed-thin**, not **queued**. For Telegram/Maria honesty: cite `res_c3a661c21740` / `INSUFFICIENT_DATA` or say Hub has no promoted row — do not claim a 500-deep wait.

## 5 · Was Maria accurate?

| Claim | Vs Hub | Vs CIO desk |
|---|---|---|
| “0 recent findings” | **Accurate** (`research_rows_30d: 0`) | **Stale/wrong** — 7 findings completed ~40 min earlier |
| “backlog is 500 deep” | **Misleading** — API page ceiling | **False** — CIO open queue ≈ 1 |
| “so it’s queued, not analyzed” | Wrong for S | **False** — `res_c3a661c21740` **completed** |

Maria was reading the **Hermes Hub / intelligence** surface; the CIO desk enqueue the operator already triggered was a different product and was already done.
