import { useEffect, useState } from 'react'
import { BB, T } from '../../lib/watchTokens'

// v1.2 P12 — TradeInView COSTS tab. Three cost classes, NEVER silently merged:
// actual cash charges (broker-posted) · embedded fund-cost ESTIMATE (paid
// through NAV — explanatory, never re-subtracted) · execution friction ESTIMATE.

const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }
const CLASS_LABEL: Record<string, string> = {
  ACTUAL_CASH: 'Actual cash charges',
  EMBEDDED_FUND_COST_ESTIMATE: 'Embedded fund cost (estimate)',
  EXECUTION_FRICTION_ESTIMATE: 'Execution friction (estimate)',
}
const fmt$ = (v: any) => (v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`)

export default function CostsPanel() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<any>(null)
  const [series, setSeries] = useState<any>(null)
  const [bySec, setBySec] = useState<any>(null)
  const [unmatched, setUnmatched] = useState<any>(null)
  const [recon, setRecon] = useState<any>(null)
  const [grain, setGrain] = useState('month')

  useEffect(() => {
    setLoading(true)
    fetch('/api/v2/journal/costs/summary').then(r => r.json())
      .then(r => { setSummary(r?.data); setError(null) })
      .catch(e => setError(String(e))).finally(() => setLoading(false))
    fetch('/api/v2/journal/costs/by-security').then(r => r.json()).then(r => setBySec(r?.data)).catch(() => null)
    fetch('/api/v2/journal/costs/unmatched').then(r => r.json()).then(r => setUnmatched(r?.data)).catch(() => null)
    fetch('/api/v2/journal/costs/reconciliation').then(r => r.json()).then(r => setRecon(r?.data)).catch(() => null)
  }, [])
  useEffect(() => {
    fetch(`/api/v2/journal/costs/timeseries?grain=${grain}`).then(r => r.json()).then(r => setSeries(r?.data)).catch(() => null)
  }, [grain])

  const classes = summary?.by_class || {}
  const badge = (kind: string) => (
    <span style={{ fontSize: 10, fontWeight: 800, padding: '1px 5px', borderRadius: 4, marginLeft: 6,
                   background: kind === 'actual' ? 'rgba(34,197,94,0.15)' : 'rgba(245,158,11,0.15)',
                   color: kind === 'actual' ? BB.green : BB.amber, textTransform: 'uppercase' }}>{kind}</span>
  )
  if (loading) return <div style={{ fontSize: 12, color: 'var(--text3)', padding: 20 }}>loading cost ledger…</div>
  if (error) return <div style={{ fontSize: 12, color: BB.red, padding: 20 }}>cost ledger unavailable: {error}</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 10, color: 'var(--text3)' }}>
        data freshness: {summary?.freshness?.latest_event_at || 'no events'} · {summary?.freshness?.total_events ?? 0} events
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {Object.keys(CLASS_LABEL).map(k => (
          <div key={k} style={{ ...panel, minWidth: 220 }}>
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>{CLASS_LABEL[k]}{badge(k === 'ACTUAL_CASH' ? 'actual' : 'estimated')}</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text0)' }}>{fmt$(classes[k]?.total ?? 0)}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>{classes[k]?.events ?? 0} events</div>
          </div>
        ))}
        {recon && (
          <div style={{ ...panel, minWidth: 200, borderColor: recon.all_ok ? 'var(--border)' : BB.red }}>
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>Independent reconciliation</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: recon.all_ok ? BB.green : BB.red }}>
              {recon.all_ok ? 'ALL CHECKS PASS' : 'DRIFT'}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>{(recon.checks || []).length} checks vs raw ledger/outcomes</div>
          </div>
        )}
      </div>

      <div style={panel}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 8 }}>
          <b style={{ fontSize: 13, color: 'var(--text0)' }}>Costs over time</b>
          {['week', 'month', 'quarter', 'year'].map(g => (
            <button key={g} onClick={() => setGrain(g)}
              style={{ fontSize: 10, padding: '2px 8px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${grain === g ? T.link : 'var(--border)'}`, background: 'transparent', color: 'var(--text1)' }}>{g}</button>
          ))}
        </div>
        {(series?.series || []).length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>no cost events in range</div>}
        {(series?.series || []).map((s: any, i: number) => (
          <div key={i} style={{ display: 'flex', gap: 10, fontSize: 11, color: 'var(--text2)', borderBottom: '1px solid var(--border)', padding: '2px 0' }}>
            <span style={{ minWidth: 90 }}>{s.period}</span>
            <span style={{ minWidth: 240, color: 'var(--text3)' }}>{CLASS_LABEL[s.class] || s.class}</span>
            <b style={{ marginLeft: 'auto', color: 'var(--text0)' }}>{fmt$(s.total)}</b>
          </div>
        ))}
      </div>

      <div style={panel}>
        <b style={{ fontSize: 13, color: 'var(--text0)' }}>By security</b>
        {(bySec?.rows || []).map((r: any, i: number) => (
          <div key={i} style={{ display: 'flex', gap: 10, fontSize: 11, color: 'var(--text2)', borderBottom: '1px solid var(--border)', padding: '2px 0' }}>
            <b style={{ minWidth: 60, color: 'var(--text0)' }}>{r.symbol}</b>
            <span style={{ minWidth: 240, color: 'var(--text3)' }}>{CLASS_LABEL[r.class] || r.class}</span>
            <span>{r.events} events</span>
            <b style={{ marginLeft: 'auto' }}>{fmt$(r.total)}</b>
          </div>
        ))}
        {!(bySec?.rows || []).length && <div style={{ fontSize: 11, color: 'var(--text3)' }}>no security-linked costs yet</div>}
      </div>

      <div style={panel}>
        <b style={{ fontSize: 13, color: 'var(--text0)' }}>Unmatched & unresolved</b>
        {(unmatched?.unmatched_charges || []).map((u: any) => (
          <div key={u.id} style={{ fontSize: 11, color: 'var(--text2)' }}>
            {u.date} · {u.category} · {fmt$(u.amount)} — {u.notes}
          </div>
        ))}
        {(unmatched?.missing_expense_ratios || []).length > 0 && (
          <div style={{ fontSize: 11, color: BB.amber, marginTop: 4 }}>
            Missing expense ratios (no accrual recorded — visible gap): {unmatched.missing_expense_ratios.join(', ')}
          </div>
        )}
        {!(unmatched?.unmatched_charges || []).length && !(unmatched?.missing_expense_ratios || []).length && (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>nothing unmatched</div>
        )}
      </div>

      <div style={{ fontSize: 10, color: 'var(--text3)' }}>
        fund NAV performance is already net of operating expenses — the embedded estimate explains cost, it is never
        subtracted from NAV-based P&L a second time · actual broker charges supersede estimates
      </div>
    </div>
  )
}
