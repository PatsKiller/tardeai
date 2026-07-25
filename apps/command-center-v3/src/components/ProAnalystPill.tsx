import { useApi } from '../hooks/useApi'

// Advisory professional-analyst pill (Gate A). One map fetch shared across all rows on a page; looks up by
// symbol. Shows Street consensus + analyst count + upside, divergence vs internal, or a "no coverage" hint.
// Read-only — never affects READY/WAIT, quality admission, validation or scoring. Its freshness badge is
// explicitly scoped to Street consensus so it cannot be mistaken for whole-card or technical staleness.

let _mapCache: any = null
export function useProAnalystMap() {
  const { data } = useApi<any>('/api/v2/pro-analyst/pills?map=1', 600_000)
  if (data?.map) _mapCache = data.map
  return _mapCache || data?.map || {}
}

const REC_COLOR: Record<string, string> = {
  strong_buy: '#16a34a', buy: '#22c55e', hold: '#f59e0b', underperform: '#ef4444', sell: '#ef4444',
}

export default function ProAnalystPill({ symbol, map, compact, neutral }: { symbol?: string; map?: any; compact?: boolean; neutral?: boolean }) {
  if (!symbol) return null
  const p = (map || {})[symbol.toUpperCase()]
  if (!p) return null
  if (!p.has) {
    return compact ? null : <span title="no professional analyst coverage (advisory information, not a decision failure)" style={{ fontSize: 9, color: 'var(--text3)', border: '1px solid var(--border)', borderRadius: 4, padding: '0 4px' }}>no analyst cov</span>
  }
  const hasRating = p.rec && String(p.rec).toLowerCase() !== 'none'
  const rc = neutral ? 'var(--text3)' : (REC_COLOR[String(p.rec || '').toLowerCase()] || 'var(--text2)')
  const border = neutral ? '1px solid rgba(71,85,105,.45)' : `1px solid ${rc}`
  const upColor = neutral ? 'var(--text3)' : ((p.upside ?? 0) > 0 ? '#22c55e' : '#ef4444')
  const staleScope = p.stale ? ' · Street consensus data is older than 7 days; technical and decision freshness are separate' : ''
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 9 }}
      title={`Street: ${hasRating ? p.rec : 'targets only (no aggregated rating)'} · ${p.n} analysts · mean target $${p.target} · upside ${p.upside}% · internal ${p.internal || 'n/a'} · divergence ${p.divergence}${staleScope}`}>
      {hasRating
        ? <span title={`Professional analyst consensus rating (${p.src === 'hermes' ? 'Hermes web research — Yahoo has no coverage' : 'Yahoo'}): ${p.rec}${p.stale ? ' — Street consensus data is older than 7 days; this does not mean the price, technicals or strategy packet are stale' : ''}`}
            style={{ fontWeight: 700, color: rc, border, borderRadius: 4, padding: '0 4px', background: neutral ? 'rgba(30,41,59,.6)' : undefined }}>
            {String(p.rec).replace('_', ' ')}
          </span>
        : <span style={{ fontWeight: 600, color: 'var(--text3)', border: '1px solid var(--border)', borderRadius: 4, padding: '0 4px' }}>
            targets only
          </span>}
      {p.stale && (
        <span style={{ fontWeight: 700, color: '#f59e0b', fontSize: 8, letterSpacing: '.03em' }} title="Street consensus data is older than 7 days. Price, technical and strategy freshness are displayed separately.">
          STREET DATA &gt;7D ⚠
        </span>
      )}
      {p.n != null && <span title={`${p.n} professional analysts covering · mean target $${p.target}`} style={{ color: 'var(--text3)' }}>{p.n} analysts</span>}
      {p.upside != null && <span title={`Upside to mean analyst target ($${p.target} vs current)`} style={{ color: upColor }}>{p.upside > 0 ? '+' : ''}{p.upside}%</span>}
      {p.src === 'hermes' && <span title="Consensus researched by Hermes from public ratings coverage (TipRanks/MarketBeat/broker notes) — Yahoo carries no consensus for this name" style={{ color: 'var(--text3)' }}>via Hermes</span>}
      {p.divergence === 'divergent' && !neutral && (
        <span style={{ color: '#ef4444', fontWeight: 700 }} title={`Internal ${p.internal || 'n/a'} vs Street ${p.street || 'n/a'}`}>
          ≠ Street ⚠
        </span>
      )}
      {p.divergence === 'divergent' && neutral && (
        <span style={{ color: 'var(--text3)', fontWeight: 700 }}>≠ Street</span>
      )}
    </span>
  )
}
