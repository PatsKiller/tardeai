import { useEffect, useMemo, useState } from 'react'
import { fmtNum } from '../lib/format'

const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const MUTED = 'var(--text3)'
const TEXT0 = 'var(--text0)'
const TEXT1 = 'var(--text1)'
const TEXT2 = 'var(--text2)'

type StrikeRow = {
  exp: string
  strike: number
  side: 'call' | 'put'
  bid?: number
  ask?: number
  last?: number
  iv?: number
  delta?: number
  oi?: number
  volume?: number
  dte?: number
}

type ChainData = {
  status?: string
  symbol?: string
  underlying_price?: number
  expirations?: {
    exp: string
    dte?: number
    contracts?: number
    total_call_oi?: number
    total_put_oi?: number
    strikes: StrikeRow[]
  }[]
  error?: string
}

function mid(r: StrikeRow): number | null {
  if (r.bid != null && r.ask != null && r.bid > 0 && r.ask > 0) return (r.bid + r.ask) / 2
  if (r.last != null && r.last > 0) return r.last
  if (r.bid != null && r.bid > 0) return r.bid
  if (r.ask != null && r.ask > 0) return r.ask
  return null
}

function moneyness(spot: number, strike: number, side: string): { label: string; c: string } {
  const itm = side === 'call' ? spot > strike : spot < strike
  const atm = Math.abs(spot - strike) / spot < 0.008
  if (atm) return { label: 'ATM', c: AMBER }
  if (itm) return { label: 'ITM', c: RED }
  return { label: 'OTM', c: GREEN }
}

