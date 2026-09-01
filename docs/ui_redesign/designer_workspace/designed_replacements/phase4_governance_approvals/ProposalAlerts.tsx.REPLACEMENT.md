# ProposalAlerts.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/ProposalAlerts.tsx`

## Changes

- Inline summary cards replaced with `StateCard` components
- Inline status pills in table replaced with `StatusBadge`
- Added import for `StatusBadge` and `StateCard`
- Removed inline `statusColor` helper (replaced by StatusBadge status mapping)
- Title updated from "Proposal Alerts" to "Proposal Alert Board"
- Added subtitle with dynamic counts

## What did NOT change

- Same API endpoint: `/api/v2/paper-proposals` with 30000ms poll
- Same alert classification logic (ACTIONABLE_READY, BLOCKED_EXECUTION, BLOCKED_NEEDS_REBUILD, NEEDS_REVIEW)
- Same table columns and layout
- Same "View" link to `/v2/paper-proposals`
- All data transforms preserved exactly

## Full Replacement

```tsx
import React from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { StateCard } from '../components/StateCard'

const mono: React.CSSProperties = { fontFamily: 'monospace' }

const alertToStatus = (alertType: string): string => {
  if (alertType === 'ACTIONABLE_READY') return 'ready'
  if (alertType.includes('BLOCKED')) return 'blocked'
  return 'warning'
}

export default function ProposalAlerts() {
  const { data } = useApi<any>('/api/v2/paper-proposals', 30000)
  const proposals = data?.proposals ?? []
  const pending = proposals.filter((p: any) => p.status === 'PENDING')

  // Classify alerts from proposal data
  const alerts = proposals.map((p: any) => {
    const blockers = p.approval_blockers || []
    const er = p.execution_readiness || {}
    const rr = p.proposed_rr || 0
    let alertType = 'NEEDS_REVIEW'
    if (p.operator_verdict === 'READY') alertType = 'ACTIONABLE_READY'
    else if (er.readiness_state?.includes('BLOCKED')) alertType = 'BLOCKED_EXECUTION'
    else if (blockers.length > 0) alertType = 'BLOCKED_NEEDS_REBUILD'

    return {
      id: p.id, symbol: p.symbol, strategy: p.strategy_id,
      alertType, status: p.status, rr: Number(rr).toFixed(2),
      spread: er.spread_pct ? `${Number(er.spread_pct).toFixed(1)}%` : '--',
      quoteProvider: er.quote_provider || p.last_price_source || '?',
      blockerCount: blockers.length,
      topBlocker: blockers[0]?.reason || blockers[0] || 'none',
      verdict: p.operator_verdict || 'REVIEW',
      age: p.age_display || '--',
      approvalAllowed: p.approval_allowed && alertType === 'ACTIONABLE_READY',
    }
  })

  const readyCount = alerts.filter((a: any) => a.alertType === 'ACTIONABLE_READY').length
  const blockedCount = alerts.filter((a: any) => a.alertType.includes('BLOCKED')).length
  const reviewCount = alerts.filter((a: any) => a.alertType === 'NEEDS_REVIEW').length

  return (
    <div style={{ minHeight: '100vh', overflowY: 'auto', paddingBottom: 40 }}>
      <PageHeader title="Proposal Alert Board" subtitle={`${proposals.length} proposals | ${readyCount} ready | ${blockedCount} blocked | ${reviewCount} review`} />

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <StateCard title="Ready" value={readyCount} status="ready" />
        <StateCard title="Blocked" value={blockedCount} status="blocked" />
        <StateCard title="Review" value={reviewCount} status="warning" />
        <StateCard title="Pending" value={pending.length} status="running" />
      </div>

      {/* Alert table */}
      <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase' }}>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>Symbol</th>
              <th style={{ padding: '8px 6px', textAlign: 'left' }}>Strategy</th>
              <th style={{ padding: '8px 6px', textAlign: 'left' }}>Alert</th>
              <th style={{ padding: '8px 6px', textAlign: 'left' }}>Verdict</th>
              <th style={{ padding: '8px 6px', textAlign: 'right' }}>R:R</th>
              <th style={{ padding: '8px 6px', textAlign: 'right' }}>Spread</th>
              <th style={{ padding: '8px 6px', textAlign: 'left' }}>Quote</th>
              <th style={{ padding: '8px 6px', textAlign: 'left' }}>Top Blocker</th>
              <th style={{ padding: '8px 6px', textAlign: 'left' }}>Age</th>
              <th style={{ padding: '8px 6px', textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {alerts.length === 0 ? (
              <tr><td colSpan={10} style={{ padding: 24, textAlign: 'center', color: 'var(--text3)' }}>No proposal alerts</td></tr>
            ) : alerts.map((a: any) => (
              <tr key={a.id} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '6px 10px', fontWeight: 700, color: 'var(--text0)' }}>{a.symbol}</td>
                <td style={{ padding: '6px', color: 'var(--text2)' }}>{a.strategy}</td>
                <td style={{ padding: '6px' }}>
                  <StatusBadge status={alertToStatus(a.alertType)} label={a.alertType.replace(/_/g, ' ')} />
                </td>
                <td style={{ padding: '6px' }}>
                  <StatusBadge status={alertToStatus(a.verdict)} label={a.verdict} />
                </td>
                <td style={{ padding: '6px', textAlign: 'right', color: Number(a.rr) >= 2 ? 'var(--green)' : 'var(--red)' }}>{a.rr}</td>
                <td style={{ padding: '6px', textAlign: 'right', color: 'var(--text2)' }}>{a.spread}</td>
                <td style={{ padding: '6px', color: 'var(--text2)' }}>{a.quoteProvider}</td>
                <td style={{ padding: '6px', color: 'var(--amber)', fontSize: 9, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.topBlocker}</td>
                <td style={{ padding: '6px', color: 'var(--text3)' }}>{a.age}</td>
                <td style={{ padding: '6px', textAlign: 'center' }}>
                  <a href="/v2/paper-proposals" style={{ fontSize: 9, color: 'var(--accent)', textDecoration: 'none' }}>View</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```
