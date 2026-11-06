/**
 * Communications → Analytics (Reports redesign v001, operator-approved 2026-11-06, mapping rows 4 + 13).
 * The alert & message analytics band and the Severity / Categories bars moved here from Reports → Archive.
 * Nothing removed: the same endpoints (/api/v2/reports/analytics, /api/v2/reports/portal-summary) feed it;
 * a type drill now filters Communications → Events instead of the old archive list.
 */
import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import AlertAnalyticsBand from './AlertAnalyticsBand'
import './reportsRedesign.css'

function Bars({ title, rows, tone }: { title: string; rows: { label: string; value: number; sev?: string }[]; tone?: string }) {
  const max = Math.max(1, ...rows.map(r => r.value))
  return (
    <div className="rp-card">
      <div className="rp-eyebrow">{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
        {rows.map(r => (
          <div key={r.label} style={{ display: 'grid', gridTemplateColumns: 'minmax(90px, 40%) 1fr auto', gap: 8, alignItems: 'center', fontSize: 12 }}>
            <span style={{ color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
            <span style={{ height: 8, background: 'var(--bg-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
              <span style={{
                display: 'block', height: '100%', width: `${(r.value / max) * 100}%`, borderRadius: 'var(--radius-pill)',
                background: r.sev === 'critical' || r.sev === 'urgent' ? 'var(--danger-color)' : r.sev === 'warning' ? 'var(--warning-color)' : (tone || 'var(--info-color)'),
              }} />
            </span>
            <span style={{ color: 'var(--text-1)', fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>{r.value}</span>
          </div>
        ))}
        {!rows.length && <div className="rp-empty">No data in this window.</div>}
      </div>
    </div>
  )
}

export default function CommsAnalyticsTab({ onDrillType }: { onDrillType: (q: string) => void }) {
  const [days, setDays] = useState(7)
  const { data: summary } = useApi<any>(`/api/v2/reports/portal-summary?days=${days}`, 300_000)
  const k = summary?.kpis || {}
  const sevRows = Object.entries(k.by_severity || {}).map(([label, value]: any) => ({ label, value: Number(value) || 0, sev: label }))
    .sort((a, b) => b.value - a.value)
  const catRows = (k.by_category || []).slice(0, 8).map((c: any) => ({ label: c.label, value: Number(c.count) || 0 }))
  return (
    <div className="rp" data-testid="comms-analytics" style={{ maxWidth: 'none' }}>
      <AlertAnalyticsBand onDrillType={onDrillType} />
      <div className="rp-filterchips" role="group" aria-label="Severity and categories window">
        <span>Portal sample window</span>
        {[1, 7, 30].map(d => (
          <button key={d} type="button" className={`rp-chip${days === d ? ' on' : ''}`} onClick={() => setDays(d)}>{d === 1 ? 'Today' : `${d}d`}</button>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 12 }}>
        <Bars title={`Severity · portal sample · ${days}d · all categories`} rows={sevRows} />
        <Bars title={`Categories · portal sample · ${days}d`} rows={catRows} />
      </div>
      <div className="rp-meta">Moved from Reports → Archive (Reports redesign v001). Tapping a type above filters Live / Events.</div>
    </div>
  )
}
