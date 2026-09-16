# Trade-AI work log — 2026-09-16

```
Date:          2026-09-16 (Wednesday)
Operator ask:  "fix SearXNG and wire up as free first ... only stuff that needs to be paid for is escalated to
               Brave"; then "thoroughly design and plan the free first, how it should work, the curation and the
               rating of the actual stuff that is found ... this needs to be a mature undertaking ... with
               fallbacks"; then "commit everything live and push live"; then "update all of the documentation".
Live at:       a91d7b3ba (PR #1045), stamped 2026-09-16 08:46 ET — origin/main = release CURRENT = dev tree
Rails:         MBI_BEHAVIOR=0. No broker writes, no orders, no stops, no 2FA changes. Advisory only.
```

This log continues `TRADE_AI_WORKLOG_2026-09-15.md`. The 2026-09-14 As-Is / Future-State set and fact bases
remain the measured record of 2026-09-14; where they describe research and web search, read this log for what
changed.

## 1. What shipped (merged, deployed, verified)

| PR | Merged (ET) | Merge | What it fixed | How it was verified |
|---|---|---|---|---|
| #1039 | — | `9d5741e78` | Material-change notice enrichment: position, P/L, stance, sector, strategy, thesis | live notice |
| #1041 | — | `c0fbf0a6f` | Maturity board showed 1 agent, not 15 — per-agent evidence bound | board shows 15 |
| #1042 | — | `e8e5830ee` | Trigger producer dropped its cursor when capacity forced a drop | cursor held on drop |
| #1043 | — | `978ebca65` | Agent lease path: `JobRequest` carries `intake_id`, `payload`, `source_timestamp` | 8 leased, 8 acked |
| #1044 | — | `c2630db26` | Staleness windows exceeded the lease interval; per-agent `stale_input_seconds` | REFUSED_STALE 0 |
| **#1045** | **01:44** | **`a91d7b3ba`** | **Free search answers a `CALLER_DAILY_CAP` refusal** (below) | **live 12:45:01Z: `free_answered: 2`** |

## 2. The measurement that drove #1045

A Brave billing alert (3,000 requests / $15.00 for September) started as a cost investigation and ended as a
**refusal** finding. The arithmetic ruled out a subscription fee immediately: 3,000 × $5/1000 = exactly $15.00,
so it was real per-request usage.

Measured on the live ledger, `persistent-state/data/runtime/search_budget.json`:

| | |
|---|---|
| denial receipts | **129** — 15 on 09-13, 70 on 09-14, 44 on 09-15 |
| distinct callers | **1** — `governed_research_producer` |
| distinct reasons | **1** — `CALLER_DAILY_CAP` |
| `spilled_to` | **null on every one** — refused, then asked of nobody |
| Brave month | **85% unspent** (228 of 1,500) |
| SearXNG allowance | **10,000/day**, container up, idle |
| `searxng` daily counters | **`{}`** — not one free search in the ledger's history |

Cron shape: hourly at `:45` with `--limit 5` = ~120 asks/day against a 25/day caller cap → **~95 questions a
day died at the gate.** We were not spending too freely; we were refusing work while free capacity idled.

**`CALLER_DAILY_CAP` is deliberately not in `web_search.spill_on`** (operator decision 2026-09-13): a per-caller
cap is fairness *between callers*, not a provider quota. That decision was not re-litigated. The refusal still
stands — what changed is that the refused question is now asked somewhere free.

## 3. What was built

| Component | Behaviour |
|---|---|
| `scripts/lib/free_search.py` *(new)* | Governed SearXNG. **One ledger unit per HTTP request, taken BEFORE the request** (a check separate from the spend lets two crons both see an under-limit counter and both call). A request that never happened is **refunded**. `news`→`general` is a **second** request costing a **second** unit — the paid path's known defect is web+news billing twice against one reserved unit, and that is not reproduced. Fails closed. |
| `governed_research_producer` | Consults it **only** on `CALLER_DAILY_CAP`, **only** behind `RESEARCH_FREE_FALLBACK=1`. |
| `search_budget.mark_spilled` *(new)* | The receipt is written at the moment of refusal, before the answer is known. Once a lane **has** answered, `spilled_to` must say so — otherwise the monitor counts answered questions as lost. Never overwrites an existing answer. |
| `search_budget.caller_daily_cap(caller, provider)` | Provider-aware. Without it the fallback is self-defeating: a cap of 25 sized to ration **money** would refuse a 10,000/day free provider after the 25th question, reproducing the very refusal the free path exists to answer. |
| `check_gap_resolution` | New finding `REFUSED_NOWHERE` — refusals today that no lane answered. 129 of them existed and nobody was ever told. |
| `gap_resolver` | `RouterResponse` has no `spilled_to`; only the *receipt* does. The old `getattr(resp, "spilled_to", None)` was `None` on **every** response, so a spilled answer was filed as `brave`. Fixed to `resp.provider`. |

