---
id: DSN-20261030-disk-monitor-purge
title: Disk-space growth monitor + reviewed purge mapping (ENOSPC follow-on)
status: PROPOSED
approval: operator (§17 scheduler install + lane row; §24.12 any purge-rule enable; threshold constants)
source: operator 2026-10-30 — ENOSPC truncated holdings.json to 0 bytes and broke the Command Center
phases:
  - id: DSN-20261030-disk-monitor-purge-P1
    title: Host-resident growth monitor (measure + baseline + transition alerts, no deletion)
    status: DONE
    tasks:
      - id: DSN-20261030-disk-monitor-purge-P1-T1
        title: scripts/disk_monitor.py + config/disk_monitor.json + tests + CI gate
        status: DONE
        areas: [scripts/disk_monitor.py, config/disk_monitor.json, tests/test_disk_monitor_20261030.py, config/ci_gates/disk_monitor_20261030.json]
  - id: DSN-20261030-disk-monitor-purge-P2
    title: Operator sign-off — purge-rule extensions in config/disk_hygiene_rules.json
    status: PROPOSED
  - id: DSN-20261030-disk-monitor-purge-P3
    title: Operator install — cron line + lane-registry row
    status: PROPOSED
---

# Disk-space growth monitor + reviewed purge mapping

## Why

In the ~48h before 2026-10-30, disk exhaustion (ENOSPC) truncated `holdings.json` to **0 bytes** and broke the
Command Center. Root was measured **98% used** (432G/468G, 12G free) at design time and `~/.hermes/state.db` was
**13.6 GB and still growing** (mtime 2026-10-30 11:25 ET). The known top consumers were `~/.cache` ≈75 GB, worktrees
(`~/tradeai-wt-*` ≈31 GB + `~/wt-*` ≈49 GB + `~/worktrees` ≈11 GB), `~/.hermes/state.db` 13.6 GB, a tail of
append-only `*.jsonl` stores 100 MB–2.2 GB, `~/.codex` 8.7 GB, `~/.npm` 4.7 GB, and `~/logs/*.log` up to 448 MB.

There was **no monitor/alert that would have caught this before ENOSPC.** The n8n band monitor
(`scripts/disk_usage_monitor.py`, lane `disk-usage-monitor`) fires only at ≥80% used and is still gated behind the
n8n relay (a fire is demoted to `dry_run` until the lane is in `TRADEAI_N8N_RELAY_LIVE_LANES`); it keeps **no
baseline**, so a store growing 63 MB/day (`research_call_accounting`) or a cache that doubles between polls is
invisible until the 80% band trips. A band alert that first fires at 80% on a 468 GB disk gives little runway.

This design fills the gap with a **host-resident growth monitor** (not n8n, not LLM-heavy) that measures both
usage % and per-path growth against a persisted baseline, and alerts on the **transition** — not the evaluation —
with the exact paths, sizes and the operator-gated purge command. It deletes nothing.

> **Overlap note (AGENTS.md §11):** a sibling `DSN-20261030-disk-recovery` is in flight in worktree
> `~/tradeai-wt-disk-root-cleanup-20261030`, modifying `scripts/disk_hygiene.py` and
> `scripts/disk_usage_monitor.py` (backup-byte reporting, disk category sizes, backup receipts during fill). This
> design **reads** those scripts (the manifest / `--dry-run`) but modifies neither; the file sets are disjoint.

## What already exists (extend, do not duplicate)

| component | what it does | this design |
|---|---|---|
| `scripts/disk_usage_monitor.py` (n8n `*/15`) | df bands ok/warn/critical, one host intent per band change | untouched; the growth monitor is the host complement |
| `scripts/disk_hygiene.py` + `config/disk_hygiene_rules.json` | reviewed rules G (git/worktrees), R (releases), C (caches), never-touch; `--apply` is grant-gated | the monitor quotes its `--dry-run`/manifest; rules extend here (§24.12) |
| `scripts/tmp_hygiene_auto.py` | host timer, deletes /tmp under standing approval, `telegram_alert` + `alert_condition_state` dedupe | the dedupe + alert pattern this monitor copies |
| `config/disk_hygiene_rules.json` `jsonl_retention` | rotation-to-archive (never delete), `enabled: false` | the map for oversized-jsonl compaction |

