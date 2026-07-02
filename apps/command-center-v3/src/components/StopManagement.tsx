import { useEffect, useMemo, useState } from 'react'
import HoldingProtectionActions from './HoldingProtectionActions'
import { mergeLiveStop } from '../lib/stopReviewTooltip'
import { EvidenceBlock } from './EvidenceBlock'

// Portfolio → Stop Management. Aggregates broker-actual + advisor-planned stops with Yellow/Amber/Red alerts,
// plus an Audit sub-tab (2FA stop requests + operator confirmations). Read-only view; live adjustments route
// through the holding's existing gated 2FA panel (Schwab) or manual ticket (Fidelity) via onFocusHolding.
// See docs/MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md.

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', RED = '#ef4444', BLUE = '#60a5fa', PURPLE = '#a855f7'
const unwrap = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j
const LEVEL_COLOR: Record<string, string> = { red: RED, amber: AMBER, yellow: '#eab308' }
const SRC_LABEL: Record<string, string> = { broker: 'broker live', confirmed: 'confirmed', broker_snapshot: 'broker (last read)', monitored: 'monitored', planned: 'planned', none: '—' }
const fmt$ = (n: any) => n == null ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
const fmtStop = (n: any) => n == null ? '—' : `$${Number(n).toFixed(2)}`
const fmtTime = (s: any) => { if (!s) return '—'; const d = new Date(s); return isNaN(+d) ? String(s).slice(0, 16) : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }

interface Props { onFocusHolding?: (symbol: string, account: string) => void }

type Row = {
  symbol: string; account: string; broker: string; route: string; stop_type: string; stop_source: string
  current_price: number; qty: number; broker_stop: number | null; planned_stop: number | null; stop: number
  divergence: string | null; distance_pct: number | null; distance_atr: number | null; distance_r: number | null
  dollars_at_risk: number; unrealized_dollars: number | null; has_active_stop: boolean
  is_trailing: boolean; trailing_should_be_active: boolean; heat_contribution_pct: number | null
  trail_pct: number | null; trailing_trigger: number | null
  trail_recommended: boolean; rec_source: string | null; rec_model: string | null; rec_rationale: string | null
  alert_level: 'red' | 'amber' | 'yellow' | null; alert_reasons: string[]
  direction?: 'long' | 'short'; narrative?: string | null; next_action?: string | null; projection?: string | null
  rec_evidence?: unknown[]; rec_data_i_doubt?: string | null
  stop_curation?: { grade?: string; recommendation?: string; rr_assessment?: string; evidence?: unknown[]; data_i_doubt?: string | null; summary?: string } | null
  holdings_llm_health?: string | null; holdings_llm_evidence?: unknown[]; holdings_llm_data_i_doubt?: string | null
  consensus_target_mean?: number | null; consensus_target_high?: number | null; consensus_target_low?: number | null
  consensus_analysts?: number | null; consensus_stale?: boolean
  price_vs_consensus_pct?: number | null; price_vs_consensus_dollars?: number | null; price_above_consensus?: boolean
  stop_above_consensus?: boolean; consensus_gap_pct?: number | null; stop_vs_consensus_pct?: number | null
  regime?: string | null; regime_label?: string | null; regime_short?: string | null; regime_confidence?: number | null
  regime_at_entry?: string | null; regime_shift_detected?: boolean; regime_shift_direction?: string | null
  regime_explanation?: string | null; trail_tighten_atr_mult?: number | null
  policy_suggestions?: string[]; stoplight_thresholds_used?: { regime?: string; yellow_r?: number; amber_r?: number; red_r?: number } | null
}

const REGIME_COLOR: Record<string, string> = {
  strong_trending_bull: GREEN, strong_trending_bear: RED, trending: BLUE,
  ranging: MUTED, high_volatility: AMBER, regime_shift: PURPLE,
}

function RegimeBadge({ r }: { r: Row }) {
  if (!r.regime_short && !r.regime_label) return <span style={{ color: MUTED, fontSize: 10 }}>—</span>
  const c = REGIME_COLOR[r.regime || ''] || MUTED
  return (
    <div title={[r.regime_label, r.regime_explanation, r.regime_shift_direction].filter(Boolean).join(' · ')}>
      <div style={{
        display: 'inline-block', fontSize: 10, fontWeight: 900, color: c,
        background: `${c}18`, border: `1px solid ${c}55`, borderRadius: 5, padding: '2px 6px',
      }}>
        {r.regime_short || r.regime}
        {r.regime_confidence != null ? ` ${Math.round(r.regime_confidence)}%` : ''}
      </div>
      {r.regime_shift_detected && (
        <div style={{ fontSize: 9.5, color: PURPLE, fontWeight: 800, marginTop: 3 }}>⇄ {r.regime_shift_direction || 'shift'}</div>
      )}
      {r.regime_at_entry && r.regime_at_entry !== r.regime && !r.regime_shift_detected && (
        <div style={{ fontSize: 9, color: MUTED, marginTop: 2 }}>entry: {r.regime_at_entry}</div>
      )}
    </div>
  )
}

const effectiveConsensusStop = (r: Row): number | null =>
  r.broker_stop ?? r.trailing_trigger ?? r.planned_stop ?? null

const pctVsMean = (value: number | null | undefined, mean: number | null | undefined): number | null => {
  if (value == null || mean == null || mean <= 0) return null
  return Math.round(10000 * (Number(value) - mean) / mean) / 100
}

