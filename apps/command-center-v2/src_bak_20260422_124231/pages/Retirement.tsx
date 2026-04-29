import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'

interface RetData { as_of: string; current_age: number; key_dates: Record<string, unknown>[]; accounts: Record<string, unknown>; loan: Record<string, unknown>; mortgage: Record<string, unknown>; timeline: unknown[]; roth_ladder: Record<string, unknown> }

export default function Retirement() {
  const { data: r } = useApi<RetData>('/api/v2/retirement')
  if (!r) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const dates = Array.isArray(r.key_dates) ? r.key_dates : Object.entries(r.key_dates || {}).map(([k, v]) => ({ label: k, ...(typeof v === 'object' ? v as Record<string, unknown> : { value: v }) }))
  const loan = r.loan || {}
  const mortgage = r.mortgage || {}
  const roth = r.roth_ladder || {}

  return (
    <>
      <PageHeader title="Retirement Roadmap" subtitle={`Age ${r.current_age?.toFixed(1)} | as of ${r.as_of}`} />

      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Current Age" value={r.current_age?.toFixed(1) ?? '—'} />
        {roth && typeof roth === 'object' && (roth as Record<string, unknown>).converted_ytd != null && <MetricTile label="Roth Converted YTD" value={fmt$((roth as Record<string, number>).converted_ytd)} deltaColor="var(--green)" />}
        {loan && typeof loan === 'object' && (loan as Record<string, unknown>).balance != null && <MetricTile label="401k Loan" value={fmt$((loan as Record<string, number>).balance)} deltaColor="var(--amber)" />}
        {mortgage && typeof mortgage === 'object' && (mortgage as Record<string, unknown>).balance != null && <MetricTile label="Mortgage" value={fmt$((mortgage as Record<string, number>).balance)} />}
      </div>

      <SectionHeader title="Key Dates" count={dates.length} />
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {dates.map((d, i) => {
            const obj = d as Record<string, unknown>
            return (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}>
                <span style={{ width: 150, fontWeight: 600, color: 'var(--text1)' }}>{String(obj.label || obj.event || obj.name || `Date ${i + 1}`)}</span>
                <span style={{ color: 'var(--accent)' }}>{String(obj.date || obj.age || obj.value || '—')}</span>
                {obj.note && <span style={{ color: 'var(--text3)', fontSize: 10 }}>{String(obj.note)}</span>}
              </div>
            )
          })}
        </div>
      </Card>

      {Array.isArray(r.timeline) && r.timeline.length > 0 && (
        <>
          <SectionHeader title="Timeline" count={r.timeline.length} />
          <Card compact>
            {(r.timeline as Record<string, unknown>[]).map((t, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                <span style={{ fontWeight: 600, color: 'var(--text2)', width: 40 }}>{String((t as Record<string, unknown>).age || '')}</span>
                <span style={{ color: 'var(--text1)' }}>{String((t as Record<string, unknown>).event || (t as Record<string, unknown>).description || JSON.stringify(t))}</span>
              </div>
            ))}
          </Card>
        </>
      )}

      {roth && typeof roth === 'object' && Object.keys(roth).length > 0 && (
        <>
          <SectionHeader title="Roth Conversion Ladder" />
          <Card compact>
            <div style={{ fontSize: 10, color: 'var(--text2)', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(roth, null, 2)}
            </div>
          </Card>
        </>
      )}
    </>
  )
}