**Explicitly not a spill adapter.** `test_brave_router_spill.py` injects the spill seam and asserts exactly one
call *plus a denial receipt*; a free hit produces no denial, and a free hit that caches produces no receipt at
all. A prototype that borrowed that seam broke 9 of those tests — correctly. It is preserved unpushed on
`feat/search-free-first-searxng-primary` (`5a29bd3ac`) for its lessons, not as a foundation.

## 4. Validation — what was actually proven

```
08:07  deploy      a91d7b3ba-main-exact-phase2-20260916-080726; main = release = dev tree
08:11  arm         RESEARCH_FREE_FALLBACK=1 on the one producer cron line (1031 lines, 1 flag line)
08:45  live run    source_sha a91d7b3ba
```

| Signal | Value |
|---|---|
| `free_answered` | **2** |
| `searxng daily` | **`{'2026-09-16': 2}`** — first non-zero in the ledger's history |
| `searxng caller_daily` | **`{'governed_research_producer': 2}`** — a caller other than `_spill` |
| Brave today | **25/25** — hit the cap exactly |
| denials today | **2**, both amended to `spilled_to: searxng` |
| `failed` / `errors` / `budget_denied` | 0 / `[]` / 0 |

`budget_denied: 0` is the designed outcome, not an absence of refusals: the refusals happened and the rescue
worked. Predicted shape before the run — 3 paid (22→25), 2 refused, 2 answered free — matched exactly.

Pre-deploy gates: 480 passed / 2 xfailed across all 28 suites touching the changed modules; CI 6/6 (including
`cio-hardening` twice at ~13 min); dark contracts 0 new; data-source authority 0 findings; lane registry clean.

## 5. Traps found today (each cost a cycle)

- **Registering a test edits a governed control surface.** `check_test_coverage.py` fails any unlisted new test,
  so a new test must be added to `run_cio_hardening_ci.py` — but that file is one of the 31 paths in
  `config/sop_120_control_surface.manifest.json`, so the edit shifts `control_surface_digest` and
  `agent_governance_sop` fails with four digest mismatches. **Run `regenerate_generated_files.sh` AFTER the
  runner edit**, not before. Controls: clean dev tree 97 passed, clean worktree 7 passed — it was not an artifact.
- **`ai_local_acceptance.sh` and `run_cio_hardening_ci.py` exit 0 while printing failure.** Observed twice
  (`CIO GATES FAILED: cio_hardening`, `CIO HARDENING CI FAILED: [...]`), both with rc=0. Grep the output; never
  trust the return code.
- **`crontab <file>` failed with a mangled path while reporting nothing useful; `crontab - < file` worked.** The
  first arming attempt printed "installed" but the live crontab had **0** flag lines. Only the post-install
  verification caught it. Always re-read the live crontab after installing.

## 6. Not done — this is P1 of 8

The approved free-first plan has eight phases. Shipped: **P1** only.

| Phase | What |
|---|---|
| P2 | `free_search` becomes a first-class `cost_class: free` vector in `gap_resolver`; registry `on_gap` chains |
| P3 | Rating model — channel aggregation, **publisher-domain independence** (today a Brave hit and a SearXNG hit on the *same article* count as two independent sources and earn a cross-check bonus), `rate_item` authority tiers, `free_web.thin` |
| P4 | `research_escalation_policy.json` — per-question-type bars, max laps, paid channels, per-question paid budget |
| P5 | Receipted paid-escalation grant with expiry, enforced in CI like `UNAPPROVED_SOURCE` |
| P6 | M3/M4 maturity — critic agreement, falsifier, scheduled check-in |
| P7 | Transport-level cap enforcement (today ~78 of 84 LLM lanes run with the global cap unset) |
| P8 | Converge the five bespoke SearXNG clients onto the shared client and the ledger |

**The grader stays free.** Deterministic scoring every lap, then a free OAuth critic, and DeepSeek Flash only
rarely — a Flash analyzer call (~$0.0025) is **half the price of a Brave search** (~$0.005), so paying to decide
whether to pay is justified only when the downstream spend is materially larger.

## Identity

```
Stamped:        2026-09-16 08:46 ET
origin/main:    a91d7b3ba
release CURRENT:a91d7b3ba-main-exact-phase2-20260916-080726
dev tree:       a91d7b3ba
Armed:          RESEARCH_FREE_FALLBACK=1 (1 crontab line); verified in the live crontab
Open:           Brave dashboard grouped by key/endpoint after rotation (operator); ARKX filled stop review;
                fancontrol; inotify limit; UPS/DC supply
```
