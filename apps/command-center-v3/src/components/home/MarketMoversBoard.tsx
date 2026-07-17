import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { BB, T, TYPE, numStyle } from '../../lib/watchTokens'

// Home v2 WS-A: the Finviz signal board. Data: /api/v2/market-movers (throttled Elite export
// capture ~12min RTH — the capture cadence IS the design; this is a decision desk, not a feed).
// Signal chips FILTER the board; held names carry ●, watchlisted ○. Row click routes: held/
// watch → the symbol's watch page; unknown → Finviz quote (external, noopener).

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''

function fmtVol(v?: number | null): string {
  if (!v) return '—'
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K'
  return String(v)
}

export default function MarketMoversBoard({ pullbackSymbols }: { pullbackSymbols?: Set<string> }) {
  const { data } = useApi<any>('/api/v2/market-movers', 300_000)
  const [filter, setFilter] = useState<string>('')
  if (!data?.ok) {
    return <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14, fontSize: TYPE.sm, color: BB.text3 }}>
      Market movers: {data?.error || 'loading…'}
    </div>
  }
  const sigs: Record<string, any> = data.signals || {}
  const errors: Record<string, string> = data.errors || {}
  const keys = Object.keys(sigs)
  const active = filter && sigs[filter] ? [filter] : keys
  const capAt = (data.captured_at || '').slice(11, 16)
  const rows: any[] = active.flatMap(k => (sigs[k].rows || []).map((r: any) => ({ ...r, _sig: k, _label: sigs[k].label })))
  const shown = filter ? rows : rows.filter((_, i) => true).slice(0, 60)

  const sigColor: Record<string, string> = {
    top_gainers: BB.green, top_losers: BB.red, new_high: BB.green, new_low: BB.red,
    unusual_volume: BB.amber, most_volatile: '#a855f7', most_active: T.link,
    earnings_before: BB.amber, earnings_after: BB.amber, insider_buying: BB.green,
  }

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${T.link}`, borderRadius: 2, padding: '10px 12px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2 }}>MARKET MOVERS</span>
        <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· finviz elite capture {capAt}Z · ~12min RTH</span>
        <span style={{ flex: 1 }} />
        {filter && <button onClick={() => setFilter('')} style={{ fontSize: TYPE.xs, color: BB.text3, background: 'transparent', border: 'none', cursor: 'pointer' }}>clear ✕</button>}
      </div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
        {keys.map(k => (
          <button key={k} onClick={() => setFilter(filter === k ? '' : k)} style={{
            fontSize: 9, fontWeight: filter === k ? 800 : 600, padding: '1px 7px', borderRadius: 2, cursor: 'pointer',
            border: `1px solid ${filter === k ? (sigColor[k] || BB.text3) : BB.borderHair}`,
            background: filter === k ? `${sigColor[k] || BB.text3}18` : 'transparent',
            color: sigColor[k] || BB.text3,
          }}>{sigs[k].label} {sigs[k].rows?.length ?? 0}</button>
        ))}
        {Object.entries(errors).map(([k, e]) => (
          <span key={k} title={String(e)} style={{ fontSize: 9, color: BB.red, border: `1px solid ${BB.red}44`, borderRadius: 2, padding: '1px 7px' }}>{k} unavailable</span>
        ))}
      </div>
      <div style={{ overflowY: 'auto', maxHeight: 330 }}>
        {shown.map((r, i) => {
          const chg = Number(r.change_pct ?? 0)
          const held = !!r.held
          const isPullback = pullbackSymbols?.has(r.symbol)
          const href = held || r.watch ? `${FQDN}/v3/watch?symbol=${r.symbol}` : `https://finviz.com/quote.ashx?t=${r.symbol}`
          const ext = !(held || r.watch)
          return (
            <a key={`${r._sig}-${r.symbol}-${i}`} href={href}
               target={ext ? '_blank' : undefined} rel={ext ? 'noopener noreferrer' : undefined}
               title={`${r.company || r.symbol} · ${r._label}${isPullback ? ' · in today’s pullback triggers' : ''}`}
               style={{
                 display: 'grid', gridTemplateColumns: '64px 58px 62px 58px 1fr', gap: 6, alignItems: 'baseline',
                 padding: '2px 4px', borderBottom: `1px solid ${BB.borderHair}`, textDecoration: 'none',
                 borderLeft: isPullback ? `2px solid ${BB.amber}` : '2px solid transparent',
               }}>
              <span style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 800, color: BB.text1 }}>
                {r.symbol}{held && <span title="held position" style={{ color: BB.green }}> ●</span>}{!held && r.watch && <span title="on watchlist" style={{ color: T.link }}> ○</span>}
              </span>
              <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text2, textAlign: 'right' }}>{r.last ?? '—'}</span>
              <span style={{ ...numStyle, fontSize: TYPE.xs, fontWeight: 700, textAlign: 'right', color: chg > 0 ? BB.green : chg < 0 ? BB.red : BB.text3 }}>
                {chg > 0 ? '+' : ''}{chg.toFixed(2)}%
              </span>
              <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text3, textAlign: 'right' }}>{fmtVol(r.volume)}</span>
              <span style={{ fontSize: 8.5, fontWeight: 700, color: sigColor[r._sig] || BB.text3, textTransform: 'uppercase', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r._label}</span>
            </a>
          )
        })}
        {shown.length === 0 && <div style={{ fontSize: TYPE.sm, color: BB.text3, padding: 8 }}>no rows in this capture</div>}
      </div>
    </div>
  )
}