/** Signed %: stop vs Street mean (+ above, − below). API field with client-side fallback. */
const stopDeltaPct = (r: Row): number | null => {
  const api = r.stop_vs_consensus_pct
  if (api != null && Number.isFinite(Number(api))) return Number(api)
  return pctVsMean(effectiveConsensusStop(r), r.consensus_target_mean)
}

/** Signed %: current price vs Street mean — primary operator signal. */
const priceDeltaPct = (r: Row): number | null => {
  const api = r.price_vs_consensus_pct
  if (api != null && Number.isFinite(Number(api))) return Number(api)
  return pctVsMean(r.current_price, r.consensus_target_mean)
}

const fmtConsensusDelta = (pct: number | null | undefined, prefix = '') => {
  if (pct == null || !Number.isFinite(Number(pct))) return null
  const n = Math.abs(Number(pct))
  const dir = pct > 0 ? `+${n.toFixed(1)}% above` : `${n.toFixed(1)}% below`
  return prefix ? `${prefix} ${dir}` : dir
}

/** Long: price above Street = extended (red); below = room to target (green). */
const priceVsStreetColor = (delta: number | null, priceAbove?: boolean) =>
  priceAbove || (delta != null && delta > 0.5) ? RED : GREEN

/** Stop above Street mean = red; under = green. */
const stopVsStreetColor = (delta: number | null, stopAbove?: boolean) =>
  stopAbove || (delta != null && delta > 0) ? RED : GREEN

function DeltaBadge({ label, pct, color }: { label: string; pct: number | null; color: string }) {
  const text = fmtConsensusDelta(pct)
  if (!text) return null
  return (
    <div style={{
      display: 'inline-block', marginTop: 3, fontSize: 10, fontWeight: 900, lineHeight: 1.35,
      color, background: `${color}18`, border: `1px solid ${color}66`, borderRadius: 5, padding: '2px 6px',
    }}>
      <span style={{ color: MUTED, fontWeight: 700 }}>{label}</span> {text}
    </div>
  )
}

function StreetGauge({ price, low, high, mean }: { price: number; low?: number | null; high?: number | null; mean: number }) {
  const lo = low ?? mean * 0.85
  const hi = high ?? mean * 1.15
  if (hi <= lo) return null
  const pct = Math.max(0, Math.min(100, 100 * (price - lo) / (hi - lo)))
  const meanPct = Math.max(0, Math.min(100, 100 * (mean - lo) / (hi - lo)))
  return (
    <div style={{ marginTop: 4, width: 88 }} title={`Price ${fmtStop(price)} on Street range ${fmtStop(lo)}–${fmtStop(hi)}`}>
      <div style={{ height: 5, borderRadius: 3, background: 'rgba(148,163,184,.25)', position: 'relative' }}>
        <div style={{ position: 'absolute', left: `${meanPct}%`, top: -2, width: 2, height: 9, background: MUTED, borderRadius: 1 }} title="Street mean" />
        <div style={{
          position: 'absolute', left: `${pct}%`, top: -3, width: 8, height: 8, marginLeft: -4,
          borderRadius: '50%', background: price > mean ? RED : GREEN, border: '1px solid rgba(15,23,42,.8)',
        }} />
      </div>
    </div>
  )
}
type NextAction = { symbol: string; account: string; alert_level: Row['alert_level']; action: string | null; projection: string | null; dollars_at_risk: number | null }

function Pill({ level, thresholds }: { level: string | null; thresholds?: Row['stoplight_thresholds_used'] }) {
  if (!level) return <span style={{ fontSize: 11, color: GREEN }}>● ok</span>
  const c = LEVEL_COLOR[level] || MUTED
  const tip = thresholds?.regime
    ? `${level} · regime ${thresholds.regime} (Y≤${thresholds.yellow_r}R A≤${thresholds.amber_r}R R≤${thresholds.red_r}R)`
    : level
  return (
    <span title={tip} style={{ fontSize: 11, fontWeight: 800, color: c, background: `${c}1e`, border: `1px solid ${c}`, borderRadius: 999, padding: '2px 8px', textTransform: 'uppercase' }}>
      {level}
    </span>
  )
}

function Card({ label, value, color = TEXT0, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{ flex: '1 1 150px', padding: '11px 13px', borderRadius: 9, background: 'var(--bg2, rgba(15,23,42,.6))', border: '1px solid rgba(148,163,184,.2)' }}>
      <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 900, color }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

const QUICK = ['All', 'Needs Attention', 'Regime Shift', 'Has Street', 'Price > Street', 'Over Consensus', 'No Stop Placed', 'Has Active Stop', 'Trailing Not Active', 'High Heat'] as const