The monitor's **own** config lives in a new file `config/disk_monitor.json` — deliberately **not** in
`config/disk_hygiene_rules.json`, which is operator-only (§24.12) and sha-pinned by the disk-standing-apply packet.

## Monitor design (P1 — implemented)

`scripts/disk_monitor.py`:

- **Modes**: `--dry-run` (default — measure + print, write/send nothing), `--apply` (record baseline + alert +
  `LaneRunReceipt`), `--with-hygiene` (also run `scripts/disk_hygiene.py --dry-run --report` and quote it).
- **Measures**: df-style used% of `/` (used/(used+available)); `du` of each hotspot
  (`~/.cache`, `~/.npm`, `~/.codex`, `~/.hermes/state.db`, `~/logs`, `~/worktrees`, `~/wt`, `~/wt-*`,
  `~/tradeai-wt-*`).
- **Baseline** (`DiskMonitorBaseline@v1`) at `<state root>/data/runtime/disk_monitor_baseline.json` (atomic write,
  same root the receipts use): a stable reference (`baseline_at`), the last snapshot (`mounts`/`hotspots`), and a
  rolling `samples` ring (8) for the growth window. First run seeds it and sends nothing.
- **Growth detection**: mount used% band (80/90); mount growth = `used_bytes −` earliest sample within
  `growth_window_hours` (24h), banded at `grow_warn_bytes` 20 GiB / `grow_critical_bytes` 50 GiB; per-hotspot flag
  (`growing`) when `bytes ≥ hotspot_growth_min_bytes` (1 GiB) **and** `≥ hotspot_growth_ratio` (1.5×) the baseline.
- **Alert**: `telegram_alert.send_telegram(priority=…)` only on a transition, deduped by `alert_condition_state`
  with stable keys `host:disk_monitor:<mount>:used` / `:growth` / `host:disk_monitor_hotspot:<id>` (never a raw
  percent). warn → **P2**, critical → **P1** (disk about to fill is operator-actionable). The text carries the exact
  paths + sizes, the growth delta + rate/day, the latest hygiene manifest's reclaimable estimate, and the
  operator-gated purge command.
- **Never deletes** (§0 rule 6): the alert reports what `disk_hygiene.py` would reclaim and prints
  `TRADEAI_DISK_HYGIENE_GRANT=<grant> scripts/disk_hygiene.py --apply …`.
- **Fail closed** (§7): an unmeasurable mount/hotspot keeps its prior baseline value and records the failure beside
  it, never an error string in the value slot. An unmeasurable hotspot is a **degradation** (recorded), not a run
  failure; only an unmeasurable mount or a failed write/send fails the run.

## Cadence (P3 — PROPOSED, operator install)

Host cron (Eastern), **6×/day, every 4h**, includes the 08:00 ET pre-market check. Not LLM-heavy, so no
`run_with_deepseek_offpeak.sh` wrapper:

```
0 0,4,8,12,16,20 * * * cd $PROJ && $PY scripts/disk_monitor.py --apply >> logs/disk_monitor.log 2>&1  # TRADEAI_LANE disk-monitor
```

`$PROJ` = the served release dir (`readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`), `$PY` = `.venv/bin/python`.
Optional: add `--with-hygiene` to the 08:00 run only, so the day's first alert carries a live (not weekly) reclaim quote.

## Purge targets → reviewed rules (P2 — PROPOSED, operator sign-off)

| consumer (measured) | existing rule | action needed (operator) |
|---|---|---|
| `~/tradeai-wt-*`, `~/wt-*`, `~/worktrees`, `~/wt` | **G (git)** — `~` depth-1 root already discovers the `wt-*`/`tradeai-wt-*` trees; `~/worktrees`, `~/wt` are explicit roots; idle 7d, clean/merged/unreferenced | none (verify with a `--dry-run`); candidates are selected but `--apply` still needs the grant |
| `~/.cache`, `~/.npm` | **C (caches)** — `~/.cache/pip`, `~/.npm/_cacache` exist, `enabled: false`; roots are `report_only` | flip `enabled: true` (and re-run the reviewed PR); a size-based cap is a follow-on |
| oversized append-only `*.jsonl` | **`jsonl_retention`** (rotate-to-archive, `enabled: false`) | flip `enabled: true`; rotation archives, never deletes |
| `~/logs/*.log` (up to 448 MB) | none — **new rule** needed | operator sign-off; propose a rotated-log rule (age > N days), never the live tail |
| `~/.hermes/state.db` (13.6 GB, growing) | none — **live DB** | **operator decision only**; flag, measure, alert; never auto |
| `~/.codex` (8.7 GB) | none | operator sign-off (codex sessions/cache) |

