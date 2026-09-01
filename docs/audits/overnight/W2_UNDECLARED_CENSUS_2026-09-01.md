# W2 Undeclared Census — 2026-09-01 (batch2 + batch3)

Authority: **READ_ONLY_ADVISORY** · `MBI_BEHAVIOR=0`  
Worktree: `/home/johnclaw/tradeai-wt-n3-undeclared-apply` · branch `wt/n3-undeclared-apply`  
Scope: shrink `undeclared_baseline` by promoting systemd timers that have a named durable `output_signal`, or retiring spent one-shots with ESTABLISHED evidence. No scheduler installs/removals. No hub↔PS repoint.

## Numbers

| Metric | Before batch2 | After batch2 | After batch3 |
| --- | ---: | ---: | ---: |
| `undeclared_baseline` | 556 | 537 | **535** |
| declared `lanes` | 40 | 59 | **61** |
| Gate `undeclared` NEW | `[]` | `[]` | **`[]`** |
| pytest `tests/test_lane_registry.py` | 32 passed | 32 passed | **32 passed** |

Net shrink this wave (batch2+3): **556 → 535 (−21)**. Not a sweep of all ~535 remaining.

Batch1 (prior): 563 → 556 (−7); due-checkpoints, cio-delivery, cio-defer-revisit, autonomy-watchdog, hermes-momentum-catalyst-morning; cron-freshness-watcher RETIRED; wake-dispatch duplicate removed.

## Batch2 promotions (ACTIVE) — durable `file_mtime`

| lane_id | timer | output_signal path |
| --- | --- | --- |
| portfolio-backup-cadence | tradeai-portfolio-backup-cadence.timer | `data/runtime/portfolio_maintenance_backup_last_run.json` |
| portfolio-daily-cadence | tradeai-portfolio-daily-cadence.timer | `data/runtime/portfolio_maintenance_daily_last_run.json` |
| portfolio-weekly-cadence | tradeai-portfolio-weekly-cadence.timer | `data/runtime/portfolio_maintenance_weekly_last_run.json` |
| portfolio-monthly-cadence | tradeai-portfolio-monthly-cadence.timer | `data/runtime/portfolio_maintenance_monthly_last_run.json` |
| portfolio-lookthrough-cadence | tradeai-portfolio-lookthrough-cadence.timer | `data/runtime/portfolio_maintenance_lookthrough_last_run.json` |
| governance-pipeline | tradeai-governance-pipeline.timer | `data/runtime/governance_pipeline_last_run.json` |
| cio-nightly-reflection | tradeai-cio-nightly-reflection.timer | `data/cio/cio_reflection_candidates.jsonl` |
| cio-memory-shadow-measure | tradeai-cio-memory-shadow-measure.timer | `data/cio/memory_shadow_measure_latest.json` |
| cio-desk-memo-regen | tradeai-cio-desk-memo-regen.timer | `data/cio/cio_desk_note_latest.md` |
| sm-render | tradeai-sm-render.timer | `data/runtime/sm_render_state.json` |
| tax-lots-rebuild | tradeai-tax-lots-rebuild.timer | `data/runtime/tax_lots_rebuild_latest.json` |
| provider-cost-reconcile | tradeai-provider-cost-reconcile.timer | `data/runtime/provider_cost/latest_reconciliation.json` |
| free-first-circulation | tradeai-free-first-circulation.timer | `data/cio/free_first_last_run.json` |
| holdings-agent-enqueue | tradeai-holdings-agent-enqueue.timer | `data/runtime/holdings_agent_enqueue_latest.json` |
| hermes-update-check | hermes-update-check.timer | `data/runtime/hermes_update_status.json` |
| portfolio-price-cache | portfolio-price-cache.timer | `data/portfolios/state/price_cache.json` |
| agent-runtime-health | tradeai-agent-runtime-health.timer | `/home/johnclaw/.local/state/tradeai/agent-runtime-health.json` (absolute; unit writes outside `data/`) |

## Batch2 retirements (RETIRED, ESTABLISHED)

| lane_id | timer | evidence |
| --- | --- | --- |
| at-observation-01 | at-observation-01.timer | One-shot `OnCalendar=2026-07-27 06:55:00`, `Persistent=false`; `SubState=elapsed`, empty `NextElapse`. Spent session-1 capture. |
| at-observation-01-closeout | at-observation-01-closeout.timer | One-shot `OnCalendar=2026-07-27 10:12:00`; same elapsed/no-next. Spent session-1 closeout. |

`reason_confidence=ESTABLISHED`. Scripts still exist; retirement is “spent one-shot calendar,” not “script missing.”

## Batch3 promotions (ACTIVE)

| lane_id | timer | output_signal path |
| --- | --- | --- |
| advisory-shadow-seed | tradeai-advisory-shadow-seed.timer | `data/cio/agent_tool_traces.jsonl` |
| cio-material-scan | tradeai-cio-material-scan.timer | `data/audit/cio_material_scan_last.json` |

`cio-material-scan` receipt is under **release-local** `data/audit/` (not a PS overlay). See monitor-root section.

## Honest keeps (still in baseline) — examples

Not promoted when no durable PS/`data/` signal could be named without inventing:

