# Phase 208C — Hermes SOUL Audit (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:27:54-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_souls.py` → `data/hermes/hermes_soul_audit_latest.json` (read-only, no secrets).

## Required conclusions
- Active SOUL count: **5** (default, tradeai, tradeai12b, dev, serverops).
- Retired SOUL count: **4** (sidecar snapshots in .hermes.RETIRED_* — audit-only).
- Duplicate SOUL hashes: only among **retired** snapshots (same content captured at 2140 & 2154) — expected, harmless. No active duplicates.
- Active SOULs safe: **YES** — every active SOUL has zero un-negated unsafe-enablement phrases.
- Any active SOUL references retired sidecar paths: **NO**.
- Any active SOUL can enable live trading: **NO**.
- Any active SOUL can enable broker mutation: **NO**.

## Active SOUL hashes
default 456b8b44 · dev 5b3364df · serverops 4b7a5b80 · tradeai c98d2b80 · tradeai12b d3c0c983 — all distinct, all clean.

## Notes
- tradeai/tradeai12b SOULs carry explicit boundary lines (no trades/orders/stops/proposals; no raw secrets).
- dev SOUL carries dev-mode + Codex data-safety policy (redact before cloud; human-invoked; not autonomous).
- Checker uses sentence-scoped negation (so "You do not execute trades" is correctly treated as safe).
