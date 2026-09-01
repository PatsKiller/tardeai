# Phase 208F — Retired Hermes Artifact Dependency Proof (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:31:05-04:00
Measured at: efcc51365 / not measured

## Proven: retired artifacts are AUDIT-ONLY; nothing active depends on them.

1. **Retired dirs exist for rollback/audit only** — `.hermes.RETIRED_20260606_2140`,
   `.hermes.RETIRED_20260606_2154`, `install.RETIRED_20260606_2140` present; mtimes 2026-06-06 (and original
   May-30 content) — **unchanged by this audit** (no write today). Tamper-proof confirmed.
2. **Gateway disabled does not break active profiles** — `hermes-gateway.service` is `is-enabled=disabled`,
   `is-active=failed`; the 5 global profiles + 9 research timers run independently (Phase 208D/E). All 9
   timers last-result = success.
3. **Active jobs do not source retired config** — call graph (208D): every scheduled job uses
   `.venv/bin/python scripts/hermes_*.py`; none reads `.hermes.RETIRED_*` config.
4. **Active jobs do not execute retired wrappers** — `run_hermes_readonly.sh`/`run_hermes_gateway.sh` are
   retirement stubs (print + exit 2). No job invokes them.
5. **Active jobs do not require the retired gateway** — 0 jobs depend on it (208D).
6. **Retired wrappers remain non-executed** — no live process uses `hermes_sidecar/install/.venv` or any
   `.RETIRED` path (process scan empty).
7. **No UI action route can run a retired artifact** — the only code touching retired paths is **read-only
   display**: `scripts/api_v2.py` + `scripts/hermes_legacy_agent_inventory.py` enumerate retired artifacts
   for the v3 legacy-agents panel; `scripts/docs/update_reference_architecture_hermes_v1_8.py` only mentions
   them in generated doc text. None execute or import retired code.

## Single benign residual
The **disabled** `hermes-gateway.service` unit file still contains the old sidecar ExecStart — inert
because disabled. Recommend repointing/removing in a separate operator-approved change (not a safety
dependency; cannot start).

## Method
grep (scripts/timers), systemctl is-enabled/is-active + show, `ps -eo args` process scan, directory mtimes,
and the 208D call graph. All read-only.
