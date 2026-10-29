Status: ACTIVE
as_of: 2026-10-29T21:20:00Z
Measured at: served release `1e62905f8` (read from `data/runtime/health_tick_last.json` `served_sha`), plus live receipt reads
Canonical repo path: docs/ops/CIO_GO_LIVE_RUNTIME_VERIFY_2026-10-29.md
Authority: read-only observation of the served release and its receipts (`[VERIFIED]` below); source reads are `[CODE]`
Supersedes: none
See also: docs/ops/CIO_GO_LIVE_MONITORING_PROPOSAL_2026-10-29.md, docs/ops/CIO_GO_LIVE_OPERATOR_APPROVALS_2026-10-28.md (on branch `wt/ops-watchdogs-20261028`, unmerged), docs/audits/CIO_READINESS_GO_LIVE_AUDIT_2026-10-28.md (same branch)

# CIO go-live — runtime verification runbook (2026-10-29)

This runbook proves, per go-live item, that the thing is working **at runtime**, using only
**read-only** reads: `SELECT` / reading JSON receipts / reading `LaneRunReceipt` files. It changes
no schedule, no cron, no broker code; `MBI_BEHAVIOR = 0`.

## How to read this

- **State root** is `production_state_root()` = `~/trade-ai-releases/persistent-state` (all paths below are
  relative to it unless noted). The canonical code root is the served release; resolve it with the operator's
  `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` (the shell guard blocks an agent from doing this —
  see "DB reads" below).
- **Served release** as of this writing: `1e62905f83bed3809311b29e4a52febfd96650d6`
  (`[VERIFIED]` `data/runtime/health_tick_last.json` `served_sha`, tick `2026-10-29T17:20-04:00`).
- **Two of the five items are NOT on the served release** (they live on the unmerged branch
  `wt/ops-watchdogs-20261028`). Their runtime proof is therefore **blocked until merge + deploy**; each section
  says so explicitly instead of implying a green that cannot exist.
- Evidence tags: `[VERIFIED]` = a read was run and its output is quoted here; `[CODE]` = source was read;
  `[DOC-CLAIM]` = a document asserts it.

---

## Item 1 — `cio_prospect` Postgres dual-write

**What it is.** The single per-security CIO truth record now dual-writes: the jsonl store of record
(`data/cio/cio_instrument_records.jsonl`) **and** the Postgres table `cio_prospect` (plus its append-only
`cio_prospect_events`). The writer is `InstrumentRecordStore.upsert_prospect` (`scripts/lib/cio_instrument_record.py`);
the production caller is `scripts/lib/cio_prospect_writer.py` `write_prospects`, invoked by the
`cio-opportunity-curator` (full universe) and `cio-entry-state` (subset) lanes. The Postgres side runs **only**
when `prospect_store_status()` reports `live` — three conditions: the registry row is granted, the operator flag
`TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1` is set, and the tables exist. `[CODE]` `scripts/lib/cio_instrument_record.py:377`,
`:1347`; `scripts/lib/cio_prospect_writer.py:1`.

**Store / receipt paths.**

| artifact | path |
|---|---|
| writer receipt (per lane) | `data/runtime/cio_prospect_writer_<caller>_last.json` — `cio-opportunity-curator`, `cio-entry-state`, `manual` |
| store of record (jsonl) | `data/cio/cio_instrument_records.jsonl` |
| shadow build artifact | `data/cio/cio_prospect_shadow.json` |
| Postgres tables | `cio_prospect`, `cio_prospect_events` (migration `migrations/2026_10_22_cio_prospect.sql`) |
| read projection | `scripts/lib/data_broker/cio_prospect.py` `get_prospects` — `source.kind == "store"` when live, else `"shadow"` |

**Prove it works — read-only commands.**

```bash
STATE=~/trade-ai-releases/persistent-state
# 1) The writer's own receipt reports the dual-write mode it actually used.
jq '{as_of, mode, flag, counts: {jsonl_written: .counts.jsonl_written, pg_upserted: .counts.pg_upserted, pg_errors: .counts.pg_errors, events_appended: .counts.events_appended}, pg}' \
  "$STATE/data/runtime/cio_prospect_writer_cio-entry-state_last.json"

# 2) Same for the full-universe curator pass.
jq '{as_of, mode, flag, pg, counts}' \
  "$STATE/data/runtime/cio_prospect_writer_cio-opportunity-curator_last.json"

# 3) The registry grant (the first of the three gates).
jq '.domains[] | select(.domain=="cio_prospect") | {domain, approval}' \
  config/data_source_authority.json

# 4) Store-of-record row count (jsonl; no DB needed).
wc -l "$STATE/data/cio/cio_instrument_records.jsonl"
```

