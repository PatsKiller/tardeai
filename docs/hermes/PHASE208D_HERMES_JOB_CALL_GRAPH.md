# Phase 208D — Hermes Job-to-Agent Call Graph (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:28:53-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_job_call_graph.py` → `data/hermes/hermes_job_call_graph_latest.json` (read-only).

## Required conclusions
- Jobs audited: **25** (systemd hermes-*.service units + crontab hermes/coordinator/librarian lines).
- Any job calls retired wrapper: **only one reference** — the `hermes-gateway.service` unit file still
  contains the old sidecar ExecStart. **That unit is `is-enabled = disabled`** → it never runs. **No ACTIVE/
  scheduled job calls a retired wrapper.**
- Any job depends on retired gateway: **NO**.
- Any job blocked by gateway disabled: **NO** (research fleet runs via project scripts/timers, not the gateway).
- Live research-fleet jobs mapped: **YES** (autonomous-loop, source-discovery, librarian-backlog,
  embedding-promotion-review, backlog-health, shadow-scorer, observation-check, advisory-cache, momentum-catalyst).
- All live jobs have an active owner: **YES** — every scheduled job invokes `.venv/bin/python scripts/hermes_*.py`.
- Jobs with broker/trading keyword: **NONE** — no Hermes job touches broker/order/stop/proposal/GO-WAIT/live-trading.

## The single retired reference (honest)
`hermes-gateway.service` (disabled) → ExecStart points at `hermes_sidecar/install`. Because it is
disabled+failed it cannot start (manually or on boot). It is retained as an inactive audit artifact;
recommend removing/repointing the unit file in a separate operator-approved change (not required for safety).

## Mapping
All 9 enabled hermes-* timers → project `.venv` + `scripts/hermes_*.py` (research/advisory, staging only,
reads Trade AI safe views). No retired path, no broker, no gateway dependency.
