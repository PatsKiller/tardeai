# n8n relay live lanes — derived from the lane registry (AGENTS.md 20.4.0)

```
Status:   CODE ON MAIN AFTER MERGE; INERT until AGENTS.md 20.4.0 is ACTIVE (policy read, no flag)
as_of:    2026-10-25
Code:     scripts/lib/n8n_relay_live_lanes.py · scripts/render_n8n_relay_live_lanes.py
          scripts/lib/n8n_due.py parse_relay_live_lanes · scripts/n8n_run_relay.py (status: live_lanes_source)
Deploy:   scripts/cio_phase2_exact_main_deploy.sh render_relay_live_lanes (prepare, before the integrity manifest)
Tests:    tests/test_n8n_relay_live_lanes_registry_20261025.py (CI gate relay_live_lanes_registry_20261025)
```

Operator, 2026-10-25: "fully done, fully automatic, no input by me, for the train systems unless there's an issue."

## What changes at ratification

Before 20.4.0 is ACTIVE nothing changes: the relay and the coordination gateway read
`TRADEAI_N8N_RELAY_LIVE_LANES` from `~/.config/tradeai/n8n-live-lanes.env` (loaded by their units), exactly as
today. From the moment the release's `AGENTS.md` shows 20.4.0 ACTIVE (header, current row and the `| 20.4.0 |` row;
`scripts/lib/hands_off_policy.py`), the live list is the release's rendered registry list. No grant, host edit or
flag is needed after the ratifying release is promoted; the promote restarts the relay and gateway (both are bound
units in `TRADEAI_CURRENT_BOUND_UNITS` and in the train delegation's `limits.named_services`).

## The registry rule

`<release>/N8N_RELAY_LIVE_LANES.json` (`N8nRelayLiveLanesRender@v1`, stamped with `BUILD_SHA` and the sha256 of the
registry and allowlist bytes) lists a lane when its allowlist entry has a non-null `live_arg`,
`lane_dispatch.dispatch_eligible` admits it (no operator hold, stay_on_cron, forbidden token, stay-behind), and
either its dispatch block is `live` (stage absent, `canary` or `cutover`, R1 class admitted) or it is a native
`scheduler.kind: n8n` row with stage `canary`/`cutover`. `shadow` is never live. A native n8n row with no stage is
not listed.

## Precedence (every override is pause-only)

```
effective = rendered registry list − ops-controls paused − host-file paused
```

| layer | where | what it can do |
|---|---|---|
| registry render | `<release>/N8N_RELAY_LIVE_LANES.json`, rendered at deploy | the ONLY source that adds a lane (via a reviewed registry PR) |
| ops-controls override | `$TRADEAI_STATE_ROOT/data/governance/n8n_relay_live_overrides.json` (`N8nRelayLiveOverrides@v1`, `{"paused": {"<lane>": {"by","at","reason"}}}`) | pause / resume a lane; repo-independent, survives every release |
| host file | `~/.config/tradeai/n8n-live-lanes.env` key `TRADEAI_N8N_RELAY_LIVE_LANES_PAUSED` | pause a lane at the host terminal |
| host file legacy key | `TRADEAI_N8N_RELAY_LIVE_LANES` | FALLBACK only: used when the render is missing, malformed or stale |

Why pause-only: an add outside the registry would recreate the unreviewed live widening this change removes. With
every layer narrowing, the layers never conflict: the most restrictive wins, and a pause holds until the layer that
set it lifts it.

Fail-safe: a missing/malformed/stale render → the legacy host list (yesterday's behavior, never wider). A present
but unreadable or wrong-schema ops override file → an empty live list (it might be hiding a pause). Lane ids are
the only values read from either override layer.

## For the Ops Controls relay toggle (feat/ops-controls-toggles-20261025)

Today `n8n_live_list.add/remove` (scripts/lib/ops_controls_core.py) rewrites the host file's
`TRADEAI_N8N_RELAY_LIVE_LANES` line. From 20.4.0 ACTIVE that line is only the fallback, so the toggle should write
the ops override file above instead (atomic replace, schema `N8nRelayLiveOverrides@v1`, pause = add a key,
resume = remove it) and keep restarting `live_list.restart_units`. "Add to live" outside the registry is not an
override; it becomes a registry PR.

## Check before ratifying

`render_n8n_relay_live_lanes.py --root <CURRENT> --diff-host-file ~/.config/tradeai/n8n-live-lanes.env` prints
lane ids only: `registry_only` (lanes the registry makes live that the host list does not) and `host_only` (lanes
live today that the registry would drop). Reconcile `host_only` (registry stage `canary`, or accept the drop)
before the ratifying release is promoted.
