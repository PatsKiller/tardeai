# Command Center v3 site validation: 2026-10-22/23 (f7c1e96cb → 0f5bf2453 → 53aa1b619)

```
Status:      ACTIVE
as_of:       2026-10-23T11:00-04:00
Measured at: served f7c1e96cb (2026-10-22 22:05 ET → 2026-10-23 08:53 ET), 0f5bf2453 (08:53 → 09:41 ET),
             53aa1b619 (09:41 ET →). Repo origin/main 53aa1b619. Build identity from /v3/build-meta.json git_sha.
```

The operator asked on 2026-10-22 at about 22:15 ET: "use playwright overnight to go through all of the pages on the site and validate everything."
On 2026-10-23 they added: "P1 and P2 you can fix automatically. P3 you'll provide me markups. Bugs, fix."

This document is the report. Artifacts (screenshots, per-view JSON, HTML summaries, P3 mockups) are in
`~/.cache/rtc/site-crawl/` on ms01-openclaw. Start at `index.html` there.

## 1. Summary

- **About 290 distinct views** were checked per build: 55 routes, every tab-like control on them, the query-param views
  (`?tab=`, `?view=classic`, `?otab=`) and 24 legacy and redirect links. Each was checked at 1440 px and 412 px.
  That is 381 / 529 / 578 view-captures for f7c1e96cb / 0f5bf2453 / 53aa1b619.
- **11 PRs** were opened for P1, P2 and bugs, plus this report's PR. None is merged. Details in §5.
- **P3**: five visual mockups plus two text items. See `mockups/P3_MOCKUPS.html` in the artifacts dir, and §4.3.
- **The site is mostly sound on layout.** No horizontal overflow was found at 412 px on any page. The defects are crashes on
  error payloads, wrong numbers, and misleading labels or badges.
- **The server is the dominant problem.** portfolio-server was SIGKILLed at its memory limit 75 times on 2026-10-22 between 00:46 and
  21:00 ET, before this crawl began at 22:05. It was killed 5 more times on 2026-10-23 after release 7 (09:14–10:24 ET). §6 covers this,
  including where **this crawl contributed**.

## 2. Method and safety

**Read-only by construction** `[VERIFIED]`. Playwright (`~/.cache/rtc/site-crawl/tools/crawl.mjs`) routes every request through
`context.route('**/*')`.

- Any **non-GET is aborted** and logged. Across all runs the pages *attempted* exactly three POSTs, all aborted:
  - `POST /api/v2/broker-proposals/detail` ×95, a lazy-loaded card-gate read;
  - `POST /api/v2/entry-desk/technical-grades` ×27, a batch grade read;
  - `POST /api/v2/journal/tagging-queue/auto-enrich` ×5, a once-per-session enrich on opening Tagging Queue.

  These are counts from the `attempts` arrays in each run's `results.json`.
