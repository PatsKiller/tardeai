# Phase 208A — Hermes End-to-End Audit Preflight (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:25:20-04:00
Measured at: efcc51365 / not measured

Safety snapshot before the audit. Read-only.

## Host / git
- host ms01-openclaw, user johnclaw, branch main.
- Working tree dirty = 25 files (config/strategies daily YAML + auto-gen governance/maturity/audit _latest — pre-existing runtime churn, not staged).

## Hermes runtime
- CLI `~/.local/bin/hermes` → global venv; **Hermes Agent v0.16.0 (2026.6.5)**.
- Profiles: default gemma3:4b · tradeai gemma3:4b · tradeai12b gemma3:12b-ctx4k · dev (model unset) · serverops (model unset).
- Tools enabled: **tradeai 0 · tradeai12b 0** (safety-critical disabled) · dev 14 (terminal/code_execution/computer_use already disabled).
- Gateway `hermes-gateway.service`: **active=failed, enabled=disabled** ✓ (must remain disabled).

## Schedulers
- 9 hermes-* systemd user timers active; 10 hermes-* services; 16 crontab hermes-related lines.
- Only live hermes process = operator's interactive global chat (`hermes-agent-venv/bin/hermes`). No sidecar gateway process.

## Endpoints
- `/api/v2/hermes/legacy-agents` → HTTP 200 (exists).

## Retired artifacts (baseline mtimes captured for tamper-proof)
- hermes_sidecar/.hermes.RETIRED_20260606_2140, .hermes.RETIRED_20260606_2154, install.RETIRED_20260606_2140 — preserved, read-only.

## Safety posture confirmed before audit
Gateway disabled; tradeai/tradeai12b tools zero; no live trading; no broker/proposal/protection mutation planned. Audit-first.
