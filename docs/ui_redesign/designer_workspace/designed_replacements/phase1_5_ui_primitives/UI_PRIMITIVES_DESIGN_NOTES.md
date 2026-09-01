# Phase 1.5 UI Primitives — Design Notes

Status:      HISTORICAL
as_of:       2026-05-25T13:05:19-04:00
Measured at: efcc51365 / not measured

## Why These Components Are Needed

The DESIGNER_MISSING_FILES_REPORT identified the #1 design system gap: **the app has no shared component library for badges, chips, status indicators, or action buttons.** Every page defines its own inline styles, leading to:

- Inconsistent colors for the same status across pages
- Duplicated rgba() helper functions in 6+ page files
- Agent chip implementations repeated in AgentCollaboration, AgentPipeline, AgentCalibration
- Status pill implementations repeated in every dashboard page
- No shared semantic meaning for "blocked" vs "stale" vs "warning"
- Button styling varies per page with no disabled/loading pattern

## Components Created

| Component | Purpose | Replaces |
|-----------|---------|----------|
| StatusBadge | System states (fresh/stale/blocked/ready/etc) | Inline `<span>` pills in 10+ pages |
| SeverityBadge | Alert/priority levels (info/low/medium/high/critical) | Inline severity spans in Alerts, Risk, Collaboration |
| AgentChip | Agent identity with color + role tooltip | Inline agent chips in Collaboration, Pipeline, Calibration |
| ActionButton | Primary/secondary/danger/ghost buttons | Inline `<button style>` in every page |
| StateCard | Dashboard summary tile with status stripe | Inline metric divs in Collaboration, Self-Improvement, SystemHealth |

## Pages That Will Use These Later

| Component | Target Pages |
|-----------|-------------|
| StatusBadge | AgentCollaboration, SystemHealth, PipelineHub, AgentPipeline, SelfImprovement, OpsHub |
| SeverityBadge | AgentCollaboration, AlertsDashboard, Risk, PaperProposals |
| AgentChip | AgentCollaboration, AgentCalibration, AgentPipeline, CIODashboard |
| ActionButton | PaperProposals, AgentCollaboration, GovernanceHub, Approvals, TradeAI |
| StateCard | AgentCollaboration, SelfImprovement, SystemHealth, OpsHub, Overview |

## What Inline Styling They Replace

### StatusBadge replaces patterns like:
```tsx
// Currently in AgentCollaboration.tsx:
<span style={{padding:'1px 6px',borderRadius:10,fontSize:8,fontWeight:800,
  background:rgba(c,.12),color:c,textTransform:'uppercase'}}>{status}</span>

// Currently in SystemHealth.tsx:
<span style={{color: s === 'healthy' ? '#0ecb81' : s === 'warning' ? '#f0b90b' : '#f6465d'}}>
```

### AgentChip replaces patterns like:
```tsx
// Currently duplicated in AgentCollaboration, AgentCalibration, AgentPipeline:
const AGENT_CLR = { Maria: '#fb7185', Steph: '#2dd4bf', ... }
<span style={{display:'inline-flex',gap:3,padding:'1px 6px',borderRadius:3,
  fontSize:9,fontWeight:700,background:rgba(c,.15),color:c}}>
```

## Production Files NOT Changed

No production source files were modified. These components exist only in:
`docs/ui_redesign/designer_workspace/designed_replacements/phase1_5_ui_primitives/`

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Breaking existing pages | None | Components not yet installed |
| API changes needed | None | Pure UI components, no API calls |
| Theme.css changes | Minimal | Uses existing variables; no changes needed |
| Bundle size | Negligible | 5 small components, ~3KB total |
| CSS specificity conflicts | Low | Inline styles only, no class conflicts |

## Recommended CSS Token Additions (for future theme.css update)

These tokens don't exist yet but would improve consistency:
```css
--orange: #f97316;
--orange-dim: rgba(249,115,22,.10);
--teal: #2dd4bf;
--teal-dim: rgba(45,212,191,.10);
--rose: #fb7185;
--rose-dim: rgba(251,113,133,.10);
--gold: #eab308;
--gold-dim: rgba(234,179,8,.10);
--cyan: #00d2d3;
--cyan-dim: rgba(0,210,211,.10);
```

Do NOT apply these yet. Document for Phase 3 design system work.

## Next Implementation Steps

1. **Phase 1.5 Apply:** Copy the 5 component files into `apps/command-center-v2/src/components/`
2. **Phase 2:** Refactor AgentCollaboration.tsx to import and use these primitives
3. **Phase 2:** Refactor SystemHealth, OpsHub, TradeAI to use these primitives
4. **Phase 3:** Refactor remaining pages systematically
5. **Phase 3:** Add the recommended CSS tokens to theme.css
