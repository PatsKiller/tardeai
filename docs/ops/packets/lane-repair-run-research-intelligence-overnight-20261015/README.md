# Lane repair 2026-10-15: RI overnight, hermes-coordinator, source litmus

The operator asked to "turn these on and then re-engineer them for n8n". The lane-disposition audit
(`docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.md`, branch `n8n/lane-disposition-wave1-20261015`) found
three lanes broken:

| Lane | How it failed | Root cause |
|---|---|---|
| `run-research-intelligence-overnight` | `ingest` exit 124 every run | The work had no bound. The 30-minute timeout was not too tight. |
| `hermes-coordinator` | `completed: false` on every tick | The `research_curator` child exited 1 on a foreign-key violation. |
| `source-litmus-vs-yahoo` | exit 1 | A BLOCK finding was written as a failed run. One sub-penny tick or one noisy row could BLOCK a source. |

The code fixes and the n8n SHADOW wiring are in the PR that carries this packet. **Only lane 1 needs a crontab
change.** That change is this packet's candidate. It is not installed: you install it under a `cron` grant
(`03_apply.md`).

## Incident: an agent probe wrote to prod `llm_process_config`. Your call.

At 09:44:36 ET the dry-run proof script called `lib.llm_consumption.should_call(...)`. The docstring says
"decision only", but the call writes. It runs `get_process_config` → `ensure_schema()` → `_seed_registry()`, and
that upserts `llm_process_config` from the registry file of the checkout it runs in, which was this branch. The
agent's rail allowed SELECT only, so this write broke the rail.

| What changed in prod | Effect while CURRENT still has the old registry |
|---|---|
| 59 rows had their `updated_at` refreshed. Their other values match main, which is what CURRENT already seeds. | None. |
| 2 new rows were inserted: `ri_narrative_enrich` and `topic_research_synthesizer` (grok/chatgpt, 120/$0.10 and 600/$0.25). | None. CURRENT's registry does not list these ids, so `get_process_config` still returns "unregistered" before it reads the database. |
| `topic_ingestion`: `daily_soft_cap` went from NULL to **600** and `daily_cost_cap_usd` from NULL to **0.25**. | **Live now.** `get_process_config` takes non-NULL caps from the database, so `topic_ingestion` is capped at 600 calls a day ($0 OAuth; the busiest day measured was 348). This is the cap the PR proposes, but it took effect without review. |

No rollback has been run. Running one is another prod write, and that decision is yours. To undo the change:

```sql
-- psql as trade_ai, in one transaction
BEGIN;
UPDATE llm_process_config SET daily_soft_cap = NULL, daily_cost_cap_usd = NULL WHERE process_id = 'topic_ingestion';
-- optional: the two new rows are inert until the PR deploys, and the deploy re-seeds them anyway
-- DELETE FROM llm_process_config WHERE process_id IN ('ri_narrative_enrich', 'topic_research_synthesizer');
COMMIT;
```

The undo can wait for the PR. When the PR deploys, the seed writes the same values from the reviewed registry.
`should_call` and `get_process_config` are documented as read-only but write. That is a separate defect and needs
its own fix.

## Lane 1: `run-research-intelligence-overnight`

**Evidence**

- `logs/ri_overnight.log`, 2026-10-13 and 2026-10-14: `FAIL ingest exit=124` after exactly 30 minutes, with no
  progress lines. Python block-buffered its stdout, so the SIGTERM discarded the output. `TOPIC INGESTION COMPLETE`
  appears 0 times in `ri_overnight.log` and 0 times in `topic_ingestion.log`. The standalone 20:45 line has never
  finished either.
- Where the time went (`llm_consumption_log`, `topic_ingestion`, 2026-10-14 20:45–21:30 ET): **331 serial OAuth
  rating calls**, 326 on grok (mean 10.6 s) and 5 on chatgpt. That is about 3,490 s of model latency inside a
  1,800 s window. The cause is one model call per search result (about 50 results per topic) with no per-topic cap
  and no run budget, so `--max-topics 20` needed about 10,500 s.
- Each result was rated before the duplicate check, so an article already stored still paid an 11 s call before it
  was dropped.
- At 20:45 the standalone ingestion line runs the same stalest-first topics. The two runs were not batch-locked.
- The provider journal (`provider_request_journal.jsonl`) has 0 `topic_ingestion` rows. These calls do not go
  through the cio bridge; they use the in-process consumption gate.
- Lock waits: none. Every step takes `flock -n`, and no SKIP_LOCK appears in the log.
- `narrative` exits 1 on every run. All 25 rows × 2 lanes got `PROCESS_NOT_REGISTERED`, because
  `ri_narrative_enrich` was never registered. The step also claimed `manual_trigger=True`, which is the one
  off-peak exemption, on a cron run.
- `topic_research_synthesizer` (the `topic_synth` and `reground` steps) called `llm_lane.generate` with no
  `process_id`. That skips the consumption gate entirely: no registration check, no cap and no log row.
