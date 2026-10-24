# n8n cutover factory: the effect-claim wrapper, and four canary rows (2026-10-23)

Task `T-20261023-f7771f` (claim board). Source: PR #1972 findings 3 and 5. Gate:
`config/ci_gates/n8n_cutover_effect_claim_wrapper_20261023.json`.

## 1. Defect and fix

AGENTS §23.25 requires a sender's cron line to carry the cron-side effect-claim wrapper:

```
flock -n /tmp/x.lock env TRADEAI_EFFECT_CLAIM=x-lane bash scripts/effect_claim_cron.sh x-lane $PY scripts/x.py ...
```

`scripts/n8n_cutover_wave.py parse_lane_argv` did not recognise this wrapper. For every line carrying it, the function
reported `unmapped_wrapper:env`, `unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM`, `unmapped_wrapper:scripts/effect_claim_cron.sh`
and `unmapped_wrapper:<lane>`. As a result, `plan` returned SKIP for every canary lane that has the wrapper, and it held
six wrapped shadow lanes.

The fix makes `parse_lane_argv(cmd, entry_command, lane_id=None)` treat the wrapper as cron-only. On the n8n side the
executor's own claim (`n8n_claim`) covers the same `fx:` key, so the executor has nothing to reproduce. The wrapper is
accepted only when **switched on for its own lane**:

| Cron prefix | Verdict |
|---|---|
| `env TRADEAI_EFFECT_CLAIM=L bash scripts/effect_claim_cron.sh L` (or a bare `TRADEAI_EFFECT_CLAIM=L`, or absolute paths), with L equal to the registry lane | clean; `effect_claim: L` |
| wrapper with no env, or an env value different from the wrapper's lane | `effect_claim_wrapper_off`: the wrapper `exec`s the command unclaimed |
| wrapper switched on for a lane other than the registry row | `effect_claim_wrapper_lane_mismatch:<lane>` |
| wrapper with no LANE_ID argument | `effect_claim_wrapper_no_lane_arg` |
| any other env assignment next to the wrapper (e.g. `TRADEAI_PENDING_DATA_APPLY=1`) | still `unmapped_wrapper:env:<VAR>`. The executor does not reproduce it. |
| any env prefix on a line **without** the wrapper | unchanged; the old verdicts are kept byte for byte |

`flock -n`, `timeout [-k N] D` and `$PY` keep their existing handling. No gate is widened: the three new checks only
add problems.

Tests: `tests/test_n8n_cutover_effect_claim_wrapper_20261023.py` covers wrapped and unwrapped lines, flock, timeout,
env prefixes, misuse cases, three verbatim live-crontab shapes, and plan-level verdicts. All 15 tests fail on the
pre-fix code.

## 2. Plan (dry run) before and after

Command (read-only; crontab snapshot from `crontab -l`, 1077 lines, sha256 `b2097df25a62…`, 2026-10-23 ~14:10 ET):

```
python3 scripts/n8n_cutover_wave.py plan --code-root . --crontab <snapshot> --review-drafts
```

| | READY_CANARY | ALREADY_CANARY | ALREADY_N8N | SKIP | plannable (READY + ALREADY_CANARY) |
|---|---|---|---|---|---|
| before (main 98bef2794) | 0 | 4 | 23 | 237 | **4** |
| after | 3 | 27 | 23 | 211 | **30** |

- **23 canary lanes** move from SKIP to ALREADY_CANARY: aegis-social-sentiment, aegis-transcript-discovery,
  agent-outcome-linker, agent-outcome-scorer, build-symbol-profiles-at-0-19, commitment-outcome-sweep,
  daily-incubator-refresh, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor,
  finviz-proactive-research, finviz-screener-runner, hermes-entity-spike-discovery, hermes-social-sentiment,
  incubator-rolloff-engine, instrument-belief-writer, journal-tilt-morning-hook, pattern-extractor,
  proposal-backtest-engine, sec-data-ingest, update-agent-performance, watchlist-enrichment-sweep and
  weekly-incubator-builder.
- **3 shadow lanes** become READY_CANARY: hermes-research-worker-pool, news-to-catalyst and update-lockup-earnings-dates.
- The six lanes PR #1972 named:
  - The 3 lanes above are now READY_CANARY.
  - social-ingest-all and trade-thesis-review-engine now parse clean (`parse_lane_argv` returns no problems). They
    are outside the directive scope (disposition CSV), so `plan` reports `not_in_directive_scope` for them, as it did
    before.
  - hermes-research-agenda-at-45-7 still SKIPs on its own argv finding: `allowlist_command_args_not_on_cron_line:['--json'] vs ['--apply', '--json']`.
