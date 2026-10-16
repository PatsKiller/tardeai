# n8n process consolidation, cohort 1 (2026-10-16)

The operator's direction, 2026-10-16: move the Hermes and research dependencies into explicit n8n flows. Each flow
should branch on verified results and start downstream work when its inputs are ready. Where practical, events or
watermarks should replace polling. Continuous shadow rehearsals stop for accepted production lanes; purposeful
regression and canary checks stay. Dry and live worker time are reported alongside execution counts. Queue wait and
runtime are measured before any change to worker capacity.

This PR delivers the following:

| Item | What | Runtime effect |
|---|---|---|
| B1 | `scripts/report_n8n_capacity.py`: a read-only report of per-lane dry and live queue wait, runtime, worker-seconds and executor concurrency | none |
| B2 | Dependency map (below) | none |
| B3 | First explicit flow: `run_done` triggers gain `require_verdict`, and the research news chain fires on the upstream's verified result | The event fire of the shadow (dry_run) lane `news-to-catalyst` is now gated on `hermes-news-bridge` output verdict `produced`. The trigger on the live lane `research-insight-extractor` stays inert (`EVENT_MODES` is dry_run only) until an operator event canary |
| B4 | `config/n8n_shadow_policy.json`, `scripts/lib/n8n_shadow_policy.py` and `scripts/report_n8n_shadow_policy.py`: a regression-canary planner plus shadow-cadence proposals | none (mode `report`, the only mode) |
| B5 | Capacity measurements and a recommendation | none (no worker or retry change) |
| B6 | LLM route evidence for the flow | none |

**Dependency:** PR #1822 (`scripts/report_n8n_dry_run_load.py`, one day, dry-run buckets) is complementary. This
report covers a window, splits dry from live, and adds queue wait and concurrency. The two share no file, so either
can merge first.

Everything was measured read-only from `~/trade-ai-releases/persistent-state/data/runtime/n8n_runs/*.json`. The
window is 2026-10-09T17:30Z to 2026-10-16T17:30Z.

## B1 + B5. Capacity (7 days)

`python scripts/report_n8n_capacity.py --days 7 --now 2026-10-16T17:30:00Z --lanes 0`

| | runs | worker-s | lanes | duration p50 / p95 / max (s) | queue wait p50 / p95 / max (s) | waits > 30 s |
|---|---|---|---|---|---|---|
| dry_run | 6,078 | 8,998 | 107 | 0.30 / 1.68 / 674 | 1.12 / 4.55 / 136.7 | 24 |
| live | 5,442 | 32,567 | 36 | 0.46 / 24.8 / 1,101 | 1.26 / 2.66 / 134.9 | 3 |

Executor:
- Worker slots observed: 4 (`w0`..`w3`; config `max_workers` is 8, so the env runs 4).
- Peak concurrency: 4.
- Mean busy workers: 0.069, which is **1.7% utilization**.
- Time with 0/1/2/3/4 workers busy: 94.1% / 5.0% / 0.64% / 0.17% / 0.007%.
- **Saturated (all 4 busy): 42.6 s in 7 days.**

By stage:

| stage | lanes | dry runs | dry worker-s | live runs | live worker-s |
|---|---|---|---|---|---|
| shadow | 44 | 4,571 | 4,056 | 1 | 0.5 |
| canary | 36 | 711 | 3,542 | 1,435 | 1,692 |
| cutover | 6 | 692 | 447 | 149 | 883 |
| (no stage: n8n infra lanes) | 27 | 104 | 952 | 3,857 | 29,992 |

Top consumers:
- `n8n-incident-fanin`: live, 2,012 runs, 28,512 worker-s (88% of live worker time; p50 15.7 s).
- `watchlist-enrichment-sweep`: dry, 65 runs, 2,876 worker-s; queue p95 34.8 s.
- `crawl-v3-dashboard`: dry, 7 runs, 1,142 worker-s.
- `momentum-lifecycle-monitor`: dry, 1,036 runs, 833 worker-s.

The five shadow lanes in B4 account for 3,649 dry runs (60% of all dry runs) and 1,873 dry worker-s.