Proposed rule fragments (for `config/disk_hygiene_rules.json`, operator-only, shipped as a **disabled**/reviewed
change so nothing selects them until enabled — deletion still needs `--apply` + grant):

```json
{ "caches": { "rules": [
  { "path": "~/.cache/pip", "older_than_days": 30, "item_depth": 1, "enabled": false },
  { "path": "~/.npm/_cacache", "older_than_days": 30, "item_depth": 1, "enabled": false }
] } }
```

(rotated-log and `~/.codex` are **not** added here — they are new rule kinds / new never-touch exceptions that
require the operator's explicit decision; see decisions below.)

## Operator-only decisions (propose, do not install)

1. **Scheduler install** — the cron line above + a lane-registry row (fragment below). §17 / §9.3.
2. **Purge-rule enables** — `caches.*.enabled: true`, `jsonl_retention.enabled: true`, and any **new** rotated-log /
   `~/.codex` rule. §24.12. The monitor deletes nothing on its own.
3. **`~/.hermes/state.db`** — live DB growth must be fixed at its source (the writer), not purged. Operator decision.
4. **Threshold constants** — 80/90% used, 20/50 GiB/24h growth, 1.5×/1 GiB hotspot — reviewed in
   `config/disk_monitor.json`; changing them is a reviewed config change.
5. **`TRADEAI_DISK_HYGIENE_GRANT`** — any actual `--apply` of `disk_hygiene.py` remains grant-gated.

### Proposed lane-registry row (NOT installed)

```json
{
  "lane_id": "disk-monitor",
  "owner": "platform",
  "scheduler": { "kind": "cron", "expression": "0 0,4,8,12,16,20 * * *", "match": "scripts/disk_monitor.py",
                 "cadence": "0 0,4,8,12,16,20 * * *", "stage": "canary", "wave": "W1" },
  "expected_cadence_hours": 4,
  "state": "NEVER_SCHEDULED",
  "state_reason": "PROPOSED 2026-10-30 (ENOSPC follow-on). Host-resident disk GROWTH monitor: df on / + du of the known hotspots vs a persisted baseline (per-path delta + 24h growth), transition-only telegram_alert (P2 warn / P1 critical) deduped by alert_condition_state. NEVER deletes; reports the reviewed disk_hygiene reclaim + operator-gated purge command. Not LLM-heavy (no offpeak wrapper).",
  "output_signal": { "kind": "json_key", "path": "data/runtime/disk-monitor_last.json", "key": "ok_at" },
  "reason_confidence": "ESTABLISHED",
  "reason_evidence": "tests/test_disk_monitor_20261030.py; docs/designs/DSN-20261030-disk-monitor-purge.md",
  "note": "Writes only <state root>/data/runtime/disk_monitor_baseline.json, the alert_condition_state conditions, and its LaneRunReceipt. Sends only on a band/growth transition. Reads the latest disk_hygiene manifest (weekly) for the reclaim estimate.",
  "severity": "Medium",
  "dispatch": { "mode": "live", "cron": ["0 0,4,8,12,16,20 * * *"], "tz": "America/New_York", "wave": "W1",
                "class": "monitor", "priority": 1, "retry_policy": "transient-2" }
}
```

## Honesty

- Hermetic PASS ≠ OBSERVED. "Working" is the forced run under its schedule's exact form (§8.1) after the operator
  installs the cron line; until then the monitor is code-complete and its `--dry-run` is quoted, nothing more.
- The monitor is a **detector + reporter**, not a purger: it only removes disk pressure if the operator then runs
  the (already reviewed, grant-gated) `disk_hygiene.py --apply`, or enables a standing rule. The alert's reclaim
  estimate is only as fresh as the last hygiene manifest (weekly) unless `--with-hygiene` is passed.
