# COGX Wave 1 · tranches 1–3 — foundations, shadow wiring, lane artifacts

```
Status:      ACTIVE
as_of:       2026-09-27T20:45:00-04:00
Measured at: cbf603526 (origin/main base) / served 8f2a178d5-main-exact-phase2-20260927-171004; nothing deployed yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Every artifact here is a read, a receipt or a declaration.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1 (all 14 items, operator 2026-09-27)
```

## What tranche 1 delivers (09 §3 Wave 1, first half)

| Deliverable | Where | Proof `[VERIFIED]` |
|---|---|---|
| Façade: `open_context` / `retrieve_or_generate` / `commit` (reads + receipts; SHADOW) | `scripts/lib/intelligence_client.py` | 13 hermetic tests (`tests/test_intelligence_client_facade.py`) |
| Ring 1 memory chokepoint linter + shrink-only baseline | `scripts/check_memory_chokepoint.py`, `config/memory_chokepoint_baseline.json` | baseline: 71 files / 137 direct silo imports; ratchet test green |
| `intelligence` schema migration + safe rollback | `migrations/2026_09_27_intelligence_v1.sql` / `.down.sql` | lab proof on a throwaway DB: up = 11 tables + RLS, re-run idempotent, down = 0 policies, DB dropped |
| Heartbeat helper (file fallback + optional Postgres upsert) | `scripts/lib/supervisor_heartbeat.py` | 3 tests incl. pg absent/written/error paths |
| SLA seed from the lane registry (dry-run default) | `scripts/seed_supervisor_sla.py` | 149 lanes; heuristics tested |
| Conformance report v0 (measure only) + silo map | `scripts/report_platform_conformance.py`, `config/platform_silos.json` | dry run on this tree: 45 UNMEASURED standards, 10 silos scored (the governance-debt baseline, 05 §8) |
| Approval-package ledger + CLI + Telegram button branch (from_id verified) | `scripts/lib/approval_package.py`, `scripts/approval_package_cli.py`, `scripts/telegram_callback_handler.py` (`pkgapprove`/`pkgdeny`/`pkgshow`) | 5 tests (chain, transitions, parser, render) |
| Contracts + drift manifest | `docs/contracts/{MemoryContext,RetrievalReceipt,ApprovalPackage,LaneHeartbeat}_v1.md`, `config/contract_manifest.json`, `scripts/check_contract_manifest.py` | checker OK (4) |
| Declarations | 4 lanes `NEVER_SCHEDULED` in `config/lane_registry.json`; 5 writer rows in `config/data_source_authority.json`; CI gate `cogx_w1_foundations` in `run_cio_hardening_ci.py`; `intelligence_client` in `KNOWN_CONSUMERS` | both validators green; coverage gate: 0 new unlisted |

## What tranche 2 adds (same PR #1305)

| Deliverable | Where | Proof `[VERIFIED]` |
|---|---|---|
| Shadow hooks at the seven chokepoints: `WakeEngine.run` (DECIDE), `HermesWorker._process_one`, `hermes_external_researcher.main`, `generate_row_opinion` (ADVISE), `options_thesis_lifecycle.request_research`, `process_watchlist_agent_jobs.process_jobs`, `run_symbol_thesis_acquisition.run_one` | `shadow_open` / `observe_generation` / `shadow_commit` in the façade; each hook is fail-soft and changes no output | existing suites for those modules: 82 passed; façade tests 16 passed |
| Live proof of the façade on production state (read-only copy of `aif_memory.jsonl`, symlinked theses/results/contradictions/registry; receipts to the scratchpad; production retrievals file mtime unchanged) | subject V | `open_context` 650 ms, not degraded, `SEC:d1871bc6…` CONFIRMED, 6 facts, thesis v25 CURRENT, 2 beliefs, **7,676 open contradiction candidates**; ladder 107 ms → HIT_FRESH (step 2 thesis field + step 6 version; step 7 not installed) |
| GIR projector v1 (batch; dry-run default; `--apply` needs the migration) with the projection-side re-key (HELD:<tkr> → SEC:) | `scripts/gir_projector.py` | dry run on production persistent-state: 129,000 entities / 5,803 envelopes / 237,866 edges; 52 of 53 instrument records re-keyed; 16 theses and 0 holdings with an unresolved symbol; 118,027 contradiction entities |
| Breach detector (detect + record; no ladder action) | `scripts/supervisor_breach_detector.py`, `docs/contracts/Breach_v1.md` | dry run with a seeded SLA file against live output signals: **25 of 115 ACTIVE lanes NO_OUTPUT** (cio-delivery, cio-defer-revisit, portfolio-repricer, indicator-cache-refresh, identity-sweep-stage0, material-change-notifier-stage2, watch-review-workers, material-change-digest, due-diligence-questions, document-mentions-backfill, morning-brief-0730, …) — silent failures the health agent does not flag today; without the seed all 115 are UNGOVERNED |
| Counterfactual section in the memory shadow measure | `agent_memory_shadow_measure.run_measure` → `memory_counterfactual` | honesty tests green |
| Identity standard in conformance v0.1 (from context receipts) | `report_platform_conformance.py` | test green |
| Contradiction cap in contexts (25 rows carried, exact count always) | façade | the V context row was 1.8 MB before the cap |
| Declarations | 2 more DSA writer rows (`intelligence_gir_projection`, `supervisor_breaches`); `on_gap` chains end with `operator_ask`; lane rows carry `reason_evidence`; dark-contract declarations on the two new entrypoints; `docs/SOURCE_OF_TRUTH.md` + AGENTS §7A table re-rendered | validators green; PR-profile hardening re-run in the PR comments |