**Recommendation: do not change the worker count or the retry timeouts.** The executor is idle 94% of the time and
saturated for 43 s a week. The p95 queue wait (2.7–4.6 s) is poll and claim latency (`poll_s` 2), not worker
scarcity. The 27 waits over 30 s cluster on the :50/:00 slot bursts (`watchlist-enrichment-sweep`,
`data-gap-resolver`, `research-insight-extractor` at 06:50). Capacity is not the constraint; schedule shape is.
Spreading those bursts with minute offsets, or moving them to events (B3), is cheaper than adding workers. The one
item worth a look is `n8n-incident-fanin`: 88% of live worker time for a fan-in. Its 15.7 s p50 suggests a
per-tick fixed cost, which is a code question, not a capacity question.

## B2. Hermes and research dependency map

Fixed-time offsets are what the clock encodes today. The data dependency is read from the scripts and manifests.

**Hermes learning** (`config/pipelines/hermes_learning.json`, `run_hermes_pipeline.sh --stage learn|tune`).
- Already an explicit n8n flow: `tradeai-fabric-hermes-learning` (config/n8n_fabric_processes.json, packet
  `n8n-hermes-learning-flow-20261015`). Each step runs through the published Run Lane sub-workflow and gates on its
  dependencies' `success`.
- learn, 10:50–11:50: `outcome_grader` 10:50 → { `tag_engine` 11:05 → `outcome_feedback_agent` 11:25 ;
  `outcome_learning` 11:35 → `config_governor` 11:45 ; `score_history_retention` 11:40 (cron, excluded) }.
- tune, 17:00: `autonomous_self_tune` (no dependency).

