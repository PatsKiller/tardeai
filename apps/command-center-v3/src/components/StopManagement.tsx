import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AgeChip, LadderLine } from './primitives/cardPrimitives'
import { WL } from '../lib/watchlistCardTokens'
import HoldingProtectionActions from './HoldingProtectionActions'
import { mergeLiveStop } from '../lib/stopReviewTooltip'
import { EvidenceBlock } from './EvidenceBlock'
import CloudLlmRunButtons from './CloudLlmRunButtons'
import { useTerminalUi } from '../lib/terminalUi'
import { hubPanel } from '../lib/terminalHubChrome'
import { StopKindPill } from './StopKindPill'

// Portfolio → Stop Management. Aggregates broker-actual + advisor-planned stops with Yellow/Amber/Red alerts,
// plus an Audit sub-tab (2FA stop requests + operator confirmations). Read-only view; live adjustments route
// through the holding's existing gated 2FA panel (Schwab) or manual ticket (Fidelity) via onFocusHolding.
// See docs/MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md.

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', RED = '#ef4444', BLUE = '#60a5fa', PURPLE = '#a855f7'
// StopKindPill (FIXED / STOP_LIMIT / TRAILING / TRAILING_LIMIT / MONITORED / NONE) is now a shared
// component in ./StopKindPill so the Holdings table renders the identical pill — imported above.
const unwrap = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j
const LEVEL_COLOR: Record<string, string> = { red: RED, amber: AMBER, yellow: '#eab308' }
const SRC_LABEL: Record<string, string> = { broker: 'broker live', confirmed: 'confirmed', broker_snapshot: 'broker (last read)', monitored: 'monitored', planned: 'planned', none: '—' }
const fmt$ = (n: any) => n == null ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
const fmtStop = (n: any) => n == null ? '—' : `$${Number(n).toFixed(2)}`
const fmtTime = (s: any) => { if (!s) return '—'; const d = new Date(s); return isNaN(+d) ? String(s).slice(0, 16) : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }

interface Props {
  onFocusHolding?: (symbol: string, account: string) => void
  /** URL-synced portfolio account filter (`?acct=`). null / omitted = All. */
  accountFilter?: string | null
  onAccountFilter?: (account: string | null) => void
}

type Row = {
  symbol: string; account: string; broker: string; route: string; stop_type: string; stop_source: string
  stop_kind?: string | null; order_type?: string | null
  current_price: number; qty: number; stop_qty?: number | null; coverage?: string | null
  broker_stop: number | null; planned_stop: number | null; stop: number
  divergence: string | null; distance_pct: number | null; distance_atr: number | null; distance_r: number | null
  distance_dollars?: number | null; unrealized_r?: number | null
  news_title?: string | null; news_source?: string | null; news_at?: string | null
  dollars_at_risk: number; unrealized_dollars: number | null; pl_if_fired?: number | null; has_active_stop: boolean
  is_trailing: boolean; trailing_should_be_active: boolean; heat_contribution_pct: number | null
  trail_pct: number | null; trailing_trigger: number | null
  trail_recommended: boolean; rec_source: string | null; rec_model: string | null; rec_rationale: string | null
  alert_level: 'red' | 'amber' | 'yellow' | null; alert_reasons: string[]
  direction?: 'long' | 'short'; narrative?: string | null; next_action?: string | null; projection?: string | null
  rec_evidence?: unknown[]; rec_data_i_doubt?: string | null
  rec_at?: string | null; holdings_llm_at?: string | null; next_earnings_date?: string | null
  stop_curation?: { grade?: string; recommendation?: string; rr_assessment?: string; evidence?: unknown[]; data_i_doubt?: string | null; summary?: string } | null
  holdings_llm_health?: string | null; holdings_llm_evidence?: unknown[]; holdings_llm_data_i_doubt?: string | null
  consensus_target_mean?: number | null; consensus_target_high?: number | null; consensus_target_low?: number | null
  consensus_analysts?: number | null; consensus_stale?: boolean
  price_vs_consensus_pct?: number | null; price_vs_consensus_dollars?: number | null; price_above_consensus?: boolean
  stop_above_consensus?: boolean; consensus_gap_pct?: number | null; stop_vs_consensus_pct?: number | null
  regime?: string | null; regime_now?: string | null; regime_label?: string | null; regime_short?: string | null; regime_confidence?: number | null
  regime_at_entry?: string | null; regime_shift_detected?: boolean; regime_shift_direction?: string | null
  regime_explanation?: string | null; trail_tighten_atr_mult?: number | null
  policy_suggestions?: string[]; stoplight_thresholds_used?: { regime?: string; yellow_r?: number; amber_r?: number; red_r?: number } | null
}

// Days until a date-only string (parsed LOCAL — UTC parsing shifts to the prior evening ET).
function daysUntil(d: string | null | undefined): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d ?? ''))
  if (!m) return null
  return Math.round((new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12).getTime() - Date.now()) / 864e5)
}

// TZ-naive server timestamps parse as LOCAL and render negative ages east of UTC — normalize to
// an explicit-UTC ISO string first (same approach as BrokerProposalCard.isoTs).
function parseTs(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const s = String(iso).trim()
  if (!s) return null
  const norm = s.includes('T') ? s : s.replace(' ', 'T')
  const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(norm) ? norm : `${norm}Z`)
  return isNaN(d.getTime()) ? null : d
}

function isoTs(iso: string | null | undefined): string | undefined {
  const d = parseTs(iso)
  return d ? d.toISOString() : undefined
}

function ageHours(ts: string | null | undefined): number | null {
  const d = parseTs(ts)
  return d ? (Date.now() - d.getTime()) / 3_600_000 : null
}

function ageLabel(h: number): string {
  return h < 48 ? `${Math.round(h)}h` : `${Math.floor(h / 24)}d`
}

function rowHasReasons(r: Row): boolean {
  const earnDays = daysUntil(r.next_earnings_date)
  return Boolean(
    r.narrative
    || (earnDays != null && earnDays >= 0 && earnDays <= 7)
    || (r.alert_reasons?.length ?? 0) > 0
    || (r.policy_suggestions?.length ?? 0) > 0
    || r.next_action
    || (r.rec_evidence?.length ?? 0) > 0
    || (r.rec_data_i_doubt && r.rec_data_i_doubt !== 'none')
    || r.stop_curation?.grade
    || (r.stop_curation?.evidence?.length ?? 0) > 0
    || (r.holdings_llm_evidence?.length ?? 0) > 0,
  )
}

// ---- Expanded-row panel (Phase C): thin banner + 2×2 module grid. Restructures the old loose
// "Reasons" stack — ALL prior content (narrative/alert reasons, exit ladder, age chips, earnings
// warning, policy, next_action, advisory evidence, Grok curation, holdings health evidence) is
// preserved inside the four modules below. rowHasReasons() gating is unchanged.

const MOD_LABEL = {
  fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.09em',
  color: WL.text.dim, marginBottom: 6,
} as const

function KV({ k, title, children }: { k: string; title?: string; children: ReactNode }) {
  return (
    <div style={{ fontSize: 11, lineHeight: 1.55, color: WL.text.secondary }} title={title}>
      <span style={{ color: WL.text.dim }}>{k} </span>{children}
    </div>
  )
}

type BannerTone = 'red' | 'amber' | 'quiet'
const BANNER_TONE: Record<BannerTone, { bg: string; border: string; accent: string }> = {
  red: { bg: 'rgba(239,83,80,.07)', border: 'rgba(239,83,80,.25)', accent: WL.signal.red },
  amber: { bg: 'rgba(245,166,35,.07)', border: 'rgba(245,166,35,.25)', accent: WL.signal.amber },
  quiet: { bg: 'transparent', border: 'rgba(148,163,184,.14)', accent: WL.text.secondary },
}