- **OS user timers**: `launchpadlib-cache-clean.timer`, `snap.firmware-updater.firmware-notifier.timer`, `systemd-tmpfiles-clean.timer`, `ubuntu-insights-collect.timer`, `ubuntu-insights-upload.timer` — live Ubuntu/snap units; not Trade AI producers; not dead.
- **`tradeai-maturity-feeds.timer`**: writes `hermes_maturity_history` (DB only). No file artifact; DB role not verified from this worktree for a `db_max` declaration this pass.
- **`tradeai-watch-decision-scheduler.timer`**, **`tradeai-iris-taxonomy.timer`**, **`tradeai-backup-enforcer.timer`**: enqueue/DB/log/stdout without a clear last_run JSON under `data/`.
- **Hermes docs reporters** (`hermes-observation-check`, backlog-health, embedding-promotion-review, source-discovery-dryrun): intend `docs/hermes/.../latest_*.json`, but observation/backlog/embedding dirs were empty at census time despite journal claiming report paths — not promoted.
- **`tradeai-agent-runtime@*.timer`** + producer: shared/queue state under `~/.local/state/tradeai`; per-instance durable path not cleanly nameable.
- Many advisory/hermes workers / aegis / recovery / news / db-retention: no unique durable last_run under preferred roots without conflating shared stores or logs-as-existence.

## Dual-home blocker (quoted honestly)

Several timers use `WorkingDirectory=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild` while CURRENT overlays `data/{cio,runtime,portfolios/state}` → PS. Live writes for governance / tax-lots / holdings-enqueue / sm-render / hermes-update / price-cache often land in **v12-rebuild’s private `data/`**, leaving PS copies stale. Canonical relative paths are still declared (same precedent as existing lanes); monitor root choice determines LIVE vs SILENT. This is a root/wiring problem, not a reason to leave producing timers undeclared forever.

---

## Monitor-root section (proposal only — do NOT repoint)

### What `observe_signal` resolves against today

In `scripts/lib/lane_registry.py`:

- `ROOT = Path(__file__).resolve().parent.parent.parent` → **the hub/checkout that contains the module** (this worktree when imported from here).
- `observe_signal(..., root=None)` defaults to that `ROOT`. Relative `output_signal.path` values become `root / path`.

So with `root=None`, the monitor reads **checkout-local** trees (`tradeai-wt-n3-undeclared-apply/data/...`), which do **not** carry the CURRENT→PS overlays for `data/cio` / `data/runtime`.

### What writers use

`scripts/lib/canonical_store_registry.production_state_root()` resolves to:

1. `TRADEAI_STATE_ROOT` / `TRADEAI_ROOT` if set  
2. else `TRADEAI_PERSISTENT_STATE_ROOT` if set  
3. else `~/trade-ai-releases/persistent-state` when `PERSISTENT_STATE_ROOT.json` exists  
4. else CURRENT, else checkout  

On this host: **`production_state_root() → /home/johnclaw/trade-ai-releases/persistent-state`**.

Most durable CIO/runtime writers that honor the store registry (and units whose `WorkingDirectory` is CURRENT with overlays) write under PS.

### What CURRENT/`data` points at (symlink check, 2026-09-01)

- `~/trade-ai-releases/portfolio-server/CURRENT` → `.../efcc51365-main-exact-phase2-20260831-114929`
- `CURRENT/data` — **directory** (not a symlink to PS)
- `CURRENT/data/cio` → **symlink** → `persistent-state/data/cio`
- `CURRENT/data/runtime` → **symlink** → `persistent-state/data/runtime`
- `CURRENT/data/health` → **symlink** → `persistent-state/data/health`
- `CURRENT/data/portfolios` — directory; `.../state` → **symlink** → `persistent-state/data/portfolios/state`
- `CURRENT/data/audit` — **release-local directory** (not overlaid)
- `CURRENT/logs` → **symlink** → `persistent-state/logs`

Worktree `tradeai-wt-n3-undeclared-apply/data/cio` is **absent**; `data/runtime` and `data/audit` are local stubs — so default `observe_signal` from this checkout will miss live PS artifacts unless `root` is passed.

### What changes if monitor were repointed to PS (proposal only)

**Do not implement in this wave.** If `collect_lane_registry_report(..., root=production_state_root())` (or equivalent):

- Relative `data/cio/*` and `data/runtime/*` signals would read the **live durable** copies (matching CURRENT overlays).
- `data/audit/cio_material_scan_last.json` would still be **absent on PS** unless audit is overlaid or the signal is absolutized to CURRENT — material-scan would stay UNVERIFIABLE under pure-PS root.
- Absolute signals (e.g. agent-runtime-health under `~/.local/state/tradeai`) unchanged.
- Dual-homed writers that only touch v12-rebuild `data/` would still look SILENT under PS until those units are moved to CURRENT/PS — that SILENT would become a useful dual-home finding rather than a false LIVE against a stale checkout copy.

---

## Gate / pytest (post batch3)

```text
PYTHONPATH=scripts:. python3 scripts/check_lane_registry.py --json
  errors: []
  undeclared NEW: []
  declared: 61

PYTHONPATH=scripts:. python3 -m pytest tests/test_lane_registry.py -q
  32 passed
```

Working tree left dirty for parent commit/PR. No cron/systemd mutation. No `docs/INDEX.md` touch.
