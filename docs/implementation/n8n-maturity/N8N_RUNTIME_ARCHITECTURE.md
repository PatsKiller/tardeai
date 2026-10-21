# N8N runtime architecture — cron vs n8n dispatch, relay, gateway, executor, locks, effect keys, ledger

```
Status:      ACTIVE
as_of:       2026-10-21T15:50:00-04:00
Measured at: origin/main 7faa8cddf (source); CURRENT 7faa8cddf-main-exact-phase2-20261021-154546; executor unit
             read with `systemctl --user cat tradeai-n8n-run-executor.service` 2026-10-21
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md §23 (where this file differs, AGENTS.md wins). Cutover standard: §23.21 (16.0.0, PROPOSED;
             rebuilt from 8.0.0 / PR #1727; operator ruling 2026-10-14 ~11:05 ET)
```

How a scheduled Trade AI lane runs today, from either scheduler, and where its evidence lands. It adds no rule.
First drafted for PR #1727 (2026-10-14, unmerged); updated here for the effect keys, the cutover factory and the
4-worker executor. Configuration detail lives in [`N8N_CONFIGURATION.md`](N8N_CONFIGURATION.md); procedures in
[`N8N_ONBOARDING_STANDARD.md`](N8N_ONBOARDING_STANDARD.md) and [`RUNBOOK_CUTOVER_ROLLBACK.md`](RUNBOOK_CUTOVER_ROLLBACK.md);
current counts in [`MIGRATION_STATE_20261021.md`](MIGRATION_STATE_20261021.md).

## 1. The diagram

```mermaid
flowchart LR
  subgraph HOST_CRON["Host scheduler (cron / systemd)"]
    CRON["crontab line<br/>flock -n LOCK · market_day_gate.sh · timeout"]
    RETIRED["commented line: # RETIRED DATE n8n-cutover LANE ORIGINAL<br/>never deleted · the fallback"]
    NEVER["F07 daemons and registry_systemd assets<br/>stay on the host (§23.25)"]
  end

  subgraph N8N["n8n container (m8m-n8n compose)"]
    DISP["tradeai-dispatcher<br/>* * * * * · GET /due · POST /run (d: slot keys)"]
    HBW["tradeai-heartbeat-watcher · lane heartbeat-watch"]
    IR["tradeai-incident-router · Error Trigger → POST /event"]
    FAB["fabric workflows: Run Lane sub-workflow, error workflow"]
  end

  RELAY["tradeai-n8n-run-relay<br/>172.19.0.1:18092 · bearer<br/>TRADEAI_N8N_RELAY_LIVE_LANES = the live list"]
  GW["tradeai-n8n-coordination-gateway<br/>127.0.0.1:18091 · coordination/run · /due<br/>claim + allowlist + key namespace; never spawns"]
  LEDGER[("coordination ledger (sqlite)<br/>runs · events · effect_claims · effect_owners")]
  EXEC["tradeai-n8n-run-executor<br/>own cgroup · WORKERS=4 · class caps · stage clamp"]
  REG[["config/lane_registry.json<br/>stage shadow | canary | cutover"]]
  ALLOW[["config/n8n_run_allowlist.json<br/>argv · lock · timeout · dry/live args"]]
  KEYS[["config/n8n_effect_keys.json<br/>STAGED | armed (n8n_claim, cron_claim)"]]
  LANE["lane runner from CURRENT<br/>same argv · same LOCK · same gates"]
  SIGNAL[("output_signal<br/>LaneRunReceipt@v2 · data/runtime/LANE_last.json")]
  SEND["host communications gateway<br/>(the only sender)"]

  CRON -- "fires on its slot until retired" --> LANE
  DISP -- "POST /run {lane_id, mode, key}" --> RELAY
  HBW --> RELAY
  IR --> RELAY
  FAB --> RELAY
  RELAY -- "HMAC claim, caller n8n-relay;<br/>live only for lanes in the live list" --> GW  GW -- "reads" --> REG
  GW -- "reads" --> ALLOW
  GW -- "writes RunRequested" --> LEDGER
  EXEC -- "claims rows; claims effect key if armed" --> LEDGER
  EXEC -- "reads" --> KEYS
  EXEC -- "spawns under the lane's lock" --> LANE
  LANE -- "writes" --> SIGNAL
  EXEC -- "writes RunReceipt<br/>exit, duration, output_signal before/after" --> LEDGER
  HBW -. "reads output_signal of watched lanes" .-> SIGNAL
  NEVER -. "watched, never fired" .-> HBW
  LEDGER -. "incident fan-in" .-> SEND
  CRON -. "same LOCK: second starter skips<br/>(RUN_SKIPPED_LOCK)" .- LANE
  CRON -- "n8n_cutover_wave.py comment-cron<br/>or _cutover.py --lane" --> RETIRED
  RETIRED -. "rollback: uncomment the tagged line" .-> CRON
```