export default function StopManagement({ onFocusHolding }: Props) {
  const [sub, setSub] = useState<'Monitor' | 'Audit'>('Monitor')
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [quick, setQuick] = useState<typeof QUICK[number]>('All')
  const [acct, setAcct] = useState('All')
  const [level, setLevel] = useState('All')
  const [adjust, setAdjust] = useState<Row | null>(null)
  const [autoStage, setAutoStage] = useState(false)
  // One-click apply: the 🔒 buttons open the modal AND auto-stage the advised stop straight to 2FA;
  // "Adjust stop" opens in manual mode (no auto-stage).
  const openAdjust = (r: Row, auto: boolean) => { setAutoStage(auto); setAdjust(r) }

  const load = () => {
    setLoading(true)
    fetch('/api/v2/stops/management').then(x => x.json()).then(j => setData(unwrap(j))).catch(() => setData(null)).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const rows: Row[] = data?.rows ?? []
  const summary = data?.summary ?? {}
  const accounts = useMemo(() => ['All', ...Array.from(new Set(rows.map(r => r.account)))], [rows])

  const filtered = rows.filter(r => {
    if (acct !== 'All' && r.account !== acct) return false
    if (level !== 'All' && r.alert_level !== level) return false
    if (quick === 'Needs Attention' && !(r.alert_level === 'amber' || r.alert_level === 'red')) return false
    if (quick === 'Regime Shift' && !r.regime_shift_detected) return false
    if (quick === 'Has Street' && r.consensus_target_mean == null) return false
    if (quick === 'Price > Street' && !(r.price_above_consensus || (priceDeltaPct(r) ?? 0) > 0.5)) return false
    if (quick === 'Over Consensus' && !r.stop_above_consensus) return false
    if (quick === 'No Stop Placed' && r.has_active_stop) return false
    if (quick === 'Has Active Stop' && !r.has_active_stop) return false
    if (quick === 'Trailing Not Active' && !r.trailing_should_be_active) return false
    if (quick === 'High Heat' && !((r.heat_contribution_pct ?? 0) >= 1.5)) return false
    return true
  })

  return (
    <div style={{ padding: '4px 2px' }}>
      {/* sub-tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        {(['Monitor', 'Audit'] as const).map(t => (
          <button key={t} onClick={() => setSub(t)} style={{ fontSize: 13, fontWeight: 800, padding: '5px 14px', borderRadius: 7, cursor: 'pointer',
            border: `1px solid ${sub === t ? BLUE : 'rgba(148,163,184,.3)'}`, background: sub === t ? `${BLUE}18` : 'transparent', color: sub === t ? BLUE : MUTED }}>{t}</button>
        ))}
      </div>

      {sub === 'Audit' ? <AuditView /> : (
        <>
          {data?.broker_stops_degraded && (
            <div style={{ marginBottom: 10, padding: '10px 12px', borderRadius: 9, background: `${RED}14`, border: `1px solid ${RED}55` }}>
              <div style={{ fontSize: 12.5, fontWeight: 800, color: RED }}>⚠ Schwab live stop read failed — broker stops may be hidden</div>
              <div style={{ fontSize: 11.5, color: MUTED, marginTop: 4, lineHeight: 1.45 }}>
                Only Fidelity monitored / planned stops are showing. Fidelity JEPQ-style rows can still appear while Schwab orders look &quot;planned only&quot;.
                {data?.broker_stops_meta?.error ? <> Error: <span style={{ color: TEXT0 }}>{String(data.broker_stops_meta.error)}</span>.</> : null}
                {' '}Refresh after the API server and venv recover; check <code style={{ fontSize: 10.5 }}>/api/v2/holdings/live-stops</code>.
              </div>
            </div>
          )}

          {/* Summary cards */}
          <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap', marginBottom: 12 }}>
            <Card label="Total Open Risk" value={fmt$(summary.total_open_risk)} />
            <Card label="Active Stops" value={`${summary.broker_stops_active ?? 0} / ${summary.positions ?? 0}`}
              color={(summary.no_stop ?? 0) > 0 ? AMBER : GREEN} sub={`${summary.no_stop ?? 0} with no active stop`} />
            <Card label="Red / Amber / Yellow" value={`${summary.red ?? 0} / ${summary.amber ?? 0} / ${summary.yellow ?? 0}`}
              color={(summary.red ?? 0) > 0 ? RED : (summary.amber ?? 0) > 0 ? AMBER : GREEN} />
            <Card label="Portfolio Heat" value={`${(summary.portfolio_heat_pct ?? 0).toFixed(1)}% / ${summary.heat_cap ?? 5}%`}
              color={(summary.portfolio_heat_pct ?? 0) > (summary.heat_cap ?? 5) ? RED : TEXT0} />
            <Card label="Trailing Not Active" value={String(summary.trailing_not_active ?? 0)} color={(summary.trailing_not_active ?? 0) > 0 ? AMBER : TEXT0} />
            <Card label="Street Coverage" value={`${summary.with_street_consensus ?? 0} / ${summary.positions ?? 0}`}
              color={(summary.with_street_consensus ?? 0) > 0 ? BLUE : MUTED}
              sub={`${summary.price_above_street ?? 0} price above · ${summary.stop_over_consensus ?? 0} stop above mean`} />
            <Card label="Regime Shifts" value={String((summary as any).regime_shifts ?? 0)}
              color={((summary as any).regime_shifts ?? 0) > 0 ? PURPLE : MUTED}
              sub="Layer 4 tighten 0.5× ATR when Trending→Ranging" />
            <Card label="Stop > Street Mean" value={String(summary.stop_over_consensus ?? 0)}
              color={(summary.stop_over_consensus ?? 0) > 0 ? RED : GREEN}
              sub="red/green badges in Street column (price + stop vs μ)" />
          </div>

          {/* Next actions — plain-English, prioritized by real risk reduction (STOP_METHODOLOGY.md-aligned) */}
          {Array.isArray((summary as any).next_actions) && (summary as any).next_actions.length > 0 && (
            <div style={{ marginBottom: 10, padding: '10px 12px', borderRadius: 9, background: `${BLUE}10`, border: `1px solid ${BLUE}44` }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: BLUE, textTransform: 'uppercase', letterSpacing: .3, marginBottom: 5 }}>Next actions — what to do now</div>
              {((summary as any).next_actions as NextAction[]).map((na, i) => (
                <div key={i} style={{ fontSize: 12.5, color: TEXT0, lineHeight: 1.5, display: 'flex', gap: 7, alignItems: 'baseline', marginBottom: 3 }}>
                  <span style={{ fontSize: 10, fontWeight: 800, color: na.alert_level === 'red' ? RED : na.alert_level === 'amber' ? AMBER : MUTED }}>{i + 1}.</span>
                  <span><b>{na.symbol}</b> <span style={{ color: MUTED }}>({na.account})</span> — {na.action}
                    {na.projection ? <span style={{ color: MUTED, fontSize: 11.5 }}> · {na.projection}</span> : null}</span>
                </div>
              ))}
            </div>
          )}

          {/* Filters */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
            {QUICK.map(qv => (
              <button key={qv} onClick={() => setQuick(qv)} style={{ fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                border: `1px solid ${quick === qv ? BLUE : 'rgba(148,163,184,.3)'}`, background: quick === qv ? `${BLUE}18` : 'transparent', color: quick === qv ? BLUE : MUTED }}>{qv}</button>
            ))}
            <span style={{ width: 8 }} />
            <select value={acct} onChange={e => setAcct(e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
              {accounts.map(a => <option key={a} value={a}>{a === 'All' ? 'All accounts' : a}</option>)}
            </select>
            <select value={level} onChange={e => setLevel(e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
              {['All', 'red', 'amber', 'yellow'].map(l => <option key={l} value={l}>{l === 'All' ? 'All levels' : l}</option>)}
            </select>
            <button onClick={load} style={{ fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>↻ Refresh</button>
            <span style={{ fontSize: 11, color: MUTED }}>{loading ? 'loading…' : `${filtered.length} of ${rows.length} · regime ${data?.regime_now ?? '—'}`}</span>
          </div>

          {/* Table */}
          <div style={{ overflowX: 'auto', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: MUTED, textAlign: 'left', background: 'rgba(15,23,42,.5)' }}>
                  {['Alert', 'Symbol · Account', 'Route', 'Regime', 'Active stop', 'Stop (broker / planned)', 'Street (μ)', 'Distance', 'Unreal.', '$ at risk', 'Reasons', ''].map(h =>
                    <th key={h} style={{ padding: '8px 9px', fontWeight: 800, whiteSpace: 'nowrap' }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={`${r.symbol}-${r.account}-${i}`} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: TEXT0 }}>
                    <td style={{ padding: '7px 9px' }}><Pill level={r.alert_level} thresholds={r.stoplight_thresholds_used} /></td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><b>{r.symbol}</b><br /><span style={{ fontSize: 10.5, color: MUTED }}>{r.account}</span></td>
                    <td style={{ padding: '7px 9px', color: MUTED, fontSize: 11 }}>{r.route}</td>
                    <td style={{ padding: '7px 9px' }}><RegimeBadge r={r} /></td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}>
                      {r.has_active_stop
                        ? <span style={{ color: GREEN, fontWeight: 700 }}>● {r.is_trailing ? 'TRAILING' : r.stop_type}<div style={{ fontSize: 9.5, color: MUTED, fontWeight: 400 }}>{SRC_LABEL[r.stop_source] || r.stop_source}</div></span>
                        : <span style={{ color: AMBER }}>○ none<div style={{ fontSize: 9.5, color: MUTED }}>{r.planned_stop != null ? 'planned only' : '—'}</div></span>}
                      {r.trailing_should_be_active ? <span style={{ color: AMBER }} title="trailing eligible but not active"> ⚠</span> : null}
                    </td>
                    <td style={{ padding: '7px 9px', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      <span style={{ color: r.broker_stop != null ? GREEN : MUTED }}>{fmtStop(r.broker_stop)}</span> / <span style={{ color: AMBER }}>{fmtStop(r.planned_stop)}</span>
                      {r.trailing_trigger != null && (
                        <div style={{ fontSize: 10, color: GREEN }} title="Trailing stop: ratchets up with price; shown at the current-equivalent trigger">
                          trail {r.trail_pct}% (≈{fmtStop(r.trailing_trigger)})
                        </div>
                      )}
                      {r.rec_source ? (
                        <div style={{ fontSize: 9.5, color: /grok|gpt|claude/i.test(r.rec_model || '') ? PURPLE : MUTED }}
                          title={r.rec_rationale || undefined}>
                          rec: {r.trail_recommended ? 'trail' : 'fixed'} · {r.rec_source.split(' · ')[0]}
                        </div>
                      ) : null}
                      {r.divergence ? <div style={{ fontSize: 10, color: r.has_active_stop ? RED : MUTED }}>{r.divergence}</div> : null}
                    </td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontSize: 11, fontFamily: 'monospace', minWidth: 118 }}>
                      {r.consensus_target_mean != null ? (() => {
                        const pricePct = priceDeltaPct(r)
                        const stopPct = stopDeltaPct(r)
                        const priceUsd = r.price_vs_consensus_dollars ?? (
                          r.current_price != null ? Math.round((r.current_price - r.consensus_target_mean!) * 100) / 100 : null
                        )
                        return (
                          <div title="Yahoo Street consensus (pro analyst pills). Red = above μ · Green = below μ.">
                            <div style={{ fontWeight: 900, color: TEXT0, fontSize: 12 }}>
                              μ {fmtStop(r.consensus_target_mean)}
                            </div>
                            {(r.consensus_target_low != null || r.consensus_target_high != null) && (
                              <div style={{ fontSize: 9.5, color: MUTED }}>
                                {fmtStop(r.consensus_target_low)} – {fmtStop(r.consensus_target_high)}
                              </div>
                            )}
                            <StreetGauge
                              price={r.current_price}
                              low={r.consensus_target_low}
                              high={r.consensus_target_high}
                              mean={r.consensus_target_mean}
                            />
                            <DeltaBadge label="Price" pct={pricePct} color={priceVsStreetColor(pricePct, r.price_above_consensus)} />
                            {priceUsd != null && pricePct != null && (
                              <div style={{ fontSize: 9, color: MUTED, marginTop: 1 }}>
                                {priceUsd >= 0 ? '+' : ''}{fmtStop(priceUsd)} vs μ
                              </div>
                            )}
                            <DeltaBadge label="Stop" pct={stopPct} color={stopVsStreetColor(stopPct, r.stop_above_consensus)} />
                            {r.consensus_analysts ? (
                              <div style={{ fontSize: 9.5, color: MUTED, marginTop: 3 }}>
                                {r.consensus_analysts} analysts{r.consensus_stale ? ' · stale' : ''}
                              </div>
                            ) : null}
                          </div>
                        )
                      })() : (
                        <span style={{ color: MUTED, fontSize: 10 }} title="No professional analyst coverage (ETFs/mutual funds)">no Street</span>
                      )}
                    </td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontSize: 11 }}>
                      {r.distance_pct != null ? `${r.distance_pct}%` : '—'}{r.distance_atr != null ? ` · ${r.distance_atr}ATR` : ''}{r.distance_r != null ? ` · ${r.distance_r}R` : ''}
                    </td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: (r.unrealized_dollars ?? 0) >= 0 ? GREEN : RED }}>{r.unrealized_dollars != null ? fmt$(r.unrealized_dollars) : '—'}</td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontWeight: 700 }}>{fmt$(r.dollars_at_risk)}</td>
                    <td style={{ padding: '7px 9px', fontSize: 10.5, color: MUTED, maxWidth: 340 }}>
                      {r.narrative ? <div style={{ color: TEXT0, fontSize: 11, lineHeight: 1.45, marginBottom: 3 }}>{r.narrative}</div> : (r.alert_reasons || []).join(' · ')}
                      {(r.policy_suggestions?.length ?? 0) > 0 && (
                        <div style={{ marginTop: 4, fontSize: 10.5, fontWeight: 800, color: PURPLE, lineHeight: 1.4 }}>
                          Policy: {r.policy_suggestions!.join(' · ')}
                        </div>
                      )}
                      {r.next_action ? (
                        <div style={{ fontSize: 10.5, fontWeight: 700, lineHeight: 1.4,
                          color: /^(Monitor|None)/.test(r.next_action) ? MUTED : (r.alert_level === 'red' ? RED : r.alert_level === 'amber' ? AMBER : BLUE) }}>
                          → {r.next_action}
                        </div>
                      ) : null}
                      {((r.rec_evidence?.length ?? 0) > 0 || (r.rec_data_i_doubt && r.rec_data_i_doubt !== 'none')) && (
                        <EvidenceBlock title="Stop advisory evidence" evidence={r.rec_evidence} dataIDoubt={r.rec_data_i_doubt} compact maxItems={3} />
                      )}
                      {r.stop_curation && ((r.stop_curation.evidence?.length ?? 0) > 0 || (r.stop_curation.data_i_doubt && r.stop_curation.data_i_doubt !== 'none') || r.stop_curation.grade) && (
                        <div style={{ marginTop: 4 }}>
                          {r.stop_curation.grade && <div style={{ fontSize: 10, color: PURPLE, fontWeight: 800, marginBottom: 2 }}>Grok curation · {r.stop_curation.grade}</div>}
                          <EvidenceBlock title="Grok stop evidence" evidence={r.stop_curation.evidence} dataIDoubt={r.stop_curation.data_i_doubt} compact maxItems={3} />
                        </div>
                      )}
                      {((r.holdings_llm_evidence?.length ?? 0) > 0 || (r.holdings_llm_data_i_doubt && r.holdings_llm_data_i_doubt !== 'none')) && (
                        <EvidenceBlock title={r.holdings_llm_health ? `Holdings health · ${r.holdings_llm_health}` : 'Holdings LLM evidence'} evidence={r.holdings_llm_evidence} dataIDoubt={r.holdings_llm_data_i_doubt} compact maxItems={2} />
                      )}
                    </td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}>
                      {r.trailing_should_be_active && (
                        <button onClick={() => openAdjust(r, true)}
                          title={`One-click: stages the advised ${r.trail_pct ?? ''}% trailing stop and goes straight to ${r.account.startsWith('fidelity') ? 'a manual ticket' : '2FA approve'}`}
                          style={{ fontSize: 11, fontWeight: 800, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', marginRight: 5,
                            border: `1px solid ${GREEN}`, background: `${GREEN}20`, color: GREEN, whiteSpace: 'nowrap' }}>
                          🔒 Trail {r.account.startsWith('fidelity') ? 'manual' : '2FA'}
                        </button>
                      )}
                      {!r.has_active_stop && r.planned_stop != null && !r.trailing_should_be_active && (
                        <button onClick={() => openAdjust(r, true)}
                          title={`One-click: stages the advised ${fmtStop(r.planned_stop)} stop and goes straight to ${r.account.startsWith('fidelity') ? 'a manual ticket' : '2FA approve'}`}
                          style={{ fontSize: 11, fontWeight: 800, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', marginRight: 5, whiteSpace: 'nowrap',
                            border: `1px solid ${AMBER}`, background: `${AMBER}20`, color: AMBER }}>
                          🔒 Set {r.account.startsWith('fidelity') ? 'manual' : '2FA'} {fmtStop(r.planned_stop)}
                        </button>
                      )}
                      <button onClick={() => openAdjust(r, false)} style={{ fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE, whiteSpace: 'nowrap' }}>Adjust stop</button>
                    </td>
                  </tr>
                ))}
                {!loading && filtered.length === 0 && (
                  <tr><td colSpan={10} style={{ padding: 20, textAlign: 'center', color: MUTED }}>No positions match this filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {adjust && <AdjustModal row={adjust} autoStage={autoStage} onClose={() => { setAdjust(null); setAutoStage(false) }} onFocusHolding={onFocusHolding} />}
        </>
      )}
    </div>
  )
}

