# Agent Collaboration & Outcomes — Design Notes (v2.0 RACI)

**Date:** 2026-05-24
**Target:** `apps/command-center-v2/src/pages/AgentCollaboration.tsx`

## What Changed (v1 -> v2)

| Area | v1 (Decision Operations) | v2 (Collaboration & Outcomes + RACI) |
|------|--------------------------|--------------------------------------|
| Title | "Decision Operations" | "Agent Collaboration & Outcomes" |
| Scorecard | Ready, Blocked, Active, Stale, Trust | Ready for John, Blocked, **Waiting on Agent**, Stale, Trust |
| Scorecard clicks | Ready + Blocked only | All cards clickable as filters |
| Filter chips | All, Ready, Blocked, Waiting, Stale, Running | + **Completed** |
| Agent chips | Display only | **Clickable** — filter missions by agent |
| Agent filter | None | Clearable chip with active indicator |
| Inspector sections | Header, Next Action, Blocker, Agents, Items, Stats | A-H structured: Summary, **RACI**, Why This Matters, Blockers, Agent Contributions, What John Should Do, Mission Items, Stats |
| RACI integration | None | **RACIMatrix component** embedded in inspector |
| RACI Map | None | **Tab toggle** — fetches all agents' RACI data |
| Collaboration scoring | None | **Honest gap message** + link to /agent-calibration |
| View tabs | None | Missions / RACI Map toggle |

## RACI Integration Details

### RACIMatrix.tsx found and reused: YES
- Location: `apps/command-center-v2/src/components/RACIMatrix.tsx`
- Already used by: `AgentDashboard.tsx`
- Export: `export function RACIMatrix({ data, onPeerClick }: Props)`
- Props: `data` (any — expects `data.processes` and `data.peer_summary`), `onPeerClick` (function)

### RACI API exists: YES
- Endpoint: `GET /api/v2/agent-detail/raci?agent=<agent_name>`
- Returns: processes with RACI roles and co_actors, peer_summary

### RACI config: `config/agent_raci.yaml`
- 9 processes defined: daily_batch, overnight_surveillance, morning_brief, alex_daily, alex_weekly, iris_hygiene, scalp_scan, event_routing, stop_surveillance
- 9 agents mapped: maria, steph, aegis, alex, risk_agent, tax_agent, iris, social_scalp, scalp_critic

### What RACI data EXISTS
- Per-agent process ownership (R/A/C/I roles)
- Co-actors per process (agent + role pairs)
- Peer summary (dominant_relationship, process_count)
- Trigger and frequency metadata

### What RACI data is MISSING
- **Per-mission RACI** — only per-agent RACI exists. The RACI API returns an agent's role across all their processes, not role assignment for a specific mission. The inspector shows the owner's full RACI context as a proxy.
- **Historical collaboration outcomes** — no event log of which agent collaborations led to good/bad decisions
- **Mission-level role assignment** — missions have `agents[]` and `primary_owner` but no RACI role per agent per mission

## What Is Now Clickable

| Element | Action | Result |
|---------|--------|--------|
| Scorecard cards (Ready, Blocked, Waiting, Stale) | Click | Sets status filter |
| Filter chips (All through Completed) | Click | Sets status filter, clears selection |
| AgentChip in mission queue | Click | Sets agent filter (toggle) |
| AgentChip in inspector Agent Contributions | Click | Sets agent filter |
| AgentChip in inspector owner | Click | Sets agent filter |
| RACIMatrix peer buttons | Click | Sets agent filter |
| John's Next Actions items | Click | Selects that mission |
| Missions / RACI Map tabs | Click | Switches view |
| Collaboration Quality link | Click | Navigates to /agent-calibration |
| RACI Map "Agent Dashboard" link | Click | Navigates to /agent-dashboard |

## Filters Added

- **Status filter "Completed"** — shows finished missions (v1 had no completed state)
- **Agent filter** — new dimension: filter missions by any involved agent or primary owner
- **Combined filtering** — status + agent filters stack (AND logic)

## Backend Telemetry Needed for Collaboration Scoring

The "Collaboration Quality" section honestly states that scoring is not yet possible. To enable it, the backend would need:

1. **Outcome events** — log when a mission completes with outcome (success/partial/failure)
2. **Agent contribution attribution** — which agent's recommendation led to the decision
3. **Decision accuracy tracking** — for trade decisions, compare agent recommendation to actual P&L
4. **Collaboration friction metrics** — time between agent handoffs, number of re-escalations
5. **Per-mission RACI assignment** — dynamic role assignment per mission, not just static process roles

Until this telemetry exists, the page links to Agent Calibration for per-agent accuracy data.

## Safety Constraints Preserved

- No trading or approval execution logic
- No new backend endpoints required
- Same primary API: `useApi('/api/v2/agent-collaboration')`
- RACI fetch uses `useState + fetch` (not useApi) for dynamic agent parameter
- No inline secrets or credentials
- All navigation uses `window.location.href` (no router dependency added)
- Original file SHA256 recorded for traceability
