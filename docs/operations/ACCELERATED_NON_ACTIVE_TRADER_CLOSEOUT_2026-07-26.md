# Accelerated Non–Active Trader Program — Consolidated Closeout (2026-07-26)

**Scope:** Phase 0 (read-only inventory) + Lanes A/B/C/D preparation. **Active Trader entirely out of
scope and untouched.** Nothing was merged, deployed, migrated, scheduled, or activated. Every lane
result is a draft PR + prepared (dry-run/unapplied) scripts.

---

## Phase 0 — host inventory result & evidence paths

- **Result:** `final_status | PASS_PRODUCTION_RECONCILIATION_INVENTORY`
- **Report:** `docs/operations/PRODUCTION_RECONCILIATION_2026-07-26.md`
- **Evidence log (mode 0600, outside repo):** `/home/johnclaw/production_reconciliation_2026-07-26.evidence`
- **Drive:** synced (manifest hash == file hash), branch `codex/production-reconciliation-audit-2026-07-26`.

### Exact current production truth
| Fact | Value |
|---|---|
| Production checkout HEAD | `d72f85086aa79f76fb4c985089145416f99830a4` (97 commits behind `main`, 74 dirty files) |
| `origin/main` | `20a24027017a5ecb0a207ac8960ed7e2f995e54d` |
| Deployed UI build (`build-meta.source_commit`) | `f8381023` — **NOT in the deployed main lineage** (built from a side branch; not reproducible from the checkout) |
| Server | `portfolio_server.py` pid 1585131, custom http.server `:7777`, started 2026-07-23 |
| `agent_runtime_api_state` | **404** (not mounted) |
| `agent_runtime_schema_state` | **ABSENT** (no schema, tables, or roles in `trade_ai` @ 5432) |
| `watch_drift_count` | **4** (all PR #151/#170/#171/#172 behaviors LIVE_NOT_IN_MAIN) |
| `defense_drift_count` | **5** (live decision board on `f8381023` that `main` deleted; quality producers unmerged) |

**Central risk:** a naive "advance host to `main` + rebuild" would (a) still not activate the agent
runtime, (b) drop the live Watch quality packets, and (c) delete the live Defense/Sectors decision
board. Reconciliation must **port live-only behavior onto `main` first** — which is what Lanes B/C do.

---

## Lane results (all draft, base `main`, not merged/ready)

| Lane | Branch | Head | Draft PR | Files |
|---|---|---|---|---|
| **A** read plane + HTTP mount | `feat/agentic-mvl-runtime-foundation` | `fd56b2d7` → **`a65fd529`** | **#163** | 5 (mount commit) |
| **B** Watch reconciliation | `codex/watch-production-reconciliation-v1` | **`4472c9ca`** | **#181** | 61 |
| **C** Defense/Sectors reconciliation | `codex/defense-sectors-production-reconciliation-v1` | **`2190c6ca`** | **#180** | 26 |
| **D** autonomous SHADOW agents | `codex/agent-autonomy-shadow-v1` | **`d4671a32`** | **#182** | 19 |

### Lane A — agent-runtime read plane, mounted (continues PR #163)
- **Changed files:** `scripts/agent_runtime/read_http.py` (new, GET-only dispatcher from canonical `READ_ROUTES`), `scripts/agent_runtime_read_boot.py` (new, feature gate + DSN factory *outside* the zero-authority package), `scripts/portfolio_server.py` (GET dispatch + 405 non-GET, same-origin, `no-store`, no CORS), `scripts/agent_runtime/deploy_read_mount.sh` (new), `tests/test_agent_runtime_read_mount.py` (new, 23 tests).
- **Behavior:** default-disabled behind `AGENT_RUNTIME_READ_API` + `AGENT_RUNTIME_READ_DSN`; honest **503** zero-authority envelope when off / unset / DB unreachable; bounded limit/offset; read-only transaction, rollback-only; rejects superuser/privileged roles; no secret/raw-payload leakage.
- **Tests/build:** 23 focused + **215 passed / 9 skipped** (`test_agent_runtime_*`) + 11 frontend states + tsc/vite (1272 modules) + design/chip guards + authority scan **clean** + `bash -n` OK.

### Lane B — Watch backend + frontend reconciliation (PR #181)
- **Approach:** ported **only** Watch-scoped files (61) from the stale governance stack; did **not** merge the 143-commit chain (which would delete ~20 agent_runtime modules). No agent_runtime/broker/order/2FA path touched.
- **Ported:** deterministic quality admission (ADMITTED/RESEARCH_ONLY/QUARANTINED) sovereign over arithmetic; valuation passthrough (P/E, fwd P/E, PEG, P/B, P/S) into `_finviz_strip_map_compute`; closed-session S/R before price; truthful validator/reviewer states (no fake PASS — reconciler returns `QUALITY_NOT_ASSESSED`/`DETERMINISTIC_NOT_RUN`); one sovereign decision; non-primary labels = OWNERSHIP ELIGIBLE / MECHANICS VALID; Street freshness split from technical/quote/event; held-position management visibility without authorizing adds.
- **Tests/build:** CC build PASS (design-token 254, chip-scope, tsc, vite 1273 modules); **141 Watch backend tests pass**; updated 3 stale `refresh_v5` assertions to the new sovereign-quality contract (39/39).
- **200-card read-only dry-run (before → after):** ADMITTED 1→0, RESEARCH_ONLY 2→122, QUARANTINED 2→78, missing-quality-evidence 195→**0**, `new_entry_allowed` 0, management_only(held) 4.
- **5-symbol packets:** DXCM ADMITTED→RESEARCH_ONLY(held, add-blocked), CECO RESEARCH_ONLY, OSS QUARANTINED→RESEARCH_ONLY, PFLT RESEARCH_ONLY(held), FATN QUARANTINED (price<$5 floor). All `new_entry_allowed=false`.

### Lane C — Defense/Sectors reconciliation (PR #180)
- **Ported:** the institutional sector→industry→ETF→stock decision board (ELIGIBLE NOW / RESEARCH WATCH / AVOID-REDUCE / NO DECISION) that `main` had deleted; exact-20-distinct-session breadth (`exact_session_breadth`); stock-quality gate; stale-row quarantine + evidence/provider/as-of ledger; per-account effective exposure/sizing/dollar-bands + explicit unmapped weight; covered-sample ≠ official-constituent labels.
- **Discipline:** v4/v10 producers **additive + DISABLED**; `sector_momentum_engine.py` stays default; live `defense_recommendations.py` untouched (no regression). `api_v2.py` patched by hand (main is 94 commits ahead of the source branch's base).
- **Not ported (deliberate):** PR #166 render-gate spec (needs Playwright; fixtures ported) and an app-wide CSS restyle (out of scope).
- **Tests/build:** **54/54** ported tests pass; py_compile clean; frontend build green (design-guard 256, chip-scope, tsc, vite).

### Lane D — autonomous SHADOW agent maturity (PR #182)
- **Layered on existing runtime** (`main` already ships the 8-table schema DDL `0001_mvl`, Sentinel pipeline, 16-agent catalog). 8 agents as governed `ShadowAgentSpec`s: Wave 1 (Sentinel/Darwin/Iris/Reflection) SHADOW-enabled; Wave 2 (Maria/Vega/Guardian-Risk/Aegis) DESIGNED/disabled. **Reviewer≠producer & scorer≠producer enforced at import.** Bounded queue, concurrency cap, budgets (cost=0), dedup, stale-input refusal, circuit breaker, cancellation.
- **12 maturity gates**, all `NOT_YET_MEASURED` → `promotable=False`; `assert_not_operational` blocks OPERATIONAL. CC read-model projection shows real spec/gate data — **no fixture looks live**; live per-run evidence depends on Lane A's read plane.
- **Tests/build:** 49 new + full `agent_runtime` **224 passed / 9 skipped**, compileall clean, authority scan clean, `bash -n` + `systemd-analyze verify` OK.

---

## Exact production migrations / services / timers that remain UNAPPLIED

| Item | Location | State |
|---|---|---|
| `agentic_runtime` schema DDL | `migrations/agentic_runtime/0001_mvl.{up,down}.sql` (in `main`) | **not applied to any DB** |
| Least-privilege roles (shadow_rw, lab_rw, reader) | `migrations/agentic_runtime/0002_roles.{up,down}.sql` (Lane D) | **prepared, not applied** (`apply.sh` refuses without `--apply`) |
| Per-agent systemd `@.service` / `@.timer` | `config/systemd/agent_runtime/` (Lane D) | **disabled, not installed** |
| Watch producer schedules | — | **unchanged** (no cron edits) |
| Defense breadth producer switch (`sector_momentum_engine` → `_v4`) | via `defense_breadth_switch_packet.sh` (Lane C) | **not switched** (dry-run only) |
| Read API gate + DSN | `AGENT_RUNTIME_READ_API` / `AGENT_RUNTIME_READ_DSN` | **unset** (routes inert → 503) |

## Deployment & rollback packets prepared (all dry-run default, none executed)
- **Lane A:** `scripts/agent_runtime/deploy_read_mount.sh` — exact-SHA + dirty gate, backend+static backup, atomic swap, one named service restart (after typed operator ack), API/health + `/v3/agents` + authority-envelope smokes, auto-rollback of backend **and** static, post-rollback verify.
- **Lane B:** `scripts/deploy_watch_production_reconciliation_from_ref.sh` — exact-40-char-SHA + ACK token + `APPLY=1` gates, git-bundle + dist backup, atomic candidate swap, data-only packet rebuild, loopback smoke, `ROLLBACK=1`. Never edits schedules.
- **Lane C:** `scripts/defense_breadth_switch_packet.sh` — dry-run default, exact-SHA + ack gated; would switch producer → regen payloads → smoke (asserts `data_quality`) → rollback. Never edits cron/timer.
- **Lane D:** `migrations/agentic_runtime/apply.sh` — prepare-only; refuses without `--apply`, refuses a production DSN.

## Secrets / credentials / host dependencies
- No DSN or credential committed anywhere. Lane A reads `AGENT_RUNTIME_READ_DSN` only at process start; Lane D role passwords must be set out-of-band from the secret store.
- Host prereqs still ABSENT in prod: `agentic_runtime` schema, dedicated read-only role, read DSN/gate, populated `data/state/valuation_supplement_cache.json` (Lane B valuations show 200/200 missing until backfilled), Playwright browsers (Lane C board e2e).

## First blocker per lane
- **A:** no `agentic_runtime` schema / read-only role / DSN in prod → routes correctly return 503 until an operator provisions them.
- **B:** valuation supplement cache unpopulated → projected valuation coverage 0 until `watch_valuation_backfill.py` is run (yfinance network; operator).
- **C:** breadth producer switch + `api_v2` annotations change live payload shape → operator-gated; board e2e needs Playwright.
- **D:** live per-agent evidence requires Lane A's read plane merged/deployed + schema/roles applied to an isolated LAB/SHADOW DB.

## Recommended MERGE order
1. **#163** (Lane A read plane + mount) — foundation the others reference; inert by default.
2. **#182** (Lane D) — depends only on runtime already in `main`; stays default-disabled.
3. **#181** (Lane B Watch) and **#180** (Lane C Defense/Sectors) — independent; either order. Resolve the two pre-existing red UI tests (Lane B note #3) before/with #181.

## Recommended DEPLOYMENT order (each operator-gated, separate authorization)
1. Apply `0001` + `0002` to an **isolated LAB/SHADOW** DB; create the read-only role; set role passwords.
2. Provision `AGENT_RUNTIME_READ_DSN` (read-only role) + `AGENT_RUNTIME_READ_API=1`; run Lane A deploy `--execute` (one service restart) → `/v3/agents` shows real read-only evidence.
3. Deploy Lane B Watch (backend + static + packet rebuild); backfill valuation cache.
4. Deploy Lane C UI (restores live board on `main`), **then** switch the breadth producer via the packet.
5. Lane D: measure maturity gates in SHADOW; enable per-agent timers only after gates pass.

## Actions requiring operator authorization (NONE performed)
Create/enable DB roles · apply migrations · provision the read DSN + set the API gate · run any lane
deploy `--execute` · switch the Defense breadth cron/timer · run `watch_valuation_backfill.py` · enable
agent systemd timers · resolve/re-pin the two pre-existing red Watch UI tests · mark any PR ready · merge.

---

## Final authority markers
```
production_database_write|NONE
service_change|NONE
schedule_change|NONE
provider_activation|NONE
broker_or_order_action|NONE
merge_action|NONE
deployment_action|NONE
final_status|PASS_ACCELERATED_NON_ACTIVE_TRADER_PREPARATION
```
