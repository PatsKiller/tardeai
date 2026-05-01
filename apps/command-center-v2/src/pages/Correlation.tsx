import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface CorrelationData {
  has_data: boolean
  correlation_matrix: Record<string, Record<string, number>>
  symbols: string[]
  high_correlations: { s1: string; s2: string; corr: number; type: string }[]
  symbols_analyzed: number
  total_value: number
  last_updated: string
}

export default function Correlation() {
  const { data } = useApi<CorrelationData>('/api/v2/correlation')
  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading correlation…</div>
  if (!data.has_data) return <><PageHeader title="Correlation" subtitle="Position correlation analysis" /><Card><div style={{ color: 'var(--text3)', padding: 20 }}>No correlation data yet. Run the daily pipeline to generate cross-position correlation analysis.</div></Card></>

  const symbols = data.symbols.slice(0, 12)
  return (
    <>
      <PageHeader title="Correlation" subtitle={`Top ${data.symbols_analyzed} positions by weight · updated ${data.last_updated || '—'}`} />
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10, padding: '6px 10px', background: 'var(--bg3)', borderRadius: 6 }}>
        Legend: ≥0.85 Very High (red) · 0.70–0.85 High (amber) · 0.40–0.70 Moderate (acceptable) · &lt;0.40 Low (green, good diversifier). Action: Trim one of any very-high pair — holding both adds little diversification.
      </div>
      <Card title="High-Correlation Warnings">
        {data.high_correlations.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No high-correlation pairs found — portfolio is well-diversified.</div>}
        {data.high_correlations.slice(0, 6).map((pair, idx) => (
          <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
            <span style={{ color: 'var(--text1)' }}>{pair.s1} + {pair.s2}</span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ color: pair.corr >= 0.85 ? 'var(--red)' : 'var(--amber)' }}>{pair.corr.toFixed(2)} — {pair.type}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{pair.corr >= 0.85 ? 'Consider trimming one' : 'Monitor'}</span>
            </div>
          </div>
        ))}
      </Card>
      <div style={{ marginTop: 12, overflow: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 4, width: '100%' }}>
          <thead>
            <tr>
              <th></th>
              {symbols.map(sym => <th key={sym} style={{ color: 'var(--text3)', fontSize: 10, padding: '0 6px' }}>{sym}</th>)}
            </tr>
          </thead>
          <tbody>
            {symbols.map(row => (
              <tr key={row}>
                <th style={{ color: 'var(--text3)', fontSize: 10, paddingRight: 6, textAlign: 'left' }}>{row}</th>
                {symbols.map(col => {
                  const v = data.correlation_matrix?.[row]?.[col] ?? 0
                  const bg = v >= 0.85 ? 'rgba(246,70,93,.28)' : v >= 0.7 ? 'rgba(240,185,11,.22)' : v <= 0.4 ? 'rgba(14,203,129,.18)' : 'var(--bg3)'
                  const color = v >= 0.85 ? 'var(--red)' : v >= 0.7 ? 'var(--amber)' : 'var(--accent-bright)'
                  return <td key={`${row}-${col}`} style={{ background: bg, border: '1px solid var(--border-subtle)', borderRadius: 6, color, fontSize: 11, textAlign: 'center', padding: '8px 4px' }}>{v.toFixed(2)}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10, marginTop: 12 }}>
        <Legend color="rgba(246,70,93,.28)" label="≥ 0.85" sub="Very High — trim one" />
        <Legend color="rgba(240,185,11,.22)" label="0.70–0.85" sub="High — monitor" />
        <Legend color="var(--bg3)" label="0.40–0.70" sub="Moderate — acceptable" />
        <Legend color="rgba(14,203,129,.18)" label="< 0.40" sub="Low — good diversifier" />
      </div>

      {/* Diversification insights */}
      {(() => {
        const allPairs = data.high_correlations || []
        const veryHigh = allPairs.filter(p => p.corr >= 0.85).length
        const high = allPairs.filter(p => p.corr >= 0.70 && p.corr < 0.85).length
        const hasBond = data.symbols.some(s => ['BND', 'AGG', 'SCHZ', 'TLT', 'VCIT'].includes(s))
        return (
          <div style={{ marginTop: 12, padding: '10px 14px', background: 'var(--bg3)', borderRadius: 8, fontSize: 11, color: 'var(--text2)', lineHeight: 1.6 }}>
            <strong style={{ color: 'var(--text0)' }}>Diversification Score: </strong>
            <span style={{ color: veryHigh === 0 && high <= 2 ? 'var(--green)' : veryHigh <= 1 ? 'var(--amber)' : 'var(--red)', fontWeight: 700 }}>
              {veryHigh === 0 && high <= 2 ? 'Good' : veryHigh <= 1 ? 'Moderate' : 'Needs Work'}
            </span>
            <span style={{ color: 'var(--text3)', marginLeft: 8 }}>({veryHigh} very high, {high} high correlation pairs)</span>
            {!hasBond && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4 }}>Consider adding a bond ETF (BND, AGG, or SCHZ) — bonds typically have negative or low correlation with equities, improving portfolio resilience.</div>}
          </div>
        )
      })()}
    </>
  )
}
function Legend({ color, label, sub }: { color: string; label: string; sub: string }) {
  return <div style={{ background: color, borderRadius: 8, padding: 10, textAlign: 'center' }}><div style={{ fontWeight: 700 }}>{label}</div><div style={{ fontSize: 10, color: 'var(--text2)' }}>{sub}</div></div>
}