## 2. How to read it

- **Two schedulers, one lock, then one effect key.** At `canary` a lane's cron line and the dispatcher can both start
  it. The allowlist `lock` equals the cron line's `flock` lock, so the second starter exits `RUN_SKIPPED_LOCK`
  (§23.12; `lane_dispatch.r1_canary_lock_matches`). A lock stops overlap, not a second run later in the same slot, so a
  lane that appends, sends or calls an LLM also carries an effect key (`scripts/lib/effect_claim.py`): STAGED at
  canary (nobody claims), armed at cutover with one owner moved by `effect_claim.py set-owner` (§23.23 (4), the fenced
  single-owner switch). A cron line claims the same key through `scripts/effect_claim_cron.sh`.
- **The stage decides the mode.** `shadow` rows fire `dry_run` only. `canary` rows ask for `live`; until the lane is in
  `TRADEAI_N8N_RELAY_LIVE_LANES` the dispatcher's due computation posts the slot as `dry_run`
  (`n8n_due._relay_dispatch_mode`) and the relay refuses any other live request (`relay_live_not_enabled`); the executor's stage clamp
  (`scripts/lib/lane_stage_clamp.py`) downgrades anything the stage does not allow. A cron-kind row stays at `canary`
  while its cron line is live: a `cutover` row with a live line fails `CRON_PRESENT_WHILE_SCHEDULER_N8N` and
  `CUTOVER_CRON_LINE_ACTIVE`.
- **Live keys are server-validated.** The gateway refuses a free-form live key from the relay
  (`run_key_namespace_refused`, audit DD03), so the usual live proof for §23.21 (4) is the dispatcher's own `d:` slot
  with the cron line present.
- **The gateway never spawns.** It validates the claim against the registry and allowlist and writes the request. The
  executor (own cgroup; `TRADEAI_N8N_EXECUTOR_WORKERS=4` from drop-in `40-memory-workers-20261014.conf`, which overrides
  the 3 in `10-executor-v2.conf`) runs the lane from CURRENT with the cron line's argv, lock and gates (§23.3).
- **Evidence is the ledger row plus the output signal**, never an n8n execution status alone: successful executions
  are retained selectively (§23.19; `N8N_CONFIGURATION.md` §1), and `scripts/lib/n8n_output_verdict.py` turns a
  missing expected output into `RUN_FAILED output_unverifiable` for lanes with an expected-output rule.
- **Watching is not scheduling.** `heartbeat-watch` reads the `output_signal` of watched lanes, including those that
  stay on the host, and hands a stale one to the incident fan-in. Only the host communications gateway sends (§24.1).

## 3. Evidence paths

| What | Where |
|---|---|
| Coordination ledger | `~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite` (open `mode=ro`) |
| Lane output signal | `$TRADEAI_STATE_ROOT/data/runtime/<lane>_last.json` (`LaneRunReceipt@v2`) |
| Cutover receipts | `$TRADEAI_STATE_ROOT/data/runtime/n8n_cutover/` (`CutoverReceipt@v1`) |
| Crontab backups | `~/.local/state/tradeai/backups/` |
| Wave packets | `n8n_cutover_wave.py packet --out <dir>`; today's: `docs/ops/packets/hermes-scorer-canary-20261021/` |