**Hermes overnight** (`config/pipelines/hermes_overnight.json`). Still clock-chained, and the order is now inverted.
- night: `discovery_yield_builder` 03:45 ("after 03:35 outcome learning") → `tag_lift_discovery` 03:50 ("after
  03:25 outcome-bus build") → `industry_novelty_discovery` 04:25 → `siem_to_hermes_backlog` 06:15.
- close: `commit-hermes-daily` 23:13 → `source_curation` 23:30.
- **Finding:** outcome learning and the outcome bus were retargeted to 11:35 and 11:25 on 2026-08-21
  (RETARGETED_OFFPEAK), but the overnight consumers still fire at 03:45 and 03:50. They now read the previous day's
  learning, about 16 h stale; the clock offset no longer encodes the dependency it was written for. This is the
  next cohort candidate: trigger `discovery_yield_builder` and `tag_lift_discovery` on verified
  `hermes-learning-outcome-learning` / `-outcome-feedback-agent` results. Neither lane has a dispatch block or an
  allowlist entry yet, so that cohort needs dry-run review of both scripts first.

**Research news chain** (dispatcher rows). This is the flow implemented here.
- `hermes-news-bridge` 06:40/12:40/18:40: live since 2026-10-16 (cron L415 retired 06:41 ET today), output verdict
  enforced.
- → `news-to-catalyst` :45 (shadow dry_run; triggers `broker_as_of catalyst_news` + `run_done hermes-news-bridge`,
  `min_interval_s` 1800).
- → `research-insight-extractor` :50 (cutover live; trigger `run_done news-to-catalyst`, inert while live).

**Research pipeline skeleton** (`run_hermes_research_pipeline.sh`, coordinator */15, DRY_RUN default): source
discovery → backlog (capped) → catalyst research → morning momentum-catalyst → news bridge → high-LLM enqueue.
These are serial steps in one skeleton. Their dispatcher equivalents are the rows above plus
`catalyst-momentum-engine-overnight` (18:00, 22:00) and `hermes-momentum-catalyst-scalp` (:25 06–15).

**Polling lanes in the Hermes/research family:**
- `hermes-score-event-feeder` */5 24x7 (shadow).
- `hermes-research-worker-pool` hourly at :05 (shadow).
- `hermes-scope-governor` :07/:37 (shadow).
- `hermes-governance-api` */10 06–20 (cutover).
- `hermes-entity-spike-discovery` and `hermes-analyst-signal-discovery` every 3 h.

The first is the polling candidate in B4. The rest poll at modest cadences, and their outputs are not consumed on a
clock offset.

## B3. First explicit flow: the research news chain on verified results

The mechanism already existed (W5, 2026-10-11): `coordination/due source=event`. The published
`tradeai-event-router` polls it every minute and runs the item through the existing gateway `run` → executor path.
A `run_done` trigger's as_of is the upstream's newest RUN_DONE, and the consumer's receipt watermark absorbs inputs
it already saw.

The gap was that **any** RUN_DONE fired the downstream, including an exit-0 run that produced nothing.

The change:
- `dispatch.triggers[].require_verdict` (`scripts/lib/lane_dispatch.py`; schema
  `registry-dispatch-block.schema.json`) is a closed, non-empty list drawn from `produced` and `empty_allowed`, the
  verdicts `scripts/lib/n8n_output_verdict.py` proves on a receipt bound to that attempt. `no_rule`,
  `declared_not_enforced` and `dry_run_exempt` cannot be named, because they prove nothing. It is allowed only on
  `run_done`.
- `scripts/lib/n8n_due.py` `_event_as_of`: a trigger with `require_verdict` counts only upstream RUN_DONE rows whose
  ledger receipt (`receipt_json`) carries a listed `output_verdict.verdict`. Without it, behaviour is byte-identical.
- `config/lane_registry.json`:
  - `news-to-catalyst`: `run_done hermes-news-bridge require_verdict [produced]`.
  - `research-insight-extractor`: `run_done news-to-catalyst require_verdict [produced]`. This is inert while the
    lane is live, and becomes the verified gate the day the operator rules an event canary.
- There is no new shell authority, no new route and no new key prefix. Fires still use `e:` keys through the
  existing event router → gateway `run` → executor (stage clamp, `.dryrun` lock). The clock slots
  (`45 6,12,18` / `50 6,12,18`) stay as the backstop sweep. Moving them to `sweep_cron` is a registry-row PR after
  the verified fires are proven.

**Before and after, from real run records (7 days):**

| Path | n | p50 | min–max |
|---|---|---|---|
| bridge finish → `news-to-catalyst` start, clock offset (`d:` :45) | 18 | **299.8 s** | 239–301 s |
| bridge finish → `news-to-catalyst` start, event (`e:` run_done) | 9 | **58.9 s** | 58.2–60.4 s |
| `news-to-catalyst` finish → `research-insight-extractor` start, clock offset | 18 | 299.6 s | 297–323 s |
| bridge start → `research-insight-extractor` finish, clock chain end to end | 18 | **604.9 s** | 544–629 s |

- Event latency is the router's 1-minute poll plus about 1 s queue wait. The chain end to end on events is projected
  at about 2.2 min against 10.1 min on the clock, once `research-insight-extractor` is event-fired (operator event
  canary).
- Only 9 of 18 bridge completions produced an event fire. The 12:40 slot never did, because `min_interval_s` 1800
  debounced it after the ~12:32 `catalyst_news` as_of event.
- **What verification changes, measured:** the bridge's 2 live runs in the window (06:40 and 12:40 today) both had
  verdict `empty_allowed` (`no_new_input`). The old trigger fired `e:news-to-catalyst:dry_run:20261016T0640` on
  that empty result; the verified trigger fires nothing. The 17 pre-cutover dry bridge runs carry no verdict, so
  they would not fire either. Downstream work now starts only when the upstream proved new output.
- Dry-run evidence is hermetic: `tests/test_n8n_consolidation_cohort1_20261016.py`. Real ledger (CoordinationLedger
  on tmp), `compute_due(source=event)`:
  - `empty_allowed`, `declared_not_enforced`, `no_rule`, `dry_run_exempt` or no receipt: no item.
  - `produced`: `e:down-lane:dry_run:<as_of minute>`.
  - A newer empty run does not move the as_of past an older produced one.
  - A plain trigger is unchanged.
- Existing W5 and due suites pass: 398 passed.

## B4. Shadow stop and regression canaries

**Accepted production lanes already get no continuous shadow.** There are 21 accepted lanes (dispatch live, stage
canary or cutover, with a verified live RUN_DONE). Across all of them there were **0 dry runs after the lane's
first live RUN_DONE** in the window. `n8n_due` emits one mode per lane per slot, and PR #1822 pins it. The only
dry-after-live rows were `momentum-cache-reconcile`, a shadow lane with one ladder live proof on 10-13, and one
manual `n8n-wf` run each on `crontab-snapshot-for-health-agent` and `source-attribution-monitor`.

**What was missing is the purposeful check.** After cutover, a release or config change got no dry run at all.

`scripts/report_n8n_shadow_policy.py canaries` (read-only; git reads only) plans one. A dry run is due for an
accepted lane only when, between the `code_sha` of its last verified live run and the current release:
- its own config changed: a digest of its registry row, allowlist entry and health contract; or
- its entry script changed (`git diff --quiet`).

A release that touches neither gives no canary. An unreadable digest is reported as `unknown`, never as due. Run
against main `5f0ea5b8c`: **21 accepted lanes, 0 due, 0 continuous dry runs planned.** Against this branch's head,
`research-insight-extractor` comes out due (`lane_config_changed`), because its registry row is the one this PR
edits.

Dispatching those canaries needs a gateway key the dispatcher can mint for a live lane's dry run. The gateway
accepts `d:`/`e:`/`g:` only. That is an operator ruling and a follow-up host PR; this PR plans and does not dispatch.

**Reduced cadence for the five shadow lanes: a proposal only.** Promotion, retirement and cadence are the
operator's §17 call. This PR changes none of the five rows, and the test pins that.

| lane | now | proposed | runs (7 d) | output changes | fires/week now → proposed | worker-s/week |
|---|---|---|---|---|---|---|
| hermes-score-event-feeder | */5 24x7 | `7 * * * *` | 1,357 | **0** (constant "would collect…" line) | 2,016 → 168 | 530 → 44 |
| momentum-lifecycle-monitor | */5 24x7 | `*/15 6-16 * * 1-5` | 1,037 (1 timeout) | 1,036 (self-stamped status block) | 2,016 → 220 | 1,621 → 177 |
| momentum-cache-reconcile | */5 24x7 | `*/15 6-16 * * 1-5` | 810 | 451 | 2,016 → 220 | 1,287 → 141 |
| scalp-hot-list | */2 06–09 wkdy | `*/10 6-9 * * 1-5` | 240 | 123 (`dry_run_no_refresh`) | 600 → 120 | 130 → 26 |
| finviz-enrichment-scalp-hot | */5 06–15 wkdy | `*/15 6-15 * * 1-5` | 208 | 176 | 600 → 200 | 331 → 110 |
| **total** | | | 3,652 | | **7,248 → 928 (−87%)** | **3,899 → 498** |

`hermes-score-event-feeder`'s dry run proves only that the process starts; 1,357 identical tails add nothing. A
promotion check for it needs a dry run that reports what it would enqueue (a code PR), not more fires.

## B6. LLM steps in this flow

| step | route | fallback | budget | validation |
|---|---|---|---|---|
| hermes-news-bridge | no LLM | n/a | n/a | output verdict (produced_count, `per_window` 48 h) |
| news-to-catalyst | local `gemma3:4b` via ollama 127.0.0.1:11434 (`scripts/catalyst_classifier.py`), only for deterministic confidence < 0.55 | the deterministic classifier (`_llm` returns None on any error or timeout of 25 s × 2 attempts) | `CATALYST_LLM_BUDGET` 25 calls per live run; **0 in dry run** (`allow_llm=not dry_run`) | structured JSON, confidence clamp 0..1, `llm.confidence >= deterministic` to replace |
| research-insight-extractor | no LLM | n/a | n/a | output verdict |

No cloud or OAuth step is in this flow, so the OAuth-first chain (grok → chatgpt → one DeepSeek escalation within
caps, `config/llm_process_registry.json`) is neither exercised nor changed here. The next cohort (Hermes overnight:
`industry_novelty_discovery` and `tag_lift_discovery` run inside `run_with_deepseek_offpeak.sh`) is where that
evidence is owed. Each LLM step's receipt must carry route, fallback taken, budget used and validation verdict
before its live arg is set.

## Operator decisions (propose and stop)

1. **Event canary for `research-insight-extractor`.** This lifts `EVENT_MODES` for one live lane: verified
   `news-to-catalyst` → extractor in about 1 min instead of the :50 clock. It requires `news-to-catalyst` to go live
   first, because a live lane needs a live predecessor.
2. **Shadow cadence for the five lanes**, per the table, or promote or retire them.
3. **A gateway key for regression-canary dry runs** of accepted lanes. Until then, the planner output is advisory.
4. **Next cohort: Hermes overnight on verified learning results.** This fixes the inverted 03:45 → 11:35 ordering.

Rails: no broker, no credential read (names only), no DB write, no crontab or systemd edit, no restart, no send. All
measurements are read-only file reads and git reads.
