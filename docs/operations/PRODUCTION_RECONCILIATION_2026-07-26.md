# Production Reconciliation — Read-Only Truth Inventory (2026-07-26)

**Scope:** Phase 0 of the accelerated non–Active Trader program. **Read-only.** No restart,
reload, enable/disable, install, migrate, rebuild, deploy, or production-state write was performed.
Active Trader is entirely out of scope.

Machine-readable evidence log (mode 0600, outside the repo):
`/home/johnclaw/production_reconciliation_2026-07-26.evidence`

---

## 1. Repository truth

| Fact | Value |
|---|---|
| Production checkout path | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` |
| Current branch | `main` |
| Deployed working-tree HEAD | **`d72f85086aa79f76fb4c985089145416f99830a4`** |
| `origin/main` | **`20a24027017a5ecb0a207ac8960ed7e2f995e54d`** |
| HEAD vs main | HEAD **is a clean ancestor** of main — host is **97 commits behind** main; **0** commits in prod-not-main |
| Dirty state | **74 modified tracked files + 4 untracked** (uncommitted working-tree drift on the shared live tree) |
| Deployed code source | **The checkout itself** — `portfolio_server.py` serves `PROJECT_ROOT/apps/command-center-v3/dist`; no release-dir indirection for v3 (a separate `/home/johnclaw/deploy/v3-next/current` exists only for the v3-next lane) |
| Linked worktrees | **18** (incl. Watch/reentry/defense lanes and the Active-Trader worktree `feat/active-trader-next @ 70ee6a9c`, which is untouched) |

**Commits main has that production lacks (97 total; agent-runtime head):** `20a24027` (merge #178) ← `189aeb95` ← `d6f8033a` (#179) ← `d03bc11d` (#176) ← `fa8550d5` (#175) ← the lifecycle/persistence lane commits. **None** of these are checked out on the host.

**Live files differing from `origin/main`:** 144 paths (74 working-tree edits + the files the 97 main commits changed). The Watch/re-entry cluster is the dominant drift (see §6).

---

## 2. Frontend truth

| Fact | Value |
|---|---|
| Serving root | `apps/command-center-v3/dist` (served by `portfolio_server.py`, `PORT=7777`) |
| `/v3/build-meta.json` `source_commit` | **`f8381023`** — commit exists but is **not in the deployed main lineage** (built from a side branch/PR, not `d72f8508`) |
| `deployment_scope` | `HOLDINGS_LEVELS_FUNDAMENTALS_UI_ONLY` |
| `built_at` | `2026-07-25T22:06:07Z` |
| Bundle asset | `assets/index-DQtVgAqc.js` |
| Served `index.html` sha256 | `2adf74f7…be239` |
| Repo `dist/index.html` sha256 | `7acf165a…4747c` |
| Served vs dist index diff | **Benign** — the server injects a `cc-boot` cache-version script at serve time; the JS bundle asset name matches exactly |
| `/v3/` | HTTP **200** |
| `/v3/agents` | HTTP **200** (SPA fallback to `index.html`) |
| Bundle contains `AgentRuntimeHub` | **ABSENT** |
| Bundle contains read adapter | **ABSENT** |
| Bundle contains `FIXTURE_ONLY` / `NOT_CONNECTED` states | **ABSENT** |
| Bundle contains read-only contract marker | **ABSENT** |

**Interpretation:** `/v3/agents` resolves only because the SPA serves `index.html` for any `/v3/*`
path. The **live bundle contains no agent-runtime page at all** — not even the fixture-only
`AgentRuntimeHub`. So the page a user sees today is not the merged fixture page; it is whatever the
older `AgentsHub` in bundle `f8381023` renders.

*Browser captures:* loopback HTTP status was captured for `/v3/agents`, `/v3/watch?tab=watchlist`,
`/v3/defense`, `/v3/sectors` (all 200 SPA responses). Full headless-browser console/overflow capture
was not run in this read-only pass (would require launching Playwright against the live port); noted
as a deferred, non-blocking item.

---

## 3. Server / API truth

| Fact | Value |
|---|---|
| Process serving `/v3` | `scripts/portfolio_server.py` |
| Kind | Custom Python `http.server` (single process, not systemd-managed) |
| PID | `1585131` |
| Started | **2026-07-23 12:29** (~2.9 days ago; predates recent changes) |
| Working dir / exe | `PROJECT_ROOT` / `.venv/bin/python` |
| Listener | `0.0.0.0:7777` |
| Route ownership | `portfolio_server.py` owns `/v3` static + `/api/*` dispatch (`/api/v2`, `/api/v3`, `/api/health`) |
| `/api/health` | **200** |
| `/api/v3/agent-runtime/runs?limit=1` | **404** |
| `/api/v3/agent-runtime/runs/nonexistent` | **404** |
| Agent-runtime routes | **404** — not mounted |
| Any adapter importing `ReadOnlyAgentRuntimeAPI` | **NONE** (only the contract module defines it) |

No process was restarted or signalled.

---

## 4. Production database truth (read-only SQL)

| Fact | Value |
|---|---|
| Database / port | `trade_ai` / **5432** (production port) |
| Schema `agentic_runtime` | **ABSENT** |
| Eight runtime tables | **NONE** present |
| Row counts | n/a (tables absent) |
| Runtime roles (`agentic_*`, `*_ro`) | **NONE** |
| Dedicated read-only role | **Not available** |
| Current app role | `trade_ai` (superuser=false) |
| Role attributes audited | no `agentic_*` roles to audit |

No DSNs, passwords, pgpass paths, or secret values were displayed.

---

## 5. Schedule & service truth (read-only)

| Area | State |
|---|---|
| Agent-runtime services / timers | **None** (no systemd units, no crons) |
| Sentinel / Darwin / Iris(runtime) / Reflection agent jobs | **None** for the *new* runtime. (Pre-existing `iris_taxonomy_agent.py` / `iris_proposal_curator.py` crons are the older taxonomy/curator agents — unrelated) |
| Watch producers / workers | **Active** (multiple: `agent_watchlist_engine`, `process_watchlist_agent_jobs`, `materialize_watchlist_strategy_cards`, `reconcile_watch_outcomes`, `premarket_watcher`, watchdogs, …) |
| Defense / Sectors producers | **Active** (Defense v7 fill-poller every 10m RTH; `defense_recommendations`, `finviz_sector_research`, `defense_inverse_stoplights`, …) |
| OpenClaw / Hermes jobs | 38 cron lines present |

Nothing was changed.

---

## 6. Watch production drift

**Live packet API:** `GET /api/v2/watch/decision/latest?symbol=X` (DB `decision_packets` table).
Desk summary (`/api/v2/watch/decision/summary`): **67 symbols, 0 verified, 11 validation_failed, 56
stale**, session OFF_HOURS, last run_id 154 COMPLETE 2026-07-24. All packets carry `contract =
watch-quality-governance-v1`, `governance_source_commit a4dc18b4` (**not in main/HEAD**),
`analysis_tier LOCAL_QUANT`, sovereign `header_state WAIT`, `primary_family null`, `model_review.mode
UNAVAILABLE` (deterministic local = PASS; independent/OAuth critic = **REVIEW_UNAVAILABLE**,
`paid_lane_called false`).

**Per-symbol live state (DXCM, CECO, OSS, PFLT, FATN):**

| Field | DXCM | CECO | OSS | PFLT | FATN |
|---|---|---|---|---|---|
| Sovereign / family | WAIT / null | WAIT / null | WAIT / null | WAIT / null | WAIT / null |
| Quality admission | **ADMITTED** | **RESEARCH_ONLY** | **QUARANTINED** | **RESEARCH_ONLY** | **QUARANTINED** |
| Reason | — | event-like RVOL 5.13x | mcap $329M<$500M, ATR 10.4%>10% | holding-mgmt only, mcap<$1B tier | price $4.61<$5, float 6.3M<20M, ATR 11.7% |
| Price | 71.54 | 75.45 | 12.50 | 6.87 | 4.58 |
| Support / Resistance | 70.79 / 77.27 | 77.25 / 90.15 | 12.19 / 18.04 | 6.86 / 7.48 | 4.53 / 6.41 |
| Freshness | CURRENT/P0 | CURRENT/P0 (**price PARTIAL**) | CURRENT/P1 | CURRENT/P1 | CURRENT/P0 |
| Validator | SWING **PASS** | (no ticket) | SWING **FAIL** | SWING **FAIL** | SWING **FAIL** |
| Queue quality status | actionable | unsafe | actionable | (none) | unsafe |
| Valuation (P/E·Fwd·PEG·P/B·P/S) | 30.5·23.1·1.1·9.3·5.7 | 213·31·0.51·9.1·5.8 | strip-map | strip-map | 12.7·13.0·null·2.5·3.3 |

*Valuation numbers come from `/api/v2/finviz-strip-map`, not the packet or `watchlist/items` (which
expose no valuation keys).*

**Behavior drift classification** — **all four PR behaviors are LIVE_NOT_IN_MAIN:**

| PR | Behavior | State | Evidence |
|---|---|---|---|
| #151 | OAuth critic / truthful labels / freshness / packet rebuild | **LIVE_NOT_IN_MAIN** | UI shim `WatchTruthAuditPanel` landed in main (frontend only); the producer generating the live labels is gov-branch `a4dc18b4`, not in main |
| #170 | valuation passthrough on queue | **LIVE_NOT_IN_MAIN** | strip-map valuation block *is* in main, but the rendering bundle (`f8381023`) is not; per-row `watchlist/items` passthrough sits on unmerged `fix/watch-valuation-passthrough` |
| #171 | S/R heat before price + valuation tooltips | **LIVE_NOT_IN_MAIN** | build-meta exactly matches PR (`f8381023`, `HOLDINGS_LEVELS_FUNDAMENTALS_UI_ONLY`); `supportResistance.tsx` present as **untracked** file, absent from main/HEAD |
| #172 | deterministic quality admission + reconciliation | **LIVE_NOT_IN_MAIN** | packets carry `quality_admission` (ADMITTED/RESEARCH_ONLY/QUARANTINED) + `ticket_review.reconciled`; `quality_admission` = **0 matches in main**; builders exist only on gov branch |

**`watch_drift_count = 4`.** The entire live Watch surface runs on unmerged code: frontend bundle
`f8381023` (gitignored `dist`) + DB decision packets from branch `agent/watch-quality-governance-v1`
(`a4dc18b4`), served by a `d72f8508` server whose tracked history — and `origin/main` — contain
neither producer. Source PRs #151/#170/#171/#172 remain OPEN/unmerged.

---

## 7. Defense / Sectors production drift

**⚠️ Critical drift: the live bundle renders a decision board that `main` has DELETED.** The served
bundle was built from `f8381023` (branch `feat/holdings-levels-fundamentals`), which renders
`ActionableSectorDecisionBoard` (via `InstitutionalRotationBrief`) on **both** `DefenseHub` and
`SectorsHub`. That component and its `rotation/` directory **do not exist in HEAD or `origin/main`**
(stripped out). **A redeploy from current `main` would remove the institutional taxonomy users see
today.**

**Live producers (read-only cron inventory):**
| Producer | Schedule | State | Note |
|---|---|---|---|
| `sector_momentum_engine.py` (breadth) | `25 17 * * 1-5` | **ENABLED** | Breadth = **% above 20-day MA**, *not* exact-20-distinct-session |
| `defense_recommendations.py` (recs) | `50 17` + `10 10` `* * 1-5` | **ENABLED** | Identical in `main`; `mode: SHADOW` (Telegram only after promote) |
| `finviz_sector_research`, `sector_rs_daily`, `finviz_industry_groups` | daily | ENABLED | supporting |

**Corrected v4/v10 additive producers:** exist **only** in worktree `wt-dq-v1`
(`agent/defense-data-quality-v1`) — `defense_data_quality.py` (`exact_session_breadth(sessions=20,
min_members=8)`, `stock_quality_gate()`, stale-quarantine) and `defense_shadow_replay.py`. **Absent
from `main`, unscheduled, unreferenced** by any main-tree file → the live decision board's
sizing/quality/quarantine/exact-20-session inputs are **structurally unfed**.

**Live API payloads** (`/api/v2/defense/posture`, `/api/v2/sectors/monitor`,
`/api/v2/defense/recommendations`) carry `breadth_pct/breadth_n`, `book_pct`, `state`, per-account
recs — but **no** `quarantined`, `quality`, or `account_sizing` fields the UI board expects.

| # | Behavior | State |
|---|---|---|
| 1 | Institutional sector→industry→ETF→stock decision board | **LIVE_NOT_IN_MAIN** |
| 2 | Exact 20-distinct-session breadth | **NOT_IMPLEMENTED** (prod; only unmerged `wt-dq-v1`) |
| 3 | Account-specific effective exposure | **LIVE_AND_IN_MAIN** ✅ |
| 4 | Per-account sizing / dollar bands | **LIVE_AND_IN_MAIN** ✅ |
| 5 | Stale-row quarantine | **NOT_IMPLEMENTED** (prod) |
| 6 | Stock-quality gate | **NOT_IMPLEMENTED** (prod) |
| 7 | ELIGIBLE NOW / RESEARCH WATCH / AVOID-REDUCE / NO DECISION exposure | **LIVE_NOT_IN_MAIN** |

**`defense_drift_count = 5`** (behaviors #1, #2, #5, #6, #7 not aligned; only #3, #4 clean).
Source PRs #166/#167/#168 remain OPEN/unmerged.

---

## 8. Headline reconciliation findings

1. **Agent runtime is merged (`20a24027`) and LAB-proven, but NOT live.** Host checked out at an
   older ancestor (`d72f8508`), live bundle has no agent-runtime UI, `/api/v3/agent-runtime/*` → 404,
   and there is **no schema, no tables, no roles, no services, no crons**.
2. **Bidirectional Git↔production drift:** several Watch changes are live (in the working tree / an
   externally-built bundle) but sit in **open, unmerged PRs**; meanwhile the merged agent runtime is
   **not deployed**.
3. **The live UI is not reproducible from the deployed checkout:** `build-meta.source_commit`
   (`f8381023`) is not in `d72f8508`'s history. Any rollout must first pin/rebuild from a known SHA.
4. **74 uncommitted tracked edits on a shared, live-served tree** — advancing the host to
   `20a24027` would collide with them; reconciliation must stash/commit that drift first.

---

## Phase 0 ending markers

```
host_inventory|PASS
production_checkout_sha|d72f85086aa79f76fb4c985089145416f99830a4
origin_main_sha|20a24027017a5ecb0a207ac8960ed7e2f995e54d
deployed_ui_sha|f8381023 (build-meta source_commit; NOT in deployed main lineage)
agent_runtime_api_state|404
agent_runtime_schema_state|ABSENT
watch_drift_count|4
defense_drift_count|5
production_mutation|NONE
final_status|PASS_PRODUCTION_RECONCILIATION_INVENTORY
```

---

## Cross-cutting conclusion

Every user-visible surface in this program's scope — the agent runtime, Watch, and Defense/Sectors —
is **decoupled from `origin/main`**, in three distinct ways:

- **Agent runtime:** merged into `main`, **not deployed** (no bundle, no API, no schema, no roles, no jobs).
- **Watch:** **live but unmerged** — runs entirely on bundle `f8381023` + gov-branch packets `a4dc18b4`.
- **Defense/Sectors:** **live but unmerged AND main-deletes-it** — the live decision board is on
  `f8381023`, which `main` has removed; its quality producers sit unmerged in `wt-dq-v1`.

**A naive "advance host to `main` + rebuild" would simultaneously (a) not activate the agent runtime,
(b) drop the live Watch quality packets, and (c) delete the live Defense/Sectors decision board.**
Reconciliation must port the live-only behavior onto `main` first (Lanes B/C), not fast-forward the
host. `deployed_ui_sha f8381023` being outside the deployed lineage is the single most important
constraint on any rollout.