- **Still held, correctly**:
  - hermes-topic-monitor-bridge: argv mismatch, the same finding as hermes-research-agenda-at-45-7.
  - hermes-scope-governor and hermes-score-event-feeder: `safe_flock.sh` with no `flock -n`.
  - resolve-due-checkpoints: no flock, plus `env:TRADEAI_PENDING_DATA_APPLY`.
  - agent-calibration-engine: DRAFT contract with UNKNOWN fields.

## 3. The four canary rows with a commented cron line (read-only verification)

`crontab -l` (read-only, 2026-10-23):

| Lane | crontab | registry on main 98bef2794 | n8n live runs (`data/runtime/n8n_runs`, read-only) |
|---|---|---|---|
| materialize-watchlist-strategy-cards | L219 `# N8N-OWNED 2026-10-22 double-run fix …` | **already `n8n`/`cutover`** (PR #1978, batch 8) | 127 live, last RUN_DONE 2026-10-23 14:00 ET |
| hermes-discovery-scorecard | L845 `# N8N-OWNED 2026-10-22 …` | **already `n8n`/`cutover`** (PR #1978) | 8 live, last RUN_DONE 2026-10-23 05:30 ET |
| sync-social-to-intelligence | L875 `# N8N-OWNED 2026-10-22 …`, **but L1077 is a live, uncommented line** (see below) | **already `n8n`/`cutover`** (PR #1978) | 11 live, last RUN_DONE 2026-10-23 11:30 ET |
| hermes-watchlist-scorer | L451 `# RETIRED 2026-10-21 n8n-cutover hermes-watchlist-scorer …` | **still `cron`/`canary`** | 186 live, all `RUN_DONE` exit 0, none lock-skipped; first 2026-10-21 15:45 ET, last 2026-10-23 14:00 ET |

Three of the four rows were reconciled to cutover in PR #1978. Only **hermes-watchlist-scorer** still contradicts the
crontab. The correct state is **cutover**, which is step 5 of its operator packet
(`docs/ops/packets/hermes-scorer-canary-20261021/README.md`):

```
python3 scripts/n8n_cutover_wave.py cutover --lanes hermes-watchlist-scorer --wave HS-20261021
# + health contract hermes-watchlist-scorer stage canary -> cutover
```

A preview on a scratch copy of `config/` changes exactly one row:

- `scheduler`: `cron`/`*/15 * * * *`/`canary` becomes `n8n`/`dispatcher`/cadence `*/15 * * * *`/`cutover`.
- `scheduler_before_cutover` records the old canary scheduler.

That registry edit is **not in this PR**. `config/lane_registry.json` and `config/n8n_health_contracts.json` are claimed
by session `2e7e1d01-rotate-pr2016` (claim `20261023T163327Z-claude-cf4362df`, open PR #2016). The claim board refused
the extension, and the refusal is not routed around. The follow-up PR is the command above, run once that claim releases.

**Contract lag (same follow-up).** The health contracts for the three rows already at cutover still say `canary`
(materialize-watchlist-strategy-cards and hermes-discovery-scorecard) and `shadow` (sync-social-to-intelligence).

### Finding: a live cron line for a lane that n8n owns

`crontab -l` line **1077**, the last line, has no flock:

```
30 11,15 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1
```

- The registry says sync-social-to-intelligence is `n8n`/`cutover`.
- The dispatcher fired it live at 11:30 ET today (`d:sync-social-to-intelligence:live:20261023T1130`, RUN_DONE).
- L875 (the flock line) is commented. L1077 does not use the lane's lock `/tmp/sync_social_to_intelligence.lock`, so the
  shared flock cannot stop a same-slot double run.
- The lane is a fold that overwrites (`social_sentiment_history -> intelligence_entities`), so a double run is
  probably idempotent. That is not verified.
- The crontab belongs to the operator (cron freeze). **Not edited.** It is reported for an operator decision: comment
  L1077 under a `cron` grant, or explain it.

## 4. Backlog row (for `~/n8n-maturity-verification/DOCS_AND_AGENTS_UPDATE_BACKLOG.md`)

That file is claimed by session `2e7e1d01-nvda`, so the row is recorded here for the next writer:

> | L57 | **n8n cutover factory reads the effect-claim wrapper (2026-10-23, T-20261023-f7771f)**: `parse_lane_argv` accepts `env TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane>` only when switched on for its own lane; plan before 4 plannable, after 30 (3 READY_CANARY). Registry: hermes-watchlist-scorer still canary with its cron line retired; it goes to cutover in a follow-up PR once lane_registry.json is free. Finding: live crontab L1077 sync-social-to-intelligence runs without a flock while n8n owns it (operator). AGENTS: none needed. | docs/ops/N8N_CUTOVER_EFFECT_CLAIM_WRAPPER_20261023.md | PR #— |

AGENTS.md: no amendment is needed. §23.25 already requires the wrapper; this change makes the factory honour it.
