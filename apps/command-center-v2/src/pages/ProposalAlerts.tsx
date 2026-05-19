import React from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }

const statusColor = (s: string) => {
  if (s?.includes('READY')) return '#22C55E'
  if (s?.includes('BLOCKED') || s?.includes('MISSED')) return '#EF4444'
  if (s?.includes('REBUILD') || s?.includes('NEEDS')) return '#F59E0B'
  return '#94A3B8'
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
      <PageHeader title="Proposal Alerts" subtitle={`${proposals.length} proposals | ${readyCount} ready | ${blockedCount} blocked | ${reviewCount} review`} />

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        {[
          { label: 'Ready', value: readyCount, color: '#22C55E' },
          { label: 'Blocked', value: blockedCount, color: '#EF4444' },
          { label: 'Review', value: reviewCount, color: '#F59E0B' },
          { label: 'Pending', value: pending.length, color: '#60A5FA' },
        ].map(c => (
          <div key={c.label} style={{ padding: '8px 16px', borderRadius: 6, background: 'var(--bg1)', border: '1px solid var(--border)', textAlign: 'center', minWidth: 80 }}>
            <div style={lbl}>{c.label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: c.color, ...mono }}>{c.value}</div>
          </div>
        ))}
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
                <td style={{ padding: '6px' }}><span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3, background: `${statusColor(a.alertType)}20`, color: statusColor(a.alertType), fontWeight: 600 }}>{a.alertType.replace(/_/g, ' ')}</span></td>
                <td style={{ padding: '6px', color: statusColor(a.verdict) }}>{a.verdict}</td>
                <td style={{ padding: '6px', textAlign: 'right', color: Number(a.rr) >= 2 ? '#22C55E' : '#EF4444' }}>{a.rr}</td>
                <td style={{ padding: '6px', textAlign: 'right', color: 'var(--text2)' }}>{a.spread}</td>
                <td style={{ padding: '6px', color: 'var(--text2)' }}>{a.quoteProvider}</td>
                <td style={{ padding: '6px', color: '#F59E0B', fontSize: 9, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.topBlocker}</td>
                <td style={{ padding: '6px', color: 'var(--text3)' }}>{a.age}</td>
                <td style={{ padding: '6px', textAlign: 'center' }}>
                  <a href="/v2/paper-proposals" style={{ fontSize: 9, color: '#60A5FA', textDecoration: 'none' }}>View</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
