/**
 * Prospectus › My history (intel/v001): the real positions I hold now, grouped by where the idea came from
 * (auto-detected discovery origin). Source: /api/v2/rec-intel/open-positions (broker holdings, not paper).
 * Read-only. A row opens that symbol's prospectus.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { realTrades } from '../../lib/intelConsolidation'

type OpenPosition = {
  symbol?: string
  account?: string
  origin?: string | null
  shares?: number | null
  avg_cost?: number | null
  current_price?: number | null
  unrealized_pnl?: number | null
  unrealized_pnl_pct?: number | null
  held_since?: string | null
}

const usd = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? '—' : `${n < 0 ? '−' : ''}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`)
const pct = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? '—' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(1)}%`)
const tone = (n: number | null | undefined) => (n == null ? 'var(--text2)' : n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--text2)')
const SYMBOL_RE = /^[A-Z0-9.\-]{1,12}$/

export default function OpenPositionsByOrigin({ linkSearch = '' }: { linkSearch?: string } = {}) {
  const { data, loading, error } = useApi<any>('/api/v2/rec-intel/open-positions', 300_000)
  const positions: OpenPosition[] = useMemo(() => realTrades((data?.positions ?? []) as OpenPosition[]), [data?.positions])
  const groups = useMemo(() => {
    const m = new Map<string, OpenPosition[]>()
    for (const p of positions) {
      const k = String(p.origin || '').trim() || 'origin not detected'
      m.set(k, [...(m.get(k) || []), p])
    }
    return [...m.entries()]
      .map(([origin, rows]) => ({
        origin,
        rows: [...rows].sort((a, b) => Math.abs(b.unrealized_pnl ?? 0) - Math.abs(a.unrealized_pnl ?? 0)),
        total: rows.reduce((s, r) => s + (r.unrealized_pnl ?? 0), 0),
      }))
      .sort((a, b) => b.rows.length - a.rows.length || a.origin.localeCompare(b.origin))
  }, [positions])

  if (loading && !data) return <div style={{ padding: 12, color: 'var(--text2)', fontSize: 13 }}>Loading my history…</div>
  if (error || data?.ok === false) return <div style={{ padding: 12, color: 'var(--amber)', fontSize: 13 }}>My history unavailable: {String(error || data?.error || 'error')}</div>

  return (
    <div data-testid="prospectus-my-history" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
      <div style={{ fontSize: 12, color: 'var(--text2)' }}>
        {positions.length} open position{positions.length === 1 ? '' : 's'} by discovery origin · real accounts only · unrealized P&amp;L from the broker sync
      </div>
      {groups.map(g => (
        <section key={g.origin} style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg2)', padding: 10, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <b style={{ textTransform: 'capitalize' }}>{g.origin.replace(/_/g, ' ')}</b>
            <span style={{ fontSize: 12, color: 'var(--text2)' }}>{g.rows.length} · <span style={{ color: tone(g.total) }}>{usd(g.total)}</span></span>
          </div>
          <div style={{ display: 'grid', gap: 4 }}>
            {g.rows.map((p, i) => {
              const sym = String(p.symbol || '').toUpperCase()
              const body = (
                <>
                  <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}><b>{sym || '—'}</b>{' '}
                    <span style={{ fontSize: 11, color: 'var(--text3)' }}>{p.account || ''}{p.held_since ? ` · since ${String(p.held_since).slice(0, 10)}` : ''}</span>
                  </span>
                  <span style={{ whiteSpace: 'nowrap', color: tone(p.unrealized_pnl), fontSize: 12 }}>{usd(p.unrealized_pnl)} · {pct(p.unrealized_pnl_pct)}</span>
                </>
              )
              const style = { display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', minHeight: 44, padding: '4px 6px', borderRadius: 6, color: 'var(--text)', textDecoration: 'none', minWidth: 0 } as const
              return SYMBOL_RE.test(sym)
                ? <Link key={`${sym}-${p.account}-${i}`} to={{ pathname: `/prospectus/${encodeURIComponent(sym)}`, search: linkSearch }} style={style} data-testid={`history-${sym}`}>{body}</Link>
                : <div key={`${sym}-${p.account}-${i}`} style={style}>{body}</div>
            })}
          </div>
        </section>
      ))}
      {!groups.length && <div style={{ fontSize: 13, color: 'var(--text2)' }}>No open positions.</div>}
    </div>
  )
}