**Expected healthy output.**

`pg` must read (quoted from the live entry-state receipt, `[VERIFIED]`):

```json
"pg": {
  "live": true,
  "mode": "dual_write",
  "reasons": [],
  "row_granted": true,
  "flag": true,
  "table_present": true
}
```

with `counts.pg_errors == 0` and `counts.jsonl_errors == 0`, and `flag: true`. A healthy pass shows
`pg_upserted ≥ 0` (0 is fine when nothing material changed — the writer is material-change-only), `events_appended ≥ 0`.

**Observed now (`[VERIFIED]`).** The `cio-entry-state` receipt (`as_of 2026-10-29T20:50:03Z`) reports
`mode: "dual_write_flag_on"`, `flag: true`, `pg.live: true`, `pg.mode: "dual_write"`, `reasons: []`,
`row_granted: true`, `table_present: true`, `pg_upserted: 1`, `jsonl_written: 1`, `events_appended: 1`,
`pg_errors: 0`. **The dual-write is live and writing.**

**Broken looks like.**

- `pg.mode == "inert"` (or `"off"`) with a non-empty `reasons[]` — name the reason:
  `registry_row_not_granted`, `dual_write_flag_off`, `table_absent`, `table_probe_failed:<Exc>`, or `no_table_probe`.
  A dual-write that silently fell back to shadow is a **fail-open** and is exactly what monitoring must catch
  (see the proposal doc).
- `pg_errors` / `jsonl_errors` climbing, or `pg.circuit: "open after 3 consecutive failures"` (jsonl keeps
  writing, PG stops — the writer fails soft by design).
- The `cio-opportunity-curator` receipt is **stale** as of this writing (`as_of 2026-10-28T20:30:27Z`, still
  `flag: false`, `mode: "shadow_only"`). That lane runs market-hours only (`*/30 9-16 * * 1-5`), so the **full
  universe has not yet been dual-written since the flag was turned on**; only the entry-state subset that changed
  on 2026-10-29 has landed in PG. The next curator pass is the full backfill. Watch item, not yet a defect.

**What I could NOT determine.** A live `SELECT count(*) FROM cio_prospect` / `cio_prospect_events` — that is a
Postgres read and is **operator-only** (see "DB reads"). `table_present: true` in the receipt is proof the tables
exist (the probe runs `SELECT to_regclass(...)`), but not a row count.

---

## Item 2 — conflict engine (rulebook)

**Status correction — this is NOT live on the served release.** On `main` / the served release,
`config/conflict_rulebook.json` reads `status: "PROPOSED"`, `approval: null`, `live_enabled: false`
(`[VERIFIED]`, read from the worktree at `origin/main`). The activation — `status: "APPROVED"`,
`live_enabled: true`, `approval` recorded verbatim from the operator's 2026-10-28 in-session authorization — is
commit `073cbf662` on branch `wt/ops-watchdogs-20261028`, **unmerged**. The producer `scripts/conflict_resolver.py`
has no `live` mode: `--dry-run` is write-free; `--shadow` writes the ledger
`data/conflicts/conflict_events.jsonl`, the comparison report `data/conflicts/reports/<sha256(run_id)>.json`, and a
lane receipt `data/runtime/conflict-resolver_last.json`. `[CODE]` `scripts/conflict_resolver.py:1`, `:182`.

**Prove it works — read-only commands (once merged + deployed).**

```bash
STATE=~/trade-ai-releases/persistent-state
# 1) The rulebook state (the activation gate).
jq '{status, live_enabled, approval: (.approval.approved_by), version, matrix_sha256}' \
  config/conflict_rulebook.json

# 2) The shadow lane receipt — proves the resolver ran and how many findings/events it produced.
jq '{lane_id, status, exit, finished_at, summary, produced_count}' \
  "$STATE/data/runtime/conflict-resolver_last.json"

# 3) The ledger is append-only and growing.
wc -l "$STATE/data/conflicts/conflict_events.jsonl"          # events written (shadow only)
ls -t  "$STATE/data/conflicts/reports/" | head                # one comparison report per shadow run
```

**Expected healthy output (target).**

- Rulebook: `status: "APPROVED"`, `live_enabled: true`, `approval.approved_by: "operator"`.
- `conflict-resolver_last.json`: `status: "ok"`, `exit: 0`, `produced_count ≥ 1`, `summary.phase: "shadow"`,
  `summary.notifications: 0` (shadow is ledger-only by design).
- `conflict_events.jsonl` line count advances by the number of reconciled events each shadow run; the comparison
  report exists per `run_id`.

**Broken looks like.**