- The 02:15 (`--phase full`) and 05:15 (`--phase archive`) lines log `PEAK_SKIP` every day. Under EDT, 02:15 ET is
  06:15 UTC and 05:15 ET is 09:15 UTC, and both fall in the official DeepSeek peak window the `--official`
  wrapper skips. Only the 20:30 run ever does work.
- `ri_overnight.log` wrote every line twice: the script's `tee -a "$LOG"` and the cron redirect both appended.

**Fix (code)**

- `topic_ingestion.py`:
  - `--budget-s`: no new search or model call starts once the budget is spent.
  - `--max-items-per-topic`.
  - Already-stored and blocked results are skipped **before** the model call.
  - A topic that is cut short keeps its old `last_searched`, so the next run resumes it first. The database is the
    checkpoint.
  - A non-blocking batch lock: a second run exits 75 and still writes its receipt.
  - SIGTERM unwinds through `finally`, so the run receipt is still written.
  - stdout is line-buffered.
  - The receipt gains `produced_count`, `attempted_count`, `skipped_reasons` and `empty_reason`.
- `run_research_intelligence_overnight.sh`:
  - Ingest runs with `--budget-s 1500 --max-items-per-topic 12` inside `timeout 30m`, which stays as the backstop.
  - Narrative gets `--budget-s 900`.
  - All values can be overridden through the environment.
  - Each line is logged once.
  - The lane receipt sums the output fields of this run's ingest and narrative receipts
    (`completion_compound_receipt.py --output-receipt/--since`).
- `research_intelligence_narrative_enrich.py`:
  - Uses governed cloud lanes only.
  - No longer passes `manual_trigger`.
  - Stops at the first governance refusal instead of trying 50 calls.
  - Gets a budget and a receipt.
- `topic_research_synthesizer.py`: calls through `lib.governed_cloud_generation.generate_cloud` with
  `process_id="topic_research_synthesizer"`, on grok then chatgpt.
- `config/llm_process_registry.json` and `config/llm_routing_policy.json`:
  - `ri_narrative_enrich` and `topic_research_synthesizer` are registered.
  - `topic_ingestion` gets caps.
  - All three are on grok/chatgpt OAuth (settled at $0). The cost caps are guards, and `LLM_GLOBAL_DAILY_USD_CAP`
    still binds.

**Dry run** (`dry_run_proof_20261015.json`; no model call):

- `--phase full --dry-run` prints the bounded plan and writes nothing.
- Plan arithmetic at the measured 10.5 s per call: about 152 s per topic (12 × 10.5 s + about 25 s of search), so
  about **9 topics per 1,500 s run**, against 0 completed before.
- Gate decisions: all three processes return `allow: true`, mode `automated`. See the Incident section for the
  write this probe caused.

**n8n SHADOW wiring.** The lane is **staged, not runnable**. The registry row carries `r1_pending`:

- `scheduler.stage: shadow`.
- `dispatch {mode: dry_run, class: llm}`.
- The LaneRunReceipt output signal.

It is not activated because the run allowlist cannot hold it yet. An llm entry must name a bridge-routed process
(`llm_route.process_id`), and none of `topic_ingestion`, `topic_research_synthesizer` or `ri_narrative_enrich` has a
cio-governed-bridge route. `n8n_run_executor.validate_entry` returns `llm_process_route_not_registered`, and a test
pins this. The executor also binds one `TRADEAI_LLM_PROCESS_ID` per run, and this compound uses three.

The reason is recorded in `config/n8n_run_allowlist.json` `blocked_reasons`. What is already in place:

- The health contract is REVIEWED, with `expected_output` `N8nExpectedOutput@v1`, `per_window` ≥1 item in 72 h.
- The effect key is staged (`append`, `llm`; `cron_claim`/`n8n_claim` false).
- The import closure has no sender and no broker module (`advisory_lane_guard`).

Activation needs a bridge-route PR for the three processes, or one lane per step. That PR includes the map entry,
`resolve_model_policy`, `sync_cio_process_caps` and a bridge restart (AGENTS "Every bridge caller names itself").

## Lane 2: `hermes-coordinator`

**Evidence**

- `logs/hermes_coordinator.log`: `research_curator: exit 1 — DETAIL: Key (id)=(239) is still referenced from table
  "strategy_watchpool"` on 485 ticks since 2026-10-05 14:33.
- `research_critique_pipeline.retention_purge` deletes curator-archived `watch_directives` older than 60 days.
- Read-only counts: 12 of the 93 eligible rows are still referenced by `strategy_watchpool` (`ON DELETE` is not
  cascade), so the DELETE raises.
- The curator exits 1, the coordinator returns 1, and the lane receipt says `completed: false`.
- `hermes_research_intelligence` has non-cascading children too: `hermes_alerts`, `hermes_embedding_queue` and
  `hermes_memory_events`.

**Fix (code)**

- `PURGE_FK_CHILDREN` holds a `NOT EXISTS` guard for every non-cascading foreign-key child. A referenced row is
  kept, never deleted.
