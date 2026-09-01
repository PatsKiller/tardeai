# PHASE 217B — Canonical Status Builder (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T18:49:05-04:00
Measured at: efcc51365 / not measured

`scripts/build_hermes_canonical_status.py` (read-only) merges live /api/v2/hermes/* + systemd timer state into
`data/runtime/hermes_canonical_status_latest.json`. Normalized fields: portal counts, profiles[], llm_lanes[],
self_learning_loops, graph_nodes[], retired_agents, gateway_status, kill_switch, deep_research_lane
(design/runner_built/timer_enabled/next_run/model/safety), codex_lane (auth/interactive/headless/runtime),
serverops (tool_count/risk/p1), canonical_docs, open_gates. Verified: 19 wf/9 nodes/6 tables/13 views,
deep timer_enabled=true, codex headless=false (hermes_headless_limit), serverops=18/P1.
