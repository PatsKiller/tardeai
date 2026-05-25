# Agent Collaboration, RACI & Outcomes -- Design Notes (v3.0)

**Date:** 2026-05-24
**Target:** `apps/command-center-v2/src/pages/AgentCollaboration.tsx`

## What Changed (v2 to v3)

| Area | v2 (Collaboration & Outcomes + RACI) | v3 (Collaboration, RACI & Outcomes) |
|------|---------------------------------------|--------------------------------------|
| Title | "Agent Collaboration & Outcomes" | "Agent Collaboration, RACI & Outcomes" |
| Subtitle | "How agents coordinate..." | "Mission ownership, handoffs, blockers, stale work, and collaboration quality" |
| Scorecard | Ready for John, Blocked, Waiting, Stale, Trust | **Needs John**, Blocked, Waiting on Agent, Stale, System Trust (same data, renamed) |
| Tabs | 2 (Missions, RACI Map) | **4** (Missions, Collaboration Flow, RACI Map, Outcome Quality) |
| Inspector sections | A-H (Summary, RACI, Why This Matters, Blockers, Contributions, Action, Items, Stats) | A-H restructured: Summary, **Collaboration Timeline**, RACI, Contributions, **Blockers/Staleness**, Action, Items, Stats |
| Timeline | None | **Inferred from mission state** (labeled as inferred) |
| RACI label | Unlabeled | **"Owner-level RACI fallback"** label shown |
| Collaboration Flow | None | **New tab** -- grouped handoff history from agent_network |
| Outcome Quality | Single "Collaboration Quality" box | **Full tab** with observable good/bad signals + missing fields list |
| RACI Map | Flat list | **Collapsible sections** per agent |
| Blocker cards | Red blocker only | Red blocker + **orange stale card** with owner and action |
| StatusBadge | Display only | **Clickable** on mission cards (filters by status) |
| Filter indicators | Agent filter only | **All active filters** shown with individual clear buttons |
| John's Next Actions | Separate section | Removed (redundant with Needs John scorecard + mission inspector) |

## 4 Tabs Added

1. **Missions** (default) -- Status/type/time filter rows, two-pane mission queue + inspector
2. **Collaboration Flow** -- Handoff history from agent_network, grouped into Agent-to-Agent, System-to-Agent, Agent-to-Operator
3. **RACI Map** -- Collapsible per-agent RACI from config/agent_raci.yaml via RACIMatrix component
4. **Outcome Quality** -- Observable good/bad signals as StateCards + missing API fields list

## RACIMatrix.tsx Reused: YES

- Location: `apps/command-center-v2/src/components/RACIMatrix.tsx`
- Used in: Mission inspector (Section C) and RACI Map tab
- Export: `export function RACIMatrix({ data, onPeerClick }: Props)`
- No modifications to the component

## Mission-Level RACI: NO

Per-mission RACI assignment does not exist in the API. The inspector shows the primary owner's full RACI context as a fallback. This is explicitly labeled as "owner-level RACI fallback" in the UI so the operator knows the limitation.

## Collaboration Timeline: INFERRED

The timeline in Section B is reconstructed from mission state fields (primary_owner, agents, primary_blocker, status). It is explicitly labeled as "inferred from mission state" in the UI. Steps shown:
- Detected / assigned to owner
- Collaboration with other agents (if agents.length > 1)
- Blocked (if primary_blocker exists)
- Current state (ready/completed/stale/in progress)

No `collaboration_event_timeline` field exists in the API.

## What Is Clickable

| Element | Action | Result |
|---------|--------|--------|
| StateCard (Needs John) | Click | Filters missions to status=ready, switches to Missions tab |
| StateCard (Blocked) | Click | Filters missions to status=blocked |
| StateCard (Waiting on Agent) | Click | Filters missions to status=waiting |
| StateCard (Stale) | Click | Filters missions to status=stale |
| Status filter chips (All-Completed) | Click | Sets status filter, clears selection |
| Type filter chips (All Types-Ticker) | Click | Sets task type filter |
| Time filter chips (All Time-30d) | Click | Sets time filter |
| Active filter clear buttons (x) | Click | Clears individual filter |
| "Clear all" button | Click | Resets all filters |
| AgentChip in mission queue | Click | Toggles agent filter |
| AgentChip in inspector owner | Click | Sets agent filter |
| AgentChip in inspector contributions | Click | Sets agent filter |
| AgentChip in collaboration flow | Click | Sets agent filter, switches to Missions tab |
| AgentChip in blocker/stale cards | Click | Sets agent filter |
| StatusBadge on mission cards | Click | Filters by that status |
| StatusBadge in inspector header | Click | Filters by that status |
| RACIMatrix peer buttons | Click | Sets agent filter |
| RACI Map collapsible headers | Click | Toggles section expand/collapse |
| Mission cards in queue | Click | Selects mission in inspector |
| Tab buttons | Click | Switches tab |
| "Open Page" ActionButton | Click | Navigates to action URL |
| "View Agent Calibration" | Click | Navigates to /agent-calibration |

## Filters

- **Status**: All, Ready, Blocked, Waiting, Stale, Running, Completed
- **Task type**: All Types, Risk, Proposals, Research, System, Alerts, Ticker
- **Time**: All Time, 24h, 7 Days, 30 Days
- **Agent**: Any agent (set via AgentChip click, cleared via x button)
- All filters stack with AND logic
- Active filters shown as clearable chips above the mission queue

## Missing API Fields for True Scoring (7 fields)

1. `collaboration_outcome` -- Success/partial/failure per mission
2. `handoff_resolution_time` -- Time between agent handoffs
3. `agent_agreement_score` -- How often agents agree on recommendations
4. `evidence_completeness` -- Whether evidence was gathered before decision
5. `per_mission_raci` -- Dynamic RACI role assignment per mission
6. `collaboration_event_timeline` -- Full event log of collaboration steps
7. `decision_accuracy_tracking` -- Agent recommendation vs actual outcome

These are listed in the Outcome Quality tab with descriptions. The UI does not fabricate scores.

## Safety

- No trading execution
- No approval bypass
- No backend changes or new endpoints
- Same primary API: `useApi('/api/v2/agent-collaboration')`
- RACI fetch uses `useState + fetch` for dynamic agent parameter
- All navigation uses `window.location.href`
- Original file SHA256 recorded for traceability
- Correct prop signatures: `name` (not agent), `children` (not label), `title` (not label)