- Each pass is capped at 2,000 rows, because about 19.6k archived research rows built up while the purge was
  blocked. With the curator running every 15 minutes, the backlog drains over about 10 ticks.
- The archive, sha256 manifest and tripwire before each delete are unchanged (`lib.retention_archive.managed_purge`).

**Dry run.** `managed_purge` with `apply=False` against prod in a READ ONLY session:

- Directives: 93 eligible under the old predicate, 81 under the new one.
- Research rows: 19,581 eligible under the new one, all purged through the archive.

**n8n:** **excluded**, with the stated reason recorded in `blocked_reasons`. The import closure reaches broker
modules and raw senders. `advisory_lane_guard.scan_entry` finds:

- On the coordinator: api_v2/schwab_transport order context and `telegram_transport` api.telegram.org.
- On its children: `research_curator` reaches `schwab_transport`, `alpaca_paper_adapter` and
  `proposal_paper_submitter` `send_telegram`.

The lane stays on host cron until that closure is cut.

## Lane 3: `source-litmus-vs-yahoo`

**Evidence.** The 2026-10-15 07:47 run exited 1 with three BLOCKs:

| Source | Result | What it was |
|---|---|---|
| `market_quotes` | 3/114 off by more than 10% | A real finding: NVNI is 707% off, RKLZ and PFAI are 13–15% off. |
| `holdings` | 1/1 | SRNE stored 0.0003 against Yahoo's 0.0002. That is one $0.0001 tick, scored as "50% off". |
| `finviz` | 1/40 | XCUR 13%. A single row in a 40-row sample already exceeds the 2% share. |

The lane receipt said `status: failed` whenever the check found what it exists to find.

**Fix (code)**

- A difference of one minimum tick or less is a match (SEC Rule 612 increments).
- A source BLOCKs only on ≥2 badly-off rows or on one gross row above 50% off. The 2026-09-14 sub-share-value
  incident still BLOCKs, and a test pins it. One moderate row is a WARN.
- The receipt is `ok`, with `summary.verdict` set to PASS, WARN or BLOCK and the v2 output fields (`produced_count`
  is the number of rows compared).
- Exit 1 on BLOCK is kept, because the systemd unit has `SuccessExitStatus=0 1`. `--exit-zero-on-block` is there
  for a scheduler that reads any non-zero exit as a failure.

**Replay of 2026-10-14** through the new rule: a BLOCK on `market_quotes` 3/114 (real) and a WARN on `finviz`.
`holdings` is a match.

**n8n SHADOW**, admitted:

- The registry row is `scheduler.stage: shadow`, with `dispatch {mode: dry_run, class: monitor, cron "45 7 * * 2-6"}`
  mirroring the timer's `Tue..Sat 07:45`. Its output signal is the LaneRunReceipt.
- The allowlist entry has `dry_run_arg ["--dry-run"]` and `live_arg null`. The lock `/tmp/source_litmus.lock` is
  PROPOSED, because the unit takes no lock.
- The "verify the unit" blocker was checked with `systemctl --user cat` and removed.
- No effect key: the lane is read-only.
- The health contract is REVIEWED, with `expected_output` `min_produced` 1 and typed `reference_unavailable` as an
  allowed empty.

## Operator packet (lane 1 crontab)

| File | What it is |
|---|---|
| `candidate.py` | Builds `crontab.candidate` from the LIVE crontab by exact-line replacement. It refuses on any drift, and `--revert` builds the rollback. |
| `02_dry_run_live.txt` | The candidate diff against the live crontab of 2026-10-15 (sha256 `6a5c6768…`): 4 lines changed. The rollback is byte-identical. |
| `03_apply.md` / `04_rollback.md` | Install under a `cron` grant, with a forced run as proof. Restore. |

The four changes:

| Change | Line | Before | After | Why |
|---|---|---|---|---|
| C1 | L731 | RI `--phase full` at 02:15 | 00:15, wrapper kept | 00:15 ET is 04:15 UTC under EDT and 05:15 UTC under EST, both outside the official peaks. |
| C2 | L732 | archive at 05:15 behind the DeepSeek wrapper | 05:15, no wrapper | The archive phase makes no model call. |
| C3 | L736 | standalone topic ingestion at 20:45 | adds `--budget-s 1500 --max-items-per-topic 12` | Bounds it like the RI ingest step. |
| C4 | L737 | standalone topic ingestion at 02:45 | the same bound, schedule unchanged | Bounds it like C3. |

Note on C3 and C4: the registry already lists these two lines as `topic-ingestion-cron-lines` RETIRED into a family
slot, but they are still in the crontab. Retiring them is the family packet's job. Until then, C3 and C4 bound them,
and the new batch lock stops them from overlapping the RI ingest step.

The code fix needs none of these changes to stop the exit 124. C1 and C2 make the two dead lines do work, and C3
and C4 stop the standalone line from being killed at 30 minutes.
