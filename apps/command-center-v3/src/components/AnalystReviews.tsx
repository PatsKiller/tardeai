import { useApi } from '../hooks/useApi'

// Bulleted analyst breakdown for a card: rating distribution (Strong Buy / Buy / Hold / Sell) + target
// range (mean / median / high / low) as bullet points, with hover tooltips for the as-of date, source,
// and detail. Aggregated data (finnhub distribution + Yahoo targets) — no individual firm names exist
// in the feeds. One shared map fetch covers all rows on a page. Advisory/read-only.

export function useAnalystMap() {
  const { data } = useApi<any>('/api/v2/analyst-detail?map=1', 600_000)
  return (data?.map ?? {}) as Record<string, any>
}

const TIERS: [string, string, string][] = [
  ['strong_buy', 'Strong Buy', '#16a34a'], ['buy', 'Buy', '#22c55e'], ['hold', 'Hold', '#f59e0b'],
  ['sell', 'Sell', '#ef4444'], ['strong_sell', 'Strong Sell', '#b91c1c'],
]

export default function AnalystReviews({ symbol, map }: { symbol: string; map: Record<string, any> }) {
  const a = map[String(symbol).toUpperCase()]
  if (!a) return null
  const dist = a.dist || {}
  const distEntries = TIERS.filter(([k]) => dist[k] != null)
  const upColor = (a.upside ?? 0) >= 0 ? '#22c55e' : '#ef4444'
  const B = ({ children, tip, color }: any) => (
    <span title={tip} style={{ fontSize: 9.5, color: color || 'var(--text2)', cursor: 'help', whiteSpace: 'nowrap' }}>• {children}</span>
  )
  return (
    <div onClick={e => e.stopPropagation()} style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 4, padding: '5px 7px', borderRadius: 6, background: 'rgba(96,165,250,.06)', border: '1px solid var(--border)' }}>
      <div style={{ fontSize: 8.5, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .3 }}>
        Analyst reviews · {a.rec ? String(a.rec).replace(/_/g, ' ') : '—'} · {a.n ?? '?'} analysts
      </div>
      {/* rating distribution bullets */}
      {distEntries.length > 0 && (
        <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap' }}>
          {distEntries.map(([k, label, c]) => (
            <B key={k} color={c} tip={`${label}: ${dist[k]} analyst${dist[k] === 1 ? '' : 's'} · distribution as of ${a.dist_period || '—'} · source ${a.dist_source || 'finnhub'} (aggregated — no individual firm names in the feed)`}>{label} {dist[k]}</B>
          ))}
        </div>
      )}
      {/* target bullets */}
      <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap' }}>
        {a.target_mean != null && <B color={upColor} tip={`Mean price target across ${a.n ?? '?'} analysts · upside ${a.upside}% vs current $${a.current} · as of ${a.as_of || '—'} · source Yahoo`}>Mean ${a.target_mean} ({a.upside >= 0 ? '+' : ''}{a.upside}%)</B>}
        {a.target_median != null && <B tip={`Median price target · as of ${a.as_of || '—'} · source Yahoo`}>Median ${a.target_median}</B>}
        {a.target_high != null && <B color="#22c55e" tip={`Highest analyst target · as of ${a.as_of || '—'} · source Yahoo`}>High ${a.target_high}</B>}
        {a.target_low != null && <B color="#ef4444" tip={`Lowest analyst target · as of ${a.as_of || '—'} · source Yahoo`}>Low ${a.target_low}</B>}
      </div>
    </div>
  )
}
