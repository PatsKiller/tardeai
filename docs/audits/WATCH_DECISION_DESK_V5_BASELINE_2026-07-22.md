# Watch Decision Desk V5 — Baseline & Source Audit (2026-07-22)

Status:      HISTORICAL
as_of:       2026-07-22T10:35:40-04:00
Measured at: efcc51365 / not measured

## Git / deploy baseline

| item | value |
|---|---|
| Branch at audit | `main` |
| Local HEAD | `fa8f9c867ecab5417514b3e684337d59945c3e2e` |
| origin/main | `ccb073f9a1ab70ed8d53717d8c2bbc75ef67701d` (the observed review head; local is 4 ahead — Schwab auto-reauth + backup-coverage commits, unrelated to Watch) |
| Dirty (untouched) | `config/ipo_lockups.json`, `docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md`, `docs/project/RELEASE_MANIFEST_LATEST.md`, `scripts/run_telegram_callback_poller.py` + untracked e2e screenshots |
| Stashes (untouched) | 3 (`unrelated-wip`, 2× runtime churn) |
| Work worktree | `wt-watch-v5` → branch `wt/watch-decision-desk-v5` (serving tree not used) |
| Deployed bundle | `index-DsNb7B0r.js` (`cc-v3 3.12+mrvgk3ce`) |
| Packet version | `1.1.0-shadow` (all 67 live packets) |
| Action-policy version | `1.1.0` (`decision_action_policy.POLICY_VERSION`) |

## Live packet population (at audit)

- `decision_packets`: 257 total, **67 live** (superseded_by IS NULL)
- Age buckets (live): **all 67 in 12–48h** — i.e. every live packet is past the 4h RTH TTL at audit time (built by yesterday's 08:15 batch; today's batch outcome not yet reflected at query time)
- By model mode (live): BLIND 58, SINGLE_LANE 9. No LLM-free tier in use.
- Cadence owner: cron `15 8 * * 1-5` → `shadow_batch_generator.py --run` (top-50 by Hermes rank + starred, fresh-skip, 40m timeout). **This is the only scheduled packet rebuild — once per weekday.** The documented "4h RTH / 12h off-hours" is a *validity TTL* (`packet_invalidation.py:46-47`, `effective_ttl_hours`), not a rebuild cadence: packets EXPIRE every 4h RTH but are only REBUILT daily at 08:15. This mismatch is why the desk shows stale cards most of the day.

## ROOT CAUSE OF REPEATED STALE CARDS (source-proven)

Two disjoint refresh surfaces share one UI affordance:

1. **`POST /api/v2/watchlist/<sym>/refresh`** (`api_v2.py:35609` → `_wl_refresh_symbol_async:6977` → `_wl_refresh_symbol:7006-7103`) refreshes news/catalyst/analyst/price-history/strategy-card/technicals/ATR and requeues the LLM agent lane. **It never touches `decision_packets`.**
2. **`POST /api/v2/shadow/strategy/build`** (`api_v2.py:11975` → `shadow_strategy_job.enqueue:74` → detached `run_worker:138` → `shadow_decision_service.evaluate:539` + `persist:750`) is the ONLY on-demand packet rebuild — exposed as "⚡ build full strategy (shadow)" buried in the card's expanded drawer (`WatchlistCardV4.tsx:590`).

The card's primary CTA **"Refresh Strategy"** (`operatorDecisionCard.ts:273`, rendered `DecisionPacketBand.tsx:176-186`) wires through `onRefresh` → `WatchlistHub.refreshSymbol:321` → `runRefresh:274` → **endpoint #1**. So the button labelled *Refresh Strategy* refreshes inputs, the packet stays old, `compare_packet_inputs` still fails, and the card immediately re-reports *Strategy inputs changed*. Worse: refreshing inputs can CHANGE the current input hash, guaranteeing INPUT_HASH_MISMATCH against the untouched packet.

**Live CECO proof (this audit):**

- Live packet `packet_id=211`, generated 2026-07-21 10:35:11 ET, `input_hash 4ced5f39…`
- Current snapshot hash `1fd0c88e…` → `inputs_match: False`, reasons `[FUNDAMENTALS_CHANGED, TECHNICALS_STALE, TTL_EXPIRED]`, TTL now 4.0h (RTH)
- Card row (`/api/v2/watchlist/items?symbol=CECO`): `action_policy.state=STALE`, same three reasons, `decision_packet_at=07-21 10:35`
- `POST /watchlist/CECO/refresh` → `{ok:true, queued}` → **live packet still 211 after completion** (packet untouched — defect proven)
- `POST /shadow/strategy/build {symbol: CECO}` → run enqueued → new packet supersedes 211 (see addendum for run/packet ids)

