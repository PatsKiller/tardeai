# Command Center Home — the "Do now" layout (2026-10-22)

```
Status:      DRAFT (branch feat/home-do-now-20261022; not merged, not served)
as_of:       2026-10-22T16:30:00-04:00
Measured at: b9804fa57 (origin/main at branch point); not measured on the live server (fixtures only)
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Tests:       tests/test_home_do_now_20261022.py (gate home_do_now_20261022);
             apps/command-center-v3/src/lib/homeDoNow.test.ts (in npm run build);
             apps/command-center-v3/e2e/home-do-now.spec.ts (fixtures, no production calls)
```

The operator approved the gate-3 Home mockup (`Home.dc.html`). This change builds it. The Home page now answers
"what do I do now?" in one list. Five boxes that each held part of that list are replaced.

## What changed on the page

| Before | Now |
|---|---|
| Header with tiles, "More metrics" expander, P/L-by-account table with seven periods | Slim header: portfolio, today, YTD, market (regime, VIX, lagging sectors), a positions age badge (STALE when old) and a **Refresh positions** link to Portfolio, where the manual broker sync is started. Home itself never calls a broker. |
| Needs action, Requires attention, Operator inbox, Top risks, Platform health (five boxes) | **One "Do now" queue.** Tabs: All, Protect money, Decide, Fix system. The top 7 show, with **Show all N** for the rest. Each row has one action button. Rows are sorted by money at risk first, then by severity. |
| Book treemap | **What moved your book today**: a bar list of the largest dollar moves, plus a "rest of the book" line, so the rows always add up to today's change in the header. |
| Risk gauges, alert rail | **Three numbers**: unprotected positions, portfolio heat (limit 5%), cash. |
| Accounts table with seven periods | **Accounts**: value, 1D, YTD. The full table is one click away (Full returns). |
| Movers board, news grid, AI briefing, agents, Hermes, release train card, all expanded | Cards: **Best opportunities**, **Market in one look**, **System pulse**. Collapsed drawers: **AI briefing**, **Release train** (the closed drawer has a **STOP releases…** button that opens the STOP control), **Agents and Hermes**, **News and market movers**. A drawer loads its data only when it is opened. |

The previous Home is still reachable at **`/v3/?view=classic`** through the **Classic view** link in the header. The
classic page has a link back. It is kept for one release.

Every number has a tooltip. The tooltip names the number's source and its basis, for example "≈ = market change
excluding transfers", "no stop on record (risk snapshot); working-stop coverage not measured", or "holdings.json via
/api/v2/overview; positions_current is not yet approved for Home".

## The queue — `GET /api/v2/home/do-now` (`HomeDoNow@v1`)

`scripts/lib/data_broker/home_do_now.py` is a registered data-broker projection (`home_do_now` in
`scripts/lib/data_broker/catalog.py`; AGENTS.md §24.3, §26.3). It is cached for 60 s in `api_v2._home_do_now`. It adds
no store and no writer. It reads sources that already exist:

| Source | Read through | What it adds |
|---|---|---|
| `needs_action` | `api_v2._needs_action` (NeedsAction@v1, 30 s cache) | system, data and approval items. Approvals go to **Decide**. A risk-protection or kill-switch health finding goes to **Protect money**. Everything else goes to **Fix system**. Data sources, pipelines, PR hygiene and approvals each roll up into one row per severity. |
| `inbox` | `api_v2._inbox` | stop alerts (merged per symbol), plus one row each for SIEM events, agent escalations, CIO review and auto-research briefs. When a count equals the inbox's SQL limit it is shown as a floor, for example "40+". |
| `risk` | `data_broker.risk_snapshot.get_risk_snapshot(max_age_s=120)` | stops that have triggered (P0), stops within 2% of price (P2), positions with no stop, portfolio heat. |
| `desk_truth` | `needs_action.probe_desk_truth` (the `held-exit-coverage-monitor` lane receipt) | which positions have no **working** stop at the broker |
| `proposals` | `home_do_now.probe_pending_proposals` (`SELECT COUNT(*) … WHERE status = 'PENDING'`) | the number of pending paper proposals, the oldest one's age, and the newest symbols |
| `deploy` | `api_v2._deploy_events({"status": "open", "days": "14"})` | open post-sale redeploy decisions |

**One row per fact.** Every row has an `id`, and rows with the same `id` merge into one, whichever source they come
from. For example, SPCX with no stop in the risk snapshot, an inbox stop alert for SPCX and a desk-truth "no working
stop" finding for SPCX all have the id `stop:SPCX`. They become one row. That row keeps the most severe severity and
the largest dollar amount, and lists every source. The proposal count and the inbox's proposal rows merge into
`proposals:pending`. The page footer shows how many source items were merged.

**Where working-stop truth comes from.** When the held-exit-coverage receipt is measured, it is the only source for
"no stop" rows. Measured means the run succeeded, it is less than 26 h old, and its verdict is COVERED or GAPS.
Otherwise the rows come from the risk snapshot's "no stop on record", and the row text says coverage was not
measured. The projection deliberately does not use the `/api/v2/risk` broker-stop overlay
(`open_trades_intelligence._broker_protective_stops`), so it never causes a broker read.

**Sort order.** First, rows with money at risk, largest first. The money basis is stated on each row: the market
value with no stop, the loss if the stop fills, or the position value for a triggered stop. Then come the other rows,
ordered by severity P0 to P3, then by category (protect, then decide, then fix).

**Freshness is honest.** Each source reports `status`, `as_of`, `as_of_basis`, `age_s` and `stale`. The basis is one
of `payload.as_of`, `risk_snapshot.computed_at`, `receipt.ok_at`, or `read_at` (a live database read with no clock of
its own). Any of three failures turns the source into one P2 **Fix system** row, "Do-now source X unavailable", and
sets `all_sources_answered` to false:

- the probe raises an error;
- the probe times out (8 s shared deadline);
- the probe answers in a malformed shape.

The page says "Nothing to do" only when every source answered. A failed fetch, a missing payload or a PARTIAL answer
shows UNAVAILABLE or STALE. It is never shown as an all-clear.

## Positions and cash — the current source, labelled

Home's positions, cash, movers and header still read `holdings.json`, through `/api/v2/overview` and the risk
snapshot. `positions_current`, the broker-synced store, is not read. Reader batch #1 is the Watch held flag, and no
approved reader batch covers Home (`config/data_source_authority.json`, `positions_store.approved_readers`). The PR
proposes Home as reader batch #3. That decision is the operator's (§7A, §17). This branch does not approve it.

## Verify

```bash
.venv/bin/python -m pytest -q tests/test_home_do_now_20261022.py
cd apps/command-center-v3 && npm run build        # runs lib/homeDoNow.test.ts
npm run preview -- --port 4391 &
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4391 npx playwright test e2e/home-do-now.spec.ts
```

Measured on this branch on 2026-10-22: backend 27 passed; `homeDoNow` 31 passed; `npm run build` exit 0
(design-guard and ui-standards pass); e2e 4 passed.

`check_data_source_authority.py` exits 1 both on this branch and on origin/main `b9804fa57`. The output is
byte-identical. The cause is an `UNAPPROVED_READER` finding: `scripts/desk_truth_monitor.py` reads
`positions_current`, which came in with PR #1927. It is not from this change.

## Open

- Operator: approve or decline Home as positions reader batch #3 (the PR body has the proposal).
- Operator: remove the Classic view after one release.
- The live payload was not sampled. The server was OOM-killed twice on 2026-10-22, so the shapes were taken from code
  and from captured fixtures. The first served request should be checked against the e2e fixture.