export default function OptionChainPanel({
  endpoint,
  highlightStrike,
  highlightExp,
  defaultSide = 'call',
}: {
  endpoint: string
  highlightStrike?: number
  highlightExp?: string
  defaultSide?: 'call' | 'put'
}) {
  const [chain, setChain] = useState<ChainData | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [side, setSide] = useState<'call' | 'put'>(defaultSide)
  const [expIdx, setExpIdx] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setErr(null)
    fetch(endpoint)
      .then(r => r.json())
      .then(j => {
        if (cancelled) return
        const data = (j?.data ?? j) as ChainData
        if (data?.status === 'error' || data?.error) {
          setErr(data.error || 'Chain fetch failed')
          setChain(null)
        } else {
          setChain(data)
          if (highlightExp && data.expirations?.length) {
            const idx = data.expirations.findIndex(e => e.exp === highlightExp || e.exp?.startsWith(highlightExp.slice(0, 10)))
            if (idx >= 0) setExpIdx(idx)
          }
        }
      })
      .catch(e => { if (!cancelled) setErr(String(e?.message || e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [endpoint, highlightExp])

  const spot = chain?.underlying_price
  const expirations = chain?.expirations ?? []
  const selectedExp = expirations[expIdx]

  const rows = useMemo(() => {
    if (!selectedExp) return []
    return (selectedExp.strikes || [])
      .filter(r => r.side === side)
      .sort((a, b) => a.strike - b.strike)
  }, [selectedExp, side])

  if (loading) return <div style={{ fontSize: 11, color: MUTED, padding: 12 }}>Loading Schwab option chain…</div>
  if (err) return <div style={{ fontSize: 11, color: RED, padding: 12 }}>Chain error: {err}</div>
  if (!chain?.expirations?.length) return <div style={{ fontSize: 11, color: MUTED, padding: 12 }}>No chain data returned — check Schwab link or symbol.</div>

  const th: React.CSSProperties = { fontSize: 9, color: MUTED, textTransform: 'uppercase', fontWeight: 800, padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }
  const td: React.CSSProperties = { fontSize: 11, padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', fontFamily: 'monospace' }

  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 900, color: TEXT0 }}>
          {chain.symbol} <span style={{ color: BLUE }}>${fmtNum(spot, 2)}</span>
          <span style={{ fontSize: 10, fontWeight: 500, color: MUTED, marginLeft: 8 }}>underlying</span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['call', 'put'] as const).map(s => (
            <button key={s} type="button" onClick={() => setSide(s)} style={{
              fontSize: 10, fontWeight: 800, padding: '4px 10px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${side === s ? BLUE : 'var(--border)'}`,
              background: side === s ? `${BLUE}22` : 'var(--bg2)',
              color: side === s ? BLUE : MUTED,
            }}>{s === 'call' ? 'Calls' : 'Puts'}</button>
          ))}
        </div>
        <select
          value={expIdx}
          onChange={e => setExpIdx(Number(e.target.value))}
          style={{ fontSize: 10, padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: TEXT0 }}
          title="Pick expiration — further dates often have more premium but slower theta"
        >
          {expirations.map((e, i) => (
            <option key={e.exp} value={i}>
              {e.exp} · {e.dte ?? '—'} DTE · {e.contracts ?? 0} strikes
            </option>
          ))}
        </select>
      </div>

      <div style={{ fontSize: 10, color: TEXT2, lineHeight: 1.45, marginBottom: 10, padding: '8px 10px', background: 'rgba(96,165,250,.08)', borderRadius: 8, border: '1px solid rgba(96,165,250,.2)' }}>
        <b style={{ color: BLUE }}>Reading the chain:</b> <b>Bid</b> = what buyers pay you (sell at bid).
        <b> Ask</b> = what sellers want (buy at ask). <b>Mid</b> ≈ fair estimate.
        <b> Delta</b> ≈ % move per $1 stock move. <b>OI</b> = open contracts (liquidity).
        {highlightStrike != null && <span> · <b style={{ color: AMBER }}>Highlighted row</b> = proposal strike.</span>}
      </div>

      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
          <thead>
            <tr>
              <th style={th} title="Strike price for this contract">Strike</th>
              <th style={th} title="Best bid — price you'd receive selling here">Bid</th>
              <th style={th} title="Best ask — price you'd pay buying here">Ask</th>
              <th style={th} title="Mid of bid/ask — used in proposals">Mid</th>
              <th style={th} title="Implied volatility %">IV</th>
              <th style={th} title="Approximate delta">Δ</th>
              <th style={th} title="Open interest">OI</th>
              <th style={th} title="In / at / out of the money vs spot">$</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const m = mid(r)
              const hi = highlightStrike != null && Math.abs(r.strike - highlightStrike) < 0.01
                && (!highlightExp || r.exp === highlightExp || highlightExp.startsWith(r.exp))
              const mn = spot ? moneyness(spot, r.strike, side) : null
              return (
                <tr key={`${r.exp}-${r.strike}-${r.side}`} style={{ background: hi ? 'rgba(245,158,11,.15)' : undefined }}>
                  <td style={{ ...td, fontWeight: hi ? 900 : 600, color: hi ? AMBER : TEXT0 }}>
                    ${fmtNum(r.strike, r.strike < 50 ? 2 : 1)}{hi ? ' ★' : ''}
                  </td>
                  <td style={{ ...td, color: GREEN }}>{r.bid != null ? r.bid.toFixed(2) : '—'}</td>
                  <td style={{ ...td, color: RED }}>{r.ask != null ? r.ask.toFixed(2) : '—'}</td>
                  <td style={{ ...td, color: TEXT1, fontWeight: 800 }}>{m != null ? m.toFixed(2) : '—'}</td>
                  <td style={{ ...td, color: MUTED }}>{r.iv != null ? `${r.iv.toFixed(1)}%` : '—'}</td>
                  <td style={td}>{r.delta != null ? r.delta.toFixed(2) : '—'}</td>
                  <td style={td}>{r.oi ?? '—'}</td>
                  <td style={td}>{mn && <span style={{ fontSize: 9, fontWeight: 800, color: mn.c }}>{mn.label}</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {selectedExp && (
        <div style={{ fontSize: 9, color: MUTED, marginTop: 8 }}>
          {side === 'call' ? 'Call' : 'Put'} OI this exp: {side === 'call' ? selectedExp.total_call_oi : selectedExp.total_put_oi ?? '—'} · Schwab read-only · advisory
        </div>
      )}
    </div>
  )
}