- Rulebook reverted to `PROPOSED` / `live_enabled: false` — the engine loads as a reference only
  (`scripts/lib/conflicts/profiles/rulebook.py` raises on `PROPOSED` + `live_enabled`, so a half-flipped file
  fails loudly; a full revert is silent and must be caught by monitoring).
- No `conflict-resolver_last.json`, or it reports `exit: 2` / `status` failure, or the ledger line count never
  grows across successive shadow runs (a resolver that runs but writes nothing).
- **Observed now:** none of these artifacts exist — `data/conflicts/` contains only `golden/` test fixtures and
  there is no `conflict-resolver_last.json` (`[VERIFIED]`). The resolver has never run shadow against production,
  and its lane admission was explicitly deferred on main (commit `2e9243672` "Defer conflict-resolver shadow
  admission (unmeasured runtime baseline)"). **Runtime proof is blocked until merge + deploy + lane admission.**

---

## Item 3 — pipeline-freshness SLO `hermes_score_snapshots_2h` same-ET-clock-hour baseline

**What it is.** `scripts/pipeline_freshness_slo.py` compares recent write volume against a trailing baseline. The
`hermes_score_snapshots_2h` check's baseline was changed from `daily_median / 12` to **the median of the same ET
clock-hour across the trailing 7 days × 2** — a false-positive fix for the intraday-shaped scorer (the pre-market
warm-pool pass was WARNing every morning). Merged as #2281 (`69916bf19`) and present in the served release.
`[CODE]` `scripts/pipeline_freshness_slo.py:66`, `:74`.

**Prove it works — read-only commands.**

```bash
# 1) The scorer is running (its own receipt; a measured zero is "nothing_due", not an outage).
jq '{lane_id, status, finished_at, summary, empty_reason, code_sha}' \
  ~/trade-ai-releases/persistent-state/data/runtime/hermes-watchlist-scorer_last.json

# 2) The SLO's own check (health-tick step + cron `15 7-17/2 * * 1-5`); operator/read-only run prints verdicts.
.venv/bin/python scripts/pipeline_freshness_slo.py --dry-run   # if supported; otherwise the live read below
```

**Expected healthy output.**

- `hermes-watchlist-scorer_last.json`: `status: "ok"`, `exit: 0`. `summary.scored` may be `0` with
  `empty_reason: "nothing_due"` — that is the scorer running and finding nothing due, **not** a silent outage
  (the §7 trap: count durable rows, not invocations).
- The SLO `hermes_score_snapshots_2h` check returns **OK** (not WARN) during the pre-market hours where the old
  baseline false-fired — the point of the fix. A real outage still hits `0 → CRITICAL`.

**Observed now (`[VERIFIED]`).** `hermes-watchlist-scorer_last.json` (finished `2026-10-29T21:15:12Z`,
`code_sha 2a2fd5da0`) reports `status: "ok"`, `exit: 0`, `scored: 0`, `empty_reason: "nothing_due"`. The scorer
runs. The SLO check's own verdict is emitted on its next cron/health-tick fire; the baseline query text is present
in the served release.

**Broken looks like.**

- The scorer receipt goes stale or `status` becomes non-`ok` (the scorer lane died).
- The SLO re-introduces pre-market WARN noise (baseline regression) — visible as WARN on
  `hermes_score_snapshots_2h` every pre-market morning despite a healthy `scored` count in the scorer receipt.
- The check is silently removed from `CHECKS` or its baseline rewritten to the old `daily_median/12` form.

---

## Item 4 — Deploy console P1 (read-only in-flight board)

**What it is.** `GET /api/v2/ops/in-flight` returns open (not-merged) PRs to `main` — number, title, head SHA,
mergeable state, and a short `why_held`. Read-only: it calls `gh pr list` (GitHub REST via subprocess), caches 60 s,
and returns `UNAVAILABLE` (never an empty list) on gh failure. Merged as #2284 (`f3b1ff3cf`) and wired at
`scripts/api_v2.py:49486` → `scripts/lib/deploy_in_flight.py` `handle`. `[CODE]` `scripts/lib/deploy_in_flight.py:1`.

**Prove it works — read-only commands.**

```bash
# 1) The endpoint itself (served release; read-only, cached 60 s).
curl -s http://127.0.0.1:<PORT>/api/v2/ops/in-flight | jq '{ok, data: {status: .data.status, count: .data.count, schema: .data.schema, repo: .data.repo, freshness: .data.freshness}}'

# 2) The underlying read, without the server (proves gh auth + parsing).
.venv/bin/python - <<'PY'
from scripts.lib import deploy_in_flight as d
import json
print(json.dumps(d.build(), indent=2))
PY
```

**Expected healthy output.**

- `data.status == "OK"`, `data.freshness == "OK"`, `data.count ≥ 0`, `data.schema == "DeployInFlight@v1"`.
- Every row has `number`, `title`, `head_sha_short`, `mergeable ∈ {MERGEABLE, CONFLICTING, UNKNOWN}`,
  `next ∈ {auto-merge, coordinator, auto-rebase, blocked-shard-hints}`.

**Broken looks like.**

- `status: "UNAVAILABLE"` with a `reason` (gh token expired / network / non-JSON) — the board fails **closed**,
  which is correct, but is silent unless someone looks: this is the monitoring gap.
- `count: null` (unavailable) or rows missing `head_sha`.

**Observed now.** Code is present and wired in the served release; the endpoint itself was not hit from this
agent's shell (the served API is not reachable in this context). Verification is a `curl` / `build()` as above.

---

## Item 5 — Watchers & alerts stoplight strip (Jobs & health)

**Status correction — this is NOT on the served release.** `scripts/lib/jobs_health.py` on main has no `_watchers`
(`[VERIFIED]` — grep found none). The strip is commit `d7d568bb3` "Jobs & health: watchers & alerts stoplight strip
(operator 2026-10-28)" on branch `wt/ops-watchdogs-20261028`, **unmerged**. When it lands, `jobs_health.build` gains
a `watchers` array: the missed-run watchdog plus three hardcoded watcher lanes (`self-heal-fixer`,
`pr-merge-telegram-notify`, `delivery-failure-alerts`), each `ok | degraded | down | absent` → green/amber/red.
`[CODE]` `scripts/lib/jobs_health.py` (branch `wt/ops-watchdogs-20261028`, `_watchers`).

**Prove it works — read-only commands (once merged + deployed).**

```bash
curl -s http://127.0.0.1:<PORT>/api/v2/ops/jobs | jq '{watchers: .watchers, monitor: .monitor}'
```

**Expected healthy output.**

- `watchers` is present; `missed-run-watchdog.status == "ok"` when the independent monitor receipt is fresh
  (`monitor_ok`); each of the three watcher lanes `status: "ok"` when its row `result ∈ {succeeded, due}`.
- A lane that is `absent`/`down` renders red **with a `cause`** — never a silent green (the strip is a guard that
  must actually run, per the `_watchers` docstring).

**Broken looks like.**

- `watchers` missing (the strip didn't ship) or a watcher lane shows `absent` ("Not a registered job — it cannot
  run, watch or page").
- `missed-run-watchdog` shows `degraded` — the independent `cron_outage_watchdog` receipt is missing/stale/dry.

**Observed now.** Not present on the served release; runtime proof is **blocked until merge + deploy**.

---

## DB reads (operator-only)

The shell guard blocks an agent from reading `~/trade-ai-releases/` (any command touching the running-release
paths, including `readlink -f`), and `psql`/secret access is off-limits to an agent (§0 rules, §24.7). **The
operator** runs these two reads to close the loop that no agent can:

```bash
# Resolve the running release pin (an agent may not).
readlink -f ~/trade-ai-releases/portfolio-server/CURRENT

# Postgres row counts behind the dual-write (an agent may not hold the credential).
psql "$DB" -c "SELECT count(*) FROM cio_prospect;"
psql "$DB" -c "SELECT count(*) FROM cio_prospect_events;"
psql "$DB" -c "SELECT max(as_of) AS newest_prospect, count(*) AS n FROM cio_prospect WHERE stage IS NOT NULL;"
```

Reconciliation target: `SELECT count(*) FROM cio_prospect` (judged rows) should converge on the jsonl prospect
count (`wc -l data/cio/cio_instrument_records.jsonl`, minus any non-prospect rows) once the full-universe curator
pass runs with the flag on. Until then, PG holds only the entry-state subset.

## Summary table

| # | Item | On served release? | Runtime proof status |
|---|---|---|---|
| 1 | `cio_prospect` PG dual-write | code yes; flag+tables yes | **LIVE** — entry-state receipt `dual_write`, `pg_upserted:1` (`[VERIFIED]`). Full-universe backfill pending next curator pass. |
| 2 | conflict engine rulebook | **no** (PROPOSED/`live_enabled:false` on main; activation on `wt/ops-watchdogs-20261028`) | **BLOCKED** — no shadow run, no lane admission, rulebook not activated on the served release. |
| 3 | SLO `hermes_score_snapshots_2h` baseline | yes (#2281) | **LIVE** — code served; scorer running (`[VERIFIED]`). Verdict on next SLO fire. |
| 4 | Deploy console in-flight board | yes (#2284) | **LIVE (code)** — wired; endpoint not hit from agent shell (server unreachable here). |
| 5 | Watchers & alerts stoplight | **no** (on `wt/ops-watchdogs-20261028`) | **BLOCKED** — not merged/deployed. |
