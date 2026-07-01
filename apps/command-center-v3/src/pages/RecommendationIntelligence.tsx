import { useEffect, useMemo, useState } from 'react'

type SrcPerf = { source?: string; closed_trades?: number; wins?: number; win_rate_pct?: number; avg_return_pct?: number; total_pnl?: number; avg_hold_days?: number }
type StratPerf = { strategy?: string; resolved?: number; wins?: number; win_rate_pct?: number; avg_return_pct?: number }
type BySource = { source?: string; tickers?: number; executed?: number }
type MultiSrc = { symbol?: string; n_sources?: number; earliest_source?: string; latest_source?: string; first_seen?: string; last_seen?: string; executed?: boolean }
type RotLink = { from?: string; to?: string; executed?: boolean; at?: string; via?: string; rotation_alpha_pct?: number }
type SrcQual = { source?: string; sample?: number; win_rate_pct?: number; avg_return_pct?: number; quality_multiplier?: number; basis?: string }
type RotOutcome = { measured?: number; avg_alpha_pct?: number; rotations_that_beat_holding?: number }
type LcEvent = { at?: string; event?: string; status?: string; symbol?: string; payload?: any }
type LifePos = {
  symbol?: string; account?: string; origin?: string; executed_lineage?: boolean
  open_date?: string; close_date?: string; buy_price?: number; sell_price?: number
  pnl?: number; pnl_pct?: number; r_multiple?: number; hold_days?: number
  setup?: string; strategy_id?: string; journaled?: boolean; journal?: any
}
type OpenPos = {
  symbol?: string; account?: string; origin?: string; shares?: number; avg_cost?: number
  current_price?: number; unrealized_pnl?: number; unrealized_pnl_pct?: number; held_since?: string
}
type Summary = {
  ok?: boolean; error?: string; total_tickers?: number; multi_source_count?: number; executed_attributions?: number
  by_source?: BySource[]; performance_by_source?: SrcPerf[]; performance_by_strategy?: StratPerf[]
  multi_source_examples?: MultiSrc[]; rotation_links?: RotLink[]; rotation_link_count?: number; generated_at?: string
  source_quality?: SrcQual[]; rotation_chains?: string[][]; rotation_outcomes?: RotOutcome
}
type Lineage = {
  ok?: boolean; symbol?: string; found?: boolean; source_count?: number
  earliest_source?: string; earliest_at?: string; latest_source?: string; latest_at?: string; executed?: boolean
  sources?: any[]; rotation_links?: RotLink[]; error?: string
}

