import { fmt$ } from '../lib/format'
import ProAnalystPill from './ProAnalystPill'

const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'

const chip = (bg: string, fg: string, strong = false) => ({ fontSize: strong ? 10 : 9, fontWeight: strong ? 850 : 750, padding: strong ? '3px 8px' : '2px 7px', borderRadius: 5, background: bg, color: fg, whiteSpace: 'nowrap' as const, display: 'inline-block', border: `1px solid ${fg}44` })
const metric = { background: 'rgba(2,6,23,.38)', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9, padding: '8px 9px' } as const
const num = (v: any, d = 2) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d))
const pct = (v: any) => (v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`)
const PRI: Record<string, string> = { critical: RED, high: AMBER, medium: BLUE, low: GREEN }
const RSI_C = (b: string) => b === 'oversold' ? GREEN : b === 'overbought' ? RED : b === 'missing' ? MUTED : BLUE
const BASIS_C: Record<string, string> = { broker: GREEN, tax_grade: GREEN, verified: BLUE, entry: BLUE, owner_provided: PURPLE, unknown: RED }
const FRESH_C: Record<string, string> = { fresh: GREEN, aging: AMBER, stale: RED, none: MUTED }
const LANE_META: Record<string, { label: string; c: string }> = { local: { label: 'GEMMA', c: '#2dd4bf' }, grok: { label: 'GROK', c: AMBER }, chatgpt: { label: 'GPT', c: '#a3e635' }, claude: { label: 'CLAUDE', c: '#d97757' } }

function Metric({ label, value, color = TEXT0 }: any) {
  return <div style={metric}><div style={{ fontSize: 8.5, color: MUTED, textTransform: 'uppercase', fontWeight: 850, letterSpacing: '.05em' }}>{label}</div><div style={{ fontSize: 13, color, fontWeight: 900, marginTop: 3 }}>{value}</div></div>
}

export default function PositionDecisionCard({ p, paMap, expanded, onToggle, onDrill, onAction, llmCov, protectionRec, symCard }: any) {
  const t = p.technical || {}, sr = p.sector_relative || {}
  const priority = p.operator_priority || 'low'
  const border = PRI[priority] || BLUE
  const news: any[] = p.news ?? []
  const lanes: Record<string, any> = {}
  for (const c of (llmCov ?? [])) { const k = LANE_META[c.lane] ? c.lane : 'local'; if (!lanes[k] || c.last_at > lanes[k].last_at) lanes[k] = c }
  const paper = p.environment === 'paper' || String(p.account ?? '').toLowerCase().includes('paper')
  const pnlColor = (p.unrealized_pnl ?? 0) >= 0 ? GREEN : RED
  const basis = p.basis_reliable ? num(p.entry_price) : 'n/a'

  return <div style={{ background: 'linear-gradient(180deg, rgba(30,41,59,.72), rgba(15,23,42,.74))', border: '1px solid rgba(148,163,184,.20)', borderLeft: `5px solid ${border}`, borderRadius: 14, padding: 16, boxShadow: '0 10px 28px rgba(0,0,0,.18)' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 20, fontWeight: 950, color: TEXT0 }}>{p.symbol}</span>
          <ProAnalystPill symbol={p.symbol} map={paMap} compact />
          <span style={{ fontSize: 11, color: MUTED }}>{p.shares} sh · {p.hold_duration ?? '—'}</span>
        </div>
        {symCard?.description && <div style={{ fontSize: 11.5, color: TEXT2, marginTop: 5, lineHeight: 1.42 }}>{symCard.description}{symCard.vs_sector_week != null && <span style={{ marginLeft: 6, fontWeight: 850, color: symCard.vs_sector_week >= 0 ? GREEN : RED }}>{symCard.vs_sector_week >= 0 ? '+' : ''}{symCard.vs_sector_week}% vs sector</span>}</div>}
      </div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {p.watchlist_state === 'directive' && <span style={chip('rgba(168,85,247,.20)', PURPLE, true)}>★ directive</span>}
        {p.watchlist_state === 'watchlist' && <span style={chip('rgba(96,165,250,.16)', BLUE, true)}>watchlist</span>}
        <span title={`${p.broker}/${p.environment}`} style={chip(paper ? 'rgba(96,165,250,.18)' : 'rgba(255,167,38,.18)', paper ? BLUE : '#ffa726', true)}>{paper ? 'PAPER' : 'REAL'} · {String(p.account ?? '?').replace(/_/g, ' ').toUpperCase()}</span>
        <span style={chip(`${border}22`, border, true)}>{priority.toUpperCase()}</span>
        <span style={chip(p.protection_state === 'protected' ? 'rgba(34,197,94,.16)' : p.protection_state === 'partial' ? 'rgba(245,158,11,.16)' : 'rgba(239,68,68,.16)', p.protection_state === 'protected' ? GREEN : p.protection_state === 'partial' ? AMBER : RED, true)}>{p.protection_state}</span>
      </div>
    </div>

    <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 10, background: `${border}14`, border: `1px solid ${border}55` }}>
      <div style={{ fontSize: 14, fontWeight: 950, color: border }}>{p.operator_decision ?? 'No action — monitored'}</div>
      <div style={{ fontSize: 11, color: TEXT2, marginTop: 3, lineHeight: 1.45 }}>{p.decision_reason}</div>
      {p.primary_next_review && <div style={{ fontSize: 10, color: MUTED, marginTop: 4 }}>Next: {p.primary_next_review}</div>}
    </div>

    {(protectionRec || Object.keys(lanes).length > 0) && <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 10, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.28)' }}>
      {protectionRec && (() => {
        const price = Number(protectionRec.price) || null, stop = Number(protectionRec.stop_price) || null, dist = protectionRec.stop_distance_pct
        const off = protectionRec.trail_recommended ? Number(protectionRec.trail_offset) : null, isPct = protectionRec.trail_type === 'PERCENT'
        const trailDollar = off == null ? null : isPct ? (price ? price * off / 100 : null) : off
        const trailPct = off == null ? null : isPct ? off : (price ? off / price * 100 : null)
        const distColor = dist == null ? MUTED : dist < 0 ? RED : dist < 2 ? RED : dist < 5 ? AMBER : GREEN
        const unprotected = p.protection_state !== 'protected'
        const mf = !!(p as any).is_mutual_fund            // open-end fund: no exchange stop can be placed
        const income = (p as any).holding_family === 'income'  // held for yield — protective stop optional
        const lockBtn = { fontSize: 9.5, fontWeight: 800, padding: '4px 9px', borderRadius: 6, border: '1px dashed #64748b', background: 'rgba(100,116,139,.12)', color: MUTED, cursor: 'not-allowed', whiteSpace: 'nowrap' as const }
        const STAGE2C_TIP = 'Protective stops on real holdings (Stage 2c) — LOCKED until the canary write test passes Monday and you arm the protective-stop policy. Each order will require web + Telegram 2FA.'
        return <>
          <div title={`${protectionRec.rationale ?? ''}\nanalyzed ${String(protectionRec.at).slice(0, 10)} by ${protectionRec.model} · confidence ${protectionRec.confidence ?? '—'}`} style={{ display: 'flex', gap: 9, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <span style={{ fontSize: 12, fontWeight: 950, color: '#d8b4fe' }}>Protection advisory</span>
            {protectionRec.family && <span style={chip('rgba(96,165,250,.14)', BLUE)}>{protectionRec.family}</span>}
            {stop != null && <span style={{ fontSize: 11, fontWeight: 850, color: TEXT1 }}>{mf ? 'ref level' : 'stop'} <b style={{ color: '#d8b4fe' }}>${stop.toFixed(2)}</b></span>}
            {off != null ? <span style={{ fontSize: 11, fontWeight: 850, color: TEXT1 }}>trail <b style={{ color: BLUE }}>{trailDollar != null ? `$${trailDollar.toFixed(2)}` : '—'}</b>{trailPct != null && <span style={{ color: MUTED, fontWeight: 500 }}> ({trailPct.toFixed(1)}%)</span>}</span> : <span style={{ fontSize: 10, color: MUTED }}>no trail yet</span>}
            {dist != null && <span style={{ fontSize: 10, fontWeight: 900, color: distColor }}>{dist < 0 ? 'price BELOW stop' : `price ${dist.toFixed(1)}% above stop`}</span>}
          </div>
          {/* concrete advised action (replaces the vague "review protection") + Stage-2c-locked order buttons.
              Two axes the buttons make explicit: fixed-vs-trailing trigger, and market-vs-limit fill. */}
          {stop != null && unprotected && mf && (
            // Open-end mutual fund: an exchange stop order cannot be placed (transacts at end-of-day NAV).
            // Show the level as REFERENCE only and steer to trim/rebalance — no order buttons.
            <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: 'rgba(100,116,139,.12)', border: '1px solid rgba(100,116,139,.30)' }}>
              <span style={{ fontSize: 10.5, fontWeight: 900, color: MUTED }}>▸ Open-end fund — no exchange stop can be placed (trades at end-of-day NAV). Protect via tax-aware <b style={{ color: TEXT1 }}>trim / rebalance</b>; ${stop.toFixed(2)} is a reference level only.</span>
            </div>
          )}
          {stop != null && unprotected && !mf && (() => {
            const trailReady = off != null && trailPct != null
            const stopTip = `Queue a FIXED sell stop (stop-market) GTC at $${stop.toFixed(2)}. If the price falls to $${stop.toFixed(2)} a MARKET sell fires — it ALWAYS fills, but the fill can slip below $${stop.toFixed(2)} in a fast drop. The trigger does NOT move.\n\n${STAGE2C_TIP}`
            const limitTip = `Queue a FIXED sell stop-limit GTC triggering at $${stop.toFixed(2)}. If the price hits $${stop.toFixed(2)} a LIMIT sell (~$${stop.toFixed(2)}) fires — it avoids a bad fill, but may NOT fill if the price gaps straight through, leaving you unprotected on the way down. The trigger does NOT move.\n\n${STAGE2C_TIP}`
            const trailTip = trailReady ? `Queue a native TRAILING sell stop GTC, trailing ${trailPct.toFixed(0)}%${trailDollar != null ? ` (≈$${trailDollar.toFixed(2)})` : ''}. The stop starts near $${stop.toFixed(2)} and RATCHETS UP as the price rises (never down), locking in profit; if the price then falls ${trailPct.toFixed(0)}% from its high a MARKET sell fires. This is the order the advisory recommends.\n\n${STAGE2C_TIP}` : ''
            const modifyTip = `Modify an ACTIVE stop — change the stop price, the trail %, or switch order type — once a protective order is already working at the broker.\n\n${STAGE2C_TIP}`
            const recBtn = { ...lockBtn, border: `1px dashed ${AMBER}`, background: 'rgba(245,158,11,.14)', color: AMBER }
            // Income holdings are held for yield — frame the level as OPTIONAL, not "ADVISED".
            const headColor = income ? BLUE : AMBER
            const orderTxt = trailReady ? `SELL TRAILING STOP, trail ${trailPct.toFixed(0)}% (starts ~$${stop.toFixed(2)})` : `SELL STOP $${stop.toFixed(2)}`
            const head = income ? `▸ OPTIONAL stop (income hold): ${orderTxt} GTC` : `▸ ADVISED: ${orderTxt} GTC`
            return <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: income ? 'rgba(96,165,250,.10)' : 'rgba(245,158,11,.10)', border: `1px solid ${income ? 'rgba(96,165,250,.32)' : 'rgba(245,158,11,.32)'}`, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10.5, fontWeight: 950, color: headColor }}>{head}</span>
              <span style={{ flex: 1 }} />
              <button disabled title={stopTip} style={lockBtn}>🔒 Queue stop (fixed)</button>
              <button disabled title={limitTip} style={lockBtn}>🔒 Queue stop-limit (fixed)</button>
              {trailReady && <button disabled title={trailTip} style={recBtn}>🔒 Queue trailing stop ★</button>}
              <button disabled title={modifyTip} style={lockBtn}>🔒 Modify</button>
            </div>
          })()}
        </>
      })()}
      {protectionRec?.rationale && <div style={{ fontSize: 10.5, color: TEXT2, marginTop: 5, lineHeight: 1.45 }}>{protectionRec.rationale}</div>}
      <div style={{ display: 'flex', gap: 5, marginTop: 6, alignItems: 'center', flexWrap: 'wrap' }}><span style={{ fontSize: 9, color: MUTED }}>reviewed by:</span>{Object.keys(lanes).length === 0 && <span style={{ fontSize: 9, color: MUTED }}>no LLM review in 30d</span>}{Object.entries(lanes).map(([lane, c]: any) => { const m = LANE_META[lane]; return <span key={lane} title={`${c.model} · analyzed ${String(c.last_at).slice(0, 10)} · ${c.n} review${c.n > 1 ? 's' : ''}`} style={{ fontSize: 8.5, fontWeight: 900, padding: '2px 6px', borderRadius: 4, background: m.c + '22', color: m.c, border: `1px solid ${m.c}55` }}>{m.label}</span> })}</div>
    </div>}

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(95px,1fr))', gap: 8, marginTop: 10 }}>
      <Metric label="P&L" value={p.unrealized_pnl != null ? fmt$(p.unrealized_pnl) : fmt$(p.market_value ?? 0)} color={p.unrealized_pnl != null ? pnlColor : TEXT0} />
      <Metric label="P&L %" value={pct(p.unrealized_pnl_pct)} color={(p.unrealized_pnl_pct ?? 0) >= 0 ? GREEN : RED} />
      <Metric label="Today" value={pct(p.today_move_pct)} color={(p.today_move_pct ?? 0) >= 0 ? GREEN : RED} />
      <Metric label="Market Value" value={fmt$(p.market_value ?? 0, 0)} color={TEXT0} />
      <Metric label="Basis" value={basis} color={BASIS_C[p.basis_quality] || TEXT2} />
      <Metric label="Now" value={num(p.current_price)} color={TEXT0} />
      <Metric label="Stop" value={p.stop_price != null ? num(p.stop_price) : '—'} color={p.stop_price != null ? RED : MUTED} />
      <Metric label="R multiple" value={p.r_multiple != null ? `${num(p.r_multiple, 1)}R` : '—'} color={p.r_multiple != null && p.r_multiple >= 1 ? GREEN : AMBER} />
    </div>

    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 10 }}>
      <span style={chip('rgba(15,23,42,.55)', TEXT1)}>{p.strategy ?? 'unclassified'}</span>
      <span style={chip('rgba(15,23,42,.55)', RSI_C(t.rsi_bucket))}>RSI {t.rsi != null ? num(t.rsi, 0) : '—'} {t.rsi_bucket}</span>
      <span style={chip('rgba(15,23,42,.55)', t.trend_label === 'bullish' ? GREEN : t.trend_label === 'bearish' ? RED : TEXT2)}>{t.trend_label}</span>
      {sr.sector && <span style={chip('rgba(15,23,42,.55)', (sr.vs_sector_5d ?? 0) > 1 ? GREEN : (sr.vs_sector_5d ?? 0) < -1 ? RED : TEXT2)}>{sr.sector}{sr.sector_etf ? ` (${sr.sector_etf})` : ''}</span>}
      <span style={chip('rgba(15,23,42,.55)', FRESH_C[p.data_freshness])}>data {p.data_freshness}</span>
      <span style={chip('rgba(15,23,42,.55)', FRESH_C[p.news_freshness])}>news {p.news_freshness}{p.latest_news_age_hours != null ? ` ${Math.round(p.latest_news_age_hours)}h` : ''}</span>
      {(p.risk_flags ?? []).map((r: string) => <span key={r} style={chip('rgba(239,68,68,.14)', RED)}>{r.replace(/_/g, ' ')}</span>)}
      {(p.opportunity_flags ?? []).map((o: string) => <span key={o} style={chip('rgba(34,197,94,.14)', GREEN)}>{o.replace(/_/g, ' ')}</span>)}
    </div>

    {p.analyst && (p.analyst.rating || p.analyst.target_mean != null) && <div style={{ fontSize: 10.5, color: TEXT2, marginTop: 8, lineHeight: 1.45 }}><b style={{ color: TEXT1 }}>Analysts:</b> {p.analyst.rating ? `${String(p.analyst.rating).toUpperCase()}${p.analyst.rating_mean != null ? ` (${Number(p.analyst.rating_mean).toFixed(1)})` : ''}` : 'no consensus'}{p.analyst.opinions != null && ` · ${p.analyst.opinions} opinions`}{p.analyst.target_mean != null && ` · target $${num(p.analyst.target_mean, 2)}`}{p.analyst.target_upside_pct != null && <span style={{ color: p.analyst.target_upside_pct > 0 ? GREEN : RED, fontWeight: 850 }}> ({p.analyst.target_upside_pct > 0 ? '+' : ''}{num(p.analyst.target_upside_pct, 1)}% to target)</span>}</div>}
    {p.strategy_rationale && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 7, fontStyle: 'italic', lineHeight: 1.45 }}>Why <b style={{ color: TEXT2 }}>{p.strategy}</b>: {p.strategy_rationale}</div>}

    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 11, alignItems: 'center' }}>{(p.recommended_manual_actions ?? []).slice(0, 4).map((a: string) => <button key={a} onClick={() => onAction?.(a, p)} title="Operator review action only" style={{ fontSize: 10, padding: '4px 10px', borderRadius: 6, border: '1px solid rgba(148,163,184,.25)', background: 'rgba(15,23,42,.55)', color: TEXT2, cursor: 'pointer' }}>{a}</button>)}<span onClick={onToggle} style={{ fontSize: 10, color: MUTED, cursor: 'pointer', textDecoration: 'underline', marginLeft: 'auto' }}>{expanded ? 'less' : 'more'}</span><span onClick={() => onDrill({ title: `${p.symbol} — ${p.account}`, subtitle: `${p.strategy ?? ''} · ${p.broker}/${p.environment}`, endpoint: '/api/v2/open-trades/intelligence', rows: [p], subjectType: 'position', subjectKey: p.symbol })} style={{ fontSize: 10, color: BLUE, cursor: 'pointer', textDecoration: 'underline', fontWeight: 800 }}>drill</span></div>

    {expanded && <div style={{ marginTop: 10, borderTop: '1px solid rgba(148,163,184,.18)', paddingTop: 10 }}><div style={{ fontSize: 11, fontWeight: 900, color: TEXT1, marginBottom: 6 }}>News & catalysts</div>{news.length === 0 && <div style={{ fontSize: 10.5, color: MUTED }}>No recent research surfaced.</div>}{news.map((n: any, i: number) => { const stale = (n.age_hours ?? 0) > 48; return <div key={i} style={{ fontSize: 11, marginBottom: 7, opacity: stale ? 0.7 : 1, lineHeight: 1.45 }}><div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}><span style={chip('rgba(15,23,42,.55)', TEXT2)}>{n.source}</span>{n.age_hours != null && <span style={{ fontSize: 9.5, color: stale ? AMBER : MUTED }}>{Math.round(n.age_hours)}h{stale ? ' stale' : ''}</span>}</div>{n.url ? <a href={n.url} target="_blank" rel="noopener noreferrer" style={{ color: '#bfdbfe', textDecoration: 'none', display: 'block', marginTop: 3, fontWeight: 650 }}>{n.title || ''}</a> : <div style={{ color: TEXT2, marginTop: 3 }}>{n.title || ''}</div>}{n.why_it_matters && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 3 }}><b style={{ color: TEXT2 }}>Why it matters:</b> {n.why_it_matters}</div>}</div> })}<div style={{ fontSize: 10, color: MUTED, marginTop: 6 }}>SMA50 {t.sma50_pct != null ? pct(t.sma50_pct) : '—'} · SMA200 {t.sma200_pct != null ? pct(t.sma200_pct) : '—'} · RVOL {t.rvol ?? '—'}{sr.sector ? ` · ${sr.sector} ${sr.label}` : ''}{p.last_hermes_review_at ? ` · Hermes ${String(p.last_hermes_review_at).slice(0, 10)}` : ''}</div></div>}
  </div>
}
