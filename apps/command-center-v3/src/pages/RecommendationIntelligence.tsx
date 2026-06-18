import { useEffect, useState } from 'react'

type SrcPerf = { source?: string; closed_trades?: number; wins?: number; win_rate_pct?: number; avg_return_pct?: number; total_pnl?: number; avg_hold_days?: number }
type StratPerf = { strategy?: string; resolved?: number; wins?: number; win_rate_pct?: number; avg_return_pct?: number }
type BySource = { source?: string; tickers?: number; executed?: number }
type MultiSrc = { symbol?: string; n_sources?: number; earliest_source?: string; latest_source?: string; first_seen?: string; last_seen?: string; executed?: boolean }
type RotLink = { from?: string; to?: string; executed?: boolean; at?: string; via?: string }
type Summary = {
  ok?: boolean; error?: string; total_tickers?: number; multi_source_count?: number; executed_attributions?: number
  by_source?: BySource[]; performance_by_source?: SrcPerf[]; performance_by_strategy?: StratPerf[]
  multi_source_examples?: MultiSrc[]; rotation_links?: RotLink[]; rotation_link_count?: number; generated_at?: string
}
type Lineage = {
  ok?: boolean; symbol?: string; found?: boolean; source_count?: number
  earliest_source?: string; earliest_at?: string; latest_source?: string; latest_at?: string; executed?: boolean
  sources?: any[]; rotation_links?: RotLink[]; error?: string
}

const ACCENT = '#60a5fa'
const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const SRC_COLOR: Record<string, string> = {
  watchlist: '#60a5fa', scan: '#22c55e', proposal: '#f59e0b', execution: '#a855f7',
  holding: '#a855f7', directive: '#ec4899', hermes_research: '#14b8a6', cio: '#eab308', rotation: '#ef4444',
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

  async function load() {
    setWarn('')
    try {
      const r = await fetch('/api/v2/rec-intel/summary')
      const j = await r.json()
      const inner = j?.data ?? j
      if (inner?.ok === false) setWarn(inner.error || 'unavailable')
      setD(inner)
    } catch (e) { setWarn(e instanceof Error ? e.message : String(e)) }
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
  useEffect(() => { load() }, [])

  const perf = d?.performance_by_source ?? []
  const strat = d?.performance_by_strategy ?? []
  const bySrc = d?.by_source ?? []
  const multi = d?.multi_source_examples ?? []
  const rot = d?.rotation_links ?? []

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
                {['Source', 'Trades', 'Win Rate', 'Avg Return', 'Total P&L', 'Avg Hold'].map(h => <th key={h} style={{ textAlign: h === 'Source' ? 'left' : 'right', padding: '8px 12px' }}>{h}</th>)}
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

      {/* Rotation chains */}
      {rot.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Rotation Links</div>
          <div style={{ ...card, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {rot.map((r, i) => (
              <span key={i} style={{ fontSize: 11, fontFamily: 'monospace', padding: '3px 8px', borderRadius: 4, background: 'var(--bg2)', border: '1px solid var(--border)' }}>
                {r.from} → <span style={{ color: '#22c55e' }}>{r.to}</span>{r.executed && <span style={{ color: '#22c55e' }}> ✓</span>}
              </span>
            ))}
          </div>
        </section>
      )}

      {d?.generated_at && <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/rec-intel/summary · {d.generated_at} · read-only lineage</div>}
    </div>
  )
}
