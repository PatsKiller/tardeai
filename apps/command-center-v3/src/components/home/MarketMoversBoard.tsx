import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { BB, T, TYPE, numStyle } from '../../lib/watchTokens'

// Home v2 WS-A: the Finviz signal board. Data: /api/v2/market-movers (throttled Elite export
// capture ~12min RTH — the capture cadence IS the design; this is a decision desk, not a feed).
// Empty-state taxonomy (2026-07-26 home-trust): market_closed | capture_failed | empty_rth.
// Signal chips FILTER the board; held names carry ●, watchlisted ○.

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''

function fmtVol(v?: number | null): string {
  if (!v) return '—'
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K'
  return String(v)
}

/** US equity cash session rough gate in local browser time (ET-aware via offset when possible). */
function usSessionHint(now = new Date()): 'weekend' | 'premarket' | 'rth' | 'afterhours' {
  // Use America/New_York when available
  let et: Date
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false,
    }).formatToParts(now)
    const wd = parts.find(p => p.type === 'weekday')?.value || ''
    const hour = parseInt(parts.find(p => p.type === 'hour')?.value || '0', 10)
    const minute = parseInt(parts.find(p => p.type === 'minute')?.value || '0', 10)
    if (wd === 'Sat' || wd === 'Sun') return 'weekend'
    const mins = hour * 60 + minute
    if (mins < 9 * 60 + 30) return 'premarket'
    if (mins >= 16 * 60) return 'afterhours'
    return 'rth'
  } catch {
    const d = now.getDay()
    if (d === 0 || d === 6) return 'weekend'
    return 'rth'
  }
}

function emptyStateMessage(data: any): { title: string; detail: string } {
  const session = usSessionHint()
  const errors = data?.errors || {}
  const errKeys = Object.keys(errors)
  const sigs: Record<string, any> = data?.signals || {}
  const rowCount = Object.values(sigs).reduce((n: number, s: any) => n + ((s?.rows || []).length), 0)
  const capAt = data?.captured_at ? String(data.captured_at) : ''

  if (errKeys.length && rowCount === 0) {
    return {
      title: 'capture failed',
      detail: `Finviz Elite export errors on ${errKeys.slice(0, 3).join(', ')}${errKeys.length > 3 ? '…' : ''} — cookie/throttle or network. Last attempt ${capAt || '—'}.`,
    }
  }
  if (session === 'weekend') {
    return {
      title: 'market closed (weekend)',
      detail: `No live RTH movers on Saturday/Sunday. Showing last capture ${capAt || '—'} — reopen Monday premarket.`,
    }
  }
  if (session === 'premarket' || session === 'afterhours') {
    return {
      title: session === 'premarket' ? 'premarket — board idle' : 'after-hours — board idle',
      detail: `Elite RTH cadence (~12 min) is offline outside the cash session. Last capture ${capAt || '—'}.`,
    }
  }
  return {
    title: 'no rows in this capture',
    detail: `RTH capture returned empty signals at ${capAt || '—'}. If this persists, check Finviz cookie + finviz_market_movers cron.`,
  }
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
  const empty = emptyStateMessage(data)

  const sigColor: Record<string, string> = {
    top_gainers: BB.green, top_losers: BB.red, new_high: BB.green, new_low: BB.red,
    unusual_volume: BB.amber, most_volatile: '#a855f7', most_active: T.link,
    earnings_before: BB.amber, earnings_after: BB.amber, insider_buying: BB.green,
  }

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${T.link}`, borderRadius: 2, padding: '10px 12px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2 }}>MARKET MOVERS</span>
        <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· finviz elite capture {capAt || '—'}Z · ~12min RTH</span>
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
        {shown.length === 0 && (
          <div style={{ fontSize: TYPE.sm, color: BB.text3, padding: 8 }}>
            <div style={{ fontWeight: 700, color: BB.amber, marginBottom: 4 }}>{empty.title}</div>
            <div style={{ lineHeight: 1.45 }}>{empty.detail}</div>
          </div>
        )}
      </div>
    </div>
  )
}