**Dropped from tranche 2, deliberately:** automatic per-package guard-grant minting on APPROVED (13 §6). The auto-mode classifier refused the change that would let the callback mint `bin/guard` grants; grants stay a manual operator action (`bin/guard grant … --reason "pkg:<id> pr:<n> sha:<sha> campaign:…"`), and the ledger records `GRANT_*` notes by hand. Revisit only on the operator's explicit instruction.

## What tranche 3 adds (same PR #1305)

| Deliverable | Where | Proof `[VERIFIED]` |
|---|---|---|
| Projector: ticker research graph source (RESEARCH:ARTIFACT, re-keyed to SEC: projection-side) + `--incremental` (source fingerprints in a state file; a bus consumer replaces it in Wave 2) | `scripts/gir_projector.py` | dry run on production state: 141,293 entities / 250,076 edges; 12,293 artifacts, 83 with an unresolved symbol; incremental test green |
| Approval reminders +4 h / +12 h and expiry (dry-run default; `--send` through the Telegram chokepoint) | `scripts/approval_package_reminder.py` | 1 hermetic test (once-each reminders, expiry marks items) |
| Unit files for the two systemd lanes + the two cron lines | `config/systemd/user/tradeai-supervisor-breach-detector.{service,timer}`, `tradeai-gir-projector.{service,timer}`, `docs/ops/COGX_WAVE1_CRONTAB_LINES.txt`; lane rows now name their schedulers | validators green |
| Operator runbook: every command only the operator can run, in order, with expected outputs and rollbacks | `docs/ops/COGX_WAVE1_OPERATOR_RUNBOOK_2026-09-27.md` | — |

## Wave 2 · tranche 1 — Ring 2 in SHADOW (branch wt/cogx-w2-t1-20260927)

| Deliverable | Where | Proof |
|---|---|---|
| `memory_ring2.check()` — mode per surface from `config/memory_influence_policy.json` (all SHADOW), env kill switch, receipts | `scripts/lib/memory_ring2.py`, `config/memory_influence_policy.json`, `docs/contracts/Ring2Decision_v1.md` | 7 hermetic tests |
| Chokepoint 1: `gate_and_generate` — research-class processes (registry `memory_context_required` / category) must carry `context_id`; falls back to the process-current context; ids ride the reservation metadata | `scripts/lib/llm_consumption.py` | test |
| Chokepoint 2: the :8766 bridge — `X-TradeAI-Context-Id` required for registry-declared research callers; 428 in ENFORCED | `scripts/lib/cio_governed_model_bridge.py`; both bridge clients send the header | bridge suite 25 passed |
| Chokepoint 3: `accept_research_result` — refusal dict in ENFORCED; `context_id` / `retrieval_receipt_id` / `memory_context_miss` in thesis provenance | `scripts/lib/research_thesis_delta.py` | test |
| Chokepoint 4: `CIOActionLedger.create_action` — `context_id` + `memory_context_miss` on every new action payload (additive; old hashes untouched); raises in ENFORCED | `scripts/lib/cio_action_ledger.py` | ledger suite 30 passed + test |
| `memory.delta` event type; `commit` publishes MemoryDelta@v1 when deltas exist (no consumer yet) | `scripts/lib/cio_event_bus.py`, `intelligence_client.commit` | wake-detector/goal suites green |
| Process-current context (`set_current_context`) so the seven hooks thread ids without touching every call site | `intelligence_client` | test |

