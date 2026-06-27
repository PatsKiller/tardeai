import { useApi } from '../../hooks/useApi'

const STATUS_COLOR: Record<string, string> = {
  implemented: '#22c55e',
  partial: '#f59e0b',
  degraded: '#f59e0b',
  missing: '#ef4444',
}

export default function ReportingAuditPanel({ days }: { days: number }) {
  const { data: raw, loading } = useApi<any>(`/api/v2/journal/reporting-audit?days=${days}`, 120_000)
  const d = (raw as any)?.data ?? raw

  if (loading && !d?.ok) {
    return <div style={{ fontSize: 10, color: 'var(--text3)', padding: 12 }}>Running reporting audit…</div>
  }
  if (!d?.ok) return null

  const s = d.summary || {}
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 700 }}>Reporting audit</div>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>
          {s.implemented} implemented · {s.partial_or_degraded} partial · {s.missing} missing
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 12 }}>
        {[
          { l: 'Coverage', v: `${s.coverage_pct}%`, c: '#60a5fa' },
          { l: 'Tag health', v: `${s.tagging_health_pct}%`, c: (s.tagging_health_pct ?? 0) >= 80 ? '#22c55e' : '#f59e0b' },
          { l: 'Need tags', v: s.trades_need_tagging, c: '#ef4444' },
          { l: 'In range', v: s.trades_in_range, c: 'var(--text0)' },
        ].map(k => (
          <div key={k.l} style={{ background: 'var(--bg2)', borderRadius: 6, padding: 8, textAlign: 'center' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: k.c }}>{k.v}</div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>{k.l}</div>
          </div>
        ))}
      </div>
      <div style={{ maxHeight: 220, overflow: 'auto', fontSize: 9 }}>
        {(d.reports || []).map((r: any) => (
          <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
            <span>{r.name} <span style={{ color: 'var(--text3)' }}>({r.tab})</span></span>
            <span style={{ color: STATUS_COLOR[r.status] || 'var(--text3)', fontWeight: 600, textTransform: 'uppercase', fontSize: 8 }}>{r.status}</span>
          </div>
        ))}
      </div>
      {(d.recommendations || []).length > 0 && (
        <div style={{ marginTop: 10, fontSize: 9, color: 'var(--text2)' }}>
          <div style={{ fontWeight: 700, marginBottom: 4, color: '#f59e0b' }}>Quick wins</div>
          {d.recommendations.map((r: string, i: number) => <div key={i} style={{ padding: '2px 0' }}>• {r}</div>)}
        </div>
      )}
    </div>
  )
}