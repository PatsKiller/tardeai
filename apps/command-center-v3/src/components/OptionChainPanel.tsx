/** Schwab option chain panel (rewritten 2026-09-28, reviewer round 3).
 *
 *  Truth rules: the request is checked (response.ok) and the typed server status is mapped to
 *  a distinct message + next action (login renewal, missing account link, mapping, rate limit,
 *  broker error, not found, genuinely empty). A one-sided or last-trade price is never called
 *  "Mid". Every row shows bid, ask, spread %, OI, volume and its own quote time/age. The
 *  proposal's legs are all highlighted and priced conservatively (sell short at bid, buy long
 *  at ask); a missing leg refuses to price and says which. Read-only; nothing here orders. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { fmtNum } from '../lib/format'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../lib/designTokens'
import { ageLabel, chainStatusMessage, executableNet, quoteAgeSeconds, quoteLabel, spreadPct, type ChainRow, type LegSpec } from '../lib/optionChainTruth'

type ChainData = {
  status?: string; error?: string; http_status?: number; symbol?: string; underlying_price?: number
  underlying_quote_time?: string | null; fetched_at?: string; trace_id?: string
  request?: { symbol?: string; strikes?: number; expiration?: string | null; side?: string | null }
  expirations?: { exp: string; dte?: number; contracts?: number; total_call_oi?: number; total_put_oi?: number; strikes: ChainRow[] }[]
}

function moneyness(spot: number, strike: number, side: string): { label: string; color: string } {
  const itm = side === 'call' ? spot > strike : spot < strike
  const atm = Math.abs(spot - strike) / spot < 0.008
  if (atm) return { label: 'ATM', color: TOKENS.warning }
  if (itm) return { label: 'ITM', color: TOKENS.danger }
  return { label: 'OTM', color: TOKENS.success }
}

export default function OptionChainPanel({ endpoint, highlightStrike, highlightStrikes, highlightExp, defaultSide = 'call', legs = [], contracts = 1 }: {
  endpoint: string
  highlightStrike?: number
  highlightStrikes?: number[]
  highlightExp?: string
  defaultSide?: 'call' | 'put'
  legs?: LegSpec[]
  contracts?: number
}) {
  const [chain, setChain] = useState<ChainData | null>(null)
  const [loading, setLoading] = useState(true)
  const [httpOk, setHttpOk] = useState(true)
  const [httpStatus, setHttpStatus] = useState<number | null>(null)
  const [netErr, setNetErr] = useState<string | null>(null)
  const [side, setSide] = useState<'call' | 'put'>(defaultSide)
  const [expIdx, setExpIdx] = useState(0)
  const [tick, setTick] = useState(0)
  const [now, setNow] = useState(Date.now())
  const wanted = useMemo(() => (highlightStrikes && highlightStrikes.length ? highlightStrikes : highlightStrike != null ? [highlightStrike] : []), [highlightStrike, highlightStrikes])

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true); setNetErr(null)
    fetch(endpoint)
      .then(async r => {
        setHttpOk(r.ok); setHttpStatus(r.status)
        let j: any = null
        try { j = await r.json() } catch { j = null }
        if (cancelled) return
        const data = (j && typeof j === 'object' && 'data' in j ? j.data : j) as ChainData | null
        setChain(data && typeof data === 'object' ? data : null)
        setNow(Date.now())
        if (data?.expirations?.length) {
          const idx = highlightExp ? data.expirations.findIndex(e => e.exp === highlightExp || e.exp?.startsWith(highlightExp.slice(0, 10))) : -1
          setExpIdx(idx >= 0 ? idx : 0)
        }
      })
      .catch(e => { if (!cancelled) { setHttpOk(false); setNetErr(String(e?.message || e)) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [endpoint, highlightExp])

  useEffect(() => load(), [load, tick])

  const spot = chain?.underlying_price
  const expirations = chain?.expirations ?? []
  const selectedExp = expirations[expIdx]
  const rows = useMemo(() => (selectedExp?.strikes || []).filter(r => r.side === side).sort((a, b) => a.strike - b.strike), [selectedExp, side])
  const legPricing = useMemo(() => (legs.length && selectedExp ? executableNet(legs, selectedExp.strikes || [], contracts) : null), [legs, selectedExp, contracts])
  const msg = chainStatusMessage(chain?.status, httpOk && !netErr, chain?.error || netErr, httpStatus)
  const fetchedAge = quoteAgeSeconds(chain?.fetched_at, now)

  const th: React.CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', fontWeight: 800, padding: '6px 8px', textAlign: 'left', borderBottom: `1px solid ${TOKENS.border}`, whiteSpace: 'nowrap' }
  const td: React.CSSProperties = { ...numStyle, fontSize: TYPE.sm, padding: '6px 8px', borderBottom: `1px solid ${TOKENS.borderSubtle}`, whiteSpace: 'nowrap' }
  const btn = (active: boolean): React.CSSProperties => ({ fontFamily: 'inherit', fontSize: TYPE.xs, fontWeight: 800, padding: '4px 10px', borderRadius: RADIUS.sm, cursor: 'pointer',
    border: `1px solid ${active ? TOKENS.info : TOKENS.border}`, background: active ? toneVars('info').bg : TOKENS.bg[2], color: active ? TOKENS.info : TOKENS.text[2] })

  const refresh = <button type="button" onClick={() => setTick(t => t + 1)} style={btn(false)} aria-label="Refresh chain">Refresh</button>

  if (loading) return <div style={{ fontSize: TYPE.sm, color: TOKENS.text[3], padding: 12 }} role="status">Loading Schwab option chain…</div>
  if (msg) {
    const t = toneVars(msg.tone)
    return (
      <div role="alert" style={{ padding: '10px 12px', borderRadius: RADIUS.md, background: t.bg, border: `1px solid ${t.border}`, borderLeft: `3px solid ${t.color}` }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }}>{msg.title}</div>
        <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 4, lineHeight: 1.45 }}>{msg.next}</div>
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', fontSize: TYPE.xs, color: TOKENS.text[3] }}>
          {refresh}
          {chain?.status && <span>status {chain.status}</span>}
          {chain?.http_status && <span>· broker HTTP {chain.http_status}</span>}
          {chain?.trace_id && <span>· trace {chain.trace_id}</span>}
        </div>
      </div>
    )
  }
  if (!expirations.length) return <div style={{ fontSize: TYPE.sm, color: TOKENS.text[3], padding: 12 }}>No expirations in the answer. {refresh}</div>

  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 900, color: TOKENS.text[0] }}>
          {chain?.symbol} <span style={{ color: TOKENS.info, ...numStyle }}>${fmtNum(spot, 2)}</span>
          <span style={{ fontSize: TYPE.xs, fontWeight: 500, color: TOKENS.text[3], marginLeft: 8 }}>underlying{chain?.underlying_quote_time ? ` · quoted ${ageLabel(quoteAgeSeconds(chain.underlying_quote_time, now))}` : ''}</span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['call', 'put'] as const).map(s => <button key={s} type="button" onClick={() => setSide(s)} style={btn(side === s)} aria-pressed={side === s}>{s === 'call' ? 'Calls' : 'Puts'}</button>)}
        </div>
        <select value={expIdx} onChange={e => setExpIdx(Number(e.target.value))} aria-label="Expiration"
          style={{ fontFamily: 'inherit', fontSize: TYPE.xs, padding: '5px 8px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.text[0] }}>
          {expirations.map((e, i) => <option key={e.exp} value={i}>{e.exp} · {e.dte ?? '—'} DTE · {e.contracts ?? 0} contracts</option>)}
        </select>
        {refresh}
        <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>chain read {ageLabel(fetchedAge)}{chain?.request?.expiration ? ` · pinned to ${chain.request.expiration}` : ''}{chain?.trace_id ? ` · trace ${chain.trace_id}` : ''}</span>
      </div>

      {legPricing && (
        <div data-testid="chain-legs-pricing" style={{ marginBottom: 8, padding: '8px 10px', borderRadius: RADIUS.md, background: toneVars(legPricing.net == null ? 'warning' : 'info').bg, border: `1px solid ${toneVars(legPricing.net == null ? 'warning' : 'info').border}`, fontSize: TYPE.sm, color: TOKENS.text[1], lineHeight: 1.5 }}>
          <b style={{ color: TOKENS.text[0] }}>Proposal legs on {selectedExp?.exp}.</b>{' '}
          {legPricing.legs.map((l, i) => (
            <span key={i}>{i ? ' · ' : ''}{l.role} {l.side} ${fmtNum(l.strike, l.strike < 50 ? 2 : 1)}{l.row ? ` bid ${l.row.bid ?? '—'} / ask ${l.row.ask ?? '—'}${l.row.oi != null ? ` · OI ${l.row.oi}` : ''}` : ' — not in this window'}</span>
          ))}
          <div style={{ marginTop: 3 }}>
            {legPricing.net == null
              ? <span style={{ color: TOKENS.warning, fontWeight: 800 }}>Cannot price: {legPricing.reason}.</span>
              : <span>Executable estimate: <b style={{ color: TOKENS.text[0], ...numStyle }}>{legPricing.kind} ${fmtNum(Math.abs(legPricing.perContract || 0), 2)}/share = ${fmtNum(Math.abs(legPricing.net), 0)}</b> for {contracts} contract{contracts === 1 ? '' : 's'} (sell short legs at bid, buy long legs at ask; midpoints are not fills).</span>}
          </div>
        </div>
      )}

      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[2], lineHeight: 1.45, marginBottom: 8, padding: '8px 10px', background: toneVars('info').bg, borderRadius: RADIUS.md, border: `1px solid ${toneVars('info').border}` }}>
        <b style={{ color: TOKENS.info }}>Reading the chain:</b> a <b>call</b> is the right to buy, a <b>put</b> the right to sell, at the <b>strike</b> until the <b>expiration</b>. <b>Bid</b> = what a buyer pays you now (you sell at bid). <b>Ask</b> = what a seller wants (you buy at ask).
        <b> Spread</b> = ask − bid as % of the middle; wide means costly to enter and exit. <b>Quote</b> shows the middle only when both sides exist and is labelled <b>Last</b> or one-sided otherwise; none of these is a fill. <b>OI</b> = open contracts, <b>Vol</b> = contracts traded today. One contract = 100 shares, so dollars = price × 100.
        {wanted.length > 0 && <span> · <b style={{ color: TOKENS.warning }}>Highlighted rows</b> = the proposal's legs.</span>}
      </div>

      <div style={{ overflowX: 'auto', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
          <thead><tr>
            <th style={th}>Strike</th><th style={th}>Bid</th><th style={th}>Ask</th><th style={th}>Spread</th><th style={th}>Quote</th><th style={th}>IV</th><th style={th}>Δ</th><th style={th}>OI</th><th style={th}>Vol</th><th style={th}>Quoted</th><th style={th}>$</th>
          </tr></thead>
          <tbody>
            {rows.map(r => {
              const q = quoteLabel(r)
              const sp = spreadPct(r)
              const hi = wanted.some(k => Math.abs(r.strike - k) < 0.01) && (!highlightExp || r.exp === highlightExp || highlightExp.startsWith(r.exp))
              const mn = spot ? moneyness(spot, r.strike, side) : null
              const age = quoteAgeSeconds(r.quote_time, now)
              return (
                <tr key={`${r.exp}-${r.strike}-${r.side}`} style={{ background: hi ? toneVars('warning').bg : undefined }}>
                  <td style={{ ...td, fontWeight: hi ? 900 : 600, color: hi ? TOKENS.warning : TOKENS.text[0] }}>${fmtNum(r.strike, r.strike < 50 ? 2 : 1)}{hi ? ' ★' : ''}</td>
                  <td style={{ ...td, color: TOKENS.success }}>{typeof r.bid === 'number' ? r.bid.toFixed(2) : '—'}</td>
                  <td style={{ ...td, color: TOKENS.danger }}>{typeof r.ask === 'number' ? r.ask.toFixed(2) : '—'}</td>
                  <td style={{ ...td, color: sp != null && sp > 12 ? TOKENS.warning : TOKENS.text[2] }}>{sp != null ? `${sp}%` : 'one-sided'}</td>
                  <td style={{ ...td, color: TOKENS.text[1], fontWeight: 800 }}>{q.value != null ? q.value.toFixed(2) : '—'} <span style={{ fontSize: TYPE.xs, fontWeight: 600, color: q.label === 'Mid' ? TOKENS.text[3] : TOKENS.warning }}>{q.label}</span></td>
                  <td style={{ ...td, color: TOKENS.text[3] }}>{typeof r.iv === 'number' ? `${r.iv.toFixed(1)}%` : '—'}</td>
                  <td style={td}>{typeof r.delta === 'number' ? r.delta.toFixed(2) : '—'}</td>
                  <td style={{ ...td, color: (r.oi ?? 0) === 0 ? TOKENS.danger : TOKENS.text[1] }}>{r.oi ?? '—'}</td>
                  <td style={td}>{r.volume ?? '—'}</td>
                  <td style={{ ...td, color: TOKENS.text[3] }} title={r.quote_time || ''}>{ageLabel(age)}</td>
                  <td style={td}>{mn && <span style={{ fontSize: TYPE.xs, fontWeight: 800, color: mn.color }}>{mn.label}</span>}{r.nonstandard ? <span style={{ fontSize: TYPE.xs, color: TOKENS.warning }} title="Adjusted / non-standard deliverable"> adj</span> : null}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {selectedExp && (
        <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginTop: 8 }}>
          {side === 'call' ? 'Call' : 'Put'} OI this expiry: {(side === 'call' ? selectedExp.total_call_oi : selectedExp.total_put_oi) ?? '—'} · {chain?.request?.strikes ?? '—'} strikes each side · Schwab read-only · advisory, not an order
        </div>
      )}
    </div>
  )
}