- A GET matching reauth-url, exchange-code, 2FA, TOTP, passkey, place-order or grant-issue patterns is aborted. None occurred.
- Only **tab-like controls** were clicked: `[role=tab]`, `.hub-tabs button`, or the `hubTab()` inline style. They were also checked
  against a text denylist (STOP, Pause, Engage, Resume, Arm, Clear, Add, Remove, Revoke, grant, Propose, Approve, Reject, Submit,
  Order, Cancel, Modify, Ask, Set alert, Protect, Refresh, Sync, passkey/TOTP, export/download, …).
  - An audit of every clicked label found 139 distinct labels. **One** matched the final denylist: "Export CSV" on Portfolio, which
    the first desktop pass clicked before "export" was added. It is a client-side download (`PortfolioDeskHealth.tsx`, "client-side;
    no broker write"), and no request was made.
  - "Alert settings" on Reports opened an overlay. Later tab clicks on that page timed out and are graded as notes.
- **Auth**: the loopback service listener, the same path the live e2e suite (`e2e-live/`) uses. `cc_auth` is `report_only`, so
  token-less GETs are answered and logged as `would_deny` in `~/.local/state/tradeai/cc_auth_decisions.jsonl`. No token or credential
  was read or printed. Ops → Controls state answered **403** to this path. That is by design: the surface requires the operator's
  tailnet identity.
- **Load**: one API request in flight at a time, 1.0–2.0 s apart, with an in-memory GET cache keyed without `_=` cache-busters.
  Heavy endpoints were skipped. Later runs added a cgroup memory guard (pause above 1.1–1.4 GB) and an abort if the server PID changed.
- **Replay** passes ("replay" in the HTML) cover views the live crawl could not safely reach. The exact build is served by
  `vite preview` (a git worktree at the served SHA), and every `/api/**` is answered from JSON captured by the live passes. **No request
  reaches portfolio-server.**
  - Replay validates routing, rendering, JS errors and layout, plus data checks where the capture exists.
  - An endpoint with no capture gets `{ok:true,data:{}}`. A crash under that fake payload is **not** claimed as a live bug unless the same
    crash follows from a real payload shape. §4.1 states the shape for each crash claimed.

Per-view checks: full-page and top screenshots; console errors; page exceptions; failed or slow (>3 s) requests with status and ms;
overflow at 412 px; rendered `NaN` / `undefined` / `null` / `[object Object]` / `Invalid Date`; negative counts;
UNAVAILABLE/STALE/ERROR badges with context; empty states; tooltips on headline numbers; redirects. The header was cross-checked
against `/api/v2/overview` from the same page load.

## 3. Results per served SHA

| served SHA | views (desktop / phone) | desktop PASS / WARN / FAIL / SKIP / PARTIAL | phone PASS / WARN / FAIL / SKIP / PARTIAL | sources |
|---|---|---|---|---|
| f7c1e96cb | 270 / 111 | 68 / 6 / 1 / 21 / 174 | 84 / 6 / 3 / 17 / 1 | all live |
| 0f5bf2453 | 260 / 269 | 215 / 15 / 6 / 24 / 0 | 235 / 2 / 5 / 27 / 0 | desktop 189 live + 71 replay; phone replay |
| 53aa1b619 | 289 / 289 | 241 / 15 / 11 / 22 / 0 | 246 / 10 / 11 / 22 / 0 | 25 live (changed pages + Home); rest replay |

- **PARTIAL** (f7c1e96cb): views captured after the crawl's own memory guard began holding requests (02:50 UTC). Their data is
  partial. Only JS errors and layout were graded.
- **SKIP**: the Health → Log tab (skipped on purpose; heavy endpoint), and tab controls belonging to a different tab state.
- **Diff between builds.** The FAIL and WARN sets are the same defects throughout. More of them were *detected* on later builds because
  coverage and replay improved. They are not regressions.
  - 0f5bf2453 adds the replay-found crashes (CIO Decisions, Health Ops Command, System Hermes).
  - 53aa1b619 adds the Schwab monitor `$NaN` (found by replaying the legacy `?tab=Schwab Accounts` link) and the Ops Controls 403
    (a new surface; by design).
  - Release 7 (0f5bf2453) did not change any finding, and batch 7 (53aa1b619) did not either.

**Header cross-check** `[VERIFIED]` (f7c1e96cb, /v3/, 2026-10-22 ~22:06 ET): PORTFOLIO $1,260,231 = `overview.portfolio_value`
1260231.3; TODAY −$10,836 −0.85% = `today_change` −10835.83 / `today_pct` −0.85; TRADING 47.9% · 238 = `journal.win_rate` /
`trade_count`; REALIZED $140,065 = `journal.realized_pnl` 140064.57.

## 4. Issues (prioritized)

### 4.1 P1: broken page or wrong number

| # | Page | Finding | Evidence | Status |
|---|---|---|---|---|
| 1 | Home | Drawer summary "AI briefing · [object Object]…" | `[VERIFIED]` live all 3 builds; `/api/v2/command` `llm_intelligence.portfolio_risk` = `{content, generated_at}` | **PR #1975** |
| 2 | every page | One failing endpoint triggered a **whole-page refetch every ~6 s** (ReconnectingBar → `signalApiRecover()` after 2 OK health probes; resets every hook's backoff). /v3/agents » Memory: 652 requests, 101 console errors in 150 s | `[VERIFIED]` vite preview, all API mocked, maturity/memory failing, 60 s: main **251** API requests → PR **11** | **PR #1984** |
| 3 | Strategy | Live R sign disagrees with P&L: reit_income −1.93R with 1/1 wins, +$298.86; pullback_macd_reversal +1.73R (rank ★2) with −$1,806 | `[VERIFIED]` `/api/v2/strategy-leaderboard` rows. Root cause `[CODE]`: `paper_trade_monitor.py` phantom-close keeps `r_multiple = COALESCE(r_multiple, …)`, the stale unrealized value | **PR #1987** flags it (amber ⚠ and tooltip). The writer is broker-execution code: not changed, see §7 |
| 4 | Health → Ops Command | Page crash (React #31). The "Auto fixed" chip falls back to `health.remediated`, an **array** of run records, whenever ops-autonomy lacks `auto_fixed_today` | `[VERIFIED]` replay of 0f5bf2453 with real `/api/v2/health` capture (12:54 UTC); `remediated` is a list | **PR #2007** |
| 5 | CIO → Decisions (+ Capital, Evidence) | Page crash. `/api/v3/cio/home` returns `{ok:false,error,detail}` on exception (`api_v3_cio.py`); UI read `home.cio_now.attention` | `[CODE]` error path; `[VERIFIED]` replay crash at 1440 and 412 | **PR #2009** |
| 6 | System → Hermes | Page crash. `wd.directives.slice` when `directive_count` is undefined (an `{ok:false}` payload or not loaded) | `[VERIFIED]` replay crash; branch replay PASS | **PR #2003** |
| 7 | Trading → Broker Orders → Schwab accounts | **AVG PRICE "$NaN" on every row** (26/26): API sends `avg_price`, UI read `avg_entry_price` | `[VERIFIED]` replay of 53aa1b619 with captured `/api/v2/schwab/accounts-live` | **PR #2014** |
| 8 | server | portfolio-server OOM-kill cycle (§6) | `[VERIFIED]` journal | server fix is #2012 (other session); UI load cuts are #1974 and #1984 |

### 4.2 P2: misleading or stale

| # | Page | Finding | Evidence | Status |
|---|---|---|---|---|
| 9 | Home | "Positions age unknown old · STALE" beside a FRESH envelope and the header's "positions observed 15:10". `Date.parse("2026-10-22 16:45:03 ET")` is NaN in Chromium | `[VERIFIED]` live, desktop and phone | **PR #1975** |
| 10 | Home | "What moved your book today" lists SPCX, SCHG, SCHD and V twice (`top_movers` is per account) | `[VERIFIED]` API rows | **PR #1975** |
| 11 | Home classic, Risk | "12 positions" (Home) vs "11 positions" (Risk) vs 32 rows (Portfolio). Different scopes, unlabelled; the server reports `position_counts.agree=false` | `[VERIFIED]` `observation.position_counts` | **PR #1975** (Home), **PR #1985** (Risk) |
| 12 | Risk → Recovery | SCHG twice with no account shown (Roth and Rollover); summary cut mid-number ("above original stop $3") | `[VERIFIED]` `/api/v2/recovery` items 15/16 | **PR #1985** |
| 13 | every page | 9.4 MB `ui/prefs` key fetched on every page and re-polled every 2 min by a component that renders only on /watch and /journal | `[VERIFIED]` 9,410,749 bytes | **PR #1974** |
| 14 | phone, 13 routes | Command bar says "Trade · Home" on /intelligence, /strategy, /agents, /hermes, /reports, … and /portfolio/re-entry | `[VERIFIED]` 412 px screenshot | **PR #1986** |
| 15 | System → Hermes | "dev profile exists: undefined" ×4; "Codex runtime enabled: false" shown in green | `[VERIFIED]` live f7c1e96cb | **PR #2003** |
| 16 | Journal → Tagging Queue | Unhandled rejection when the silent auto-enrich POST fails | `[VERIFIED]` live, every build | **PR #1998**; "view triggers a write" reported, not changed |
| 17 | Portfolio vs header | Portfolio total $1,259,648 / today −$10,514 vs header $1,260,231 / −$10,836 (two valuation clocks: holdings reprice vs overview snapshot). Home accounts table 1D −$10,818 is a third value | `[VERIFIED]` `/api/v2/portfolio/holdings` `total_value` 1259648.34 vs overview 1260231.3 | **Not fixed**: positions source-of-truth area (AGENTS.md "Positions … source of truth"); owner decision |
| 18 | Portfolio, Intelligence | "Rotation advisory UNAVAILABLE · account_stale": Schwab accounts carry a date-only `source_as_of` that becomes `2026-10-22T00:00:00+00:00` (20:00 ET the day before) while positions were observed that afternoon. `rotation/summary.portfolio_total` = 584,656 vs ~$1.26M | `[VERIFIED]` `/api/v2/rotation/summary` `publication` | **Not fixed**: publication safety gate; owner decision |
| 19 | slow endpoints | `watchlist/items?sort=hermes(&full=1)` 29–41 s (Entry Desk, Intelligence); `?symbols=` chunks 20–51 s (Re-Entry fires several); `/api/v3/advisory` 21–38 s, 3.8 MB; `scheduler-operations` 22.7 s; `coordination/migration-board` 27.7 s; `paper-proposals` 16.4 s; `active-trader/alerts?limit=300` 18.9 s; `data-sources/finviz/credential-health` 10–29 s on f7c1e96cb (cached in release 7, not re-measured live) | `[VERIFIED]` server time per request (queue time excluded) | **Not fixed here**: overlaps #2012 (advisory, watchlist/items) |
| 20 | Reports | 5 producers show **NEVER RUN**: Aegis Morning Brief, Weekly Portfolio Review (Sun 20:30), Monthly Portfolio Report, Enterprise Report Set, Live Automation Readiness | `[VERIFIED]` screenshot 0f5bf2453 | **Not fixed**: scheduled jobs (cron freeze); owner |
| 21 | stale feeds | `agents/summary` `feeds.agent_debate_log.as_of` 2026-05-05; `defense/posture` `would_have_fired.generated_at` 2026-07-18; `redeploy/book` `feeds.redeploy_analytics_cache.as_of` 2026-09-02; `maturity/learning` `disposition_outcomes.updated_at` 2026-08-20; `warrior-audit/latest` 2026-10-19 | `[VERIFIED]` captured JSON | **Not fixed**: producers; check that each page labels its age |
| 22 | Intelligence → Research | LLM brief prints "(INSUFFICIENT_DATA, v.null)", echoing a JSON `null` thesis version from `research_prompt_context.py` | `[VERIFIED]` live | **Not fixed**: research prompt contract |
| 23 | Active Trader | "Actionable (46)" while every row is VETO or UNKNOWN with 0/5 facts | `[VERIFIED]` screenshot f7c1e96cb | **Not fixed**: needs owner definition of "actionable" |
| 24 | Coordination → Release train | "History UNAVAILABLE · unknown freshness null" | replay | **Noted for the in-flight Releases/release-train owner** |

### 4.3 P3: cosmetic (mockups, no code change)

Mockups are in `mockups/P3_MOCKUPS.html` (self-contained). "Before" is the current build rendered with captured data; "after" is the
proposed CSS or text applied in the page.

1. **Header TRADING tile** is cut to "… · $…", hiding the journal P&L; the VIX source and price stamp are cut too. Let the value wrap,
   and drop the repeated "trades".
2. **Rotation advisory card**: a withheld advisory is the largest text on the page, with raw ISO timestamps in microseconds. Make it a
   one-line notice with reason chips and ET times.
3. **Active Trader KPI captions** are ellipsised (`.at-kpi span` nowrap). Let them wrap.
4. **Strategy leaderboard** shows raw identifiers (fib_retracement_bounce, maintain_current). Use human labels, with the identifier in
   the tooltip.
5. **Trading Opportunities tiles** count the scanner universe while the header counts the latest run. Name the population on the tile.
6. (Text) Legacy `?tab=Entry Desk` / Manual ToS / Broker Recon / Schwab Accounts / Broker+Proposals open the right desk but keep the
   retired name in the URL. Rewrite to the canonical URL, as `?tab=Scalp` already does.
7. (Text) Date-only `source_as_of` shown as UTC midnight. Display it as a date.

### 4.4 Checked and not a defect

- Control Plane (preview) pages print a literal `null` on purpose (`formatUnknown` / `renderField`, r22/r24 guard tests).
- Ops → Controls "UNAVAILABLE — forbidden" for the loopback caller is the designed answer without tailnet identity.
- The legacy and redirect links all route correctly: 13 route redirects, `?tab=Scalp/ATM Controls/Execution`, `/go/order/:id`,
  `/go/proposal/:id`, `/intelligence?tab=rotation`, `/cio?tab=cio-now`. Unknown routes render the shell without a crash.
- "⚠ NO STOP — risk undefined" (Entry Desk) is intentional prose (`lib/exitLadder.ts`).

## 5. PRs opened

All are off origin/main, pushed with the operator-relayed override (at most two pushes per branch), not merged, and CI-watched.

| PR | Area | What changed | Priority |
|---|---|---|---|
| #1974 | app shell | SharedIntelligenceBridge fetches its 5 prefs (one 9.4 MB) only on /watch and /journal (+ CI gate file) | P2 / server load |
| #1975 | Home | briefing `[object Object]`; ET-stamp parse (Positions STALE); one mover bar per symbol; classic count labelled "over $100" | P1 + P2 |
| #1984 | app shell | ReconnectingBar: global refetch only after a real outage; `lib/reconnectProbe.ts` + test | P1 |
| #1985 | Risk | "risk-tracked positions"; account on Recovery rows; word-safe summary clip (`lib/clipText.ts` + test) | P2 |
| #1986 | Navigation | phone command bar labels for off-rail routes (`lib/navLocate.ts` + test) | P2 |
| #1987 | Strategy | `/api/v2/strategy-leaderboard` `live.r_sign_conflicts` / `avg_r_suspect`; amber ⚠ on Live R (+ test, CI gate) | P1 (flag) |
| #1998 | Journal | Tagging Queue silent enrich `.catch` | bug |
| #2003 | System | Hermes panel crash on `{ok:false}`; yes/no/— instead of "undefined"; green only when true | P1 + P2 |
| #2007 | Health | Ops Command "Auto fixed" shows a count (React #31 crash) | P1 |
| #2009 | CIO | `/api/v3/cio/home` error payload → "Office home unavailable" (keeps the `home = data` alias for the payload-flow tracer) | P1 |
| #2014 | Trading | Schwab account monitor reads `avg_price`; missing numbers render "—" | P1 |

PR #1984 and PR #1975 hit an intermittent failure in `tests/test_guard_grant_finalize_20261021.py::test_crash_between_append_and_ledger_rewrite_recovers_without_duplicates`
(cio-hardening). It passes 3/3 locally, and the PRs touch nothing near it. The failed job was re-run once for each.

## 6. Server stability: OOM-kill cycle

`[VERIFIED]` `journalctl --user -u portfolio-server.service`: "Main process exited, code=killed, status=9/KILL" with 1.5–1.6 GB memory
peaks (MemoryHigh 1.5 G, MemoryMax 2 G). Kill times:

- 2026-10-22, before this crawl: **75 kills between 00:46 and 21:00 ET**, about every 10–24 minutes.
- During or after the crawl: 22:16:58 and 22:20:58 on 10-22; then 08:34:58, 09:14:58, 09:30:57, 09:56:58, 10:12:57 and 10:24:57 on 10-23.
- Kills land at second :53–:58 of the minute.

**Where this crawl contributed.** Be clear about this. PR #2012 measures `/api/v3/maturity/memory` at **+1,192 MB per call** and CIO
brain/observability at **+1.2 GB**. The crawl requested:

- `/api/v3/maturity/{memory,promotions,cases}` at about 22:15 ET; they were in flight 63–73 s when the 22:16:58 kill came.
- `/api/v2/hermes/{sources,outcome-bus/history,discovery-*}` before 22:20:58.
- `/api/v2/hermes/thresholds` before 08:34:58 and 09:14:58.
- `/api/v3/cio/observability` from about 09:28 until it timed out at 90 s. The guard then paused at 1,611 MB, 65 s before the
  09:30:57 kill.

The 75 kills on 10-22 before 21:00, and those at 09:56, 10:12 and 10:24 on 10-23, happened with no crawl running. After each kill the crawl stopped and
added the route family to its skip list. **Live crawling of :7777 stopped at 09:31 ET on 10-23**, except a 25-view smoke of 5 pages at
09:46–09:50 ET with hermes, maturity and CIO observability excluded. Everything after that is replay.

Recommendations (owner and operator):
1. Merge #2012 (server read bounds).
2. Merge #1974 and #1984 (UI-side load).
3. Adopt the candidate rule in backlog L53: agent UI validation targets replay or `vite preview`, never live :7777, during market hours.
   This crawl's experience supports it.
4. The :53–:58 second alignment suggests a minute-aligned trigger. Worth checking the crontab and timers against the kill seconds.

## 7. Not fixed, and why

- **Strategy Live R root cause**: `scripts/paper_trade_monitor.py` places Alpaca stops, so it is broker-execution code (AGENTS.md §0
  rule 2). Needs an `execution-engineering` grant and its owner. #1987 only flags the number.
- **Valuation clocks (#17)**: positions source-of-truth area, an owner decision.
- **Rotation publication gate (#18)**: loosening a safety gate is not a low-risk display fix.
- **Never-run report producers (#20)** and **stale feeds (#21)**: scheduled jobs, under the cron freeze.
- **v.null in LLM briefs (#22)**: research prompt contract.
- **Slow endpoints (#19)**: the server side is in #2012; no duplicate fix here.
- **In-flight areas** (Ops Controls tabs #1964 and stacked; Releases page; Options desk; Open Trades watchlist): no competing PR. Notes
  for the owners: Coordination → Release train prints "unknown freshness null"; Options → Proposals fires `POST
  /api/v2/broker-proposals/detail` on view (a read, by design).

## 8. Coverage gaps

- Health → Log tab: not opened (heavy endpoint).
- Live data for /retirement … /control-plane on 0f5bf2453 and later is replay-backed. Data checks there use JSON captured at
  2026-10-22 22:xx ET and 2026-10-23 09:1x ET.
- Hermes and maturity endpoints on 0f5bf2453 and later were not exercised live.
- Tooltips: the per-view count of large numbers with and without a title is in `summary.json` (`nums` / `tipped`). It was not graded.
- Re-run after market close or on a non-production copy: `node tools/crawl.mjs --out=<dir> --gap=2000 --mempause=1300` from
  `~/.cache/rtc/site-crawl/` (see the tool header for flags; `--replayjson` for replay mode).

## 9. Corrections (what the crawl got wrong along the way)

- The first run misattributed slow `watchlist/items?symbols=` responses to Risk and Trading. They belonged to Re-Entry: a response was
  logged to whichever view was current when it finished. Fixed: requests are tagged to the view that issued them.
- The first runs keyed the GET cache on URLs that included `useApi`'s `_=<ts>` cache-buster, so nothing was cached. Fixed.
- Run 2 declared pages settled while their requests were still queued (298 skipped). Run 3 waits for a per-view pending counter.
- The first header mockup invented a P&L value. It was redone to re-flow only the real text.
- The memory guard's long pauses starved most of the f7c1e96cb desktop pass after 02:50 UTC. Those views are graded PARTIAL, not PASS.
