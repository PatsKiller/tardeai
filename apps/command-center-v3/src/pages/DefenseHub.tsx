import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE, numStyle, heatRamp } from '../lib/watchTokens'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'

// Defense Desk v2 (WS-D2 rebuild): whole-market layer (state line, indices, styles,
// internals) + RRG-style rotation scatter (Sectors|Industries) + heat-celled sector
// spine + industry drill + 30d confirmed-transitions timeline. The would-have-fired
// fold is DEBOUNCED (raw flips demoted to a footnote). Advisory-only — this page
// places NOTHING. All colors come from watchTokens (zero raw hex).

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''
const STATE_COLOR: Record<string, string> = {
  LEADING: BB.green, WEAKENING: BB.amber, LAGGING: BB.red, IMPROVING: T.link,
}

const card: React.CSSProperties = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }

function Head({ title, corpus, rail }: { title: string; corpus?: string; rail?: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap', borderLeft: rail ? `3px solid ${rail}` : undefined, paddingLeft: rail ? 8 : 0 }}>
      <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2, textTransform: 'uppercase' }}>{title}</span>
      {corpus && <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· {corpus}</span>}
    </div>
  )
}

function pct(v: number | null | undefined, digits = 1): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(digits)}%`
}

/** Heat-colored numeric cell. scale = how much of the value maps to full ramp depth. */
function Heat({ v, scale = 1, suffix = '%' }: { v: number | null | undefined; scale?: number; suffix?: string }) {
  return (
    <span style={{ ...numStyle, textAlign: 'right', background: v != null ? heatRamp(v / scale) : 'transparent', color: BB.text0 ?? BB.text1, borderRadius: 2, padding: '1px 4px', fontWeight: 700 }}>
      {v != null ? `${v >= 0 ? '+' : ''}${v}${suffix}` : '—'}
    </span>
  )
}

// ── RRG-style rotation scatter ─────────────────────────────────────────────────
// x = trend level (RS20 / rel1m), y = trend direction (slope / rel1w). Quadrants
// match classify(): LEADING top-right · WEAKENING bottom-right · IMPROVING
// top-left · LAGGING bottom-left. Dot area ∝ book weight (min size for zero).
type Dot = { key: string; label: string; x: number; y: number; book: number; state: string | null; held?: string[]; watched?: string[] }

function RotationScatter({ dots, xLabel, yLabel, xMax, yMax, onPick }: {
  dots: Dot[]; xLabel: string; yLabel: string; xMax: number; yMax: number; onPick?: (key: string) => void
}) {
  const W = 520, H = 320, M = 26
  const sx = (v: number) => M + ((Math.max(-xMax, Math.min(xMax, v)) + xMax) / (2 * xMax)) * (W - 2 * M)
  const sy = (v: number) => H - M - ((Math.max(-yMax, Math.min(yMax, v)) + yMax) / (2 * yMax)) * (H - 2 * M)
  const quad = (x0: number, y0: number, w: number, h: number, color: string, name: string, tx: number, ty: number, anchor: string) => (
    <g key={name}>
      <rect x={x0} y={y0} width={w} height={h} fill={color} opacity={0.07} />
      <text x={tx} y={ty} fill={color} opacity={0.75} fontSize={9} fontWeight={800} textAnchor={anchor as any} style={{ textTransform: 'uppercase', letterSpacing: '.08em' }}>{name}</text>
    </g>
  )
  const cx = sx(0), cy = sy(0)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: 640, display: 'block' }}>
      {quad(cx, M, W - M - cx, cy - M, BB.green, 'leading', W - M - 4, M + 12, 'end')}
      {quad(cx, cy, W - M - cx, H - M - cy, BB.amber, 'weakening', W - M - 4, H - M - 6, 'end')}
      {quad(M, M, cx - M, cy - M, T.link, 'improving', M + 4, M + 12, 'start')}
      {quad(M, cy, cx - M, H - M - cy, BB.red, 'lagging', M + 4, H - M - 6, 'start')}
      <line x1={cx} y1={M} x2={cx} y2={H - M} stroke={BB.border} strokeWidth={1} />
      <line x1={M} y1={cy} x2={W - M} y2={cy} stroke={BB.border} strokeWidth={1} />
      <text x={W - M} y={cy - 5} fill={BB.text3} fontSize={8.5} textAnchor="end">{xLabel} →</text>
      <text x={cx + 5} y={M + 9} fill={BB.text3} fontSize={8.5}>{yLabel} ↑</text>
      {dots.map(d => {
        const r = Math.max(4, 3 + Math.sqrt(Math.max(0, d.book)) * 2.4)
        const c = STATE_COLOR[d.state || ''] || BB.text3
        return (
          <g key={d.key} onClick={() => onPick?.(d.key)} style={{ cursor: onPick ? 'pointer' : 'default' }}>
            <circle cx={sx(d.x)} cy={sy(d.y)} r={r} fill={c} opacity={0.85} stroke={BB.bg} strokeWidth={1}>
              <title>{`${d.label} — x ${d.x.toFixed(1)} · y ${d.y.toFixed(1)}${d.book ? ` · book ${d.book}%` : ''}${d.held?.length ? ` · holding ${d.held.join('/')}` : ''}${d.watched?.length ? ` · starred ${d.watched.join('/')}` : ''}`}</title>
            </circle>
            <text x={sx(d.x) + r + 3} y={sy(d.y) + 3} fill={BB.text2} fontSize={8.5} fontWeight={700}>{d.label}</text>
          </g>
        )
      })}
    </svg>
  )
}

export default function DefenseHub() {
  const [terminalUi] = useTerminalUi()
  const { data } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: industries } = useApi<any>('/api/v2/defense/industries', 300_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 300_000)
  const [whfOpen, setWhfOpen] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [scatterMode, setScatterMode] = useState<'sectors' | 'industries'>('sectors')
  const [drillSector, setDrillSector] = useState<string | null>(null)

  const rows: any[] = data?.momentum?.rows || []
  const market = data?.momentum?.market
  const transitions: any[] = data?.momentum?.transitions_today || []
  const whfConfirmed: any[] = data?.would_have_fired?.confirmed || []
  const whfRaw: any[] = data?.would_have_fired?.transitions || []
  const net = data?.net_exposure
  const genAt = (data?.momentum?.generated_at || '').slice(0, 16)
  const weakLag = rows.filter(r => r.state === 'WEAKENING' || r.state === 'LAGGING')
  const bookLine = weakLag.filter(r => (r.book_pct ?? 0) > 0)
    .map(r => `${r.book_pct}% ${r.sector.toLowerCase()} (${r.state})`).join(' · ')

  const ind: any[] = industries?.industries || []
  const indBySector = useMemo(() => {
    const m: Record<string, any[]> = {}
    ind.forEach(g => { (m[g.sector || 'Other'] ||= []).push(g) })
    Object.values(m).forEach(list => list.sort((a, b) => (b.rel1w ?? -99) - (a.rel1w ?? -99)))
    return m
  }, [ind])

  const scatterDots: Dot[] = useMemo(() => {
    if (scatterMode === 'sectors') {
      return rows.filter(r => r.rs20 != null && r.slope != null).map(r => ({
        key: r.etf, label: r.etf, x: r.rs20, y: r.slope, book: r.book_pct ?? 0, state: r.state,
      }))
    }
    // industries: the 144-dot cloud is unreadable — plot held/starred + rel1w extremes
    const ranked = ind.filter(g => g.rel1m != null && g.rel1w != null)
      .sort((a, b) => (b.rel1w ?? 0) - (a.rel1w ?? 0))
    const pickSet = new Set<string>([
      ...ranked.slice(0, 8).map(g => g.industry), ...ranked.slice(-8).map(g => g.industry),
      ...ind.filter(g => g.held?.length || g.watched?.length).map(g => g.industry),
    ])
    return ranked.filter(g => pickSet.has(g.industry)).map(g => ({
      key: g.industry, label: g.industry.length > 22 ? g.industry.slice(0, 20) + '…' : g.industry,
      x: g.rel1m, y: g.rel1w, book: g.held?.length ? 4 : 0, state: g.state, held: g.held, watched: g.watched,
    }))
  }, [scatterMode, rows, ind])

  // 30d confirmed transitions timeline: backfill ledger + today's live confirmations
  const timeline = useMemo(() => {
    const all = [
      ...whfConfirmed.map(t => ({ ...t, live: false })),
      ...transitions.map(t => ({ as_of: (data?.momentum?.generated_at || '').slice(0, 10), sector: t.sector, from: t.from, to: t.to, live: true })),
    ]
    const byDate: Record<string, any[]> = {}
    all.forEach(t => { (byDate[t.as_of] ||= []).push(t) })
    return Object.entries(byDate).sort((a, b) => a[0] < b[0] ? 1 : -1).slice(0, 12)
  }, [whfConfirmed, transitions, data])

  const drillList = drillSector ? (indBySector[drillSector] || []) : []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1480, margin: '0 auto' }}>
      <div>
        <div style={hubTitle()}>Defense Desk</div>
        <div style={hubSubtitle(terminalUi)}>
          whole market · sectors · industries · rotation — advisory only, nothing here places orders
        </div>
      </div>

      {/* Row 1 — Market layer (WS-A2): state line, indices, styles, internals */}
      <div style={{ ...card, borderLeft: `3px solid ${weakLag.length >= 3 ? BB.red : weakLag.length ? BB.amber : BB.green}` }}>
        <Head title="Market posture" corpus={`sector_momentum_state · nightly 17:25 · ${genAt}Z`} />
        {market?.state_line && (
          <div style={{ fontSize: TYPE.md ?? 13, fontWeight: 700, color: BB.text1, marginBottom: 8 }}>{market.state_line}</div>
        )}
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 8 }}>
          {(market?.indices || []).map((ix: any) => (
            <span key={ix.symbol} style={{ fontSize: TYPE.sm, color: BB.text2 }}>
              <b style={{ color: BB.text1 }}>{ix.symbol}</b>{' '}
              <span style={{ ...numStyle, color: (ix.short ?? 0) >= 0 ? BB.green : BB.red }}>{pct(ix.short)}</span>
              {ix.rs_mid != null && <span style={{ ...numStyle, color: BB.text3 }} title={`${ix.symbol} 20d return minus SPY 20d return`}> rs20 {pct(ix.rs_mid)}</span>}
            </span>
          ))}
          <span style={{ fontSize: TYPE.sm, color: BB.text2 }}>
            regime <b style={{ color: BB.amber }}>{regime?.regime_label?.replace(/_/g, ' ') ?? '—'}</b>
          </span>
          <span style={{ fontSize: TYPE.sm, color: BB.text2 }}>VIX <b style={{ ...numStyle }}>{tradeAi?.vix ?? '—'}</b></span>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 8 }}>
          {(market?.styles || []).map((st: any) => (
            <span key={st.key} title={`${st.pair}: 20d spread ${pct(st.s20)} · slope ${st.slope >= 0 ? '+' : ''}${st.slope}`}
              style={{ fontSize: TYPE.xs, fontWeight: 700, color: STATE_COLOR[st.state] || BB.text3, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '2px 8px' }}>
              {st.key.replace(/_/g, ' ')} <span style={{ ...numStyle }}>{pct(st.s20)}</span> {st.state?.toLowerCase() || ''}
            </span>
          ))}
          {market?.internals && (
            <span style={{ fontSize: TYPE.xs, color: BB.text3 }} title={market.internals.source}>
              NH/NL <b style={{ ...numStyle, color: BB.text2 }}>{market.internals.new_high}/{market.internals.new_low}</b> (top-15 capped)
              · unusual vol <b style={{ ...numStyle, color: BB.text2 }}>{market.internals.unusual_volume}</b>
            </span>
          )}
          {net && (
            <span style={{ fontSize: TYPE.xs, color: BB.text2 }}>
              net equity <b style={{ ...numStyle, color: BB.amber }}>{net.equity_pct}%</b>
              <span style={{ color: BB.text3 }}> ({net.cash_pct}% cash ≈ ${Math.round(net.cash_dollars / 1000)}K — already a hedge)</span>
            </span>
          )}
        </div>
        {bookLine && <div style={{ fontSize: TYPE.sm, color: BB.text2, marginBottom: 6 }}>your book: <b style={{ color: BB.amber }}>{bookLine}</b></div>}
        {transitions.length > 0 ? transitions.map((t, i) => (
          <div key={i} style={{ fontSize: TYPE.sm, color: t.severity === 'urgent' ? BB.red : BB.amber, padding: '2px 0' }}>{t.line}</div>
        )) : <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>no confirmed transitions today (alerts fire only on 2-close-confirmed state changes, ≤4/day)</div>}
      </div>

      {/* Row 2 — rotation scatter + sector spine */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(340px, 5fr) minmax(480px, 7fr)', gap: 12, alignItems: 'start' }}>
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <Head title="Rotation map" corpus={scatterMode === 'sectors' ? 'x = RS20 vs SPY · y = RS20 slope · dot ∝ your book' : 'x = rel 1m vs SPY · y = rel 1w · held/starred + extremes'} />
            <div style={{ display: 'flex', gap: 4 }}>
              {(['sectors', 'industries'] as const).map(m => (
                <button key={m} onClick={() => setScatterMode(m)} style={{ fontSize: 8.5, fontWeight: 800, textTransform: 'uppercase', color: scatterMode === m ? BB.text1 : BB.text3, background: scatterMode === m ? BB.border : 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '2px 8px', cursor: 'pointer' }}>{m}</button>
              ))}
            </div>
          </div>
          <RotationScatter
            dots={scatterDots}
            xLabel={scatterMode === 'sectors' ? 'RS20' : 'rel 1m'}
            yLabel={scatterMode === 'sectors' ? 'slope' : 'rel 1w'}
            xMax={scatterMode === 'sectors' ? 8 : 12}
            yMax={scatterMode === 'sectors' ? 4 : 15}
            onPick={key => {
              if (scatterMode === 'sectors') setExpanded(e => e === key ? null : key)
              else {
                const g = ind.find(x => x.industry === key)
                if (g?.sector) setDrillSector(g.sector)
              }
            }}
          />
        </div>

        <div style={card}>
          <Head title="Sector spine" corpus="click a row → detail + industry drill" />
          <div style={{ overflowX: 'auto' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '160px 88px 62px 62px 62px 56px 64px 46px 92px', gap: 6, fontSize: 8.5, color: BB.text3, textTransform: 'uppercase', fontWeight: 800, padding: '2px 4px', borderBottom: `1px solid ${BB.border}` }}>
              <span>Sector</span><span>State</span><span>RS 5d</span><span>RS 20d</span><span>Slope</span><span>Breadth</span><span>Hermes Δ</span><span>News−</span><span>Your book</span>
            </div>
            {rows.map((r: any) => {
              const c = STATE_COLOR[r.state] || BB.text3
              const open = expanded === r.etf
              return (
                <div key={r.etf}>
                  <div onClick={() => { setExpanded(open ? null : r.etf); setDrillSector(open ? null : r.sector) }} style={{ display: 'grid', gridTemplateColumns: '160px 88px 62px 62px 62px 56px 64px 46px 92px', gap: 6, fontSize: TYPE.xs, padding: '3px 4px', borderBottom: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${c}`, cursor: 'pointer', alignItems: 'center' }}>
                    <span style={{ color: BB.text1, fontWeight: 700 }}>{r.sector} <span style={{ ...numStyle, color: BB.text3 }}>{r.etf}</span></span>
                    <span style={{ fontSize: 9, fontWeight: 800, color: c }}>{r.state || r.note}</span>
                    <Heat v={r.rs5} scale={1.5} />
                    <Heat v={r.rs20} scale={2.5} />
                    <Heat v={r.slope} scale={1.5} suffix="" />
                    <span style={{ ...numStyle, textAlign: 'right', background: r.breadth_pct != null ? heatRamp((r.breadth_pct - 50) / 12) : 'transparent', color: BB.text0, borderRadius: 2, padding: '1px 4px', fontWeight: 700 }} title={`${r.breadth_n ?? 0} members above own 20DMA`}>{r.breadth_pct != null ? `${r.breadth_pct}%` : '—'}</span>
                    <Heat v={r.hermes_delta} scale={2} suffix="" />
                    <span style={{ ...numStyle, color: r.news_negatives ? BB.red : BB.text3, textAlign: 'right' }}>{r.news_negatives ?? 0}</span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{ flex: 1, height: 7, background: BB.borderHair, borderRadius: 1, overflow: 'hidden' }}>
                        <span style={{ display: 'block', height: '100%', width: `${Math.min(100, (r.book_pct ?? 0) * 4)}%`, background: (r.book_pct ?? 0) >= 15 ? BB.amber : BB.green }} />
                      </span>
                      <span style={{ ...numStyle, color: (r.book_pct ?? 0) >= 15 ? BB.amber : BB.text2, fontWeight: 700, minWidth: 34, textAlign: 'right' }}>{r.book_pct != null ? `${r.book_pct}%` : '—'}</span>
                    </span>
                  </div>
                  {open && (
                    <div style={{ padding: '6px 10px 8px 14px', fontSize: TYPE.xs, color: BB.text3, borderBottom: `1px solid ${BB.borderHair}`, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                      <span>RS60 <b style={{ ...numStyle, color: BB.text2 }}>{r.rs60 ?? '—'}%</b></span>
                      <span>breadth n=<b style={{ ...numStyle, color: BB.text2 }}>{r.breadth_n ?? 0}</b> above own 20DMA</span>
                      <span>book <b style={{ ...numStyle, color: BB.text2 }}>${((r.book_dollars ?? 0) / 1000).toFixed(0)}K</b></span>
                      {r.top_negative && <span>loudest negative: {String(r.top_negative).slice(0, 80)}</span>}
                      <a href={`${FQDN}/v3/sectors?sector=${encodeURIComponent(r.sector)}`} style={{ color: T.link, textDecoration: 'none', fontWeight: 700 }}>Sectors tab ↗</a>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Row 3 — Industry layer (WS-B2) */}
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap' }}>
          <Head title="Industries" corpus={`144 finviz groups vs SPY · ${(industries?.captured_at || '').slice(0, 16)}Z · ${industries?.capture_kind || ''} · states confirm on 2 closes`} />
          {industries?.counts && (
            <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>
              {(['LEADING', 'IMPROVING', 'WEAKENING', 'LAGGING'] as const).map(s => (
                <span key={s} style={{ marginLeft: 10 }}><b style={{ color: STATE_COLOR[s] }}>{industries.counts[s]}</b> {s.toLowerCase()}</span>
              ))}
            </span>
          )}
        </div>

        {/* top/bottom strips */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
          <span style={{ fontSize: 8.5, fontWeight: 800, color: BB.green, textTransform: 'uppercase', minWidth: 62 }}>Top 1w</span>
          {ind.filter(g => (industries?.top10 || []).includes(g.industry)).map(g => (
            <span key={g.industry} onClick={() => setDrillSector(g.sector)} title={`${g.industry} (${g.sector}) rel1w ${pct(g.rel1w)}`} style={{ fontSize: TYPE.xs, color: BB.text2, background: heatRamp((g.rel1w ?? 0) / 4), borderRadius: 2, padding: '1px 6px', cursor: 'pointer' }}>{g.industry} <b style={{ ...numStyle }}>{pct(g.rel1w)}</b></span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
          <span style={{ fontSize: 8.5, fontWeight: 800, color: BB.red, textTransform: 'uppercase', minWidth: 62 }}>Bottom 1w</span>
          {ind.filter(g => (industries?.bottom10 || []).includes(g.industry)).map(g => (
            <span key={g.industry} onClick={() => setDrillSector(g.sector)} title={`${g.industry} (${g.sector}) rel1w ${pct(g.rel1w)}`} style={{ fontSize: TYPE.xs, color: BB.text2, background: heatRamp((g.rel1w ?? 0) / 4), borderRadius: 2, padding: '1px 6px', cursor: 'pointer' }}>{g.industry} <b style={{ ...numStyle }}>{pct(g.rel1w)}</b></span>
          ))}
        </div>

        {/* sector drill */}
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
          {Object.keys(indBySector).sort().map(s => (
            <button key={s} onClick={() => setDrillSector(d => d === s ? null : s)} style={{ fontSize: 8.5, fontWeight: 700, color: drillSector === s ? BB.text1 : BB.text3, background: drillSector === s ? BB.border : 'transparent', border: `1px solid ${BB.borderHair}`, borderRadius: 2, padding: '2px 7px', cursor: 'pointer' }}>{s} ({indBySector[s].length})</button>
          ))}
        </div>
        {drillSector && (
          <div style={{ overflowX: 'auto', marginBottom: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '230px 88px 64px 64px 64px 64px 1fr', gap: 6, fontSize: 8.5, color: BB.text3, textTransform: 'uppercase', fontWeight: 800, padding: '2px 4px', borderBottom: `1px solid ${BB.border}` }}>
              <span>Industry ({drillSector})</span><span>State</span><span>Rel 1w</span><span>Rel 1m</span><span>Perf 1w</span><span>1d</span><span>Yours</span>
            </div>
            {drillList.map(g => (
              <div key={g.industry} style={{ display: 'grid', gridTemplateColumns: '230px 88px 64px 64px 64px 64px 1fr', gap: 6, fontSize: TYPE.xs, padding: '3px 4px', borderBottom: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${STATE_COLOR[g.state] || BB.text3}`, alignItems: 'baseline' }}>
                <span style={{ color: BB.text1, fontWeight: 700 }}>{g.industry} <span style={{ ...numStyle, color: BB.text3 }}>({g.stocks})</span></span>
                <span style={{ fontSize: 9, fontWeight: 800, color: STATE_COLOR[g.state] || BB.text3 }}>{g.state || '—'}</span>
                <Heat v={g.rel1w} scale={4} />
                <Heat v={g.rel1m} scale={4} />
                <Heat v={g.perf_week} scale={4} />
                <Heat v={g.change_1d} scale={1.5} />
                <span style={{ fontSize: TYPE.xs, color: BB.text2 }}>
                  {g.held?.length ? <span style={{ color: BB.amber, fontWeight: 700 }}>holding {g.held.join(' ')}</span> : null}
                  {g.watched?.length ? <span style={{ color: T.link, marginLeft: 6 }}>★ {g.watched.join(' ')}</span> : null}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* candidate pools — advisory feeds, never auto-trade */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
          <div>
            <div style={{ fontSize: 8.5, fontWeight: 800, color: BB.red, textTransform: 'uppercase', marginBottom: 3 }}>defensive-short pool · source_type=industry_momentum · advisory</div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {(industries?.candidates?.defensive_short_pool || []).map((c: any) => (
                <span key={c.industry} onClick={() => setDrillSector(c.sector)} style={{ fontSize: TYPE.xs, color: BB.text2, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${BB.red}`, borderRadius: 2, padding: '1px 6px', cursor: 'pointer' }}>{c.industry} <b style={{ ...numStyle, color: BB.red }}>{pct(c.rel1w)}</b></span>
              ))}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 8.5, fontWeight: 800, color: T.link, textTransform: 'uppercase', marginBottom: 3 }}>improving → watch rail · advisory</div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {(industries?.candidates?.watch_rail || []).map((c: any) => (
                <span key={c.industry} onClick={() => setDrillSector(c.sector)} style={{ fontSize: TYPE.xs, color: BB.text2, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${T.link}`, borderRadius: 2, padding: '1px 6px', cursor: 'pointer' }}>{c.industry} <b style={{ ...numStyle, color: BB.green }}>{pct(c.rel1w)}</b></span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Row 4 — 30d confirmed transitions timeline */}
      <div style={card}>
        <Head title="Confirmed transitions · 30 sessions" corpus="debounced (2-close) state changes — the same rule live alerts use" />
        {timeline.length === 0 && <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>none in the window</div>}
        {timeline.map(([date, items]) => (
          <div key={date} style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '3px 0', borderBottom: `1px solid ${BB.borderHair}`, flexWrap: 'wrap' }}>
            <span style={{ ...numStyle, color: BB.text3, minWidth: 78, fontSize: TYPE.xs }}>{date}</span>
            {items.map((t: any, i: number) => (
              <span key={i} style={{ fontSize: TYPE.xs, fontWeight: 700, color: STATE_COLOR[t.to] || BB.text2, border: `1px solid ${t.live ? (STATE_COLOR[t.to] || BB.border) : BB.borderHair}`, borderRadius: 2, padding: '1px 7px' }}>
                {t.sector} {t.from?.slice(0, 4)}→{t.to}{t.live ? ' · live' : ''}
              </span>
            ))}
          </div>
        ))}
        <div style={{ fontSize: 8.5, color: BB.amber, marginTop: 4 }}>
          Technology → LAGGING confirmed Jul 14 (flip Jul 13) — three sessions before the operator asked why the system was silent. Entries before engine go-live (Jul 17) are backfilled/hypothetical; thresholds tune here before they earn trust.
        </div>
      </div>

      {/* Credibility fold — would-have-fired (debounced primary, raw flips footnote) */}
      <div style={card}>
        <Head title="Would-have-fired (hypothetical)" corpus="state machine over price history — threshold-tuning evidence, NOT a backtest" rail={BB.amber} />
        <button onClick={() => setWhfOpen(o => !o)} style={{ fontSize: TYPE.xs, fontWeight: 700, color: BB.text3, background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '3px 9px', cursor: 'pointer' }}>
          {whfOpen ? '▾' : '▸'} {whfConfirmed.length} debounce-confirmed hypothetical transitions · last 30 sessions
        </button>
        {whfOpen && (
          <div style={{ marginTop: 6 }}>
            {whfConfirmed.slice().reverse().map((t: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 10, fontSize: TYPE.xs, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}`, alignItems: 'baseline' }}>
                <span style={{ ...numStyle, color: BB.text3, minWidth: 78 }}>{t.as_of}</span>
                <span style={{ color: BB.text1, minWidth: 150 }}>{t.sector}</span>
                <span style={{ fontWeight: 700, color: STATE_COLOR[t.to] || BB.text2 }}>{t.from}→{t.to}</span>
                <span style={{ ...numStyle, color: BB.text3 }}>rs20 {t.rs20}</span>
              </div>
            ))}
            <div style={{ fontSize: 8.5, color: BB.text3, marginTop: 4 }}>
              footnote: {whfRaw.length} raw un-debounced flips in the same window — the debounce filter absorbed {Math.max(0, whfRaw.length - whfConfirmed.length)} single-day flickers.
            </div>
          </div>
        )}
      </div>

      {/* Deferred engines — honest build status (E2 cut line) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}>
        <div style={card}>
          <Head title="Move-out advisories" corpus="WS-C · not built yet" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            Defensive-score join (sector state × position internals × Hermes divergence × catalyst clustering ×
            short-float trend) is below the v2 cut line — ships next Defense session, then runs 10 trading days
            SHADOW before Telegram. Rotation-alternatives "not_yet" root cause documented (verdict-clarity wait by design).
          </div>
        </div>
        <div style={card}>
          <Head title="Positioning intelligence" corpus="WS-B · verified viable, not built yet" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            Phase 0 verified: Schwab option chains READABLE through the existing fence; short_float_pct captured by
            Finviz enrichment. Chain snapshots + OI-delta inference + short-float chips (as-of dated) below the v2
            cut line. "Positioning inference", never "order flow".
          </div>
        </div>
        <div style={card}>
          <Head title="Hedge advisor" corpus="WS-D2 · capabilities matrix live" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            config/account_capabilities.json is LIVE: Taxable short-stock VERIFIED (margin enabled);
            IRAs = inverse ETFs + covered calls{data?.account_capabilities ? '' : ' (config missing!)'} ·
            options_level awaits operator fill — menus degrade to inverse-ETF + CC until then.
          </div>
        </div>
        <div style={card}>
          <Head title="Short-side desk" corpus="WS-D4/D5 · paper-first, not built yet" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            defensive_short paper strategy (≤$2K, ≤3 concurrent, buy-stop ladder) + taxable advisories
            (mandatory stop, max-loss, ≤2% cap, anti-squeeze filter) below the v2 cut line; the industry
            LAGGING pool above already feeds its candidate list.
          </div>
        </div>
      </div>
    </div>
  )
}