const ACCENT = '#60a5fa'
const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const SRC_COLOR: Record<string, string> = {
  watchlist: '#60a5fa', scan: '#22c55e', screener: '#22c55e', proposal: '#f59e0b', execution: '#a855f7',
  holding: '#a855f7', directive: '#ec4899', hermes_research: '#14b8a6', research: '#14b8a6',
  cio: '#eab308', rotation: '#ef4444',
}
const pct = (v?: number) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v}%`)
const usd = (v?: number) => (v == null ? '—' : v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }))
const rcol = (v?: number) => (v == null ? 'var(--text2)' : v >= 0 ? '#22c55e' : '#ef4444')

function SummaryCard({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <div style={{ ...card, textAlign: 'center', padding: '14px 10px' }}>
      <div style={{ fontSize: 24, fontWeight: 800, color: color ?? 'var(--text0)' }}>{value}</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>{label}</div>
    </div>
  )
}
function SrcTag({ s }: { s?: string }) {
  const c = SRC_COLOR[s || ''] ?? '#6b7280'
  return <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: `${c}1f`, color: c, border: `1px solid ${c}44` }}>{s}</span>
}

export default function RecommendationIntelligence() {
  const [d, setD] = useState<Summary | null>(null)
  const [warn, setWarn] = useState('')
  const [sym, setSym] = useState('')
  const [lin, setLin] = useState<Lineage | null>(null)
  const [linBusy, setLinBusy] = useState(false)
  const [events, setEvents] = useState<LcEvent[]>([])
  const [life, setLife] = useState<LifePos[]>([])
  const [lifeOnlyOrigin, setLifeOnlyOrigin] = useState(false)
  const [openPos, setOpenPos] = useState<OpenPos[]>([])
  const [fOrigin, setFOrigin] = useState('')   // unified origin-source filter (drives both position tables)

  async function load() {
    setWarn('')
    try {
      const r = await fetch('/api/v2/rec-intel/summary')
      const j = await r.json()
      const inner = j?.data ?? j
      if (inner?.ok === false) setWarn(inner.error || 'unavailable')
      setD(inner)
    } catch (e) { setWarn(e instanceof Error ? e.message : String(e)) }
    try {
      const r = await fetch('/api/v2/rec-intel/lifecycle')
      const j = await r.json()
      setEvents((j?.data ?? j)?.events ?? [])
    } catch { /* noop */ }
    try {
      const r = await fetch('/api/v2/rec-intel/lifecycle-performance?limit=300')
      const j = await r.json()
      setLife((j?.data ?? j)?.positions ?? [])
    } catch { /* noop */ }
    try {
      const r = await fetch('/api/v2/rec-intel/open-positions')
      const j = await r.json()
      setOpenPos((j?.data ?? j)?.positions ?? [])
    } catch { /* noop */ }
  }
  async function lookup(s?: string) {
    const q = (s ?? sym).trim().toUpperCase()
    if (!q) return
    setSym(q); setLinBusy(true); setLin(null)
    try {
      const r = await fetch(`/api/v2/rec-intel/ticker?symbol=${encodeURIComponent(q)}`)
      const j = await r.json()
      setLin(j?.data ?? j)
    } catch (e) { setLin({ ok: false, error: e instanceof Error ? e.message : String(e) }) }
    finally { setLinBusy(false) }
  }
  useEffect(() => {
    load()
    // deep-link support: /v3/rec-intel?symbol=XYZ (e.g. a Watchlist card's "Rec-Intel →") auto-loads the ticker
    const s = new URLSearchParams(window.location.search).get('symbol')
    if (s) lookup(s)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const perf = d?.performance_by_source ?? []
  const strat = d?.performance_by_strategy ?? []
  const bySrc = d?.by_source ?? []
  const multi = d?.multi_source_examples ?? []
  const rot = d?.rotation_links ?? []

  // Unified origin filter — derived from the position tables' OWN origins (self-consistent; the headline
  // perf-by-source table uses a different attribution layer, so it's intentionally NOT wired here).
  const originChips = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const p of [...life, ...openPos]) { const o = p.origin || 'direct/manual'; counts[o] = (counts[o] || 0) + 1 }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [life, openPos])
  const matchOrigin = (o?: string) => !fOrigin || (o || 'direct/manual') === fOrigin

  return (
    <div style={{ padding: 4 }}>
      <header style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Recommendation Intelligence</div>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 3 }}>Every ticker traced from origin source → execution → outcome, attributable by source/strategy/account</div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 5, fontWeight: 600 }}>Read-only lineage + analytics · no broker action</div>
      </header>

      {warn && <div style={{ marginBottom: 14, padding: '8px 12px', borderRadius: 8, fontSize: 11, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)', color: '#f59e0b' }}>{warn}</div>}

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 20 }}>
        <SummaryCard label="Tickers Tracked" value={d?.total_tickers ?? '—'} color={ACCENT} />
        <SummaryCard label="Multi-Source" value={d?.multi_source_count ?? '—'} color="#a855f7" />
        <SummaryCard label="Executed Attributions" value={d?.executed_attributions ?? '—'} color="#22c55e" />
        <SummaryCard label="Rotation Links" value={d?.rotation_link_count ?? '—'} color="#ef4444" />
      </section>

      {/* Ticker lineage lookup */}
      <section style={{ ...card, marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Trace a ticker's lineage</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input value={sym} onChange={e => setSym(e.target.value.toUpperCase())} onKeyDown={e => e.key === 'Enter' && lookup()} placeholder="e.g. GCTS"
            style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text0)', border: '1px solid var(--border)', borderRadius: 8, width: 140 }} />
          <button onClick={() => lookup()} disabled={linBusy} style={{ padding: '7px 14px', fontSize: 12, fontWeight: 700, borderRadius: 8, border: `1px solid ${ACCENT}55`, background: 'rgba(96,165,250,.15)', color: ACCENT, cursor: 'pointer' }}>{linBusy ? 'Tracing…' : 'Trace'}</button>
        </div>
        {lin && (lin.found === false ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 10 }}>No internal recommendation source has introduced {lin.symbol}.</div>
        ) : lin.found ? (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11, color: 'var(--text2)', marginBottom: 10 }}>
              <span><b style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{lin.symbol}</b></span>
              <span>{lin.source_count} source types</span>
              <span>earliest: <SrcTag s={lin.earliest_source} /> {String(lin.earliest_at).slice(0, 10)}</span>
              <span>latest: <SrcTag s={lin.latest_source} /> {String(lin.latest_at).slice(0, 10)}</span>
              <span style={{ color: lin.executed ? '#22c55e' : 'var(--text3)' }}>{lin.executed ? '✓ executed' : 'not executed'}</span>
            </div>
            <div style={{ borderLeft: '2px solid var(--border)', paddingLeft: 12 }}>
              {(lin.sources ?? []).map((s: any, i: number) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10.5, color: 'var(--text2)', padding: '3px 0' }}>
                  <span style={{ width: 80, color: 'var(--text3)', fontFamily: 'monospace' }}>{String(s.first_seen_at).slice(0, 10)}</span>
                  <SrcTag s={s.source_type} />
                  {s.executed && <span style={{ color: '#22c55e', fontSize: 9 }}>✓</span>}
                  <span style={{ color: 'var(--text3)' }}>{s.source_detail?.discovery_source || s.source_detail?.origin_system || s.source_detail?.research_type || s.source_detail?.decision || s.source_detail?.action || s.account || ''}</span>
                  {s.source_detail?.outcome_pnl_pct != null && <span style={{ color: rcol(s.source_detail.outcome_pnl_pct) }}>{pct(s.source_detail.outcome_pnl_pct)}</span>}
                </div>
              ))}
            </div>
            {(lin.rotation_links ?? []).length > 0 && (
              <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 8 }}>Rotations: {(lin.rotation_links ?? []).map((r, i) => <span key={i}>{r.from}→{r.to}{i < (lin.rotation_links!.length - 1) ? ', ' : ''}</span>)}</div>
            )}
          </div>
        ) : <div style={{ fontSize: 11, color: '#ef4444', marginTop: 10 }}>{lin.error}</div>)}
      </section>

      {/* Return by origin source — the headline metric */}
      <section style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Return by Origin Source</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Realized outcomes of closed trades, attributed to the source that originally introduced the ticker. This is which recommendation sources actually make money.</div>
        {perf.length === 0 ? <div style={{ ...card, fontSize: 11, color: 'var(--text3)' }}>No closed trades with attributable origin yet.</div> : (
          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
              <thead><tr style={{ background: 'var(--bg2)', color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.4 }}>
                {['Source', 'Trades', 'Source win rate', 'Avg Return', 'Total P&L', 'Avg Hold'].map(h => <th key={h} style={{ textAlign: h === 'Source' ? 'left' : 'right', padding: '8px 12px' }}>{h}</th>)}
              </tr></thead>
              <tbody>{perf.map((s, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '8px 12px' }}><SrcTag s={s.source} /></td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--text1)' }}>{s.closed_trades}</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 700, color: (s.win_rate_pct ?? 0) >= 50 ? '#22c55e' : '#ef4444' }}>{s.win_rate_pct == null ? '—' : `${s.win_rate_pct}%`}</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 700, color: rcol(s.avg_return_pct) }}>{pct(s.avg_return_pct)}</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', color: rcol(s.total_pnl) }}>{usd(s.total_pnl)}</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--text2)' }}>{s.avg_hold_days == null ? '—' : `${s.avg_hold_days}d`}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16, marginBottom: 20 }}>
        {/* Coverage by source */}
        <section>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Coverage by Source</div>
          <div style={{ ...card }}>
            {bySrc.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', fontSize: 11.5 }}>
                <span style={{ width: 110 }}><SrcTag s={s.source} /></span>
                <div style={{ flex: 1, height: 7, background: 'var(--bg2)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, (s.tickers ?? 0) / (d?.total_tickers || 1) * 100)}%`, height: '100%', background: SRC_COLOR[s.source || ''] ?? '#6b7280' }} />
                </div>
                <span style={{ width: 56, textAlign: 'right', color: 'var(--text1)' }}>{s.tickers}</span>
                {!!s.executed && <span style={{ width: 56, textAlign: 'right', color: '#22c55e', fontSize: 10 }}>{s.executed} exec</span>}
              </div>
            ))}
          </div>
        </section>

        {/* Performance by strategy */}
        <section>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Performance by Strategy</div>
          <div style={{ ...card }}>
            {strat.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>No resolved strategy outcomes yet.</div> : strat.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', fontSize: 11 }}>
                <span style={{ flex: 1, color: 'var(--text1)', fontFamily: 'monospace', fontSize: 10.5 }}>{s.strategy}</span>
                <span style={{ width: 60, textAlign: 'right', color: (s.win_rate_pct ?? 0) >= 50 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>{s.win_rate_pct == null ? '—' : `${s.win_rate_pct}%`}</span>
                <span style={{ width: 60, textAlign: 'right', color: rcol(s.avg_return_pct) }}>{pct(s.avg_return_pct)}</span>
                <span style={{ width: 40, textAlign: 'right', color: 'var(--text3)', fontSize: 10 }}>n{s.resolved}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Unified origin filter — drives both position tables (self-consistent: chips come from their data) */}
      {originChips.length > 0 && (
        <section style={{ ...card, marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4 }}>Filter trades by origin</span>
          <button onClick={() => setFOrigin('')} style={{ fontSize: 10.5, fontWeight: fOrigin === '' ? 800 : 600, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${fOrigin === '' ? ACCENT : 'var(--border)'}`, background: fOrigin === '' ? 'rgba(96,165,250,.12)' : 'var(--bg2)', color: fOrigin === '' ? ACCENT : 'var(--text2)' }}>All</button>
          {originChips.map(([o, n]) => {
            const on = fOrigin === o; const c = SRC_COLOR[o] ?? '#6b7280'
            return <button key={o} onClick={() => setFOrigin(on ? '' : o)} style={{ fontSize: 10.5, fontWeight: on ? 800 : 600, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${on ? c : 'var(--border)'}`, background: on ? `${c}1f` : 'var(--bg2)', color: on ? c : 'var(--text2)' }}>{o} <span style={{ opacity: 0.7 }}>{n}</span></button>
          })}
        </section>
      )}

      {/* Open positions — monitoring (held now, unrealized, auto-detected origin) */}
      {openPos.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Open Positions — Monitoring</div>
            <span style={{ fontSize: 10, color: 'var(--text3)' }}>{openPos.length} held · {openPos.filter(p => p.origin).length} with detected origin · total unrealized <b style={{ color: rcol(openPos.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0)) }}>{usd(openPos.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0))}</b></span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Currently-held real positions in the "monitored till sale" phase — cost basis from your buys, current price, unrealized P&amp;L, held-since, and the auto-detected recommendation origin. Click to trace lineage.</div>
          <div style={{ ...card, padding: 4, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead><tr style={{ color: 'var(--text3)', textAlign: 'right' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px' }}>Symbol</th>
                <th style={{ textAlign: 'left', padding: '6px 8px' }}>Origin</th>
                <th style={{ padding: '6px 8px' }}>Shares</th><th style={{ padding: '6px 8px' }}>Avg cost</th>
                <th style={{ padding: '6px 8px' }}>Current</th><th style={{ padding: '6px 8px' }}>Unrealized</th>
                <th style={{ padding: '6px 8px' }}>$</th><th style={{ textAlign: 'left', padding: '6px 8px' }}>Held since</th>
              </tr></thead>
              <tbody>
                {openPos.filter(p => matchOrigin(p.origin)).slice(0, 60).map((p, i) => (
                  <tr key={i} onClick={() => lookup(p.symbol)} style={{ borderTop: '1px solid var(--border)', cursor: 'pointer', textAlign: 'right' }}>
                    <td style={{ textAlign: 'left', padding: '6px 8px', fontFamily: 'monospace', fontWeight: 800, color: 'var(--text0)' }}>{p.symbol}</td>
                    <td style={{ textAlign: 'left', padding: '6px 8px' }}>{p.origin ? <SrcTag s={p.origin} /> : <span style={{ fontSize: 9, color: 'var(--text3)' }}>direct/manual</span>}</td>
                    <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{p.shares != null ? (p.shares % 1 === 0 ? p.shares : p.shares.toFixed(2)) : '—'}</td>
                    <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>{p.avg_cost != null ? `$${p.avg_cost.toFixed(2)}` : '—'}</td>
                    <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>{p.current_price != null ? `$${p.current_price.toFixed(2)}` : '—'}</td>
                    <td style={{ padding: '6px 8px', fontWeight: 700, color: rcol(p.unrealized_pnl_pct) }}>{pct(p.unrealized_pnl_pct)}</td>
                    <td style={{ padding: '6px 8px', color: rcol(p.unrealized_pnl) }}>{usd(p.unrealized_pnl)}</td>
                    <td style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontSize: 10 }}>{p.held_since ? String(p.held_since).slice(0, 10) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Purchased → Sold lifecycle (real closed trades, auto-detected origin + journal) */}
      <section style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Purchased → Sold Lifecycle</div>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>{life.length} real closed positions · {life.filter(p => p.origin).length} with detected origin · {life.filter(p => p.journaled).length} journaled</span>
          <span style={{ flex: 1 }} />
          <label style={{ fontSize: 10, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={lifeOnlyOrigin} onChange={e => setLifeOnlyOrigin(e.target.checked)} /> only with detected origin
          </label>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Each real sold position auto-linked to the recommendation origin that introduced it (watchlist / proposal / screener / research / directive) → entry → exit P&amp;L · R · hold → its journal review. No manual tagging. Click a row to trace full lineage.</div>
        <div style={{ ...card, padding: 4, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'right' }}>
              <th style={{ textAlign: 'left', padding: '6px 8px' }}>Symbol</th>
              <th style={{ textAlign: 'left', padding: '6px 8px' }}>Origin</th>
              <th style={{ padding: '6px 8px' }}>Buy</th><th style={{ padding: '6px 8px' }}>Sell</th>
              <th style={{ padding: '6px 8px' }}>Return</th><th style={{ padding: '6px 8px' }}>P&amp;L</th>
              <th style={{ padding: '6px 8px' }}>R</th><th style={{ padding: '6px 8px' }}>Hold</th>
              <th style={{ textAlign: 'left', padding: '6px 8px' }}>Strategy</th>
              <th style={{ padding: '6px 8px' }}>Journal</th>
            </tr></thead>
            <tbody>
              {life.filter(p => (!lifeOnlyOrigin || p.origin) && matchOrigin(p.origin)).slice(0, 120).map((p, i) => (
                <tr key={i} onClick={() => lookup(p.symbol)} style={{ borderTop: '1px solid var(--border)', cursor: 'pointer', textAlign: 'right' }}>
                  <td style={{ textAlign: 'left', padding: '6px 8px', fontFamily: 'monospace', fontWeight: 800, color: 'var(--text0)' }}>{p.symbol}</td>
                  <td style={{ textAlign: 'left', padding: '6px 8px' }}>{p.origin ? <SrcTag s={p.origin} /> : <span style={{ fontSize: 9, color: 'var(--text3)' }}>direct/manual</span>}</td>
                  <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>{p.buy_price != null ? `$${p.buy_price.toFixed(2)}` : '—'}</td>
                  <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>{p.sell_price != null ? `$${p.sell_price.toFixed(2)}` : '—'}</td>
                  <td style={{ padding: '6px 8px', fontWeight: 700, color: rcol(p.pnl_pct) }}>{pct(p.pnl_pct)}</td>
                  <td style={{ padding: '6px 8px', color: rcol(p.pnl) }}>{usd(p.pnl)}</td>
                  <td style={{ padding: '6px 8px', color: rcol(p.r_multiple) }}>{p.r_multiple != null ? `${p.r_multiple.toFixed(2)}R` : '—'}</td>
                  <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{p.hold_days != null ? `${p.hold_days}d` : '—'}</td>
                  <td style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontSize: 10 }}>{p.strategy_id || '—'}</td>
                  <td style={{ padding: '6px 8px' }}>{p.journaled ? <span style={{ color: '#22c55e', fontWeight: 700 }} title={p.journal?.lesson || ''}>✓{p.journal?.realized_r != null ? ` ${p.journal.realized_r}R` : ''}</span> : <span style={{ color: 'var(--text3)' }}>—</span>}</td>
                </tr>
              ))}
              {life.length === 0 && <tr><td colSpan={10} style={{ textAlign: 'center', padding: 18, color: 'var(--text3)' }}>No closed positions yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {/* Multi-source tickers */}
      <section style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Multi-Source Tickers</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Tickers surfaced by more than one recommendation source — the earliest source that introduced it and the most recent. Click to trace.</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 8 }}>
          {multi.slice(0, 24).map((m, i) => (
            <div key={i} onClick={() => lookup(m.symbol)} style={{ ...card, padding: '8px 10px', cursor: 'pointer' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{m.symbol}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{m.n_sources} sources</span>
                <span style={{ flex: 1 }} />
                {m.executed && <span style={{ fontSize: 9, color: '#22c55e' }}>✓ exec</span>}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 9.5, color: 'var(--text3)' }}>
                <SrcTag s={m.earliest_source} /> <span>→</span> <SrcTag s={m.latest_source} />
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Rotation chains + edges (with measured alpha) */}
      {(rot.length > 0 || (d?.rotation_chains ?? []).length > 0) && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Rotation Chains &amp; Edges</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Detected from the executed trade history (close X → open Y, same account). Each edge's <b>alpha</b> = the to-leg return minus the from-leg return since the rotation — green means rotating beat holding the original.</div>
          {(d?.rotation_chains ?? []).length > 0 && (
            <div style={{ ...card, marginBottom: 10 }}>
              {(d?.rotation_chains ?? []).map((ch, i) => (
                <div key={i} style={{ fontSize: 12, fontFamily: 'monospace', padding: '3px 0', color: 'var(--text1)' }}>
                  {ch.map((s, j) => <span key={j}>{j > 0 && <span style={{ color: 'var(--text3)' }}> → </span>}<span style={{ color: j === 0 ? 'var(--text3)' : j === ch.length - 1 ? '#22c55e' : 'var(--text1)' }}>{s}</span></span>)}
                </div>
              ))}
            </div>
          )}
          <div style={{ ...card, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {[...rot].sort((a, b) => (b.rotation_alpha_pct ?? -999) - (a.rotation_alpha_pct ?? -999)).map((r, i) => (
              <span key={i} title={r.at} style={{ fontSize: 11, fontFamily: 'monospace', padding: '3px 8px', borderRadius: 4, background: 'var(--bg2)', border: `1px solid ${r.rotation_alpha_pct == null ? 'var(--border)' : r.rotation_alpha_pct >= 0 ? '#22c55e44' : '#ef444444'}` }}>
                {r.from} → <span style={{ color: 'var(--text1)' }}>{r.to}</span>
                {r.rotation_alpha_pct != null && <span style={{ color: rcol(r.rotation_alpha_pct), fontWeight: 700 }}> {pct(r.rotation_alpha_pct)}</span>}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Source Learning — Phase 3 feedback loop */}
      {(d?.source_quality ?? []).length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Source Learning <span style={{ fontSize: 10, fontWeight: 400, color: '#a855f7' }}>· feedback loop</span></div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>The engine learns each origin source's realized quality and assigns a ranking multiplier (0.50–1.50, 1.0 = neutral until 5+ trades). Sources with better outcomes get boosted in future ranking. Opt-in: <span style={{ fontFamily: 'monospace' }}>REC_SOURCE_WEIGHTING=1</span> applies it to proposal ranking; advisory by default.</div>
          <div style={{ ...card }}>
            {(d?.source_quality ?? []).map((s, i) => {
              const boost = (s.quality_multiplier ?? 1) > 1.02
              const demote = (s.quality_multiplier ?? 1) < 0.98
              const col = boost ? '#22c55e' : demote ? '#ef4444' : 'var(--text2)'
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderTop: i ? '1px solid var(--border)' : undefined }}>
                  <span style={{ width: 120 }}><SrcTag s={s.source} /></span>
                  <div style={{ flex: 1, position: 'relative', height: 16, background: 'var(--bg2)', borderRadius: 4 }}>
                    <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'var(--text3)' }} />
                    <div style={{ position: 'absolute', top: 2, bottom: 2, borderRadius: 3, background: `${col}55`,
                      left: (s.quality_multiplier ?? 1) >= 1 ? '50%' : `${50 - ((1 - (s.quality_multiplier ?? 1)) / 0.5) * 50}%`,
                      width: `${Math.abs((s.quality_multiplier ?? 1) - 1) / 0.5 * 50}%` }} />
                  </div>
                  <span style={{ width: 56, textAlign: 'right', fontWeight: 800, color: col }}>{(s.quality_multiplier ?? 1).toFixed(2)}×</span>
                  <span style={{ width: 150, fontSize: 9.5, color: 'var(--text3)', textAlign: 'right' }}>{s.basis}</span>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Rotation outcomes — Phase 2 */}
      {(d?.rotation_outcomes?.measured ?? 0) > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Rotation Outcomes</div>
          <div style={{ ...card, display: 'flex', gap: 24, fontSize: 12 }}>
            <span>measured: <b>{d!.rotation_outcomes!.measured}</b></span>
            <span>beat holding: <b style={{ color: '#22c55e' }}>{d!.rotation_outcomes!.rotations_that_beat_holding}</b></span>
            <span>avg alpha: <b style={{ color: rcol(d!.rotation_outcomes!.avg_alpha_pct) }}>{pct(d!.rotation_outcomes!.avg_alpha_pct)}</b></span>
          </div>
        </section>
      )}

      {/* Lifecycle Journal — Phase 2 immutable events */}
      {events.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Lifecycle Journal</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Immutable lineage events appended to the <span style={{ fontFamily: 'monospace' }}>lifecycle_events</span> spine as tickers transition (promoted → executed → rotated).</div>
          <div style={{ ...card, maxHeight: 320, overflow: 'auto', padding: 0 }}>
            {(() => {
              // Collapse identical (day · symbol · event · status · source) rows into one with ×N — the same
              // screener hit re-proposed every 30 min (or a scalp re-fired) would otherwise show dozens of
              // identical lines. The cooldown fix prevents new floods; this keeps the journal readable.
              const groups: any[] = []
              const idx: Record<string, number> = {}
              for (const e of events) {
                const src = e.payload?.discovery_source || e.payload?.account || e.status || ''
                const key = `${String(e.at).slice(0, 10)}|${e.symbol}|${e.event}|${src}`
                if (idx[key] == null) { idx[key] = groups.length; groups.push({ ...e, _src: src, _n: 1 }) }
                else groups[idx[key]]._n++
              }
              return groups.map((e, i) => {
                const ec = e.event === 'rec_executed' ? '#22c55e' : e.event === 'rec_rotated' ? '#ef4444' : '#f59e0b'
                return (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 12px', borderTop: i ? '1px solid var(--border)' : undefined, fontSize: 10.5 }}>
                    <span style={{ width: 78, color: 'var(--text3)', fontFamily: 'monospace' }}>{String(e.at).slice(0, 10)}</span>
                    <span style={{ width: 64, fontFamily: 'monospace', fontWeight: 700, color: 'var(--text0)' }}>{e.symbol}</span>
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: `${ec}1f`, color: ec, border: `1px solid ${ec}44` }}>{(e.event || '').replace('rec_', '').replace(/_/g, ' ')}</span>
                    <span style={{ color: 'var(--text3)' }}>{e._src}</span>
                    {e._n > 1 && <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: 'var(--text2)' }} title={`${e._n} identical events that day (deduped for readability)`}>×{e._n}</span>}
                    {e.payload?.pnl_pct != null && <span style={{ color: rcol(e.payload.pnl_pct) }}>{pct(e.payload.pnl_pct)}</span>}
                  </div>
                )
              })
            })()}
          </div>
        </section>
      )}

      {d?.generated_at && <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/rec-intel/summary · {d.generated_at} · read-only lineage</div>}
    </div>
  )
}
