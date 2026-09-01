# PHASE 216B — Doc vs Portal Mismatch Audit (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:50:18-04:00
Measured at: efcc51365 / not measured

Compared stale architecture/matrix docs to live portal (216A). Mismatches found: **6**.

| # | Stale doc claim | Live portal truth | Resolution |
|---|---|---|---|
| 1 | "10 live loops" | **11** (added external_researcher_feedback) | corrected in new matrix |
| 2 | External lanes "designed, advisory-only, **not enabled**" | Grok **WIRED+working** (xai-oauth proxy); Codex **authed** (interactive); Claude **authed** (credits needed); Nous pending | corrected |
| 3 | serverops "future (HOLD)" / unset | serverops has **18 tools enabled** incl terminal/code_execution/computer_use — **P1 hardening required** | corrected + flagged |
| 4 | Codex: "future Codex (high-risk tools off)" | dev=gpt-5-codex authed; **headless unavailable** (hermes_headless_limit); runtime enabled=false (human-invoked) | corrected |
| 5 | Internal deep lane status ambiguous | **designed (not enabled)** per researcher-matrix; runner built, nightly timer scheduled | clarified (built+scheduled, lane status "designed/operator-run") |
| 6 | Kill-switch path references | canonical `data/runtime/HERMES_DISABLED` (Phase 214); retired ignored | corrected |

No mismatch found on: loop_count safety (0 mutate scoring — correct), tradeai/tradeai12b tool-less (0/0 — correct),
retired gateway disabled (correct), 19 workflows / 9 nodes / 6 tables / 13 views (matches).
