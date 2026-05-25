# Source Export: types.ts

- **Original path:** apps/command-center-v2/src/components/morning-brief/types.ts
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** 57daabffcadae15b637b59882a820c13a7d395b2b8281d82592f5750d18de91e
- **File size:** 3285 bytes
- **Exists:** YES

```typescript
/* Shared types for Morning Brief subcomponents */

export interface BriefSection { priority: number; title: string; items: string[] }
export interface BriefData { sections: BriefSection[]; next_actions: string[]; portfolio_summary: string; has_findings: boolean }
export interface StephItem { symbol: string; category: string; reason: string; review_status: string; steph_verdict: string | null; send_to_john: boolean; john_question: string | null }
export interface CoveredCall { symbol: string; verdict: string; reasoning: string }
export interface Rotation { from_symbol: string; to_symbol: string; switch_verdict: string; evidence: string }
export interface RecoveryItem { symbol: string; analyst_verdict: string; analyst_confidence?: number; temp_allocation_verdict: string }

export interface ChatCtx {
  morning_brief: BriefData
  steph_escalations: StephItem[]
  covered_calls: CoveredCall[]
  rotations: Rotation[]
  recovery: RecoveryItem[]
  evidence_summary: { available?: boolean; symbols_checked: number; sufficiency: Record<string, number>; bias_flagged: number; conflicts: number }
  john_decisions: { pending_count: number; overdue_count: number; due_this_week: number; pending_items: { id: number; symbol: string; title: string; action: string }[]; deferred_items: { id: number; symbol: string; title: string; revisit_on: string }[] }
  outcome_tracking: { total: number; evaluated: number; pending: number; avg_score: number | null }
}

export interface OvData {
  portfolio_value: number; today_change: number; today_pct: number
  as_of: string; last_repriced: string; pipeline_status: string; pipeline_completed: string
  trade_ai: { vix: number | null; breadth: string | null }
  pending_approvals: number
}

export interface RiskPos { symbol: string; current_price: number; stop_price: number | null; distance_pct: number | null; max_loss: number; market_value: number; triggered: boolean }
export interface EscItem { symbol: string; max_loss?: number; distance_pct?: number; market_value?: number }
export interface RiskData {
  portfolio_heat_pct: number; total_risk_dollars: number; pct_protected: number
  total_unprotected_mv: number; position_count: number
  positions: RiskPos[]
  escalation?: { danger: EscItem[]; warning: EscItem[]; unprotected: EscItem[] }
}

export interface LadderRow {
  pri: number; type: string; typeColor: string; symbol: string; issue: string
  exposure: number; exposureFmt: string; owner: string; next: string; due: string
  conf: number; route: string; routeLabel: string
}

/* ── Label maps ── */
const VL: Record<string, string> = { wait_monitor: 'Monitor for Re-entry', reentry_candidate: 'Re-entry Candidate', do_not_reenter: 'Do Not Re-enter', stay_cash: 'Stay in Cash', hold_for_reentry: 'Hold for Re-entry', rotate_existing_conviction: 'Rotate to Conviction', review_needed: 'Review Needed', avoid: 'Avoid', pending_review: 'Pending Review', resolved: 'Resolved', needs_john: 'Needs Your Decision' }
const CL: Record<string, string> = { rotation_review: 'Rotation', thesis_review: 'Thesis', stop_review: 'Stop Review', allocation_review: 'Allocation', covered_call: 'Covered Call' }
export const vl = (v: string) => VL[v] || v.replace(/_/g, ' ')
export const cl = (c: string) => CL[c] || c.replace(/_/g, ' ')
```