/** Banner priority: no stop → REVIEW-looser → earnings ≤7d → stale advisory → quiet protected. */
function bannerFor(r: Row): { word: string; tone: BannerTone; text: string } {
  const earnDays = daysUntil(r.next_earnings_date)
  const advAge = ageHours(r.rec_at)
  if (!r.has_active_stop) {
    return {
      word: 'NO STOP', tone: 'red',
      text: r.planned_stop != null
        ? `advised ${fmtStop(r.planned_stop)} is not placed at the broker — ${fmt$(r.dollars_at_risk)} rides unprotected`
        : 'no broker stop and no advised stop on this position',
    }
  }
  if (r.divergence && /looser/i.test(r.divergence)) {
    return { word: 'REVIEW', tone: 'amber',
      text: `broker stop ${fmtStop(r.broker_stop)} is looser than advised ${fmtStop(r.planned_stop)} — tighten to plan` }
  }
  if (earnDays != null && earnDays >= 0 && earnDays <= 7) {
    return { word: `EARNINGS ${earnDays}d`, tone: 'amber',
      text: 'price can gap through the stop overnight — review size/stop before the print' }
  }
  if (advAge != null && advAge > 48) {
    return { word: 'REVIEW', tone: 'amber',
      text: `stop advisory ${ageLabel(advAge)} old — levels may not reflect current price/ATR` }
  }
  return {
    word: r.stop_source === 'monitored' ? 'MONITORED' : 'PROTECTED', tone: 'quiet',
    text: `${r.is_trailing ? 'trailing' : (r.stop_type || 'stop').toLowerCase()} stop ${fmtStop(r.broker_stop)}${r.distance_pct != null ? ` · ${r.distance_pct}% below price` : ''}`,
  }
}

