import { Fragment, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

interface Props { onDrill?: (ctx: any) => void }

type Banner = { id: string; severity: string; title: string; detail: string }
type FieldState = {
  value?: any
  state?: string
  source?: string
  as_of?: string | null
  freshness?: string | null
  quality?: string
  reason?: string | null
  display?: string | null
}
type DeskRow = {
  symbol: string
  account?: string
  row_class: string
  verdict: string
  confidence?: number
  setup_state?: string
  setup_confidence?: number
  watch_filters?: string[]
  watch_rank?: number
  market_value?: number
  weight_pct?: number
  gain_loss_pct?: number
  rationale?: string
  rationale_signals?: string[]
  why_call?: string
  advisory_row_hash?: string
  row_id?: string
  data_quality?: {
    evidence_count?: number
    gap_count?: number
    lot_data_status?: string
    sufficient?: boolean
    evidence_gaps?: string[]
    conflicts?: string[]
    quality?: string
    action_suppressed?: boolean
    banner?: string
  }
  canonical_financial_facts?: any
  advisory_provenance?: any
  field_states?: any
  watch_intelligence?: any
  reentry?: any
  durable_memory?: any
  financial_senses?: any
  reentry_state?: string
  reentry_entry_low?: number
  reentry_entry_high?: number
  reentry_price?: number
  reentry_rsi?: number
  reentry_distance_label?: string
  reentry_next_action?: string
  reentry_reason?: string
  reentry_wash_status?: string
  expand?: {
    lots?: any
    price_action?: any
    analyst?: any
    memory?: any
    evidence_items?: any[]
    opinion?: any
    instrument?: any
    canonical_financial_facts?: any
    advisory_provenance?: any
    watch_intelligence?: any
    reentry?: any
    durable_memory?: any
    financial_senses?: any
    field_states?: any
  }
}

const VERDICT_COLOR: Record<string, string> = {
  TRIM: 'var(--amber)', EXIT: 'var(--red)', ADD: 'var(--green)',
  HOLD: 'var(--text2)', RE_ENTER: 'var(--accent)', WAIT: 'var(--text3)',
  AVOID: 'var(--orange)', INSUFFICIENT_DATA: 'var(--text3)',
}

const VERDICT_HELP: Record<string, string> = {
  ADD: 'Add / increase — evidence supports a new or larger position.',
  HOLD: 'Hold — within normal parameters; no signal to act.',
  TRIM: 'Trim — reduce size (concentration, gain, or loss trigger).',
  EXIT: 'Exit — close the position.',
  RE_ENTER: 'Re-enter — watch for a recovery/confirmation entry.',
  WAIT: 'Wait — hold off until a trigger clears.',
  AVOID: 'Avoid — do not initiate; negative signal present.',
  INSUFFICIENT_DATA: 'Not enough evidence to act — verdict suppressed.',
}

const SEV_BG: Record<string, string> = {
  critical: 'var(--red-ghost)',
  warn: 'var(--amber-ghost)',
  info: 'var(--bg2)',
}
const SEV_FG: Record<string, string> = {
  critical: 'var(--red)',
  warn: 'var(--amber)',
  info: 'var(--text2)',
}

const BANNER_ACTION: Record<string, string> = {
  OK: 'Facts current and structurally valid.',
  VALIDATION_FAIL: 'Fix validation_errors before relying on verdicts.',
  DESK_STALE: 'Do not treat this snapshot as current. Recompute or wait for a fresh desk.',
  DESK_PARTIAL: 'Some families are incomplete — read why-missing on each row.',
  DESK_DEGRADED: 'Facts may be current; opinions or memory are not.',
  DESK_UNKNOWN: 'Health contract missing — do not assume healthy.',
  PLAUSIBILITY_OK: 'Verdict distribution and weight sum are within bounds.',
  PLAUSIBILITY_FAIL: 'Verdict distribution out of bounds — review before acting.',
  LOTS_OK: 'Lot data trusted; cost basis is reliable.',
  UNTRUSTED_LOTS: 'Review affected rows — lot-derived signals are suppressed.',
  LLM_ON: 'Flash/Pro opinions active in this snapshot.',
  LLM_DRY: 'Run enrichment to generate Flash/Pro opinions.',
  LLM_OFF: 'Enable ADVISORY_DESK_V1 to run Flash/Pro enrichment.',
  INVARIANTS_OK: 'No external reality failures.',
  INVARIANT_VIOLATIONS: 'Rows forced to INSUFFICIENT_DATA — resolve data gaps.',
  DATA_CONFLICT: 'Do not act on conflicted marks — ACTION SUPPRESSED until prices/MV reconcile.',
}

const MATERIALITY_FLOOR = 500
const CLASSES = ['all', 'holding', 'watchlist', 'closed_journal', 'allocation'] as const
const WATCH_FILTERS = [
  ['all', 'All'],
  ['needs_attention', 'Needs attention'],
  ['near_trigger', 'Near trigger'],
  ['review_now', 'Review now'],
  ['starred', 'Starred'],
  ['strongest_evidence', 'Strongest evidence'],
  ['catalyst_upcoming', 'Catalyst upcoming'],
  ['needs_data', 'Needs data'],
  ['stale', 'Stale'],
  ['avoid', 'Avoid'],
] as const

function fmtUSD(n: number | null | undefined) {
  if (n == null) return null
  const abs = Math.abs(n)
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return null
  return `${n >= 0 ? '+' : ''}${Number(n).toFixed(1)}%`
}

function fmtPrice(n: number | null | undefined) {
  if (n == null || Number.isNaN(Number(n))) return null
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtWhen(v: any) {
  if (!v) return null
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).replace('T', ' ').slice(0, 19)
  return d.toLocaleString()
}

function ageLabel(v: any) {
  if (!v) return null
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return null
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000)
  if (s < 90) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`
  return `${(s / 86400).toFixed(1)}d`
}

function qualityTone(q: string | undefined) {
  const u = String(q || '').toUpperCase()
  if (u === 'CONFLICTED' || u === 'FAILED') return 'var(--red)'
  if (u === 'STALE' || u === 'DATA_UNAVAILABLE' || u === 'EXPIRED' || u === 'DEGRADED' || u === 'PARTIAL') return 'var(--amber)'
  if (u.startsWith('VERIFIED') || u === 'AVAILABLE' || u === 'CURRENT' || u === 'HEALTHY' || u === 'PASS') return 'var(--green)'
  if (u === 'NOT_APPLICABLE' || u === 'N/A') return 'var(--text3)'
  return undefined
}

function Field({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: string; hint?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '2px 0', fontSize: 11.5 }} title={hint}>
      <span style={{ color: 'var(--text3)' }}>{label}</span>
      <span style={{ color: tone || 'var(--text)', fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' }}>{value}</span>
    </div>
  )
}

function cardWrap(title: string, children: ReactNode) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10, background: 'var(--bg)' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', marginBottom: 6, letterSpacing: 0.3, textTransform: 'uppercase' }}>{title}</div>
      {children}
    </div>
  )
}

function FieldStateView({ label, fs, format }: { label: string; fs?: FieldState | null; format?: (v: any) => string | null }) {
  if (!fs || typeof fs !== 'object') {
    return <Field label={label} value={<span style={{ color: 'var(--text3)', fontStyle: 'italic' }}>unavailable · no field state</span>} />
  }
  const state = String(fs.state || '').toUpperCase()
  if (state === 'NOT_APPLICABLE') {
    return <Field label={label} value="N/A" tone="var(--text3)" hint={fs.reason || 'not applicable'} />
  }
  if (state === 'DATA_UNAVAILABLE' || state === 'NOT_RUN' || state === 'NOT_CONFIGURED') {
    const why = fs.reason || state.toLowerCase().replace(/_/g, ' ')
    return <Field label={label} value={why} tone="var(--amber)" hint={`${fs.source || ''} ${fs.as_of || ''}`.trim()} />
  }
  const raw = format ? format(fs.value) : (fs.display || (fs.value == null ? null : String(fs.value)))
  const shown = raw ?? fs.display ?? (fs.value == null ? 'unavailable' : String(fs.value))
  const extra = [fs.freshness, fs.quality !== state ? fs.quality : null, fs.reason].filter(Boolean).join(' · ')
  return (
    <Field
      label={label}
      value={<>{shown}{extra ? <span style={{ color: 'var(--text3)', fontWeight: 500 }}> · {extra}</span> : null}</>}
      tone={qualityTone(fs.freshness || fs.quality || state)}
      hint={[fs.source, fs.as_of, fs.reason].filter(Boolean).join(' · ')}
    />
  )
}

function LotsCard({ d, fieldStates }: { d: any; fieldStates?: any }) {
  const sharesNA = fieldStates?.shares?.state === 'NOT_APPLICABLE'
  if (sharesNA) {
    return <span style={emptyStyle}>Lots N/A — {fieldStates.shares.reason || 'no open position'}.</span>
  }
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>Lot data unavailable — no lot_basis on this row.</span>
  const lots = Array.isArray(d.lots) ? d.lots : []
  return (
    <div>
      <Field label="Lot data" value={String(d.lot_data_status || 'unavailable')} />
      <Field label="Shares" value={d.total_shares != null ? Number(d.total_shares).toLocaleString() : 'unavailable'} />
      <Field label="Weighted avg basis" value={d.weighted_avg_basis != null ? (fmtUSD(d.weighted_avg_basis) || 'unavailable') : 'unavailable'} />
      <Field label="Holding period" value={String(d.holding_period || 'unavailable')} />
      <Field label="Lots" value={`${d.lot_count ?? lots.length} open · ${d.lots_in_profit ?? 0} in profit · ${d.lots_underwater ?? 0} underwater`} />
      {lots.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 6, fontSize: 10.5 }}>
          <thead>
            <tr>
              {['Lot date', 'Shares', 'Cost/sh', 'Open'].map(h => (
                <th key={h} style={miniTh}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lots.slice(0, 8).map((l: any, i: number) => (
              <tr key={i}>
                <td style={miniTd}>{String(l.lot_date || l.acquired_date || '—').slice(0, 10)}</td>
                <td style={{ ...miniTd, textAlign: 'right' }}>{l.shares_remaining != null ? Number(l.shares_remaining).toLocaleString() : '—'}</td>
                <td style={{ ...miniTd, textAlign: 'right' }}>{l.cost_per_share != null ? fmtUSD(l.cost_per_share) : '—'}</td>
                <td style={{ ...miniTd, textAlign: 'right' }}>{l.closed ? 'no' : 'yes'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function CurrentFinancialFactsCard({ d, fieldStates }: { d: any; fieldStates?: any }) {
  const fs = fieldStates || {}
  if (fs.position?.state === 'NOT_APPLICABLE') {
    return <span style={emptyStyle}>{fs.note || 'Position facts N/A for this class.'}</span>
  }
  if (fs.current_mark || fs.shares || fs.market_value) {
    return (
      <div>
        <FieldStateView label="Current mark" fs={fs.current_mark} format={fmtPrice} />
        <FieldStateView label="As of" fs={fs.as_of} />
        <Field label="Source" value={String(fs.source || d?.source || 'unavailable')} />
        <FieldStateView label="Shares" fs={fs.shares} format={(v) => v != null ? Number(v).toLocaleString() : null} />
        <FieldStateView label="Market value" fs={fs.market_value} format={fmtUSD} />
        {fs.implied_price && <FieldStateView label="Implied from MV" fs={fs.implied_price} format={fmtPrice} />}
        {fs.reference_market_snapshot && <FieldStateView label="Reference snapshot" fs={fs.reference_market_snapshot} format={fmtPrice} />}
        <FieldStateView label="Total cost basis" fs={fs.total_cost_basis} format={fmtUSD} />
        <FieldStateView label="Avg cost/share" fs={fs.average_cost} format={fmtPrice} />
        <FieldStateView label="Unrealized P/L" fs={fs.unrealized_pl} format={fmtUSD} />
        <Field label="Quality" value={String(fs.quality || d?.quality || 'unavailable')} tone={qualityTone(fs.quality || d?.quality)} />
        {Array.isArray(fs.why_missing) && fs.why_missing.length > 0 && (
          <div style={{ fontSize: 10.5, color: 'var(--amber)', marginTop: 6, lineHeight: 1.35 }}>
            Why missing: {fs.why_missing.join(' · ')}
          </div>
        )}
      </div>
    )
  }
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No canonical mark — desk row has no price fields and live holdings did not join.</span>
  const q = String(d.quality || 'unavailable')
  return (
    <div>
      <Field label="Current mark" value={d.current_mark_display && d.current_mark_display !== '—' ? d.current_mark_display : (fmtPrice(d.current_mark) || 'unavailable')} />
      <Field label="As of" value={d.as_of ? String(d.as_of).replace('T', ' ').slice(0, 19) : 'unavailable'} />
      <Field label="Source" value={String(d.source || 'unavailable')} />
      <Field label="Shares" value={d.shares != null ? Number(d.shares).toLocaleString() : 'unavailable'} />
      <Field label="Market value" value={d.market_value_display && d.market_value_display !== '—' ? d.market_value_display : (fmtUSD(d.market_value) || 'unavailable')} />
      {d.implied_price_from_mv != null && <Field label="Implied from MV" value={fmtPrice(d.implied_price_from_mv) || 'unavailable'} />}
      <Field label="Quality" value={q} tone={qualityTone(q)} />
    </div>
  )
}

function PriceActionCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>Price-action unavailable — no OHLCV/Finviz snapshot on this row.</span>
  const dir = d.trend_direction
  return (
    <div>
      {(d.current_mark != null || d.as_of || d.source) && (
        <>
          {d.current_mark != null && <Field label="Mark used" value={fmtPrice(d.current_mark) || 'unavailable'} />}
          {d.as_of && <Field label="As of" value={String(d.as_of).replace('T', ' ').slice(0, 19)} />}
          {d.source && <Field label="Source" value={String(d.source)} />}
        </>
      )}
      <Field label="1d / 5d / 20d" value={`${fmtPct(d.price_change_pct_1d) || 'n/a'} / ${fmtPct(d.price_change_pct_5d) || 'n/a'} / ${fmtPct(d.price_change_pct_20d) || 'n/a'}`} />
      <Field label="Off 52w high" value={fmtPct(d.pct_off_52w_high) || 'unavailable'} />
      <Field label="Off 52w low" value={fmtPct(d.pct_off_52w_low) || 'unavailable'} />
      <Field label="From cost basis" value={fmtPct(d.distance_from_cost_basis_pct) || 'N/A'} />
      <Field label="Trend" value={dir ? String(dir) : 'unavailable'} tone={dir === 'down' || dir === 'falling' ? 'var(--red)' : dir === 'up' || dir === 'rising' ? 'var(--green)' : undefined} />
      <Field label="Volatility (1w)" value={fmtPct(d.volatility_w_pct) || 'unavailable'} />
    </div>
  )
}

function AnalystCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No analyst coverage attached.</span>
  const target = d.target ?? d.price_target_mean
  const denomIsCurrent = Boolean(d.denominator_is_canonical_current)
  const vsCanonical = d.target_upside_vs_current
  const vsProvider = d.target_upside_vs_provider_snapshot
  const denomPx = d.denominator_price
  const denomAsOf = d.denominator_as_of
  return (
    <div>
      <Field label="Consensus" value={String(d.consensus_rating || d.recommendation_mean || 'unavailable')} />
      <Field label="Target" value={target != null ? (fmtPrice(target) || 'unavailable') : 'unavailable'} />
      <Field label="Target as of" value={String(d.target_as_of || d.as_of || 'unavailable').slice(0, 10)} />
      <Field
        label="Target range"
        value={d.price_target_low != null && d.price_target_high != null
          ? `${fmtPrice(d.price_target_low)} – ${fmtPrice(d.price_target_high)}`
          : 'unavailable'}
      />
      <Field
        label="Upside vs canonical current"
        value={vsCanonical != null ? (fmtPct(vsCanonical) || 'unavailable') : 'not labeled vs current'}
        tone={denomIsCurrent ? undefined : 'var(--text3)'}
      />
      <Field label="Upside vs provider snapshot" value={vsProvider != null ? (fmtPct(vsProvider) || 'unavailable') : 'unavailable'} />
      <Field
        label="Denominator"
        value={
          denomPx != null
            ? `${fmtPrice(denomPx)}${denomAsOf ? ` · ${String(denomAsOf).slice(0, 10)}` : ''}${denomIsCurrent ? ' · canonical' : ' · provider snapshot'}`
            : 'unavailable'
        }
      />
      {!denomIsCurrent && (vsProvider != null || denomPx != null) && (
        <div style={{ fontSize: 10.5, color: 'var(--amber)', marginTop: 6, lineHeight: 1.35 }}>
          Provider snapshot is not the canonical current mark — not labeled as current.
        </div>
      )}
      <Field label="Analysts" value={d.analyst_count ?? 'unavailable'} />
    </div>
  )
}

function MemoryCard({ d, durable }: { d: any; durable?: any }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: 'var(--text3)', marginBottom: 4 }}>DURABLE AIF MEMORY (Program 3)</div>
      {durable ? (
        <>
          <Field label="Provider" value={String(durable.provider || 'unavailable')} />
          <Field label="Retrieval" value={String(durable.retrieval_status || durable.state || 'unavailable')} tone={qualityTone(durable.retrieval_status || durable.state)} />
          <Field label="Summary" value={String(durable.summary || durable.reason || 'unavailable')} />
          <Field label="Influence" value={`${durable.influence_mode || 'OFF'} · MBI ${durable.memory_behavior_influence || '0'}`} />
          {(durable.supporting || []).slice(0, 3).map((m: any, i: number) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>• {String(m.subject || m.memory_id || '').slice(0, 160)}</div>
          ))}
        </>
      ) : (
        <span style={emptyStyle}>Durable memory not joined — this is not “no memories”, it is a wiring gap.</span>
      )}
      <div style={{ fontSize: 10.5, color: 'var(--text3)', margin: '8px 0 4px' }}>LEGACY ADVISORY THRASH (separated)</div>
      {d && typeof d === 'object' && Object.keys(d).length > 0 ? (
        <>
          {d.conviction != null && <Field label="Conviction (pre-thrash)" value={d.conviction_pre_thrash ?? d.conviction} />}
          {d.thrash_penalty != null && <Field label="Thrash penalty" value={Number(d.thrash_penalty).toFixed(2)} tone="var(--amber)" />}
          {d.prior_verdict && <Field label="Prior verdict" value={String(d.prior_verdict)} />}
        </>
      ) : (
        <span style={emptyStyle}>No legacy thrash object on this row.</span>
      )}
    </div>
  )
}

function SensesCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>Financial Senses not joined.</span>
  return (
    <div>
      <Field label="State" value={String(d.state || 'unavailable')} tone={qualityTone(d.state)} />
      <Field label="Summary" value={String(d.summary || d.reason || 'no current evidence')} />
      <Field label="Influence" value={String(d.influence_mode || 'OFF')} />
      <Field label="As of" value={fmtWhen(d.as_of) || 'no receipt'} />
    </div>
  )
}

function WatchIntelCard({ d, setup }: { d: any; setup?: string }) {
  if (!d || !d.available) {
    return <span style={emptyStyle}>Watch intelligence unavailable — {d?.reason || 'canonical projection not joined'}.</span>
  }
  const off = d.relative?.pct_off_52w_high
  return (
    <div>
      <Field label="Setup" value={setup || 'WATCH'} tone="var(--accent)" />
      {off != null && <Field label="Vs 52w high" value={fmtPct(-Math.abs(Number(off))) || String(off)} />}
      <FieldStateView label="Quote" fs={d.quote?.last} format={fmtPrice} />
      <Field label="Quote source" value={`${d.quote?.price_source || 'unavailable'} · ${d.quote?.freshness_state || ''} · ${fmtWhen(d.quote?.price_as_of) || ''}`} />
      <FieldStateView label="Trade AI" fs={d.trade_ai?.primary_state} />
      <Field label="Next action" value={String(d.trade_ai?.next_operator_action || 'unavailable')} />
      <Field label="Meaning" value={String(d.trade_ai?.operator_meaning || 'unavailable')} />
      <Field label="Primary risk" value={String(d.trade_ai?.primary_risk || 'unavailable')} />
      <FieldStateView label="Support" fs={d.technicals?.support} format={fmtPrice} />
      <FieldStateView label="Resistance" fs={d.technicals?.resistance} format={fmtPrice} />
      <FieldStateView label="RSI" fs={d.technicals?.rsi} format={(v) => v != null ? Number(v).toFixed(1) : null} />
      <FieldStateView label="RVOL" fs={d.technicals?.rvol} />
      <FieldStateView label="ATR" fs={d.technicals?.atr} />
      <FieldStateView label="Catalyst" fs={d.catalyst?.summary} />
      <FieldStateView label="Street" fs={d.street?.rating} />
      <FieldStateView label="Analysts" fs={d.street?.analyst_count} />
      <FieldStateView label="Target" fs={d.street?.target} format={fmtPrice} />
      <Field label="Target as of" value={d.street?.target_as_of ? `${String(d.street.target_as_of).slice(0, 10)} · ${d.street.target?.freshness || ''}` : 'unavailable'} />
      {d.why_wait && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6, lineHeight: 1.4 }}>Why: {String(d.why_wait)}</div>}
    </div>
  )
}

function ReentryCard({ d, row }: { d: any; row: DeskRow }) {
  if (!d || !d.available) {
    return <span style={emptyStyle}>Re-entry intelligence unavailable — {d?.reason || 'no decision-desk row'}.</span>
  }
  const state = d.state?.value || row.reentry_state || 'unavailable'
  return (
    <div>
      <Field label="State" value={String(state)} tone="var(--accent)" />
      <FieldStateView label="Current price" fs={d.price} format={fmtPrice} />
      <Field label="Entry zone" value={d.entry_zone_display || 'unavailable'} />
      <Field label="Distance" value={d.distance_label || 'unavailable'} />
      <FieldStateView label="RSI" fs={d.rsi} format={(v) => v != null ? Number(v).toFixed(1) : null} />
      <Field label="RSI band" value={d.rsi_band || '40–70'} />
      <Field label="Wash" value={String(d.wash_status || (d.wash_blocked ? 'BLOCKED' : 'CLEAR'))} />
      <FieldStateView label="Next action" fs={d.next_action} />
      <Field label="Why" value={String(d.why || d.reason || row.reentry_reason || 'unavailable')} />
      <Field label="As of" value={`${fmtWhen(d.as_of) || 'unavailable'} · ${d.freshness || ''}`} />
    </div>
  )
}

function OpinionCard({ d, label }: { d: any; label?: string }) {
  if (!d || typeof d !== 'object' || Object.keys(d).length === 0) {
    return <span style={emptyStyle}>No Flash row opinion — missing opinion is not HOLD. This row was not covered in the latest enrichment run.</span>
  }
  return (
    <div>
      {label && <div style={{ fontSize: 10.5, color: 'var(--amber)', marginBottom: 4 }}>{label}</div>}
      <Field label="Verdict" value={String(d.verdict || 'unavailable')} tone="var(--accent)" />
      <Field label="Conviction" value={d.conviction != null ? String(d.conviction) : 'unavailable'} />
      {d.what_changed && <div style={{ fontSize: 11.5, color: 'var(--text)', marginTop: 6 }}>{String(d.what_changed)}</div>}
      {d.rationale && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4 }}>{String(d.rationale)}</div>}
      {d.key_risk && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, lineHeight: 1.4 }}>Risk: {String(d.key_risk)}</div>}
      {d.model && <Field label="Model" value={String(d.model)} />}
    </div>
  )
}

function InstrumentCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No instrument identity.</span>
  return (
    <div>
      <Field label="Name" value={String(d.name || 'unavailable')} />
      <Field label="Type" value={String(d.type || 'unavailable')} />
      <Field label="Sector" value={String(d.sector || 'unavailable')} />
      <Field label="Exchange" value={String(d.exchange || 'unavailable')} />
      {d.listing_date && <Field label="Listed" value={String(d.listing_date).slice(0, 10)} />}
      {d.market_cap != null && <Field label="Market cap" value={fmtUSD(d.market_cap) || 'unavailable'} />}
    </div>
  )
}

function EvidenceCard({ items }: { items: any[] }) {
  if (!Array.isArray(items) || items.length === 0) return <span style={emptyStyle}>No evidence items attached.</span>
  return (
    <div>
      {items.slice(0, 12).map((it, i) => {
        const isAgent = it?.type === 'agent_opinion'
        const agent = it?.agent ? String(it.agent) : ''
        const rec = it?.recommendation ? ` — ${String(it.recommendation)}` : ''
        const label = isAgent
          ? `agent_opinion · ${agent || it?.source || 'unknown'}${rec}`
          : `${it?.type || 'evidence'}`
        const source = !isAgent && it?.source ? ` · ${String(it.source).slice(0, 40)}` : ''
        return (
          <div key={i} style={{ padding: '2px 0', fontSize: 11, color: 'var(--text2)' }}>
            • <span style={{ color: 'var(--text3)' }}>{label}</span>{source}
          </div>
        )
      })}
    </div>
  )
}

const emptyStyle: CSSProperties = { fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }
const miniTh: CSSProperties = { textAlign: 'left', padding: '3px 5px', fontSize: 10, color: 'var(--text3)', fontWeight: 600, borderBottom: '1px solid var(--border)' }
const miniTd: CSSProperties = { padding: '3px 5px', fontSize: 10.5, color: 'var(--text2)', borderBottom: '1px solid var(--border)' }

function Stamp({ label, at, fresh }: { label: string; at?: any; fresh?: string }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px', minWidth: 140 }}>
      <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700, letterSpacing: 0.3 }}>{label}</div>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: qualityTone(fresh) || 'var(--text)' }}>{fresh || 'n/a'}</div>
      <div style={{ fontSize: 10.5, color: 'var(--text2)' }}>{fmtWhen(at) || 'no timestamp'}{ageLabel(at) ? ` · ${ageLabel(at)}` : ''}</div>
    </div>
  )
}

function classHeadline(r: DeskRow) {
  if (r.row_class === 'watchlist') {
    const wi = r.watch_intelligence
    const last = wi?.quote?.last?.value
    const setup = r.setup_state || 'WATCH'
    return `${setup}${last != null ? ` · ${fmtPrice(last)}` : ''}`
  }
  if (r.row_class === 'closed_journal' || r.verdict === 'RE_ENTER') {
    const st = r.reentry?.state?.value || r.reentry_state
    const zone = r.reentry?.entry_zone_display
    return `${st || r.verdict}${zone ? ` · ${zone}` : ''}`
  }
  return r.verdict
}

export default function AdvisoryDeskHub({ onDrill }: Props) {
  const [cls, setCls] = useState<(typeof CLASSES)[number]>('all')
  const [watchFilter, setWatchFilter] = useState<string>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [feedbackMsg, setFeedbackMsg] = useState<string>('')
  const [showRemnants, setShowRemnants] = useState(false)
  const path = cls === 'all' ? '/api/v3/advisory' : `/api/v3/advisory?class=${cls}`
  const { data, loading, error, refetch } = useApi<any>(path, 60_000)

  const rows: DeskRow[] = useMemo(() => data?.rows ?? [], [data?.rows])
  const banners: Banner[] = useMemo(() => data?.banners ?? [], [data?.banners])
  const ts = data?.timestamps || {}
  const health = data?.desk_health || {}

  const visibleRows = useMemo(() => {
    let out = rows.filter(r =>
      r.row_class !== 'holding' || showRemnants || (r.market_value ?? 0) >= MATERIALITY_FLOOR,
    )
    if (cls === 'watchlist' || (cls === 'all' && watchFilter !== 'all')) {
      if (watchFilter !== 'all') {
        out = out.filter(r => r.row_class !== 'watchlist' || (r.watch_filters || []).includes(watchFilter))
      }
    }
    return [...out].sort((a, b) => {
      const ra = a.watch_rank ?? 50
      const rb = b.watch_rank ?? 50
      if (a.row_class === 'watchlist' && b.row_class === 'watchlist' && ra !== rb) return ra - rb
      return 0
    })
  }, [rows, showRemnants, cls, watchFilter])
  const hiddenRemnants = rows.filter(r => r.row_class === 'holding' && !showRemnants && (r.market_value ?? 0) < MATERIALITY_FLOOR).length

  async function postFeedback(kind: 'rate' | 'ack' | 'snooze', row: DeskRow, extra?: Record<string, string>) {
    try {
      const body: any = { symbol: row.symbol, row_id: row.row_id, ...extra }
      if (row.account) body.symbol = `${row.symbol}:${row.account}`
      const res = await fetch(`/api/v3/advisory/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const j = await res.json()
      setFeedbackMsg(j.ok ? `✓ ${kind} ${row.symbol}` : `✗ ${j.error || 'failed'}`)
      refetch?.()
    } catch (e: any) {
      setFeedbackMsg(`✗ ${e?.message || e}`)
    }
  }

  if (loading) return <div style={{ padding: 32, color: 'var(--text2)' }}>Loading advisory desk…</div>
  if (error) return <div style={{ padding: 32, color: 'var(--red)' }}>Advisory data unavailable: {String(error)}</div>

  const overall = String(health.overall || data?.desk_freshness_state || 'UNKNOWN')

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1360 }}>
      <div style={hubTitle()}>📋 Advisory Desk</div>
      <div style={hubSubtitle()}>
        READ_ONLY_ADVISORY · class-aware facts · watch intelligence · re-entry · durable memory
        <span style={{ color: qualityTone(overall) || 'var(--text3)', marginLeft: 16, fontWeight: 700 }}>
          {overall}
        </span>
        {data?.desk_cache_age_seconds != null && (
          <span style={{ color: 'var(--text3)', marginLeft: 10 }}>
            cache {Math.round(data.desk_cache_age_seconds)}s · {data.desk_freshness_state || ''}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '10px 0 12px' }}>
        <Stamp label="FACTS AS OF" at={ts.facts} fresh={ts.facts_freshness} />
        <Stamp label="WATCH INTEL" at={ts.watch} fresh={ts.watch_freshness} />
        <Stamp label="RE-ENTRY" at={ts.reentry} fresh={ts.reentry_freshness} />
        <Stamp label="SENSES" at={ts.senses} fresh={ts.senses_freshness} />
        <Stamp label="MEMORY" at={ts.memory} fresh={ts.memory_freshness} />
        <Stamp label="FLASH OPINION" at={ts.flash} fresh={ts.flash_freshness} />
        <Stamp label="PRO SYNTHESIS" at={ts.synthesis} fresh={ts.synthesis_freshness} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 8, margin: '0 0 16px' }}>
        {banners.map((b) => (
          <div
            key={b.id}
            data-testid={`banner-${b.id}`}
            style={{
              background: SEV_BG[b.severity] || 'var(--bg2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: 11, color: SEV_FG[b.severity] || 'var(--text3)', fontWeight: 600 }}>{b.id}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginTop: 2 }}>{b.title}</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>{b.detail}</div>
            {BANNER_ACTION[b.id] && (
              <div style={{ fontSize: 10.5, color: 'var(--accent)', marginTop: 4 }}>{BANNER_ACTION[b.id]}</div>
            )}
          </div>
        ))}
      </div>

      {data?.synthesis && (
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8,
          padding: 14, marginBottom: 16, fontSize: 13, lineHeight: 1.5, color: 'var(--text)',
        }}>
          <div style={{ fontSize: 11, color: ts.synthesis_label === 'PRIOR SYNTHESIS' ? 'var(--amber)' : 'var(--text3)', marginBottom: 6, fontWeight: 600 }}>
            {ts.synthesis_label || 'DESK SYNTHESIS'}
            {ts.synthesis ? ` · generated ${fmtWhen(ts.synthesis)} · age ${ageLabel(ts.synthesis) || '?'}` : ''}
          </div>
          {data.synthesis}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        {CLASSES.map((c) => (
          <button
            key={c}
            onClick={() => setCls(c)}
            style={{
              padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)',
              background: cls === c ? 'var(--accent)' : 'var(--bg2)',
              color: cls === c ? 'var(--text0)' : 'var(--text2)', cursor: 'pointer', fontSize: 12,
            }}
          >
            {c}{c !== 'all' && data?.by_class?.[c] != null ? ` (${data.by_class[c]})` : ''}
          </button>
        ))}
        <button
          onClick={() => setShowRemnants(v => !v)}
          title="Toggle sub-$500 close-out remnants"
          style={{
            padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)',
            background: showRemnants ? 'var(--bg2)' : 'var(--bg)', cursor: 'pointer', fontSize: 12,
            color: showRemnants ? 'var(--text2)' : 'var(--text)',
          }}
        >
          {showRemnants ? `Hide remnants` : `Show ${hiddenRemnants} remnants`}
        </button>
        <span style={{ fontSize: 12, color: 'var(--text3)', marginLeft: 8 }}>
          {visibleRows.length} shown · {data?.row_count ?? 0} rows · validation {data?.metadata?.validation_ok ? 'OK' : 'FAIL'}
        </span>
        {feedbackMsg && <span style={{ fontSize: 12, color: 'var(--green)', marginLeft: 8 }}>{feedbackMsg}</span>}
      </div>

      {(cls === 'watchlist' || cls === 'all') && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          {WATCH_FILTERS.map(([id, label]) => (
            <button
              key={id}
              onClick={() => setWatchFilter(id)}
              style={{
                padding: '3px 8px', borderRadius: 999, border: '1px solid var(--border)',
                background: watchFilter === id ? 'var(--bg2)' : 'var(--bg)',
                color: 'var(--text2)', cursor: 'pointer', fontSize: 11,
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg2)', textAlign: 'left' }}>
              {['Symbol', 'Class', 'State', 'Conf', 'Now', 'Quality', 'Why', ''].map((h) => (
                <th key={h} style={{ padding: '8px 10px', color: 'var(--text3)', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((r) => {
              const key = `${r.symbol}:${r.account || ''}:${r.advisory_row_hash || ''}`
              const open = expanded === key
              const dq = r.data_quality || {}
              const headline = r.why_call || (r.rationale_signals || [])[0] || r.rationale || 'no rationale attached'
              return (
                <Fragment key={key}>
                  <tr
                    style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                    onClick={() => setExpanded(open ? null : key)}
                    data-testid={`row-${r.symbol}`}
                  >
                    <td style={{ padding: '8px 10px', fontWeight: 600 }}>{r.symbol}
                      {r.account ? <div style={{ fontSize: 10, color: 'var(--text3)' }}>{r.account}</div> : null}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text2)' }}>{r.row_class}</td>
                    <td style={{ padding: '8px 10px', fontWeight: 700, color: VERDICT_COLOR[r.verdict] || 'var(--text)' }}
                      title={VERDICT_HELP[r.verdict]}>
                      {r.verdict}
                      {r.setup_state && r.row_class === 'watchlist' && (
                        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)' }}>{r.setup_state}</div>
                      )}
                      {r.reentry_state && (r.row_class === 'closed_journal' || r.verdict === 'RE_ENTER') && (
                        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)' }}>{r.reentry_state}</div>
                      )}
                    </td>
                    <td style={{ padding: '8px 10px' }}>{r.confidence != null ? Number(r.confidence).toFixed(2) : 'n/a'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text2)' }}>{classHeadline(r)}</td>
                    <td style={{ padding: '8px 10px' }} data-testid="data-quality">
                      ev {dq.evidence_count ?? 0}
                      {dq.gap_count ? ` · gaps ${dq.gap_count}` : ''}
                      {dq.action_suppressed ? <span style={{ color: 'var(--red)', fontWeight: 700 }}> · DATA CONFLICT</span>
                        : dq.quality ? ` · ${dq.quality}` : ''}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text2)', maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={headline}>
                      {headline}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text3)' }}>{open ? '▾' : '▸'}</td>
                  </tr>
                  {open && (
                    <tr style={{ background: 'var(--bg2)' }}>
                      <td colSpan={8} style={{ padding: 14 }}>
                        {(() => {
                          const facts = r.expand?.canonical_financial_facts || r.canonical_financial_facts
                          const fieldStates = r.expand?.field_states || r.field_states
                          const prov = r.expand?.advisory_provenance || r.advisory_provenance
                          const wi = r.expand?.watch_intelligence || r.watch_intelligence
                          const re = r.expand?.reentry || r.reentry
                          const durable = r.expand?.durable_memory || r.durable_memory
                          const senses = r.expand?.financial_senses || r.financial_senses
                          const conflicts: string[] = [
                            ...((dq.conflicts as string[]) || []),
                            ...((facts?.conflicts as string[]) || []),
                            ...((prov?.conflicts as string[]) || []),
                          ].filter((c, i, a) => c && a.indexOf(c) === i)
                          const suppressed = Boolean(dq.action_suppressed || facts?.action_suppressed || prov?.action_suppressed || conflicts.length)
                          const synthesis = prov?.opinion_synthesis
                          const holdingish = r.row_class === 'holding'
                          const watchish = r.row_class === 'watchlist'
                          const reish = r.row_class === 'closed_journal' || r.verdict === 'RE_ENTER'
                          return (
                            <>
                              {suppressed && (
                                <div style={{
                                  background: 'var(--red-ghost)', border: '1px solid var(--red)',
                                  borderRadius: 6, padding: '8px 10px', marginBottom: 10,
                                  color: 'var(--red)', fontSize: 12, fontWeight: 700,
                                }}>
                                  DATA CONFLICT — ACTION SUPPRESSED
                                  <div style={{ fontWeight: 500, marginTop: 4, color: 'var(--text2)', fontSize: 11, lineHeight: 1.4 }}>
                                    {conflicts.filter(c => c !== 'DATA CONFLICT — ACTION SUPPRESSED').join(' · ') || 'Mark / MV / target denominators disagree.'}
                                  </div>
                                </div>
                              )}
                              {r.why_call && (
                                <div style={{
                                  background: 'var(--bg)', border: '1px solid var(--border)',
                                  borderRadius: 6, padding: '8px 10px', marginBottom: 10,
                                  fontSize: 12, color: 'var(--text)', lineHeight: 1.4,
                                }}>
                                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text3)', letterSpacing: 0.3, marginBottom: 4 }}>
                                    WHY THIS CALL
                                  </div>
                                  {r.why_call}
                                </div>
                              )}
                              {synthesis && (
                                <div style={{
                                  background: 'var(--bg)', border: '1px solid var(--border)',
                                  borderRadius: 6, padding: '8px 10px', marginBottom: 10,
                                  fontSize: 12, color: 'var(--text)', lineHeight: 1.4,
                                }}>
                                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text3)', letterSpacing: 0.3, marginBottom: 4 }}>OPINION SYNTHESIS</div>
                                  {synthesis}
                                </div>
                              )}
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
                                {watchish && cardWrap('Watch intelligence', <WatchIntelCard d={wi} setup={r.setup_state} />)}
                                {reish && cardWrap('Re-entry', <ReentryCard d={re} row={r} />)}
                                {cardWrap('Current financial facts', <CurrentFinancialFactsCard d={facts} fieldStates={fieldStates} />)}
                                {holdingish && cardWrap('Lots', <LotsCard d={r.expand?.lots} fieldStates={fieldStates} />)}
                                {holdingish && cardWrap('Price action', <PriceActionCard d={r.expand?.price_action} />)}
                                {holdingish && cardWrap('Analyst', <AnalystCard d={r.expand?.analyst} />)}
                                {cardWrap('Memory', <MemoryCard d={r.expand?.memory} durable={durable} />)}
                                {cardWrap('Financial senses', <SensesCard d={senses} />)}
                                {cardWrap('Opinion', <OpinionCard d={r.expand?.opinion} label={ts.synthesis_label === 'PRIOR SYNTHESIS' ? 'PRIOR SYNTHESIS — not current desk synthesis' : undefined} />)}
                                {cardWrap('Instrument', <InstrumentCard d={r.expand?.instrument} />)}
                                {cardWrap('Evidence', <EvidenceCard items={r.expand?.evidence_items || []} />)}
                              </div>
                            </>
                          )
                        })()}
                        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          <button type="button" style={btnStyle} onClick={(e) => { e.stopPropagation(); postFeedback('ack', r) }}>Ack</button>
                          <button type="button" style={btnStyle} onClick={(e) => { e.stopPropagation(); postFeedback('snooze', r) }}>Snooze</button>
                          <button type="button" style={btnStyle} onClick={(e) => { e.stopPropagation(); postFeedback('rate', r, { rating: 'useful' }) }}>Useful</button>
                          <button type="button" style={btnStyle} onClick={(e) => {
                            e.stopPropagation()
                            postFeedback('rate', r, { rating: 'notuseful', reason_code: 'DISAGREE_THESIS', note: 'held through' })
                          }}>Not useful · DISAGREE_THESIS</button>
                          {onDrill && (
                            <button type="button" style={btnStyle} onClick={(e) => {
                              e.stopPropagation()
                              onDrill({ title: r.symbol, subtitle: r.verdict, endpoint: '/api/v3/advisory', rows: [r] })
                            }}>Drill</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {visibleRows.length === 0 && (
              <tr><td colSpan={8} style={{ padding: 16, color: 'var(--text3)', textAlign: 'center' }}>No rows in this class / filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const btnStyle: CSSProperties = {
  padding: '5px 10px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg)',
  color: 'var(--text2)',
  cursor: 'pointer',
  fontSize: 12,
}