// Adjust modal — broker-aware stop-type selection. Choosing a type jumps to the holding's inline gated panel
// (Schwab → per-order 2FA request; Fidelity → manual ticket). No stop is submitted from here.
function AdjustModal({ row, autoStage, onClose, onFocusHolding }: { row: Row; autoStage?: boolean; onClose: () => void; onFocusHolding?: (s: string, a: string) => void }) {
  const isFidelity = row.account.startsWith('fidelity')
  const recKind = row.trail_recommended ? 'TRAILING' : 'FIXED'
  // One-click apply: only auto-stage when the row is genuinely actionable (naked — no active stop). An
  // existing stop needs manual Replace/ToS, so never auto-fire there.
  const autoStageKind: 'STOP' | 'TRAILING' | null = (autoStage && !row.has_active_stop)
    ? (row.trail_recommended ? 'TRAILING' : 'STOP') : null
  // Assemble the exact props the holding card passes, so the inline panel renders identical live-stop state
  // (never a false "none"). Sources: portfolio/holdings, portfolio/llm-coverage (protection + confirmed_stops),
  // holdings/live-stops (by_key), holdings/monitored-stops (by_key). Then reuse the same protective-stop panel.
  const [pack, setPack] = useState<{ h: any; pr: any; mon: any; conf: any; fetchedAt: any } | null>(null)
  const [perr, setPerr] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  useEffect(() => {
    let cancelled = false
    const key = `${row.symbol.toUpperCase()}:${row.account}`
    Promise.all([
      fetch('/api/v2/portfolio/holdings').then(x => x.json()).catch(() => null),
      fetch('/api/v2/portfolio/llm-coverage').then(x => x.json()).catch(() => null),
      fetch('/api/v2/holdings/live-stops').then(x => x.json()).catch(() => null),
      fetch('/api/v2/holdings/monitored-stops').then(x => x.json()).catch(() => null),
    ]).then(([hj, cj, lj, mj]) => {
      if (cancelled) return
      const hd = unwrap(hj) ?? {}
      const arr: any[] = Array.isArray(hd) ? hd : (hd.holdings ?? [])
      const h = arr.find(x => String(x.symbol).toUpperCase() === row.symbol.toUpperCase() && String(x.account) === row.account)
      const cov = unwrap(cj) ?? {}
      const pr = (cov.protection ?? {})[row.symbol.toUpperCase()] ?? {}
      const ls = unwrap(lj) ?? {}
      const conf = mergeLiveStop((cov.confirmed_stops ?? {})[key], (ls.by_key ?? {})[key])
      const mon = (unwrap(mj)?.by_key ?? {})[key]
      const fetchedAt = ls.fetched_at ?? cov.broker_stops_fetched_at ?? null
      if (h) setPack({ h, pr, mon, conf, fetchedAt }); else setPerr('holding not found for this symbol/account')
    }).catch(() => setPerr('could not load holding data'))
    return () => { cancelled = true }
  }, [row.symbol, row.account, reloadKey])

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', zIndex: 1000, padding: '4vh 0', overflow: 'auto' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 760, maxWidth: '94vw', maxHeight: '92vh', overflow: 'auto', background: 'var(--bg1, #0f172a)', border: '1px solid rgba(148,163,184,.3)', borderRadius: 12, padding: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: TEXT0 }}>Manage stop — {row.symbol}</div>
          <button onClick={onClose} style={{ fontSize: 18, color: MUTED, background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ fontSize: 12.5, color: TEXT0, lineHeight: 1.6, marginBottom: 10 }}>
          <b>{row.account}</b> · {row.route} · <span style={{ color: isFidelity ? AMBER : BLUE }}>{isFidelity ? 'Fidelity (manual)' : 'Schwab (2FA)'}</span><br />
          Price <b>{fmtStop(row.current_price)}</b> · Active stop <b style={{ color: row.broker_stop != null ? GREEN : AMBER }}>{row.broker_stop != null ? `${fmtStop(row.broker_stop)} (${SRC_LABEL[row.stop_source] || row.stop_source})` : 'none'}</b> · Advised fixed <b style={{ color: AMBER }}>{fmtStop(row.planned_stop)}</b>{row.trailing_trigger != null ? <> · Trail <b style={{ color: GREEN }}>{row.trail_pct}% (≈{fmtStop(row.trailing_trigger)})</b></> : null}<br />
          Distance {row.distance_pct}%{row.distance_atr != null ? ` · ${row.distance_atr}ATR` : ''} · $ at risk <b>{fmt$(row.dollars_at_risk)}</b>
        </div>

        {/* Recommendation attribution — who (system vs external LLM) recommends fixed vs trailing */}
        <div style={{ fontSize: 12, padding: '8px 11px', borderRadius: 8, marginBottom: 12,
          background: row.trail_recommended ? `${GREEN}12` : 'rgba(15,23,42,.5)',
          border: `1px solid ${row.trail_recommended ? GREEN : 'rgba(148,163,184,.3)'}` }}>
          <b style={{ color: row.trail_recommended ? GREEN : AMBER }}>Recommended: {recKind} stop</b>
          {row.rec_source ? <span style={{ color: MUTED }}> · by <b style={{ color: row.rec_model && /grok|gpt|claude/i.test(row.rec_model) ? PURPLE : BLUE }}>{row.rec_source}</b>{row.rec_model ? ` (${row.rec_model})` : ''}</span> : null}
          {row.rec_rationale ? <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>{row.rec_rationale}</div> : null}
          <EvidenceBlock evidence={row.rec_evidence} dataIDoubt={row.rec_data_i_doubt} compact maxItems={5} />
        </div>

        {row.stop_curation && (
          <div style={{ fontSize: 12, padding: '8px 11px', borderRadius: 8, marginBottom: 12, background: `${PURPLE}10`, border: `1px solid ${PURPLE}44` }}>
            <b style={{ color: PURPLE }}>Grok stop curation{row.stop_curation.grade ? ` · ${row.stop_curation.grade}` : ''}</b>
            {row.stop_curation.rr_assessment && <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>{row.stop_curation.rr_assessment}</div>}
            <EvidenceBlock evidence={row.stop_curation.evidence} dataIDoubt={row.stop_curation.data_i_doubt} compact />
          </div>
        )}

        {((row.holdings_llm_evidence?.length ?? 0) > 0 || (row.holdings_llm_data_i_doubt && row.holdings_llm_data_i_doubt !== 'none')) && (
          <div style={{ fontSize: 12, padding: '8px 11px', borderRadius: 8, marginBottom: 12, background: 'rgba(45,212,191,.08)', border: '1px solid rgba(45,212,191,.3)' }}>
            <b style={{ color: '#2dd4bf' }}>Holdings LLM health{row.holdings_llm_health ? ` · ${row.holdings_llm_health}` : ''}</b>
            <EvidenceBlock evidence={row.holdings_llm_evidence} dataIDoubt={row.holdings_llm_data_i_doubt} compact />
          </div>
        )}

        {/* Plain-English "what this means" + the projected effect of the 2FA stop trade */}
        {(row.narrative || row.projection || row.next_action) && (
          <div style={{ fontSize: 12, padding: '9px 11px', borderRadius: 8, marginBottom: 12, background: 'rgba(15,23,42,.5)', border: '1px solid rgba(148,163,184,.25)' }}>
            {row.narrative ? <div style={{ color: TEXT0, lineHeight: 1.5 }}>{row.narrative}</div> : null}
            {row.next_action && !/^(Monitor|None)/.test(row.next_action) ? (
              <div style={{ marginTop: 5, fontWeight: 700, color: row.alert_level === 'red' ? RED : row.alert_level === 'amber' ? AMBER : BLUE }}>→ {row.next_action}</div>
            ) : null}
            {row.projection ? (
              <div style={{ marginTop: 5, fontSize: 11.5, color: MUTED }}><b style={{ color: TEXT0 }}>Projection:</b> {row.projection}</div>
            ) : null}
          </div>
        )}

        {/* Inline gated 2FA / manual panel — the SAME verified holding panel; nothing submits without per-order 2FA */}
        {perr ? (
          <div style={{ fontSize: 12, color: RED, padding: 10 }}>⛔ {perr}. <button onClick={() => { onFocusHolding?.(row.symbol, row.account); onClose() }} style={{ color: BLUE, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Open full holding card ↗</button></div>
        ) : !pack ? (
          <div style={{ fontSize: 12, color: MUTED, padding: 14 }}>Loading stop controls…</div>
        ) : (
          <HoldingProtectionActions h={pack.h} pr={pack.pr} monitored={pack.mon} confirmedStop={pack.conf}
            brokerStopsFetchedAt={pack.fetchedAt} autoStageKind={autoStageKind} onRefresh={() => setReloadKey(k => k + 1)} />
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <button onClick={() => { onFocusHolding?.(row.symbol, row.account); onClose() }} style={{ fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 7, border: `1px solid ${BLUE}55`, background: 'transparent', color: BLUE, cursor: 'pointer' }}>Open full holding card ↗</button>
          <button onClick={onClose} style={{ fontSize: 13, fontWeight: 700, padding: '7px 14px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Close</button>
        </div>
      </div>
    </div>
  )
}

// Audit sub-tab — read-only trail of protective-stop actions (2FA requests + operator confirmations).
function AuditView() {
  const [d, setD] = useState<any>(null)
  const [rw, setRw] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    Promise.all([
      fetch('/api/v2/stops/audit').then(x => x.json()).then(j => unwrap(j)).catch(() => null),
      fetch('/api/v2/stops/reentry-watch?days=365').then(x => x.json()).then(j => unwrap(j)).catch(() => null),
    ]).then(([audit, watch]) => { setD(audit); setRw(watch) }).finally(() => setLoading(false))
  }, [])
  const events = d?.events ?? []
  const counts = d?.counts ?? {}
  const watchRows: any[] = rw?.reentry_watch ?? []
  const reviewRows: any[] = rw?.reviews ?? []
  // Accurate per-row action label. Schwab positions are API/2FA-eligible, so an unconfirmed Schwab row is
  // "Schwab 2FA (pending)" — NOT manual (only Fidelity, which has no trading API, is truly manual).
  const actionFor = (e: any): { label: string; color: string } => {
    if (e.kind === '2fa_stop_request') return { label: '2FA stop request', color: BLUE }
    if (e.kind === 'confirmation') {
      if (e.confirmed) return { label: 'confirmed', color: GREEN }
      if (e.route === 'fidelity_manual') return { label: 'manual ticket (pending)', color: AMBER }
      return { label: 'Schwab 2FA (pending)', color: BLUE }
    }
    return { label: e.kind, color: MUTED }
  }
  const STATUS_COLOR: Record<string, string> = { confirmed: GREEN, approved: GREEN, consumed: GREEN, pending: AMBER, superseded: MUTED, expired: MUTED, rejected: RED }
  return (
    <>
      <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap', marginBottom: 12 }}>
        <Card label="Audit events" value={String(d?.total ?? 0)} />
        <Card label="2FA stop requests" value={String(counts['2fa_stop_request'] ?? 0)} color={BLUE} />
        <Card label="Confirmations / pending" value={String(counts['confirmation'] ?? 0)} color={GREEN} />
        <Card label="Stop-out reviews" value={String(rw?.total_reviews ?? 0)} color={AMBER} sub="advisory · journal lifecycle" />
        <Card label="Re-entry watch" value={String(rw?.total_watch ?? 0)} color={PURPLE} sub="WAIT status" />
      </div>
      <div style={{ overflowX: 'auto', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ color: MUTED, textAlign: 'left', background: 'rgba(15,23,42,.5)' }}>
              {['When', 'Action', 'Symbol · Account', 'Order', 'Status', 'Channel', 'Detail'].map(h =>
                <th key={h} style={{ padding: '8px 9px', fontWeight: 800, whiteSpace: 'nowrap' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {events.map((e: any, i: number) => {
              const k = actionFor(e)
              return (
                <tr key={i} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: TEXT0 }}>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: MUTED }}>{fmtTime(e.at)}</td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><span style={{ color: k.color, fontWeight: 700 }}>{k.label}</span></td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><b>{e.symbol || '—'}</b> <span style={{ fontSize: 10.5, color: MUTED }}>{e.account || ''}</span></td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 11 }}>{e.order_type || '—'}{e.stop_price != null ? ` @ ${fmtStop(e.stop_price)}` : ''}{e.trail_pct != null ? ` ${e.trail_pct}%` : ''}</td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontWeight: 700, color: STATUS_COLOR[String(e.status)] || TEXT0 }}>{e.status || '—'}</td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: MUTED }}>{e.channel || '—'}</td>
                  <td style={{ padding: '7px 9px', fontSize: 10.5, color: MUTED, maxWidth: 260 }}>{e.reason || e.attestation || (e.evidence_hash ? `evidence ${e.evidence_hash}` : '') || (e.reminder_count ? `${e.reminder_count} reminders` : '')}</td>
                </tr>
              )
            })}
            {!loading && events.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: MUTED }}>No stop-action audit events yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 18, padding: '12px 14px', borderRadius: 9, background: `${PURPLE}10`, border: `1px solid ${PURPLE}44` }}>
        <div style={{ fontSize: 12, fontWeight: 900, color: PURPLE, marginBottom: 6 }}>Stop-out re-entry watch — advisory only</div>
        <div style={{ fontSize: 11, color: MUTED, marginBottom: 10, lineHeight: 1.45 }}>
          Loss round-trips from journal lifecycle. Does not route orders — use triggers as a checklist before re-entering.
          {rw?.advisory_only ? ' · advisory_only=true' : ''}{rw?.error ? ` · ${rw.error}` : ''}
        </div>
        <div style={{ overflowX: 'auto', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: MUTED, textAlign: 'left', background: 'rgba(15,23,42,.5)' }}>
                {['Symbol', 'Exit', 'P&L', 'Why stopped', 'Triggers', 'Status'].map(h =>
                  <th key={h} style={{ padding: '8px 9px', fontWeight: 800, whiteSpace: 'nowrap' }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {watchRows.map((w: any, i: number) => {
                const rev = reviewRows.find((r: any) => r.symbol === w.symbol)
                return (
                  <tr key={`${w.symbol}-${i}`} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: TEXT0 }}>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><b>{w.symbol}</b>{rev?.account ? <div style={{ fontSize: 10, color: MUTED }}>{rev.account}</div> : null}</td>
                    <td style={{ padding: '7px 9px', fontFamily: 'monospace' }}>{fmtStop(w.exit_price)}</td>
                    <td style={{ padding: '7px 9px', color: (w.realized_pnl ?? 0) < 0 ? RED : GREEN, fontWeight: 700 }}>{w.realized_pnl != null ? `$${Number(w.realized_pnl).toFixed(2)}` : '—'}</td>
                    <td style={{ padding: '7px 9px', fontSize: 10.5, color: MUTED, maxWidth: 280 }}>{w.why_stopped || rev?.policy_quality || '—'}</td>
                    <td style={{ padding: '7px 9px', fontSize: 10, color: MUTED, maxWidth: 220 }}>{(w.triggers ?? []).slice(0, 4).join(' · ')}{(w.triggers?.length ?? 0) > 4 ? ' …' : ''}</td>
                    <td style={{ padding: '7px 9px', fontWeight: 800, color: w.status === 'WAIT' ? AMBER : GREEN }}>{w.status || '—'}</td>
                  </tr>
                )
              })}
              {!loading && watchRows.length === 0 && (
                <tr><td colSpan={6} style={{ padding: 20, textAlign: 'center', color: MUTED }}>No stop-out re-entry watch rows in the last {rw?.days ?? 365} days.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