function ReasonsSubRow({ r }: { r: Row }) {
  const earnDays = daysUntil(r.next_earnings_date)
  const earnSoon = earnDays != null && earnDays >= 0 && earnDays <= 7
  const advAge = ageHours(r.rec_at)
  const healthAge = ageHours(r.holdings_llm_at)
  const newsAge = ageHours(r.news_at)
  // Exit ladder for a held long: T1 = +1R off the effective stop, T2 = Street mean, T3 = Street high.
  const _stopRef = r.broker_stop ?? r.planned_stop
  const _rps = _stopRef && r.current_price > _stopRef ? r.current_price - _stopRef : null
  const ladder = (r.direction !== 'short' && _rps && r.consensus_target_mean && r.consensus_target_mean > r.current_price)
    ? [
        { label: 'T1', px: r.current_price + _rps, action: 'sell ⅓ at +1R' },
        { label: 'T2', px: r.consensus_target_mean, action: 'sell ⅓ at Street mean' },
        ...(r.consensus_target_high ? [{ label: 'T3', px: r.consensus_target_high, action: 'runner to Street high' }] : []),
      ]
    : null
  const banner = bannerFor(r)
  const tone = BANNER_TONE[banner.tone]
  const looser = Boolean(r.divergence && /looser/i.test(r.divergence))
  return (
    <div style={{ fontSize: 10.5, color: MUTED, lineHeight: 1.45, maxWidth: '100%', padding: '4px 0 2px' }}>
      {/* Banner — verdict word + the one sentence that matters. Tinted only when amber/red. */}
      <div style={{
        display: 'flex', gap: 10, alignItems: 'baseline', minWidth: 0, borderRadius: 6,
        padding: '5px 10px', marginBottom: 8, background: tone.bg, border: `1px solid ${tone.border}`,
      }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.11em', color: tone.accent, whiteSpace: 'nowrap' }}>{banner.word}</span>
        <span title={banner.text} style={{ fontSize: 11, color: WL.text.secondary, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{banner.text}</span>
      </div>

      {/* 2×2 module grid — collapses to a single column when the table gets narrow. */}
      <div style={{ display: 'grid', gap: '10px 26px', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 460px), 1fr))' }}>
        <div style={{ minWidth: 0 }}>
          <div style={MOD_LABEL}>Protection</div>
          <KV k="Advised" title={r.rec_rationale || undefined}>
            <span style={{ color: WL.text.primary, fontWeight: 700 }}>{fmtStop(r.planned_stop)}</span>
            {r.rec_rationale ? <span style={{ color: WL.text.dim }}> · {r.rec_rationale.length > 96 ? `${r.rec_rationale.slice(0, 95)}…` : r.rec_rationale}</span> : null}
          </KV>
          <KV k="Broker">
            <span style={{ color: WL.text.primary, fontWeight: 700 }}>{fmtStop(r.broker_stop)}</span>
            {' vs advised '}{fmtStop(r.planned_stop)}
            {looser ? <span style={{ color: WL.signal.amber, fontWeight: 700 }}> · looser ⚠</span> : null}
            {!looser && r.divergence ? <span style={{ color: WL.text.dim }}> · {r.divergence}</span> : null}
          </KV>
          <KV k="Type">
            {r.stop_type}{r.is_trailing && r.trail_pct != null ? ` · trailing ${r.trail_pct}%` : ''}
            {r.trailing_trigger != null ? ` (≈${fmtStop(r.trailing_trigger)})` : ''}
          </KV>
          <KV k="Distance">
            {r.distance_pct != null ? `${r.distance_pct}%` : '—'}
            {r.distance_dollars != null ? ` · ${fmt$(r.distance_dollars)}` : ''}
            {r.distance_atr != null ? ` · ${r.distance_atr} ATR` : ''}
            {r.distance_r != null ? ` · ${r.distance_r}R` : ''}
          </KV>
          <KV k="At risk"><span style={{ color: WL.text.primary, fontWeight: 700 }}>{fmt$(r.dollars_at_risk)}</span></KV>
          {(advAge != null || r.rec_model) && (
            <KV k="Advisory">
              {advAge != null ? <AgeChip ts={isoTs(r.rec_at)} prefix="" warnAfterHours={48} /> : '—'}
              {r.rec_model ? <span style={{ color: WL.text.dim }}> · {r.rec_model}</span> : null}
            </KV>
          )}
        </div>

        <div style={{ minWidth: 0 }}>
          <div style={MOD_LABEL}>Exit Plan</div>
          {ladder ? (
            <LadderLine steps={ladder} stepTooltip={(l, px, a) => `${l} $${px.toFixed(2)} — ${a}`} style={{ marginTop: 0 }} />
          ) : (
            <div style={{ fontSize: 11, color: WL.text.dim }}>no ladder — needs an effective stop below price and a Street mean above it</div>
          )}
          <div style={{ fontSize: 11, color: WL.text.secondary, marginTop: 5 }}>
            {r.consensus_target_mean != null ? (
              <>Street μ <span style={{ color: WL.text.primary, fontWeight: 700 }}>{fmtStop(r.consensus_target_mean)}</span>
                {(r.consensus_target_low != null || r.consensus_target_high != null) ? <span> · {fmtStop(r.consensus_target_low)}–{fmtStop(r.consensus_target_high)}</span> : null}
                {r.consensus_analysts ? <span style={{ color: WL.text.dim }}> · {r.consensus_analysts} analysts</span> : null}
                {r.consensus_stale ? <span style={{ color: WL.signal.amber }}> · stale</span> : null}</>
            ) : <span style={{ color: WL.text.dim }}>no Street coverage</span>}
          </div>
        </div>

        <div style={{ minWidth: 0 }}>
          <div style={MOD_LABEL}>Health</div>
          <KV k="Verdict">
            <span style={{ color: WL.text.primary, fontWeight: 700 }}>{r.holdings_llm_health || '—'}</span>
            {healthAge != null ? <span style={{ color: WL.text.dim }}> · <AgeChip ts={isoTs(r.holdings_llm_at)} prefix="checked" warnAfterHours={72} /></span> : null}
          </KV>
          <KV k="Unrealized">
            <span style={{ color: (r.unrealized_dollars ?? 0) >= 0 ? WL.price.up : WL.price.down, fontWeight: 700 }}>
              {r.unrealized_dollars != null ? fmt$(r.unrealized_dollars) : '—'}
            </span>
            {r.unrealized_r != null ? ` · ${r.unrealized_r}R` : ''}
          </KV>
          <KV k="Heat">
            {r.heat_contribution_pct != null ? `${r.heat_contribution_pct}% of portfolio heat` : '—'}
            {r.regime_now ? <span style={{ color: WL.text.dim }}> · regime {r.regime_now}</span> : null}
          </KV>
          {((r.holdings_llm_evidence?.length ?? 0) > 0 || (r.holdings_llm_data_i_doubt && r.holdings_llm_data_i_doubt !== 'none')) && (
            <EvidenceBlock title={r.holdings_llm_health ? `Holdings health · ${r.holdings_llm_health}` : 'Holdings LLM evidence'} evidence={r.holdings_llm_evidence} dataIDoubt={r.holdings_llm_data_i_doubt} compact maxItems={2} />
          )}
        </div>

        <div style={{ minWidth: 0 }}>
          <div style={MOD_LABEL}>Context</div>
          {earnSoon ? (
            <div style={{ color: WL.signal.amber, fontWeight: 700, fontSize: 11, marginBottom: 3 }}>
              ⚠ earnings in {earnDays}d — price can gap through the stop overnight; review size/stop before the print
            </div>
          ) : (earnDays != null && earnDays > 0 ? <KV k="Earnings">in {earnDays}d</KV> : null)}
          <KV k="News" title={r.news_title || undefined}>
            {r.news_title ? (
              <>
                <span style={{ color: WL.text.dim }}>{r.news_source || 'news'}{newsAge != null && newsAge >= 0 ? ` · ${ageLabel(newsAge)} ago` : ''} </span>
                {r.news_title.length > 110 ? `${r.news_title.slice(0, 109)}…` : r.news_title}
              </>
            ) : <span style={{ color: WL.text.dim }}>no indexed news (7d)</span>}
          </KV>
          {r.narrative ? <div style={{ color: TEXT0, fontSize: 11, marginTop: 3 }}>{r.narrative}</div>
            : (r.alert_reasons?.length ? <div style={{ marginTop: 3 }}>{r.alert_reasons.join(' · ')}</div> : null)}
          {(r.policy_suggestions?.length ?? 0) > 0 && (
            <div style={{ marginTop: 4, fontWeight: 800, color: PURPLE }}>Policy: {r.policy_suggestions!.join(' · ')}</div>
          )}
          {r.next_action ? (
            <div style={{ marginTop: 4, fontWeight: 700,
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
        </div>
      </div>
    </div>
  )
}

type NextAction = { symbol: string; account: string; alert_level: Row['alert_level']; action: string | null; projection: string | null; dollars_at_risk: number | null }

function Card({ label, value, color = TEXT0, sub, terminalUi }: { label: string; value: string; color?: string; sub?: string; terminalUi?: boolean }) {
  return (
    <div style={{ flex: '1 1 150px', ...hubPanel(!!terminalUi), background: terminalUi ? undefined : 'var(--bg2, rgba(15,23,42,.6))' }}>
      <div style={{ fontSize: terminalUi ? 9 : 11, color: MUTED, fontWeight: 700, marginBottom: terminalUi ? 2 : 4 }}>{label}</div>
      <div style={{ fontSize: terminalUi ? 16 : 21, fontWeight: 900, color }}>{value}</div>
      {sub && <div style={{ fontSize: terminalUi ? 9 : 10.5, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

/** Primary operator filters — scannable institutional desk views. */
const QUICK = [
  'All',
  'Needs Action',
  'Partial Coverage',
  'No Stop',
  'All Protected',
  'Trailing Stops',
  'Trailing Eligible',
  'High Heat',
  'Regime Shift',
] as const

const STOPS_CACHE_KEY = 'cc-v3-stops-management-v1'

// ── Position status (semantic color + why) ────────────────────────────────────

type StatusKind = 'needs_attention' | 'partial' | 'no_stop' | 'protected' | 'monitored' | 'review'

type PositionStatus = {
  kind: StatusKind
  label: string
  color: string
  why: string
  sort: number // lower = more urgent
}

function derivePositionStatus(r: Row): PositionStatus {
  if (!r.has_active_stop) {
    return {
      kind: 'no_stop',
      label: 'NO STOP',
      color: RED,
      why: r.planned_stop != null
        ? `Advised ${fmtStop(r.planned_stop)} is not placed — ${fmt$(r.dollars_at_risk)} unprotected`
        : 'No live broker stop on this lot',
      sort: 0,
    }
  }
  if (r.coverage === 'partial') {
    return {
      kind: 'partial',
      label: 'PARTIAL',
      color: AMBER,
      why: `Stop covers ${r.stop_qty ?? '—'}/${r.qty} sh — ${Number(r.qty) - Number(r.stop_qty || 0)} sh unprotected after size-up`,
      sort: 1,
    }
  }
  if (r.coverage === 'oversized') {
    return {
      kind: 'needs_attention',
      label: 'OVERSIZED',
      color: RED,
      why: `Stop ${r.stop_qty} sh > held ${r.qty} — may short/reject excess on trigger`,
      sort: 1,
    }
  }
  if (r.alert_level === 'red') {
    return {
      kind: 'needs_attention',
      label: 'NEEDS ATTENTION',
      color: RED,
      why: (r.alert_reasons?.[0] || r.next_action || 'Red stoplight — review stop distance or risk').slice(0, 140),
      sort: 2,
    }
  }
  if (r.divergence && /looser/i.test(r.divergence)) {
    return {
      kind: 'review',
      label: 'REVIEW',
      color: AMBER,
      why: `Broker stop looser than advised (${fmtStop(r.broker_stop)} vs ${fmtStop(r.planned_stop)})`,
      sort: 3,
    }
  }
  if (r.alert_level === 'amber' || r.trailing_should_be_active) {
    return {
      kind: 'review',
      label: r.trailing_should_be_active ? 'TRAIL ELIGIBLE' : 'REVIEW',
      color: AMBER,
      why: r.trailing_should_be_active
        ? 'Gains support a trailing stop — not yet active at broker'
        : (r.alert_reasons?.[0] || 'Amber stoplight — moderate concern').slice(0, 140),
      sort: 4,
    }
  }
  if (r.stop_source === 'monitored') {
    return {
      kind: 'monitored',
      label: 'MONITORED',
      color: BLUE,
      why: 'Software-monitored / Fidelity recorded stop — not a live Schwab GTC',
      sort: 6,
    }
  }
  return {
    kind: 'protected',
    label: 'PROTECTED',
    color: GREEN,
    why: `${r.is_trailing ? 'Trailing' : (r.stop_type || 'Fixed')} stop live${r.distance_pct != null ? ` · ${r.distance_pct}% below price` : ''}`,
    sort: 8,
  }
}

type PrimaryCta = {
  label: string
  autoStage: boolean
  tone: 'amber' | 'green' | 'blue' | 'red'
  reason: string
  secondary?: string
}

function derivePrimaryCta(r: Row): PrimaryCta {
  const isFid = r.account.startsWith('fidelity')
  const via = isFid ? 'manual ticket' : '2FA'
  if (r.coverage === 'partial') {
    return {
      label: `Replace to full ${Math.floor(r.qty)} sh via ${via}`,
      autoStage: true,
      tone: 'amber',
      reason: `Stop only covers ${r.stop_qty}/${r.qty} shares — GTC does not auto-resize after buys`,
      secondary: 'Adjust stop…',
    }
  }
  if (r.coverage === 'oversized') {
    return {
      label: `Resize stop to ${Math.floor(r.qty)} sh via ${via}`,
      autoStage: true,
      tone: 'red',
      reason: `Stop qty ${r.stop_qty} exceeds held ${r.qty}`,
      secondary: 'Adjust stop…',
    }
  }
  if (!r.has_active_stop && r.planned_stop != null) {
    if (r.trail_recommended || r.trailing_should_be_active) {
      const trailBit = r.trail_pct != null ? ` ${r.trail_pct}%` : ''
      return {
        label: `Set trailing${trailBit} via ${via}`,
        autoStage: true,
        tone: 'amber',
        reason: r.rec_rationale || 'No live stop — advisory recommends trail',
        secondary: 'Adjust stop…',
      }
    }
    return {
      label: `Set stop ${fmtStop(r.planned_stop)} via ${via}`,
      autoStage: true,
      tone: 'amber',
      reason: r.rec_rationale || `Advised fixed stop not placed — ${fmt$(r.dollars_at_risk)} at risk`,
      secondary: 'Adjust stop…',
    }
  }
  if (r.trailing_should_be_active) {
    const trailBit = r.trail_pct != null ? ` ${r.trail_pct}%` : ''
    return {
      label: `Trail${trailBit} via ${via}`,
      autoStage: true,
      tone: 'green',
      reason: 'Position is trail-eligible; fixed stop still on book',
      secondary: 'Adjust stop…',
    }
  }
  if (r.divergence && /looser/i.test(r.divergence) && r.planned_stop != null) {
    return {
      label: `Tighten to ${fmtStop(r.planned_stop)}`,
      autoStage: false,
      tone: 'amber',
      reason: 'Broker stop is looser than plan — review before replace',
      secondary: 'Open adjust…',
    }
  }
  if (r.alert_level === 'red' || r.alert_level === 'amber') {
    return {
      label: 'Review & adjust stop',
      autoStage: false,
      tone: r.alert_level === 'red' ? 'red' : 'amber',
      reason: r.next_action && !/^(Monitor|None)/.test(r.next_action)
        ? r.next_action
        : (r.alert_reasons?.[0] || 'Stoplight flag — open adjust panel'),
      secondary: 'Open adjust…',
    }
  }
  return {
    label: 'Adjust stop',
    autoStage: false,
    tone: 'blue',
    reason: r.next_action && !/^(Monitor|None)/.test(r.next_action)
      ? r.next_action
      : 'Protected — optional adjust / trail / replace',
  }
}

const CTA_TONE: Record<PrimaryCta['tone'], { bg: string; border: string; color: string }> = {
  amber: { bg: `${AMBER}22`, border: AMBER, color: AMBER },
  green: { bg: `${GREEN}20`, border: GREEN, color: GREEN },
  blue: { bg: `${BLUE}18`, border: BLUE, color: BLUE },
  red: { bg: `${RED}20`, border: RED, color: RED },
}

function StatusBadge({ status }: { status: PositionStatus }) {
  return (
    <span
      title={status.why}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        fontSize: 10, fontWeight: 900, letterSpacing: '.06em',
        color: status.color, background: `${status.color}18`,
        border: `1px solid ${status.color}66`, borderRadius: 6,
        padding: '3px 8px', whiteSpace: 'nowrap',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: status.color, flexShrink: 0 }} />
      {status.label}
    </span>
  )
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{
      fontSize: 9.5, fontWeight: 800, letterSpacing: '.1em', textTransform: 'uppercase',
      color: MUTED, marginBottom: 6,
    }}>
      {children}
    </div>
  )
}

/** Compact terminal strip + expandable depth. Protected lots stay one line; needs-action opens the plan. */
function HoldingStopCard({
  r, expanded, onToggle, onPrimary, onSecondary, onFocus,
}: {
  r: Row
  expanded: boolean
  onToggle: () => void
  onPrimary: (auto: boolean) => void
  onSecondary: () => void
  onFocus?: (s: string, a: string) => void
}) {
  const status = derivePositionStatus(r)
  const cta = derivePrimaryCta(r)
  const tone = CTA_TONE[cta.tone]
  const urgent = status.kind === 'no_stop' || status.kind === 'partial' || status.kind === 'needs_attention'
    || status.kind === 'review'
  const showPlan = expanded || urgent


  const coverageLabel = r.coverage === 'partial'
    ? `${r.stop_qty}/${r.qty} sh`
    : r.coverage === 'oversized'
      ? `${r.stop_qty}/${r.qty} sh`
      : r.has_active_stop
        ? (r.stop_qty != null ? `${r.stop_qty} sh` : 'full')
        : '—'

  const chip = (label: string, value: string, color = MUTED) => (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 1, minWidth: 64,
      padding: '4px 8px', borderRadius: 6,
      background: 'rgba(0,0,0,.22)', border: '1px solid rgba(148,163,184,.1)',
    }}>
      <span style={{ fontSize: 8.5, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: MUTED }}>{label}</span>
      <span style={{ fontSize: 12.5, fontWeight: 800, fontFamily: 'ui-monospace, Menlo, monospace', color, letterSpacing: '-0.02em' }}>{value}</span>
    </div>
  )

  return (
    <article
      data-testid={`stop-card-${r.symbol}-${r.account}`}
      style={{
        borderRadius: 10,
        border: `1px solid ${urgent ? `${status.color}50` : 'rgba(148,163,184,.14)'}`,
        background: urgent
          ? `linear-gradient(90deg, ${status.color}14 0%, rgba(15,23,42,.85) 48%)`
          : 'rgba(15,23,42,.78)',
        boxShadow: urgent ? `0 0 0 1px ${status.color}18, 0 10px 28px rgba(0,0,0,.25)` : '0 4px 14px rgba(0,0,0,.18)',
        overflow: 'hidden',
      }}
    >
      {/* ── SCAN STRIP (always visible) — not a table row ── */}
      <div style={{ display: 'flex', alignItems: 'stretch', minHeight: 64 }}>
        {/* status rail */}
        <div
          title={status.why}
          style={{
            width: 6, flexShrink: 0, background: status.color,
            boxShadow: `0 0 12px ${status.color}66`,
          }}
        />
        <div style={{
          flex: 1, minWidth: 0, display: 'flex', flexWrap: 'wrap',
          alignItems: 'center', gap: 10, padding: '10px 12px',
        }}>
          {/* Identity */}
          <div style={{ flex: '0 1 168px', minWidth: 120 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => onFocus?.(r.symbol, r.account)}
                style={{
                  fontSize: 17, fontWeight: 900, color: TEXT0, background: 'none', border: 'none',
                  cursor: onFocus ? 'pointer' : 'default', padding: 0, letterSpacing: 0.4,
                }}
              >
                {r.symbol}
              </button>
              <StatusBadge status={status} />
            </div>
            <div style={{ fontSize: 10.5, color: MUTED, marginTop: 3, lineHeight: 1.3 }}>
              {r.account.replace(/_/g, ' ')}
              <span style={{ opacity: 0.45 }}> · </span>
              <span style={{ fontFamily: 'monospace', color: TEXT0, fontWeight: 700 }}>{fmtStop(r.current_price)}</span>
              {r.qty != null && <span> · {r.qty} sh</span>}
            </div>
          </div>

          {/* Key metrics as chips (not columns) */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, flex: '1 1 320px', alignItems: 'center' }}>
            {chip(
              'Stop',
              r.has_active_stop ? fmtStop(r.broker_stop ?? r.stop) : 'none',
              r.has_active_stop ? GREEN : AMBER,
            )}
            {chip(
              'Dist',
              r.distance_pct != null ? `${r.distance_pct}%` : '—',
              (r.distance_pct != null && r.distance_pct < 3) ? AMBER : TEXT0,
            )}
            {chip('At risk', fmt$(r.dollars_at_risk), urgent ? status.color : TEXT0)}
            {chip(
              'Cover',
              coverageLabel,
              r.coverage === 'partial' ? AMBER : r.coverage === 'oversized' ? RED : r.has_active_stop ? GREEN : AMBER,
            )}
            {chip('Plan', fmtStop(r.planned_stop), AMBER)}
            {r.unrealized_dollars != null && chip(
              'P/L',
              `${r.unrealized_dollars >= 0 ? '+' : ''}${fmt$(r.unrealized_dollars)}`,
              r.unrealized_dollars >= 0 ? GREEN : RED,
            )}
            {/* Realized P/L if THIS stop fills — the outcome, not just the risk. */}
            {r.pl_if_fired != null && chip(
              'If fired',
              `${r.pl_if_fired >= 0 ? '+' : ''}${fmt$(r.pl_if_fired)}`,
              r.pl_if_fired >= 0 ? GREEN : RED,
            )}
            <div style={{ fontSize: 10, color: MUTED, paddingLeft: 2 }}>
              <div style={{ marginBottom: 2 }}>
                <StopKindPill kind={r.stop_kind || (r.is_trailing ? 'TRAILING' : r.has_active_stop ? (r.stop_type === 'MONITORED' ? 'MONITORED' : 'FIXED') : 'NONE')}
                  trailPct={r.trail_pct} distPct={r.distance_pct} orderType={r.order_type} small />
              </div>
              <div title={status.why} style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {status.why}
              </div>
            </div>
          </div>

          {/* CTA cluster */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5, flex: '0 0 auto', marginLeft: 'auto' }}>
            <button
              type="button"
              data-testid="stop-card-primary-cta"
              onClick={() => onPrimary(cta.autoStage)}
              title={cta.reason}
              style={{
                fontSize: 11.5, fontWeight: 900, padding: '9px 14px', borderRadius: 8,
                cursor: 'pointer', border: `1px solid ${tone.border}`, background: tone.bg,
                color: tone.color, whiteSpace: 'nowrap', maxWidth: 260,
                boxShadow: urgent ? `0 0 16px ${tone.color}33` : undefined,
              }}
            >
              {cta.label}
            </button>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {cta.secondary && (
                <button
                  type="button"
                  onClick={onSecondary}
                  style={{
                    fontSize: 10.5, fontWeight: 700, padding: '3px 8px', borderRadius: 5,
                    cursor: 'pointer', border: '1px solid rgba(148,163,184,.25)',
                    background: 'transparent', color: MUTED,
                  }}
                >
                  {cta.secondary}
                </button>
              )}
              <button
                type="button"
                onClick={onToggle}
                style={{
                  fontSize: 10.5, fontWeight: 700, padding: '3px 8px', borderRadius: 5,
                  cursor: 'pointer', border: 'none', background: 'transparent', color: BLUE,
                }}
              >
                {expanded ? '▾ less' : '▸ details'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── ACTION PLAN (urgent always; optional expand) ── */}
      {showPlan && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)',
          gap: 0,
          borderTop: `1px solid ${status.color}33`,
          background: 'rgba(0,0,0,.2)',
        }}>
          <div style={{ padding: '12px 14px', borderRight: '1px solid rgba(148,163,184,.1)' }}>
            <SectionLabel>Next action</SectionLabel>
            <div style={{ fontSize: 13.5, fontWeight: 800, color: TEXT0, marginBottom: 4, lineHeight: 1.3 }}>
              {cta.label}
            </div>
            <div style={{ fontSize: 12, color: MUTED, lineHeight: 1.45, marginBottom: 10 }}>
              {cta.reason}
            </div>
            {r.projection && (
              <div style={{ fontSize: 11, color: MUTED, marginBottom: 10 }}>
                <span style={{ color: TEXT0, fontWeight: 700 }}>If you act: </span>{r.projection}
              </div>
            )}
            <button
              type="button"
              onClick={() => onPrimary(cta.autoStage)}
              style={{
                fontSize: 12, fontWeight: 900, padding: '10px 16px', borderRadius: 8,
                cursor: 'pointer', border: `1px solid ${tone.border}`, background: tone.bg,
                color: tone.color,
              }}
            >
              {cta.autoStage ? '▶ Stage now' : 'Open adjust'}
            </button>
          </div>
          <div style={{ padding: '12px 14px' }}>
            <SectionLabel>Protection snapshot</SectionLabel>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 11.5 }}>
              <div>
                <div style={{ color: MUTED, fontSize: 9.5, fontWeight: 700 }}>LIVE / ADVISED</div>
                <div style={{ fontFamily: 'monospace', fontWeight: 800 }}>
                  <span style={{ color: r.has_active_stop ? GREEN : AMBER }}>{fmtStop(r.broker_stop)}</span>
                  <span style={{ color: MUTED }}> / </span>
                  <span style={{ color: AMBER }}>{fmtStop(r.planned_stop)}</span>
                </div>
              </div>
              <div>
                <div style={{ color: MUTED, fontSize: 9.5, fontWeight: 700 }}>DISTANCE</div>
                <div style={{ fontFamily: 'monospace', fontWeight: 800, color: TEXT0 }}>
                  {r.distance_pct != null ? `${r.distance_pct}%` : '—'}
                  {r.distance_atr != null ? <span style={{ color: MUTED, fontWeight: 600 }}> · {r.distance_atr}ATR</span> : null}
                </div>
              </div>
              <div>
                <div style={{ color: MUTED, fontSize: 9.5, fontWeight: 700 }}>COVERAGE</div>
                <div style={{ fontWeight: 800, color: r.coverage === 'partial' ? AMBER : r.has_active_stop ? GREEN : AMBER }}>
                  {r.coverage === 'partial' ? `PARTIAL ${r.stop_qty}/${r.qty}`
                    : r.coverage === 'oversized' ? `OVERSIZED ${r.stop_qty}/${r.qty}`
                      : r.has_active_stop ? 'Full size' : 'No stop'}
                </div>
              </div>
              <div>
                <div style={{ color: MUTED, fontSize: 9.5, fontWeight: 700 }}>HEALTH</div>
                <div style={{ fontWeight: 700, color: TEXT0 }}>
                  {r.holdings_llm_health || '—'}
                  {r.unrealized_dollars != null && (
                    <span style={{ color: r.unrealized_dollars >= 0 ? GREEN : RED, marginLeft: 6 }}>
                      {r.unrealized_dollars >= 0 ? '+' : ''}{fmt$(r.unrealized_dollars)}
                    </span>
                  )}
                </div>
              </div>
            </div>
            {r.divergence && (
              <div style={{ marginTop: 8, fontSize: 11, color: /looser/i.test(r.divergence) ? AMBER : MUTED }}>
                vs plan: {r.divergence}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── DEEP DETAIL (explicit expand only — Grok/evidence/exit) ── */}
      {expanded && (
        <div style={{
          borderTop: '1px solid rgba(148,163,184,.12)',
          padding: '8px 12px 12px',
          background: 'rgba(0,0,0,.28)',
        }}>
          <SectionLabel>Exit · Street · Grok · evidence</SectionLabel>
          <ReasonsSubRow r={r} />
        </div>
      )}
    </article>
  )
}

export default function StopManagement({ onFocusHolding, accountFilter = null, onAccountFilter }: Props) {
  const [terminalUi] = useTerminalUi()
  const [sub, setSub] = useState<'Monitor' | 'Audit' | 'Policy'>('Monitor')
  const [data, setData] = useState<any>(() => {
    try {
      const raw = sessionStorage.getItem(STOPS_CACHE_KEY)
      return raw ? JSON.parse(raw) : null
    } catch { return null }
  })
  const [loading, setLoading] = useState(!data)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [quick, setQuick] = useState<typeof QUICK[number]>('Needs Action')
  // Prefer URL-synced portfolio account filter when parent provides it.
  const [acctLocal, setAcctLocal] = useState('All')
  const acct = accountFilter ? accountFilter : acctLocal
  const setAcct = (v: string) => {
    if (onAccountFilter) {
      onAccountFilter(v === 'All' ? null : v)
    } else {
      setAcctLocal(v)
    }
  }
  useEffect(() => {
    if (accountFilter) setAcctLocal(accountFilter)
    else if (accountFilter === null && onAccountFilter) setAcctLocal('All')
  }, [accountFilter, onAccountFilter])
  const [level, setLevel] = useState('All')
  const [adjust, setAdjust] = useState<Row | null>(null)
  const [autoStage, setAutoStage] = useState(false)
  const [expandedKeys, setExpandedKeys] = useState<Record<string, boolean>>({})
  // One-click apply: primary CTAs may auto-stage; "Adjust" opens manual mode.
  const openAdjust = (r: Row, auto: boolean) => { setAutoStage(auto); setAdjust(r) }

  const load = (force = false) => {
    setLoading(true)
    setFetchError(null)
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 90_000)
    const url = force ? '/api/v2/stops/management?refresh=1' : '/api/v2/stops/management'
    fetch(url, { signal: ctrl.signal })
      .then(x => { if (!x.ok) throw new Error(`HTTP ${x.status}`); return x.json() })
      .then(j => {
        const next = unwrap(j)
        setData(next)
        try { sessionStorage.setItem(STOPS_CACHE_KEY, JSON.stringify(next)) } catch { /* quota */ }
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e)
        setFetchError(msg.includes('abort') ? 'Request timed out (90s) — showing last-known data if available.' : msg)
        if (!data) setData(null)
      })
      .finally(() => { window.clearTimeout(timer); setLoading(false) })
  }
  useEffect(() => { load(false) }, [])

  const rows: Row[] = data?.rows ?? []
  const summary = data?.summary ?? {}
  const accounts = useMemo(() => ['All', ...Array.from(new Set(rows.map(r => r.account)))], [rows])

  const filtered = useMemo(() => {
    const list = rows.filter(r => {
      if (acct !== 'All' && r.account !== acct) return false
      if (level !== 'All' && r.alert_level !== level) return false
      const st = derivePositionStatus(r)
      if (quick === 'Needs Action') {
        return st.kind === 'needs_attention' || st.kind === 'no_stop' || st.kind === 'partial'
          || r.alert_level === 'red' || r.alert_level === 'amber'
          || r.coverage === 'partial' || r.coverage === 'oversized'
          || Boolean(r.trailing_should_be_active)
      }
      if (quick === 'Partial Coverage' && r.coverage !== 'partial' && r.coverage !== 'oversized') return false
      if (quick === 'No Stop' && r.has_active_stop) return false
      if (quick === 'All Protected') {
        return st.kind === 'protected' || st.kind === 'monitored'
      }
      if (quick === 'Trailing Stops' && !(r.has_active_stop && r.is_trailing)) return false
      if (quick === 'Trailing Eligible' && !r.trailing_should_be_active) return false
      if (quick === 'High Heat' && !((r.heat_contribution_pct ?? 0) >= 1.5)) return false
      if (quick === 'Regime Shift' && !r.regime_shift_detected) return false
      return true
    })
    // Urgent first: no stop / partial / red, then amber, then protected
    return [...list].sort((a, b) => {
      const sa = derivePositionStatus(a).sort
      const sb = derivePositionStatus(b).sort
      if (sa !== sb) return sa - sb
      return (b.dollars_at_risk || 0) - (a.dollars_at_risk || 0)
    })
  }, [rows, acct, level, quick])

  const deskStats = useMemo(() => {
    let needs = 0, partial = 0, protectedN = 0, noStop = 0, trailing = 0
    let atRiskNeeds = 0
    for (const r of rows) {
      const st = derivePositionStatus(r)
      if (st.kind === 'no_stop') {
        noStop++; needs++; atRiskNeeds += r.dollars_at_risk || 0
      } else if (st.kind === 'partial' || st.kind === 'needs_attention') {
        needs++; atRiskNeeds += r.dollars_at_risk || 0
      } else if (st.kind === 'review') {
        needs++
      } else if (st.kind === 'protected' || st.kind === 'monitored') {
        protectedN++
      }
      if (r.coverage === 'partial' || r.coverage === 'oversized') partial++
      if (r.is_trailing && r.has_active_stop) trailing++
    }
    return { needs, partial, protectedN, noStop, trailing, atRiskNeeds, positions: rows.length }
  }, [rows])

  const [fidSync, setFidSync] = useState<{ busy: boolean; msg: string }>({ busy: false, msg: '' })

  const syncFidelityStops = async () => {
    if (fidSync.busy) return
    setFidSync({ busy: true, msg: '' })
    try {
      const r = await fetch('/api/v2/fidelity-stops/sync', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      })
      const j = await r.json()
      const d = unwrap(j?.data ?? j)
      const n = Array.isArray(d?.upserted) ? d.upserted.length : 0
      if (j?.ok !== false && !d?.errors?.length) {
        setFidSync({ busy: false, msg: `✓ Fidelity GTC · ${n} stops` })
        load(true)
      } else {
        setFidSync({ busy: false, msg: `⛔ ${j?.error || d?.errors?.[0]?.error || 'sync failed'}` })
      }
    } catch {
      setFidSync({ busy: false, msg: '⛔ sync request failed' })
    }
  }

  return (
    <div style={{ padding: terminalUi ? '2px 0' : '4px 2px' }}>
      {/* sub-tabs */}
      <div style={{ display: 'flex', gap: terminalUi ? 3 : 4, marginBottom: terminalUi ? 8 : 12 }}>
        {(['Monitor', 'Audit', 'Policy'] as const).map(t => (
          <button key={t} onClick={() => setSub(t)} style={{ fontSize: 13, fontWeight: 800, padding: '5px 14px', borderRadius: 7, cursor: 'pointer',
            border: `1px solid ${sub === t ? BLUE : 'rgba(148,163,184,.3)'}`, background: sub === t ? `${BLUE}18` : 'transparent', color: sub === t ? BLUE : MUTED }}>{t}</button>
        ))}
      </div>

      {sub === 'Policy' ? <PolicyMigrationView terminalUi={terminalUi} /> : sub === 'Audit' ? <AuditView terminalUi={terminalUi} /> : (
        <>
          {fetchError && (
            <div style={{ marginBottom: terminalUi ? 6 : 10, ...hubPanel(terminalUi), background: `${AMBER}14`, border: `1px solid ${AMBER}55` }}>
              <div style={{ fontSize: 12.5, fontWeight: 800, color: AMBER }}>⚠ Stop Management load issue</div>
              <div style={{ fontSize: 11.5, color: MUTED, marginTop: 4, lineHeight: 1.45 }}>{fetchError}</div>
            </div>
          )}
          {!loading && !fetchError && rows.length === 0 && (
            <div style={{ marginBottom: terminalUi ? 6 : 10, ...hubPanel(terminalUi), background: `${AMBER}10`, border: `1px solid ${AMBER}44` }}>
              <div style={{ fontSize: 12.5, fontWeight: 800, color: AMBER }}>No stop rows returned</div>
              <div style={{ fontSize: 11.5, color: MUTED, marginTop: 4 }}>Backend may be reconnecting — click ↻ Refresh or wait for the API server.</div>
            </div>
          )}
          {data?.broker_stops_degraded && (
            <div style={{ marginBottom: terminalUi ? 6 : 10, ...hubPanel(terminalUi), background: `${RED}14`, border: `1px solid ${RED}55` }}>
              <div style={{ fontSize: 12.5, fontWeight: 800, color: RED }}>⚠ Schwab live stop read failed — broker stops may be hidden</div>
              <div style={{ fontSize: 11.5, color: MUTED, marginTop: 4, lineHeight: 1.45 }}>
                Only Fidelity monitored / planned stops are showing. Fidelity JEPQ-style rows can still appear while Schwab orders look &quot;planned only&quot;.
                {data?.broker_stops_meta?.error ? <> Error: <span style={{ color: TEXT0 }}>{String(data.broker_stops_meta.error)}</span>.</> : null}
                {' '}Refresh after the API server and venv recover; check <code style={{ fontSize: 10.5 }}>/api/v2/holdings/live-stops</code>.
              </div>
            </div>
          )}

          {/* Page header — desk summary */}
          <div style={{
            marginBottom: 12, padding: '12px 14px', borderRadius: 12,
            border: '1px solid rgba(148,163,184,.16)',
            background: 'linear-gradient(180deg, rgba(30,41,59,.55), rgba(15,23,42,.4))',
          }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 15, fontWeight: 900, color: TEXT0, letterSpacing: '-0.02em' }}>
                  Stop Management desk
                </div>
                <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>
                  {loading ? 'Loading…' : `${deskStats.positions} positions`}
                  {' · '}regime <b style={{ color: TEXT0 }}>{data?.regime_now ?? '—'}</b>
                  {data?.cached ? ' · cached' : ''}
                  {' · '}sorted by urgency
                </div>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                <button onClick={() => load(true)} style={{ fontSize: 12, fontWeight: 700, padding: '5px 11px', borderRadius: 7, cursor: 'pointer', border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>↻ Refresh</button>
                <button onClick={() => void syncFidelityStops()} disabled={fidSync.busy} title="Re-apply Fidelity Rollover IRA GTC stops from config/fidelity_rollover_stops.json"
                  style={{ fontSize: 12, fontWeight: 700, padding: '5px 11px', borderRadius: 7, cursor: fidSync.busy ? 'wait' : 'pointer', border: `1px solid ${PURPLE}`, background: `${PURPLE}18`, color: PURPLE }}>
                  {fidSync.busy ? '⟳ Fidelity…' : '⟳ Fidelity GTC'}
                </button>
                <CloudLlmRunButtons processId="holding_protection_advisor_batch" lanePolicy="grok_only" batchLimit={6} onDone={() => load(true)} />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Card terminalUi={terminalUi} label="Needs action" value={String(deskStats.needs)}
                color={deskStats.needs > 0 ? AMBER : GREEN}
                sub={deskStats.atRiskNeeds > 0 ? `${fmt$(deskStats.atRiskNeeds)} at risk on flagged` : 'all clear'} />
              <Card terminalUi={terminalUi} label="Active stops" value={`${summary.broker_stops_active ?? 0} / ${deskStats.positions || summary.positions || 0}`}
                color={(summary.no_stop ?? deskStats.noStop) > 0 ? AMBER : GREEN}
                sub={`${deskStats.noStop || summary.no_stop || 0} with no stop`} />
              <Card terminalUi={terminalUi} label="Partial / oversized" value={String(deskStats.partial)}
                color={deskStats.partial > 0 ? AMBER : GREEN}
                sub="size ≠ held shares" />
              <Card terminalUi={terminalUi} label="Total open risk" value={fmt$(summary.total_open_risk)}
                sub={`heat ${(summary.portfolio_heat_pct ?? 0).toFixed(1)}% / ${summary.heat_cap ?? 5}%`}
                color={(summary.portfolio_heat_pct ?? 0) > (summary.heat_cap ?? 5) ? RED : TEXT0} />
              <Card terminalUi={terminalUi} label="Trailing live" value={String(deskStats.trailing)}
                color={GREEN}
                sub={`${summary.trailing_not_active ?? 0} trail-eligible not active`} />
              <Card terminalUi={terminalUi} label="Stoplight R/A/Y" value={`${summary.red ?? 0} / ${summary.amber ?? 0} / ${summary.yellow ?? 0}`}
                color={(summary.red ?? 0) > 0 ? RED : (summary.amber ?? 0) > 0 ? AMBER : GREEN} />
            </div>
            {/* Color legend */}
            <div style={{
              display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 10, paddingTop: 10,
              borderTop: '1px solid rgba(148,163,184,.12)', fontSize: 10.5, color: MUTED, alignItems: 'center',
            }}>
              <span style={{ fontWeight: 800, color: TEXT0, letterSpacing: '.04em', fontSize: 9.5, textTransform: 'uppercase' }}>Status</span>
              {[
                { c: GREEN, l: 'PROTECTED', w: 'Live stop aligned with held size' },
                { c: AMBER, l: 'PARTIAL / REVIEW', w: 'Undersized stop or moderate concern' },
                { c: RED, l: 'NO STOP / ATTENTION', w: 'Unprotected or misaligned — act first' },
                { c: BLUE, l: 'MONITORED', w: 'Fidelity/software stop, not Schwab GTC' },
              ].map(x => (
                <span key={x.l} title={x.w} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, cursor: 'help' }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: x.c }} />
                  <b style={{ color: x.c, fontSize: 10 }}>{x.l}</b>
                  <span style={{ opacity: 0.85 }}>— {x.w}</span>
                </span>
              ))}
            </div>
            {fidSync.msg && <div style={{ fontSize: 11, marginTop: 6, color: fidSync.msg.startsWith('✓') ? GREEN : RED }}>{fidSync.msg}</div>}
          </div>

          {/* Global actions needed */}
          {(deskStats.needs > 0 || (Array.isArray((summary as any).next_actions) && (summary as any).next_actions.length > 0)) && (
            <div style={{
              marginBottom: 12, borderRadius: 10, padding: '10px 12px',
              background: `${AMBER}0d`, border: `1px solid ${AMBER}40`,
            }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: AMBER, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 6 }}>
                Actions needed — work top-down
              </div>
              {Array.isArray((summary as any).next_actions) && (summary as any).next_actions.length > 0 ? (
                ((summary as any).next_actions as NextAction[]).slice(0, 8).map((na, i) => (
                  <div key={i} style={{ fontSize: 12.5, color: TEXT0, lineHeight: 1.5, display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 4 }}>
                    <span style={{ fontSize: 10, fontWeight: 900, color: na.alert_level === 'red' ? RED : na.alert_level === 'amber' ? AMBER : MUTED, minWidth: 14 }}>{i + 1}.</span>
                    <button
                      type="button"
                      onClick={() => {
                        const row = rows.find(x => x.symbol === na.symbol && x.account === na.account)
                        if (row) openAdjust(row, true)
                      }}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left',
                        color: TEXT0, fontSize: 12.5,
                      }}
                    >
                      <b style={{ color: BLUE }}>{na.symbol}</b>
                      <span style={{ color: MUTED }}> ({na.account})</span>
                      {' — '}{na.action}
                      {na.projection ? <span style={{ color: MUTED, fontSize: 11 }}> · {na.projection}</span> : null}
                    </button>
                  </div>
                ))
              ) : (
                <div style={{ fontSize: 12, color: MUTED }}>
                  {deskStats.needs} holding{deskStats.needs === 1 ? '' : 's'} need review — use filter <b style={{ color: AMBER }}>Needs Action</b> below.
                </div>
              )}
            </div>
          )}

          {/* Filters */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            {QUICK.map(qv => {
              const active = quick === qv
              const urgent = qv === 'Needs Action' || qv === 'No Stop' || qv === 'Partial Coverage'
              return (
                <button
                  key={qv}
                  onClick={() => setQuick(qv)}
                  style={{
                    fontSize: 11.5, fontWeight: 800, padding: '5px 11px', borderRadius: 7, cursor: 'pointer',
                    border: `1px solid ${active ? (urgent ? AMBER : BLUE) : 'rgba(148,163,184,.28)'}`,
                    background: active ? (urgent ? `${AMBER}18` : `${BLUE}18`) : 'transparent',
                    color: active ? (urgent ? AMBER : BLUE) : MUTED,
                  }}
                >
                  {qv}
                </button>
              )
            })}
            <span style={{ width: 4 }} />
            <select value={acct} onChange={e => setAcct(e.target.value)} style={{ fontSize: 12, padding: '5px 8px', borderRadius: 7, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
              {accounts.map(a => <option key={a} value={a}>{a === 'All' ? 'All accounts' : a}</option>)}
            </select>
            <select value={level} onChange={e => setLevel(e.target.value)} style={{ fontSize: 12, padding: '5px 8px', borderRadius: 7, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
              {['All', 'red', 'amber', 'yellow'].map(l => <option key={l} value={l}>{l === 'All' ? 'All stoplights' : l}</option>)}
            </select>
            <span style={{ fontSize: 11, color: MUTED, marginLeft: 4 }}>
              {loading ? 'loading…' : `Showing ${filtered.length} of ${rows.length}`}
            </span>
          </div>
          <div style={{ fontSize: 10, color: MUTED, marginBottom: 12, lineHeight: 1.45 }}>
            Primary buttons stage Schwab 2FA or Fidelity manual tickets — nothing submits without approval.
            {' '}<b style={{ color: PURPLE }}>Fidelity GTC</b> are operator-recorded (SnapTrade positions only).
          </div>

          {/* Holding cards */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {filtered.map((r, i) => {
              const key = `${r.symbol}:${r.account}:${i}`
              const exp = Boolean(expandedKeys[key])
              return (
                <HoldingStopCard
                  key={key}
                  r={r}
                  expanded={exp}
                  onToggle={() => setExpandedKeys(prev => ({ ...prev, [key]: !prev[key] }))}
                  onPrimary={(auto) => openAdjust(r, auto)}
                  onSecondary={() => openAdjust(r, false)}
                  onFocus={onFocusHolding}
                />
              )
            })}
            {!loading && filtered.length === 0 && (
              <div style={{
                padding: 28, textAlign: 'center', color: MUTED, borderRadius: 12,
                border: '1px dashed rgba(148,163,184,.25)',
              }}>
                No positions match this filter.
              </div>
            )}
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
          <div style={{ fontSize: 16, fontWeight: 900, color: TEXT0, display: 'flex', alignItems: 'center', gap: 9 }}>
            Manage stop — {row.symbol}
            {/* Current stop kind, so the type stays visible while managing */}
            <StopKindPill kind={row.stop_kind || (row.is_trailing ? 'TRAILING' : row.has_active_stop ? (row.stop_type === 'MONITORED' ? 'MONITORED' : 'FIXED') : 'NONE')}
              trailPct={row.trail_pct} distPct={row.distance_pct} orderType={row.order_type} />
          </div>
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
/** Policy migration panel — ranked stops sitting outside their dynamic tier band.
 * ADVISORY ONLY by design: there is deliberately no mass-update control; each row
 * routes to the normal per-order path (Schwab 2FA / Fidelity manual / Alpaca paper). */
function PolicyMigrationView({ terminalUi }: { terminalUi: boolean }) {
  const [rep, setRep] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    fetch('/api/v2/portfolio/stop-policy-migration')
      .then(r => r.json())
      .then(j => (j.ok ? setRep(j.data) : setErr(j.error || 'load failed')))
      .catch(e => setErr(String(e)))
  }, [])
  if (err) return <div style={{ color: RED, fontSize: 12, padding: 10 }}>⛔ {err}</div>
  if (!rep) return <div style={{ color: MUTED, fontSize: 12, padding: 10 }}>Loading policy report…</div>
  const tierColor = (t: string) => t === 'vol_low' || t === 'income_defensive' ? GREEN
    : t === 'vol_high' || t === 'momentum' ? RED : AMBER
  const divergences: any[] = rep.divergences || []
  const covered: any[] = (rep.rows || []).filter((r: any) => !r.divergence)
  const regime = rep.regime?.posture
  return (
    <div style={{ fontSize: terminalUi ? 12 : 13 }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 8 }}>
        <b style={{ color: TEXT0 }}>Stop-policy migration</b>
        <span style={{ color: MUTED }}>policy {rep.policy_version} · {String(rep.generated_at || '').slice(0, 16)}</span>
        {regime && <span style={{ color: regime === 'risk_on' ? GREEN : regime === 'risk_off' ? RED : MUTED, fontWeight: 700 }}>regime {String(regime).replace('_', '-')}</span>}
        <span style={{ color: rep.diverged ? AMBER : GREEN, fontWeight: 800 }}>{rep.diverged} outside band</span>
      </div>
      <div style={{ color: MUTED, fontSize: 11, marginBottom: 10 }}>{rep.note}</div>
      {divergences.length > 0 && (
        <div style={{ overflowX: 'auto', marginBottom: 14 }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead><tr style={{ color: MUTED, fontSize: 11, textAlign: 'left' }}>
              <th style={{ padding: '4px 8px' }}>Symbol</th><th style={{ padding: '4px 8px' }}>Value</th>
              <th style={{ padding: '4px 8px' }}>Tier</th><th style={{ padding: '4px 8px' }}>Band</th>
              <th style={{ padding: '4px 8px' }}>Stop</th><th style={{ padding: '4px 8px' }}>Distance</th>
              <th style={{ padding: '4px 8px' }}>Divergence</th>
            </tr></thead>
            <tbody>
              {divergences.map((r: any, i: number) => (
                <tr key={i} style={{ borderTop: '1px solid rgba(148,163,184,.15)', color: TEXT0 }}>
                  <td style={{ padding: '5px 8px', fontWeight: 800 }}>{r.symbol}<span style={{ color: MUTED, fontWeight: 400, fontSize: 10 }}> {r.account}</span></td>
                  <td style={{ padding: '5px 8px' }}>${Number(r.value_usd).toLocaleString()}</td>
                  <td style={{ padding: '5px 8px' }}><b style={{ color: tierColor(r.tier) }}>{r.tier}</b><span style={{ color: MUTED, fontSize: 10 }}> {r.tier_source}</span></td>
                  <td style={{ padding: '5px 8px' }}>{r.band_pct?.[0]}–{r.band_pct?.[1]}%</td>
                  <td style={{ padding: '5px 8px' }}>{r.stop_price != null ? `$${Number(r.stop_price).toFixed(2)}` : '—'}</td>
                  <td style={{ padding: '5px 8px' }}>{r.stop_distance_pct != null ? `${r.stop_distance_pct}%` : '—'}</td>
                  <td style={{ padding: '5px 8px', color: AMBER, fontSize: 11 }}>{r.divergence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ color: MUTED, fontSize: 11, marginBottom: 4 }}>In-band / no-stop holdings ({covered.length}) — tier assignments:</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        {covered.map((r: any, i: number) => (
          <span key={i} title={`${r.stop_price != null ? `Current stop: $${Number(r.stop_price).toFixed(2)}${r.stop_distance_pct != null ? ` (${r.stop_distance_pct}% below)` : ''}` : 'Current stop: none'}\nWe advise ${r.trail_band_pct?.[0]}\u2013${r.trail_band_pct?.[1]}% trailing based on ${String(r.tier_label || r.tier).toUpperCase()} (${r.tier_source}).\nMinimum floor: ${r.band_pct?.[0]}% (family/swing-low rule governs final placement).${r.note ? '\n' + r.note : ''}`}
            style={{ fontSize: 11, padding: '2px 8px', borderRadius: 5, border: `1px solid ${tierColor(r.tier)}44`, color: tierColor(r.tier), background: `${tierColor(r.tier)}12` }}>
            {r.symbol} <span style={{ opacity: .75 }}>{r.tier}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function AuditView({ terminalUi }: { terminalUi: boolean }) {
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
      <div style={{ display: 'flex', gap: terminalUi ? 6 : 9, flexWrap: 'wrap', marginBottom: terminalUi ? 8 : 12 }}>
        <Card terminalUi={terminalUi} label="Audit events" value={String(d?.total ?? 0)} />
        <Card terminalUi={terminalUi} label="2FA stop requests" value={String(counts['2fa_stop_request'] ?? 0)} color={BLUE} />
        <Card terminalUi={terminalUi} label="Confirmations / pending" value={String(counts['confirmation'] ?? 0)} color={GREEN} />
        <Card terminalUi={terminalUi} label="Stop-out reviews" value={String(rw?.total_reviews ?? 0)} color={AMBER} sub="advisory · journal lifecycle" />
        <Card terminalUi={terminalUi} label="Re-entry watch" value={String(rw?.total_watch ?? 0)} color={PURPLE} sub="WAIT status" />
      </div>
      <div style={{ overflowX: 'auto', ...(terminalUi ? hubPanel(terminalUi) : { border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }) }}>
        <table className={terminalUi ? 'cc-table-dense' : undefined} style={{ width: '100%', borderCollapse: 'collapse', fontSize: terminalUi ? 10 : 12.5 }}>
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

      <div style={{ marginTop: terminalUi ? 10 : 18, ...hubPanel(terminalUi), background: `${PURPLE}10`, border: `1px solid ${PURPLE}44` }}>
        <div style={{ fontSize: 12, fontWeight: 900, color: PURPLE, marginBottom: 6 }}>Stop-out re-entry watch — advisory only</div>
        <div style={{ fontSize: 11, color: MUTED, marginBottom: 10, lineHeight: 1.45 }}>
          Loss round-trips from journal lifecycle. Does not route orders — use triggers as a checklist before re-entering.
          {rw?.advisory_only ? ' · advisory_only=true' : ''}{rw?.error ? ` · ${rw.error}` : ''}
        </div>
        <div style={{ overflowX: 'auto', ...(terminalUi ? hubPanel(terminalUi) : { border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }) }}>
          <table className={terminalUi ? 'cc-table-dense' : undefined} style={{ width: '100%', borderCollapse: 'collapse', fontSize: terminalUi ? 10 : 12 }}>
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
