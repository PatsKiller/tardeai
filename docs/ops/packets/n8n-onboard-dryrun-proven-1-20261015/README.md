# n8n onboarding ONB-1 (2026-10-15): operator packet

Operator directive 2026-10-15, "N8N Cutover Decision": every lane family moves to n8n except the F07 daemons and the
`registry_systemd` assets (`docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv`, disposition
`MIGRATE_N8N`). The cutover factory needs each lane **onboarded** first: an allowlist entry whose dry run is proven
write-free (AGENTS §2 / §23.21).

This packet does two things:

- It **onboards 2 lanes in SHADOW.**
- It **fixes the dry run of 6 more** that a policy gate keeps off the dispatcher.

**At merge: inert.** Nothing reaches the host until a release that contains this PR is promoted. No cron line moves.

## Onboarded (SHADOW: dispatcher fires the offline `--dry-run`; the cron line keeps doing the real work)

| Lane | Cron line (2026-10-15) | Class | Lock | Change |
|---|---|---|---|---|
| `cio-stance-classification-drain` | L987 `20 7,19 * * 1-5` | pipeline | `/tmp/cio_stance_classify.lock` (on the line) | None to its dry run, which was already write-free (refactor M5). The receipt gains `produced_count` (symbols classified). |
| `drain-discovery-backlog` | L867 `0 6 * * 1-5` | hygiene | `/tmp/drain-discovery-backlog.lock` **PROPOSED** (shard 05 `lock_proposed`) | None to its dry run, which was already write-free (refactor W3). The receipt gains `produced_count` (candidates moved). |

Both rows adopt their **refactor shard 05 proposal unchanged**: `scheduler.wave R2-05`, and the allowlist command is
the frozen cron argv including `--apply`. `--dry-run` wins over `--apply`, and the write recorder proves that.
build-symbol-profiles-at-0-19 is the precedent (lane repair 2026-10-15). Both lanes were in SW4 EXCLUDED only because
SW4 admitted R1 classes (ingest / llm / learn); they are released the same way LD-W1 released
hermes-discovery-scorecard.

Each lane also carries:

- a REVIEWED health contract with an `N8nExpectedOutput@v1` rule. The rule passes FW-M6 and is declared only: no
  `output_receipt` is set.
- a staged effect key (`cron_claim` / `n8n_claim` false).
- a DD01 capability-baseline entry. Broker reach is lazy, never at import, and `--check` reports new=0.
- a dispatch row that passes the dispatcher sender gate: no send anywhere in the definition-level reach.

## Fix only: dry runs that wrote, held off the dispatcher by the sender gate

These six lanes are MIGRATE_N8N, but every one reaches a send through the `telegram_alert` chokepoint. The dispatcher
sender gate (`tests/test_agents_policy_7_0_0_advisory_market_data.py`, AGENTS §23.3) refuses any dispatched lane that
does, and its BASELINE is **shrink-only**. Admitting them is an operator/architect policy decision, not an onboarding
edit. Until then they get no allowlist entry and no dispatch row.

Their `--dry-run` did write. This PR fixes that, so each lane is ready the day the decision is made:

| Lane | What `--dry-run` did before | Now |
|---|---|---|
| `premarket-watcher` | appended `logs/premarket_watcher.log`, INSERT/UPDATE `pipeline_runs`, called EDGAR / StockTwits / Yahoo for up to 50 symbols | offline plan before the module's `.env` load; old run is `--preview`; LaneRunReceipt on a real run; import no longer needs `.env` |
| `strategy-weekly-review` | `mkdir logs/`, appended the log, `pipeline_runs`, rewrote the health_agent snapshot, could send Telegram on an empty registry | offline plan before any import side effect; `--preview` never snapshots or sends; errors exit 1 (was 0); receipt |
| `generate-weekly-docx` | rendered 3 chart PNGs into the reports root | offline plan; old JSON print is `--preview`; a failed export exits 1 and sends no false "generated" notice; receipt |
| `youtube-cookie-health-check` | opened the cookie jar (operator-only credential, §24.7) and queried the DB | offline plan that never opens the jar; old run is `--preview`; LaneRunReceipt next to the legacy ScheduledJobReceipt |
| `hermes-discovery-ingestors` | loaded env, connected to the DB, ran SELECTs | offline plan before `db_adapter` is imported; old run is `--preview`; receipt gains `produced_count` |
| `system-rollup-snapshot` | computed the rollup through `api_v2`; `lib/llm_consumption.ensure_schema` ran DDL + ALTERs + an `llm_process_config` upsert; probed the OAuth proxies | offline plan; old run is `--preview`; LaneRunReceipt on a real run |

All receipt counts ride on `write_lane_receipt(output={...})`, so the document stays `LaneRunReceipt@v1`. v1 readers
match the schema exactly.

## Dry-run proof (`dry_run_proof.json`)

1. **Write recorder.** `tests/support/dry_run_write_recorder.py` runs each script as `__main__` under a CPython audit
   hook (PEP 578), with the cron line's live switches added before `--dry-run` and no DB or TELEGRAM variables. The
   hook records:
   - every write-mode `open`;
   - every filesystem mutation;
   - every `socket.connect` / `getaddrinfo`;
   - every subprocess;
   - every `sqlite3.connect`.

   **All 8 scripts: zero events**, and none imports a DB, HTTP, dotenv or send module. A negative-control test proves
   the recorder catches a write, a mkdir, a connect and a child process.
2. **Real executor.** `scripts/n8n_run_executor.py --once` drains a **live** request for each onboarded lane, using a
   scratch ledger, scratch state and scratch locks with the real allowlist and registry. The stage clamp runs each one
   `dry_run`. Both end `RUN_DONE` with their `DRY-RUN …` plan, and no lane receipt is written.

The same proof runs in CI as `tests/test_n8n_onboard_dryrun_proven_1_20261015.py`.

## Operator steps

1. Merge, then prepare and promote as usual (`release-write` grant naming this PR and SHA).
2. After the first natural slot of each lane, verify it on the ledger (read-only). Expect `RUN_DONE` / `dry_run`:
   ```bash
   sqlite3 "file:$HOME/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite?mode=ro" \
     "SELECT lane_id, state, mode, finished_at FROM runs WHERE lane_id IN ('cio-stance-classification-drain','drain-discovery-backlog') ORDER BY requested_at DESC LIMIT 10"
   ```
3. **Rollback:** revert the PR and promote, or set `dispatch.mode` to `off` in a registry PR. No host change is
   needed.

**Decision wanted:** whether chokepoint senders may join the dispatcher, either by growing the sender-gate BASELINE or
by moving their sends to the comms/incident path. That decision unlocks the six fix-only lanes, plus the other sender
lanes listed in the PR. Canary for the two onboarded lanes needs:

- the AGENTS §23.21 standard;
- a cron flock for drain-discovery-backlog;
- their effect keys armed.