## Secondary defects (source-cited)

- **Timestamp hidden when stale**: `operatorDecisionCard.ts:479-483` — `NEEDS REFRESH` chip and the `built …` stamp are mutually exclusive; `:474` replaces the stamp line with "needs refresh". Contradicts the documented always-visible timestamp.
- **Browser owns freshness**: `WatchlistHub.tsx:438-457` useEffect auto-refreshes ONE stale symbol per page per session (`autoRefreshDone` Set) — an accidental client-side scheduler, and it refreshes *inputs* only.
- **Five families buried**: LONG_TERM/SWING/BEARISH/OPTIONS/NO_TRADE render only inside the Audit drawer (`DecisionPacketBand.tsx:217-275`); the legacy plan/sizing grid still renders below the packet band (`WatchlistCardV4.tsx:451-506`, dimmed 0.72) — hidden comparison + duplicated mechanics.
- **Full packet JSON joined into every list row** (`/api/v2/watchlist/items` rows carry `decision_packet` object) — list-payload weight; no summary table.
- **LLM-free path exists but not first-class**: `evaluate(..., run_models=False)` (`shadow_decision_service.py:539`, deterministic fallback 650-660) — reachable only via env/CLI, not exposed as an operator tier.
- **Design-system drift**: packet band uses raw hexes (`operatorDecisionCard.ts:535-540`, `DecisionPacketBand.tsx:29-33`) instead of `watchTokens` — violates the import-never-fork house rule.

## Reusable assets for V5 (found, not to be reinvented)

- `decision_runs` already has: symbol, stages JSONB, current_stage, sla_deadline, worker_pid, heartbeat_at, packet_id (migrations 2026_07_25/26) + `sweep_stale` recovery (`shadow_strategy_job.py:269`, not cron-scheduled).
- Atomic job claim exemplar: `inference_ensemble_worker.claim_jobs` (`FOR UPDATE SKIP LOCKED`).
- Versioned YAML policy w/ mtime hot-reload exemplar: `config/stop_policy.yaml` + `holding_family._policy()`.
- Single-sourced TTL: `packet_invalidation.effective_ttl_hours` consumed by policy, batch generator, and action policy alike.
- Blind lanes: `blind_review_runner` (grok+chatgpt free OAuth lanes), lanes recorded in packet + columns.
- Action authority: `decision_action_policy.evaluate_action` — pure, versioned, backend-computed; card renders it (no drift). V5 must keep this the sole authority.

## Test baseline

Recorded separately at implementation start (targeted: shadow/packet/action-policy suites; full: `TRADE_AI_CI=1` source-only CI set) — see V5 progress log.

## Addendum — live reproduction + V5 build evidence (same day)

**CECO both-directions proof:**
- `POST /watchlist/CECO/refresh` (inputs) → 202 queued → live packet STILL 211. Defect proven.
- `POST /shadow/strategy/build` → decision_run 348 COMPLETE → packet **258 supersedes 211**.

**V5 orchestrator proof (this branch):**
- Run 3 (FULL_STRATEGY · LOCAL_QUANT · force): all 6 dimensions refreshed → packet 260 → parity OK.
- Run 9 (AFFECTED_DIMENSIONS · LOCAL_QUANT): detected `TECHNICALS_CHANGED` → refreshed ONLY
  technicals (1.3s) → packet 261 → CECO freshness **STALE → CURRENT**, timestamps present
  throughout, `lane_calls=0`.
- Idempotency: duplicate enqueue vs live job → `SKIPPED_LOCKED` (partial unique index).
- Sweeper: dead-worker job swept → run reconciled → re-runnable.

**Production regressions found & fixed during the build:**
1. Post-SM-migration, dozens of scripts `read_text()` the deleted `.env` at import
   (`setup_quality_prior.py:22` et al) — every fresh process importing them crashed since
   2026-07-21 15:58. Fixed globally: `.env` → symlink to the Bitwarden tmpfs render
   (serving tree + worktree). Legacy readers get always-fresh env; no plaintext on disk.
2. Foreign enrichers close db_adapter's shared thread-local connection and `sys.exit()` on
   error paths — V5 workers use a private connection + BaseException isolation.

**Pre-existing test failures (baseline-verified on main, identical node IDs):**
`test_shadow_batch.py` band `useState(true)` trio — older band-open contract, already failing
before V5.