Wave 2 approval items are drafted in `docs/ops/COGX_WAVE2_PACKAGE_SPEC.json` (11 items: the mode flips per surface, six adapter writers, `memory.delta` consumer lane, filings feed, identity sources, sudoers for L1, citation index, M2 cutover, PG heartbeats, effort). Nothing is enforced until the operator flips a policy row.
## Findings fixed (operator: "fix findings", 2026-09-27 evening) `[VERIFIED by triage; fixes in this PR]`
**25 NO_OUTPUT breaches → 2 broken jobs, 15 wrong signals, 6 weekday lanes judged on a Sunday, 2 not yet due.**
| Root cause | Fix |
|---|---|
| The detector never queried the database, so every `db_max` lane read as silent | `supervisor_breach_detector` passes a read-only `db_query` (BEGIN READ ONLY … ROLLBACK) to `observe_signal` |
| The detector judged "3 × cadence" every day, so weekday/market-hours lanes breached every weekend | `scripts/lib/cron_schedule.py` (dependency-free 5-field cron parser); NO_OUTPUT now means "the last scheduled fire that had `max_run` to finish produced nothing"; `active_days` extends the cadence window; a declared `first_due` (e.g. `llm-spend-report-monthly` → 2026-10-01) is honoured |
| Signals that only move when the lane has work (outbox, lineage, candidates, notified_at) | pointed at the real per-run artifact (`cio_defer_revisit_last.json`, `logs/identity_sweep.log`, `logs/material_change_notify.log`, `logs/advisory_lessons.log`, dormant-lane consumers' own log); `cio-delivery` keeps its pinned outbox with a 24 h cadence; new signal kind `systemd_result` (last successful exit of a oneshot unit) for future use |
| Five signals pointed at absolute dev-tree log paths, stale since the crontab `PROJ` moved to CURRENT at 10:45 ET | made state-root-relative (`logs/…`): options thesis lifecycle, options memory projector, options runtime export, both alpaca stop managers |
| `instrument-belief-writer` signal read a count (`written_beliefs`) instead of a timestamp | key → `as_of` |
| `governed-agent-flash-market` still ACTIVE though its crontab line was retired (W0-7) | RETIRED with evidence |
| **JOB_BROKEN** `watch-review-workers`: every run refused `CONTAINMENT_REQUIRED:containment_not_active` since the operator's 09-15 "agents clear" archived the containment flag | `agent_jobs_containment.containment_cleared()` (the W0-1 precedent) and the watch-review policy gate honours the operator-cleared tripwire |
| **JOB_BROKEN** `indicator-cache-refresh`: 0 of ~800 symbols updated on three weekdays — yfinance "Too Many Requests" on every call, no backoff | `indicator_engine._history_with_backoff`: throttle, exponential backoff, and a run-level cooldown after 5 consecutive refusals (env-tunable) |
**19 unresolvable symbols → three causes, no hand-built map (AGENTS §7).**
- AIFF, GLND, HASI, SDOT: Schwab evidence (CUSIP + description) arrived with Saturday's sweep, after Friday's mint → the Monday 05:50 mint promotes them to CONFIRMED. Nothing to change; verify Monday.
- ABOVE, BLD, CXMT, EKSO: asked Schwab, `broker_returned_no_identifier`; the sweep's resume skips recorded misses. Re-ask is a sweep option (`--no-resume`), left to the Saturday lane or the operator.
- BOOK (53 artifacts), DYNC, EUDA, FUBO, IRTC, RIBB, STLN, SVCC, WBTN, YHNA, YXT: never entered the registry because the mint's symbol sources were holdings, watchlist and decision tables only. `mint_identity_registry._intelligence_surface_rows()` adds the symbol-thesis projection and the ticker research graph as additive sources; the Monday mint registers them UNRESOLVED and the Saturday sweep asks Schwab.

## Wave 2 · tranche 2 (branch wt/cogx-w2-t2-20260927)

| Deliverable | Where | Proof |
|---|---|---|
| **Defect fixed before any enforcement:** the façade's default loaders used bare imports; under the wake engine's, the Hermes worker's and thesis acquisition's sys.path shape every class degraded (`ModuleNotFoundError`) — 100 % of contexts on three lanes in the first live receipts | `intelligence_client._lib()` import shim (bare → `lib.` → `scripts.lib.` → path load) | regression test under a ROOT-only path; live proof under that shape: V → CONFIRMED, 6 facts, thesis v25, 2 beliefs, not degraded |
| UUID subjects (the wake passes `subject_guid`) resolve through the registry by GUID | `_resolve_subjects` + `Loaders.resolve_guid` | test |
| Per-lane context mode `context:<lane_id>` in the policy; ENFORCED + DECIDE + memory unreachable → the wake HOLDS (`MemoryUnavailable` propagates; runner records `outcome=error`; dispatcher retries; REFUSED row on the ledger) — row shipped as SHADOW | `intelligence_client.shadow_open`, `persistent_agent_wake` hook, `config/memory_influence_policy.json` | test: enforced lane raises, shadow lane never does, monitors degrade |
| Postgres heartbeat upsert from the detector and the projector (item 10) | `supervisor_breach_detector`, `gir_projector` | live after deploy |
| Wave 2 decision record | `docs/ops/COGX_WAVE2_APPROVAL_PACKAGE_2026-09-28.md` | ledger 29 rows verified |

## Wave 2 · flip 1 — `context:persistent-wake` → ENFORCED (branch wt/cogx-w2-enforce-wake-20260927)

Package item 1, first surface. Operator instruction 2026-09-27 21:38 ET: "flip persistent-wake to enforced when receipts are clean".

| Evidence | Value | Tag |
|---|---|---|
| Release under test | CURRENT = `aa14c24a9-main-exact-phase2-20260927-212341` (tranche 2 promoted 21:33 ET) | [VERIFIED] |
| Runner dry run from CURRENT (cron command + `--dry-run`) | rc 0; slot `2026-09-28T01:00Z` already complete; `would invoke run_scheduled_wake; no writes` for `HELD:XAR` (`instrument_record_due`) | [VERIFIED] |
| First context on the lane under the runner's path shape (project root only) on the new release | `ctx_21f4e27cd0a24e54` 01:40Z: mode SHADOW, **degraded False**, subject GUID `1527f991-…` → XAR, 5 facts, thesis present, contradiction_state OPEN; committed as `DRY_TEST` (no decision) | [VERIFIED] |
| Last contexts on the OLD release (01:27–01:30Z, other lanes) | degraded True, `IDENTITY_LOADER_FAILED:*:ModuleNotFoundError` — the tranche 2 defect, as expected | [VERIFIED] |
| Change | one policy row: `ring2.surfaces["context:persistent-wake"]`: SHADOW → ENFORCED | [CODE] |

What ENFORCED does on this lane: a DECIDE/ADVISE context that cannot open raises `MemoryUnavailable` from `shadow_open`; the wake hook propagates it; the runner records `outcome=error` for that subject and the dispatcher retries; a REFUSED row lands on the ledger. Contexts that open degraded still proceed (degradation is recorded, not fatal). Monitors are never held.

**Rollback (tranche 3, PR #1319, 22:40 ET):** the shipped ENFORCED rule also refuses any UNRESOLVED subject. The full CI wake gate groups (which the config-only flip PR did not run — a CI finding) showed the consequence on the tranche 3 branch: 63 wake tests HOLD because synthetic subjects are never in a registry, and in production any wake on a GUID the registry has not minted would HOLD the same way. Production never tripped (0 REFUSED; all three 22:00 ET subjects resolved), but main's full gate group is red with the row ENFORCED, so `context:persistent-wake` goes back to SHADOW in this PR. The semantics question is the operator's (§17 influence-ladder flips): (A) keep the strict rule and re-flip once the mint lane closes the identity gaps, or (B) narrow ENFORCED to HOLD only on a memory outage (a required class fails to load) and let an unresolved subject open degraded as in SHADOW, which changes the façade's refusal test. A narrowing was drafted and withdrawn here; it ships only on an explicit operator decision.

Rollback criterion (package §2): HOLD rate on the lane > 5 % of DECIDE contexts over any 24 h window, or any HOLD that is not `MemoryUnavailable` → revert the row (one-line PR) and report. Watch: `memory_contexts.jsonl` rows with `event=REFUSED` and `actor.lane_id=persistent-wake`, plus `outcome=error` in `~/logs/persistent_wake.log`.

## Wave 2 · tranche 3 — single write path, edge fan-out, citation index (branch wt/cogx-w2-t3-20260927)

Package items 2, 3, 4, 8 of `pkg-20260928-wave-2-enforcement-35c4`. Operator 2026-09-27 21:47 ET: "build 3 now … then push 3 and 4 live".

**Flip 1 verified first.** 22:00 ET cron on CURRENT `0a9680a59` (first ENFORCED cycle): 3 contexts opened in mode ENFORCED (ADBE, WMT, XAR), degraded False, all committed DECIDED; REFUSED rows 0; `outcome=error` 0. `[VERIFIED]`

| Deliverable | Where | Proof |
|---|---|---|
| Item 2 — ONE write path: `research_write_path.submit()` stamps memory provenance (context_id / retrieval_receipt_id / miss flag, captured BEFORE `shadow_commit` clears the process-current context), normalises to the ResearchResult shape, and either records a `WritePathReceipt@v1` (SHADOW) or calls the existing single writer (LIVE). Six producers spliced: hermes-external-* and hermes-cio-worker (passthrough receipts — they already reached the writer; now with provenance), watchlist-agent-*, advisory-desk-opinion, options-cio-review, aec-thesis-fact | `scripts/lib/research_write_path.py`; splices in `hermes_external_researcher.py`, `hermes_worker.py`, `process_watchlist_agent_jobs.py`, `advisory/advisory_opinion_engine.py`, `options_thesis_lifecycle.py`, `aec_command_center_cycle.py`; policy `write_path.adapters` (Hermes LIVE, four others SHADOW) | tests (mode precedence, shadow touches no store, live calls the writer with provenance, never raises, classification never upgraded) |
| Finding fixed on the way: the survey showed **no producer passed context_id into accept_research_result** (the façade clears the contextvar at commit), so every Ring 2 check on that surface was a MISS by construction | `stamp_provenance` before commit | test |
| Item 3 — memory.delta now fires on every non-MONITOR commit. Finding: Wave 1 emitted only when deltas were attached and no producer attaches deltas yet → **0 memory.delta events on the production bus** (grep, 02:05Z) | `intelligence_client.commit` | façade suite green |
| Items 3–4 — `edge-fanout-consumer` lane: bus consumer `edge-fanout` (memory.delta + thesis.changed, 48 h window) → bounded BFS over `intelligence.gir_edge` (depth ≤ 3, ≤ 200 nodes, 5 s statement timeout) → `EdgeFanoutWorkItem@v1` (reproject / notify: accounts that HOLD, beliefs that depend, sibling listings, open contradictions → cio) + `gir_projector_dirty.json`, which the projector now treats as a source and marks consumed (never deleted) | `scripts/edge_fanout_consumer.py`, `config/systemd/user/tradeai-edge-fanout-consumer.{service,timer}` (5 min), lane row NEVER_SCHEDULED, DSA row `edge_fanout_work_items` | live dry run from CURRENT against the production bus + graph: 11 events, 8 subjects, 35 items (13 reproject / 22 notify), pg=true, rc 0 `[VERIFIED 02:14Z]` |
| Item 8 — citation + deterministic index: after every accepted delta, rows into `intelligence.research_index` (thesis / catalysts / invalidation / bear_case → delta id; `citation` rows per canonical URL per day, URL + extraction ref only). Readers `latest()` / `cited_urls()` for the ladder | `scripts/lib/research_index_writer.py`, hook in `research_thesis_delta.accept_research_result`, DSA row `intelligence_research_index` | tests (canonical URL, rows, fail-soft without a DSN, kill switch) |
| Governance | 3 DSA rows (approval = pkg 35c4), `docs/SOURCE_OF_TRUTH.md` + AGENTS §7A re-rendered, lane row, CI gate `cogx_w1_foundations` += `tests/test_research_write_path_and_fanout.py`, dark-contract reason on the new entrypoint | validators green (DSA findings=0, dark contracts, chokepoints 137/137, unlisted coverage 0) |

Notes: (1) a probe `memory.delta` event (source `probe`, LOW) was written to the production bus at 02:05Z while diagnosing the missing events — harmless, the consumer counts it as unresolved. (2) `tests/test_advisory_desk_phase2.py::test_build_evidence_stats` fails in any worktree without production data (it builds the live desk); it passes in the dev tree and is unrelated. (3) `check_lane_registry --fail-on-new` exits 1 on main too (undeclared host crons from other campaigns).

**Deploy needs (operator):** release-write (merged SHA, campaign), a service grant to install + enable `tradeai-edge-fanout-consumer.timer` from CURRENT, `seed_supervisor_sla.py --apply` (db-write) for the new lane's SLA row. LIVE flips for the four SHADOW adapters are later one-line policy PRs after their receipts show sane classifications.

## Wave 2 · tranche 4 — SEC filings feed → EVENT nodes → material changes (branch wt/cogx-w2-t4-20260927, stacked on tranche 3)

Package item 5. Operator 2026-09-27 21:48 ET: "and build 4 … then push 3 and 4 live".

| Deliverable | Where | Proof |
|---|---|---|
| `scripts/sec_filings_feed.py` — free EDGAR submissions API (fair-access User-Agent, 0.15 s spacing, one request per symbol per run, ticker→CIK map cached 7 days); every 8-K / 10-Q / 10-K inside the window becomes an immutable `FilingEvent@v1` keyed `uuid5(issuer_guid \| FILING_<form> \| accession)` (a sibling listing names the same event); identity resolved through the registry (unresolved → skipped and counted); append-only JSONL deduped on event_guid; UNAVAILABLE counted, never read as "no filings" | `data/cio/sec_filing_events.jsonl`, `data/runtime/sec_filings_feed_latest.json`, heartbeat lane `sec-filings-feed` | live dry run (no writes) NOC, DELL, LDOS, BAH, 45 d: 4 fetched, 6 events, 2 high — DELL 2026-09-01 8-K Item 2.02 (the EX-99.1 filing the options desk cited) and DELL 2026-09-15 Item 1.01 `[VERIFIED 02:19Z]` |
| GIR: source 4b projects each row to `EVENT:<guid>` (class MARKET, kind EVENT, freshness IMMUTABLE) with `EVENT —AFFECTED_BY→ SEC:<security_guid>`; the feed file is an incremental-trigger source | `gir_projector.py` | test (3 nodes, 2 edges, 1 unresolved counted) |
| Wake entry: `material_change_detector.new_filings` — HIGH-severity filings (Items 1.01 / 1.03 / 2.01 / 2.02 / 4.02) on tracked names observed inside `NEW_HOURS` → `MaterialChange@v1` kind `sec_filing` (magnitude by catalyst type, precedence from the universe). The detector stays the single Market owner (02 §2); 10-Q/10-K are graph events only. Finding it fixes: today only Item 2.01 filings could reach the wake, indirectly via `catalyst_events` weights — earnings 8-Ks were dropped | `material_change_detector.py` (`--kind sec_filing` added) | test (fired 1 / untracked 1 / below severity 2 / outside window 1; deterministic change_guid) |
| Governance | lane row `sec-filings-feed` (cron 08:20/12:20/17:20/21:20 ET market days, NEVER_SCHEDULED until the cron grant), DSA row `sec_filing_events` (provider `sec_edgar`, approval pkg 35c4 item 5), crontab line in `docs/ops/COGX_WAVE2_CRONTAB_LINES.txt`, source-of-truth re-rendered, CI gate += `tests/test_sec_filings_feed.py`, dark-contract reasons | validators green |
| Fix carried from tranche 3 | `edge_fanout_consumer.state_root` / `sec_filings_feed.state_root` resolve through `canonical_store_registry.production_state_root` (the consumer's first dry run only worked because cwd was CURRENT) | first feed dry run from the worktree resolved 0/4 identities until the root was pinned |

**Deploy needs (operator):** release-write (merged SHA), cron grant to append the one crontab line, `seed_supervisor_sla.py --apply` for the lane's SLA row, then one `sec_filings_feed.py --apply` from CURRENT and a projector `--apply` so the first EVENT nodes exist before the next detector cycle.

## Wave 2 · tranches 3 + 4 LIVE — closeout (branch wt/cogx-w2-closeout-20260927)

Operator ran `docs/ops/COGX_WAVE2_T3_T4_OPERATOR_HANDOFF_2026-09-27.md` 2026-09-27 22:43–22:45 ET: #1319 merged `37a06db39`, #1321 merged `f677855fa`, CURRENT = `f677855fa-main-exact-phase2-20260927-224302`. `[VERIFIED 22:52 ET]`

| Proof | Value |
|---|---|
| `tradeai-edge-fanout-consumer.timer` | enabled, first run 22:44:04 ET: 35 work items (13 reproject / 22 notify → 8 accounts, 4 beliefs, 10 cio contradiction notices, 3 sibling listings), `pg: true`; second run 22:45 found 0 new events (cursor advanced) |
| `sec-filings-feed` first `--apply` (45 d) | 67 symbols, 51 fetched, 49 `FilingEvent@v1` (10 high — DELL 09-01 earnings + 09-15 material agreement, ADBE 09-10 earnings, CSWC ×2, SPCX, GSIT, SIBN, GOVX, P), 15 no CIK (funds / ETFs), 1 unresolved identity, 0 unavailable; crontab line present (1) |
| GIR after projector `--apply` | 49 `MARKET:EVENT` nodes, 49 `AFFECTED_BY` edges in `intelligence.gir_entity` / `gir_edge`; 142,211 entities / 251,680 edges total |
| SLA rows (`seed_supervisor_sla --apply`) | `edge-fanout-consumer` max_silence 600 s; `sec-filings-feed` 64,800 s |
| Lane rows | both flipped NEVER_SCHEDULED → ACTIVE in this PR with the evidence above |
| Write-path receipts | `research_write_path_receipts.jsonl` not yet created at 22:52 ET — no producer has run on the new release yet; expected on the next Hermes / watchlist / advisory cycle |
| Detector `--kind sec_filing` | first cycle after promote is the 23:00 ET `*/30` run; `stats.sec_filing.fired` expected > 0 (10 high-severity events inside `NEW_HOURS` by observed_at) |

Still open for the operator: flip 1 semantics (row is SHADOW); package items 7 (sudoers) and 9 (M2 cutover apply); LIVE flips for the four SHADOW write-path adapters after their receipts show sane classifications.

## Waves 3–5 package SENT (2026-09-27 22:53 ET)

`pkg-20260928-waves-3-5-cognition-unification-maturity-80f2` — 18 items (spec `docs/ops/COGX_WAVE3_5_PACKAGE_SPEC.json`), created in the live ledger, sent as two chunks (Telegram 54509 / 54511), SUBMITTED (ledger 31 rows, chain ok). Finding: the inline approve/deny buttons fail (HTTP 400) for this package id because `pkgapprove:<id>` is 68 bytes and Telegram caps callback data at 64 — the typed reply (`APPROVE <pkg> all`) is the approval route; a short-id alias for buttons is a Wave 3 fix on the callback handler. Building starts immediately in SHADOW; each item deploys under its own scope after the reply.

Detector first cycle after tranche 4 (23:00 ET): 5 `MaterialChange` rows of kind `sec_filing` (ADBE, SPCX, CSWC ×2, GSIT — the high-severity filings on tracked names). `[VERIFIED]`

## Wave 3 · tranche 1 — Cognition (branch wt/cogx-w3-t1-20260927; package pkg-…-80f2 items O-W3-1..4, B-W3-1)

Operator 2026-09-27 22:55 ET: "do rest of waves now". Everything below ships dark: every surface row stays SHADOW, promotion needs an operator reply, the adjudicator lane is NEVER_SCHEDULED until the service grant.

| Item | Deliverable | Where | Proof |
|---|---|---|---|
| O-W3-1 | `CognitiveCheckpoint@v1` per agent, hash-chained, written by the façade on every non-MONITOR commit (task_ref WAKE:/RUN:/CTX:, considered / waiting_on / next_action when the agent passes them); `restore()` + `ResumeReceipt@v1`; `shadow_open` attaches the last checkpoint (`resumed_from`, open waits, open commitments) — no authority, the agent re-validates | `scripts/lib/cognitive_checkpoint.py`, façade `_auto_checkpoint` + `shadow_open`; store `data/cio/agent_checkpoints/<agent>.jsonl`; kill switch `TRADEAI_COGNITIVE_CHECKPOINT=0` | tests (chain, restore, kill switch, monitors never checkpoint, façade attaches resume) |
| O-W3-2 | ONE lesson promotion queue (`LessonPromotion@v1`) over the five disconnected stores; only PROMOTED rows reach `MemoryContext.lessons` (was hardcoded `[]`); `decide` refuses any non-operator actor; weekly batch = an ApprovalPackage | `scripts/lib/lesson_promotion.py`, `scripts/lesson_promotion_cli.py`, façade loader `lessons`; store `data/cio/lesson_promotions.jsonl` | live gather on production stores: **617 candidates** (599 LessonCandidate@v2, 14 iris-"ratified" KB rows, 3 KB candidates, 1 procedural hint); 0 promoted → contexts unchanged `[VERIFIED 23:15 ET]`; tests |
| O-W3-3 | `contradiction-adjudicator` lane: newest subjects first (consumer digest) → DeepSeek Flash judge → `ContradictionVerdict@v1`; spend fail-closed on the process cap ($0.50/day, registry entry `contradiction_adjudicator`) AND the Tier-2 policy ($2/day, off-peak, deepseek, unknown spend = deny); verdicts close pairs in the façade (`open_contradictions`) and the GIR (`CONTRA:` + SEC envelope `{state, open, resolved}`) | `scripts/contradiction_adjudicator.py`, units `tradeai-contradiction-adjudicator.{service,timer}` (19:30 local), lane row NEVER_SCHEDULED, DSA row | live dry run: 129,547 candidates scanned, 0 judged, 5 selected (RTX pairs), no call made `[VERIFIED 23:13 ET]`; tests (selection, parsing, fail-closed gate, verdicts close pairs in façade + projector) |
| O-W3-4 | Influence ladder per surface (`memory_influence.mode_for` reads `policy.influence` — nothing did before; the code knew only SHADOW/ENFORCED); under ADVISORY+ the model SEES a named "MEMORY SAYS" block with lineage and RECONSIDER / CONTESTED / STALE flags, never merged into evidence; receipts carry `mode / surface / mir / memory_content_present / would_render`. Spliced: Hermes external (context now opens BEFORE the prompt is built), Hermes CIO worker (`prompt_context.memory_advisory`), watchlist agents (appended to the context text) | `scripts/lib/memory_influence.py`, façade `shadow_open(surface=…)` + `commit`, splices | live proof on production state with the mode forced to ADVISORY for one process (receipts to scratch): see below; policy rows unchanged (SHADOW) so nothing renders in production |
| B-W3-1 | judge inside the existing caps; no new paid lane | registry entry | — |

**Live proof (O-W3-4, 23:20 ET, production state, mode forced to ADVISORY for one process, receipts to scratch):** `shadow_open("hermes-cio-worker", ["V"], surface="research")` rendered the block — thesis v25 (hold, CURRENT, 17 h), two calibrated beliefs (HOLD 17/17, TRIM 0/20), 7,698 open contradictions → flag CONTESTED; commit receipt `{mode: ADVISORY, surface: research, mir: true, memory_content_present: true}`; a checkpoint was written and the second open resumed from it. `[VERIFIED]`

**Findings fixed on the way:** (1) the façade's facts class returned the provider's NEAREST memories, not the subject's — XLB / XAR / DELL / BOOK case summaries came back for V (5 of 5) and would have been rendered as V's memory under ADVISORY; facts that name neither a requested symbol nor GUID are now counted (`facts_off_subject`) and not carried. (2) facts / beliefs / theses are structured rows (memory refs, calibrated beliefs), not prose — the renderer prints their real fields (type, freshness, confidence, lineage; belief key + track record) instead of empty claims.

Governance: 3 DSA rows (`agent_checkpoints`, `lesson_promotions`, `contradiction_verdicts`), lane row, CI gate += `tests/test_wave3_cognition.py` (7), dark-contract reasons, source-of-truth re-rendered; validators green; 583 tests across the touched modules pass — the 4 failures (`test_gate_b2_closure`, `test_governed_agent_flash_market`, flash canary) are pre-existing on main.

## Wave 4 · tranche 1 — Unification (branch wt/cogx-w4-t1-20260927, stacked on Wave 3; package items O-W4-1..5)

Everything ships in SHADOW or as a reference implementation: no routing, model lane, page or restart changes until the operator flips a switch.

| Item | Deliverable | Where | Proof |
|---|---|---|---|
| O-W4-2 | **One agent registry** (`AgentRegistry@v1`, 23 agents): canonical id, the aliases it absorbs (maria/maria_research, aegis/aegis_core, steph/steph_allocation, tax_agent/ledger, cio/alex/cio_agent, risk_agent/guardian/risk), role, lanes, bus events, model caller. The wake spine keeps `cio` as the CIO id. `route_to_agents` answers from the static map (SHADOW) and records every disagreement; `TRADEAI_AGENT_REGISTRY_ROUTING=1` flips to the registry. `KNOWN_AGENTS` = the five + registry wake-eligible ids. `memory.delta` is deliberately routed to no agent (the fan-out consumer owns it) | `config/agent_registry.json`, `scripts/lib/agent_registry.py`, hooks in `cio_event_bus`, `persistent_agent_wake` | test: every id in the four hard-coded lists resolves; shadow routing unchanged + receipt; flag → registry routing |
| O-W4-3 | **One model chooser** (`model_chooser.choose/apply`): lane + policy + model from the process registry's `allowed_lanes` / `deepseek_default_policy` / `lane_policy`; free lane first unless `deepseek_only`; paid-cap-exhausted → free allowed lane. Modes `shadow` (default: caller's lane kept, disagreement receipts), `advise` (only when no caller lane), `enforce` (only replaces a lane the process does not allow). Hooked into `gate_and_generate` and the governed bridge (receipt beside its hard-coded map) | `scripts/lib/model_chooser.py`, hooks | tests (shadow/advise/enforce, dedup of allowed_lanes, never introduces a paid provider) |
| O-W4-4 | **Graph-native decisions and actions**: `DEC:` (options thesis decisions from the file, `cio_decisions` from Postgres read-only, 90 d / 5,000 cap) with `DECIDED_ON` → SEC and `SUPERSEDES`; `ACT:` (action ledger CREATED events) with `CAUSED_BY` → DEC / RUN and `TRIGGERED` → SEC (symbol from `affected_symbols`, else recovered from the title — finding: the ledger payload never sets `affected_symbols`) | `gir_projector.py` source 4c + fingerprints | dry run on production state: 5,014 decisions, 16,980 actions, 259 decision symbols unresolved; 164,212 entities / 288,514 edges `[VERIFIED 23:58 ET]`; tests |
| O-W4-5 | **Ladder L4/L5** in the breach detector: L4 pages the operator through the ops-exempt path (`STOP HEALTH` signature, one page per breach via `alert_transition`) when a breach stays OPEN ≥ 3 h and the SLA row's `ladder_max ≥ 4`; L5 writes an `OrchestrationProposal@v1` when a lane × kind recurs 3× in 7 d and `ladder_max ≥ 5`. SHADOW unless `--ladder` (receipts only; the installed timer runs without it). **Finding fixed:** the L3 call passed one argument to `enqueue_escalations(policy, findings)` and rows without `severity` — the TypeError was swallowed, so L3 had never enqueued anything | `supervisor_breach_detector.py` | tests (shadow records, no page; live pages once; ladder_max caps; L5 proposal) |
| O-W4-1 | **Worker contract** (`WorkerLease@v1`): one lane lease (owner / boot_id / TTL, flock, stale reclaim recorded), the shared status vocabulary with the mapping from every queue's words, one heartbeat at exit; `edge-fanout-consumer` is the reference lane (a concurrent run gets `LeaseHeld` and exits 0). Migration order per lane in the doc. Finding recorded: `watchlist_agent_jobs` claims without `FOR UPDATE SKIP LOCKED` | `scripts/lib/worker_contract.py`, `docs/architecture/WORKER_CONTRACT.md`, `edge_fanout_consumer.py` | tests (lease, vocabulary, reclaim) |
| O-W4-6 | WEIGHTED mode renders the advisory block plus an explicit weighting instruction (advice ranking / wording only; MBI_BEHAVIOR = 0 stated in the text); rows stay SHADOW | `memory_influence.render` | test |

Governance: 3 DSA rows (`agent_registry` manual/PR-only, `model_chooser_receipts`, `supervisor_ladder_receipts`), CI gate += `tests/test_wave4_unification.py` (7), source-of-truth re-rendered, `cio_governed_model_bridge.py` edited byte-wise (CRLF preserved). Deploy needs: release-write only (no new lane, no grant); the flips (`TRADEAI_AGENT_REGISTRY_ROUTING=1`, `TRADEAI_MODEL_CHOOSER=advise|enforce`, `--ladder`, S-W4-1 sudoers for L1) are operator switches after the receipts are read.

## What is NOT in Wave 1 yet (after the operator runbook)
- The `memory.delta` bus consumer (Wave 2) — until then the projector is hourly-incremental by source fingerprint.
- The operator steps in the runbook: credential rotation, roles + migration, merge + deploy, grants, lane install, first real runs.
- Post-deploy validation (stage 6) and marking the package items EXECUTED / VALIDATED.
- Per-package guard grants stay manual (classifier refusal).

## Operator-executed prerequisites (unchanged)
1. Rotate the plaintext DSNs (BWS edit → render → ALTER ROLE).
2. One superuser session on production: `CREATE ROLE intelligence_reader NOLOGIN; CREATE ROLE intelligence_writer NOLOGIN;`
   then `psql -d trade_ai -f migrations/2026_09_27_intelligence_v1.sql`, then the GRANT lines from the migration header.
   Rollback: `migrations/2026_09_27_intelligence_v1.down.sql` (safe); full revert is the operator's reviewed `DROP SCHEMA`.

## Closeout format (AGENTS.md §14) — filled at wave exit
Shipped: this PR. Found: `report_docs_inventory` indexes only tracked files (git add before `--write-index`); `pg_tables` has no `forcerowsecurity` column (use `pg_class.relforcerowsecurity`). Closed as already merged: none. Stopped: none. Unpublished: nothing deployed. Operator-only list: unchanged (2 prerequisites above + the 09-27 inherited items).
