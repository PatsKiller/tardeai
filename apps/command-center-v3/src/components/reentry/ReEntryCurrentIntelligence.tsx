import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { useReEntryExitEvidence } from '../../hooks/useReEntryExitEvidence'
import { BB } from '../../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  MANDATE_KEY,
  REENTRY_FLAGS,
  classificationLabel,
  classificationState,
  finite,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  rowPrice,
  rowShares,
  text,
  type ExitEvidenceField,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ClassificationState,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'
import { HelpTip } from './ReEntryHelpGuide'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 11.5, padding: '7px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '5px 9px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })
const sectionLabel: CSSProperties = { fontSize: 10, fontWeight: 900, color: BB.text3, letterSpacing: 0.4, textTransform: 'uppercase', marginBottom: 5 }
const LIST_PAGE = 15

function LookthroughBlock({ lookthrough, compact = false }: { lookthrough: any; compact?: boolean }) {
  if (!lookthrough) return null
  const sectors: any[] = Array.isArray(lookthrough.sectors) ? lookthrough.sectors : []
  const holdings: any[] = Array.isArray(lookthrough.top_holdings) ? lookthrough.top_holdings : []
  const fs = compact ? 10.5 : 12
  return (
    <div style={{ marginTop: compact ? 14 : 18 }}>
      <div style={sectionLabel}>Fund / ETF look-through{lookthrough.as_of ? ` · as of ${String(lookthrough.as_of).slice(0, 10)}` : ''}</div>
      <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, padding: compact ? 9 : 12, fontSize: fs, lineHeight: 1.55 }}>
        <div>
          <b>{lookthrough.fund_name || 'Fund/ETF'}</b>
          {lookthrough.fund_type ? <span style={{ color: BB.text3 }}> · {lookthrough.fund_type}</span> : null}
          {lookthrough.source ? <span style={{ color: BB.text3 }}> · {lookthrough.source}</span> : null}
        </div>
        {!lookthrough.available && <div style={{ color: BB.amber, marginTop: 4 }}>{lookthrough.note || 'Look-through weights not on file yet'}</div>}
        {!!sectors.length && (
          <div style={{ marginTop: 6 }}>
            <b style={{ color: BB.text3, fontSize: 10 }}>SECTORS</b>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
              {sectors.map((s: any) => (
                <span key={String(s.name)} style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3, border: '1px solid var(--border)', color: BB.text2 }}>
                  {s.name} {s.pct == null ? '' : `${Number(s.pct).toFixed(1)}%`}
                </span>
              ))}
            </div>
          </div>
        )}
        {!!holdings.length && (
          <div style={{ marginTop: 8 }}>
            <b style={{ color: BB.text3, fontSize: 10 }}>TOP HOLDINGS</b>
            <div style={{ marginTop: 3 }}>
              {holdings.map((h: any) => (
                <div key={String(h.ticker)} style={{ display: 'grid', gridTemplateColumns: '64px 1fr 48px', gap: 6, fontSize: compact ? 10.5 : 12, padding: '2px 0', borderBottom: '1px solid var(--border)' }}>
                  <b>{h.ticker}</b>
                  <span style={{ color: BB.text3 }}>{h.name || '—'}</span>
                  <span style={{ textAlign: 'right' }}>{h.pct == null ? '—' : `${Number(h.pct).toFixed(1)}%`}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

type Summary = { symbol: string; rows: ExitEvidenceRow[]; latest: ExitEvidenceRow; shares: number | null; avgExit: number | null; proceeds: number; eventGapCount: number; derivedCount: number }
type IntelState =
  | 'READY TO REVIEW'
  | 'NEAR ENTRY'
  | 'OVERSOLD REVIEW'
  | 'OVERBOUGHT WAIT'
  | 'WAIT'
  | 'CURRENTLY HELD'
  | 'STALE'
  | 'MISSING PLAN'
  | 'MISSING MARKET'
  | 'WASH BLOCK'

type Gate = { id: string; pass: boolean; label: string; value: string }
type DeskRow = {
  symbol: string
  price: number | null
  price_as_of: string | null
  price_source: string | null
  price_age_h: number | null
  rsi: number | null
  rsi_status?: string | null
  sma20_pct: number | null
  sma50_pct: number | null
  sma200_pct: number | null
  sma_20?: number | null
  sma_50?: number | null
  sma_200?: number | null
  macd_signal: string | null
  macd_histogram_direction?: string | null
  atr?: number | null
  alignment?: string | null
  entry_low: number | null
  entry_high: number | null
  stop: number | null
  target: number | null
  rr: number | null
  plan_as_of?: string | null
  resistance: { state: string; level: number | null; distance_pct: number | null; hold_days: number | null; as_of: string | null; live_price: number | null; live_as_of: string | null; source: string }
  catalyst: { verified?: boolean; headline?: string | null; confidence?: number | null; at?: string | null } | null
  wash_blocked: boolean
  wash_until: string | null
  held: boolean
  heat_pct: number | null
  gates?: Gate[]
  why?: string[]
  intel: { state: IntelState; action: string; reason: string; distance_pct: number | null; chips: { tone: string; label: string; detail?: string }[] }
  research_summary: string | null
  company?: string | null
  earnings_date?: string | null
  advisory?: {
    date: string
    action: string
    ticker: string
    company: string | null
    reentry_range_low: number | null
    reentry_range_high: number | null
    stop_loss: number | null
    risk_per_share_low: number | null
    risk_per_share_high: number | null
    target: number | null
    reward_low: number | null
    reward_high: number | null
    rr: number | null
    live_price: number | null
    earnings_date: string | null
    earnings_days: number | null
    sizing: {
      book_equity: number
      risk_pct: number
      max_alloc_pct: number
      max_dollar_risk: number
      risk_per_share: number | null
      shares: number | null
      allocation: number | null
      note: string
      formula: string
    }
    criteria: { id: string; met: boolean | null; label: string; detail: string }[]
    rationale: string[]
    confirmations_complete?: boolean
    confirmation_gaps?: string[]
    is_fund?: boolean
    lookthrough?: {
      available: boolean
      fund_name?: string | null
      fund_type?: string | null
      as_of?: string | null
      source?: string | null
      sectors?: { name: string; pct: number }[]
      top_holdings?: { ticker: string; name?: string | null; pct?: number | null }[]
      note?: string | null
    } | null
    advisory_only: boolean
  }
  obv_signal?: string | null
  obv_trend?: string | null
  cmf_signal?: string | null
  volume_ratio?: number | null
}

type StateFilter = 'ACTIONABLE' | 'READY TO REVIEW' | 'NEAR ENTRY' | 'OVERSOLD REVIEW' | 'WASH BLOCK' | 'WAIT' | 'ALL'

function unwrap(value: any): any { let result = value; for (let i = 0; i < 4 && result?.data && typeof result.data === 'object'; i += 1) result = result.data; return result ?? {} }
function money(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '—' : `$${value.toFixed(2)}` }
function pct(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(1)}%` }
function ageLabel(hours: number | null | undefined, asOf?: string | null): string {
  if (hours == null || !Number.isFinite(hours)) {
    if (!asOf) return 'as-of unavailable'
    const time = new Date(asOf).getTime()
    if (!Number.isFinite(time)) return String(asOf).slice(0, 16)
    const h = Math.max(0, Math.round((Date.now() - time) / 36e5))
    return h < 1 ? 'current' : h < 48 ? `${h}h old` : `${Math.round(h / 24)}d old`
  }
  return hours < 1 ? 'current' : hours < 48 ? `${Math.round(hours)}h old` : `${Math.round(hours / 24)}d old`
}
function daysSince(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const t = new Date(dateStr).getTime()
  if (!Number.isFinite(t)) return String(dateStr).slice(0, 10)
  const d = Math.max(0, Math.round((Date.now() - t) / 864e5))
  return d === 0 ? 'today' : `${d}d ago`
}
function classify(symbols: string[]) { window.dispatchEvent(new CustomEvent('reentry:classify-symbol', { detail: { symbols } })) }
function openWatch(symbol: string) { window.location.href = `/v3/watch?symbol=${encodeURIComponent(symbol)}&review=1` }
function stateTone(state: string): string {
  if (state === 'READY TO REVIEW') return BB.green
  if (state === 'NEAR ENTRY' || state === 'OVERSOLD REVIEW') return BB.amber
  if (state === 'MISSING MARKET' || state === 'MISSING PLAN' || state === 'STALE' || state === 'WASH BLOCK') return BB.red
  if (state === 'CURRENTLY HELD' || state === 'OVERBOUGHT WAIT') return BB.amber
  return BB.blue
}
function chipTone(tone: string): string {
  if (tone === 'green') return BB.green
  if (tone === 'red') return BB.red
  if (tone === 'amber') return BB.amber
  return BB.blue
}
function toneDim(tone: string): string {
  if (tone === BB.green || tone === 'green') return BB.greenDim
  if (tone === BB.red || tone === 'red') return BB.redDim
  if (tone === BB.amber || tone === 'amber') return BB.amberDim
  return BB.blueDim
}
function signalTone(raw: string | null | undefined): string {
  const s = String(raw || '').toUpperCase()
  if (!s || s === '—' || s === 'UNAVAILABLE' || s === 'NONE') return BB.text3
  if (/BULL|BUY|STRONG|POSITIVE|ABOVE|ALIGNED|UP|VERIFIED|READY|COMPLETE/.test(s)) return BB.green
  if (/BEAR|SELL|NEGATIVE|BELOW|BLOCK|FAIL|STALE|MISSING|WASH/.test(s)) return BB.red
  if (/NEUTRAL|NEAR|CHECK|WAIT|CAUTION|OVERSOLD|OVERBOUGHT|HELD|TESTING/.test(s)) return BB.amber
  return BB.blue
}
function rsiTone(rsi: number | null | undefined): string {
  if (rsi == null || !Number.isFinite(rsi)) return BB.text3
  if (rsi >= 70 || rsi < 30) return BB.red
  if (rsi >= 65 || rsi < 40) return BB.amber
  return BB.green
}
function rrTone(rr: number | null | undefined): string {
  if (rr == null || !Number.isFinite(rr)) return BB.text3
  if (rr >= 3) return BB.green
  if (rr >= 2) return BB.green
  if (rr >= 1.5) return BB.amber
  return BB.red
}
function ageTone(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours)) return BB.amber
  if (hours > 96) return BB.red
  if (hours > 24) return BB.amber
  return BB.green
}
function Chip({ label, tone, tip }: { label: string; tone: string; tip?: string }) {
  return (
    <span
      title={tip}
      aria-label={tip ? `${label}. ${tip}` : label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        fontSize: 10,
        fontWeight: 800,
        padding: '3px 7px',
        borderRadius: 4,
        border: `1px solid ${tone}`,
        color: tone,
        background: toneDim(tone),
        whiteSpace: 'nowrap',
        cursor: tip ? 'help' : 'default',
      }}
    >
      {label}
    </span>
  )
}
function TipLabel({ children, tip }: { children: ReactNode; tip: string }) {
  return <span style={{ color: BB.text3, fontWeight: 700, display: 'inline-flex', alignItems: 'center' }}>{children}<HelpTip text={tip} /></span>
}
function ctaForState(state: string, confirmationsComplete: boolean | undefined): { label: string; detail: string; tone: string } {
  if (state === 'READY TO REVIEW' && confirmationsComplete !== false) {
    return { label: 'CTA · REVIEW LIMIT', detail: 'Hard gates + confirmations green. Open Watch to size the limit — advisory only, no broker write.', tone: BB.green }
  }
  if (state === 'READY TO REVIEW' || state === 'NEAR ENTRY') {
    return { label: 'CTA · CONFIRM SETUP', detail: 'Zone/RSI may pass, but amber/red confirmations mean not clean READY. Fix gaps before sizing.', tone: BB.amber }
  }
  if (state === 'WASH BLOCK') {
    return { label: 'CTA · BLOCKED', detail: 'Wash-sale window still open on taxable exits. Do not re-enter this symbol until clear.', tone: BB.red }
  }
  if (state === 'MISSING MARKET' || state === 'STALE' || state === 'MISSING PLAN') {
    return { label: 'CTA · REFRESH DATA', detail: 'Price, RSI, or entry plan is missing/stale. Refresh desk/resistance before acting.', tone: BB.red }
  }
  if (state === 'OVERSOLD REVIEW') {
    return { label: 'CTA · CAUTION', detail: 'Oversold — review for bounce risk; not a clean READY re-entry.', tone: BB.amber }
  }
  if (state === 'CURRENTLY HELD') {
    return { label: 'CTA · MANAGE HOLDING', detail: 'Already held — use Watch/Rotation, not a fresh re-entry ticket.', tone: BB.amber }
  }
  return { label: 'CTA · MONITOR', detail: 'Not actionable yet. Keep on the desk until zone + RSI + confirmations align.', tone: BB.blue }
}
function sourceFor(row: ExitEvidenceRow, fieldName: ExitEvidenceField): string { return row.field_sources?.[fieldName] || row.import_source || 'source unavailable' }
function suggestedShares(mandate: ReEntryMandate, price: number | null, avgExitShares: number | null): number | null {
  if (price == null || price <= 0) return null
  if (mandate.targetWeightPct != null && mandate.targetWeightPct > 0) {
    const notional = (1_250_000 * mandate.targetWeightPct) / 100
    return Math.max(1, Math.floor(notional / price))
  }
  if (avgExitShares != null && avgExitShares > 0) return Math.max(1, Math.floor(avgExitShares * 0.25))
  return null
}
function matchesStateFilter(state: string, filter: StateFilter): boolean {
  if (filter === 'ALL') return true
  if (filter === 'ACTIONABLE') return state === 'READY TO REVIEW' || state === 'NEAR ENTRY'
  return state === filter
}

const STATE_ORDER: Record<string, number> = {
  'READY TO REVIEW': 0,
  'NEAR ENTRY': 1,
  'OVERSOLD REVIEW': 2,
  WAIT: 3,
  'OVERBOUGHT WAIT': 4,
  STALE: 5,
  'MISSING PLAN': 6,
  'MISSING MARKET': 7,
  'WASH BLOCK': 8,
  'CURRENTLY HELD': 9,
}

const CRITERIA_TIPS: Record<string, string> = {
  ma_bounce: 'MET if price is within 1.5% of SMA20/50/200, or holding above SMA20 with bullish structure.',
  support: 'MET when price is in the entry zone or resistance state is ABOVE/TESTING.',
  rsi_reset: 'Constructive band is 40 ≤ RSI < 70 (same as rotation gates). ≥70 overbought; ≤30 oversold.',
  macd: 'Passes unless MACD is explicitly bearish/negative/sell.',
  volume: 'Equities need OBV/CMF accumulation or volume ≥1× avg. Funds/ETFs skip (N/A MET).',
  rr: 'Prefer ≥2:1 reward-to-risk; 3:1 ideal. Below 2:1 blocks clean READY confirmations.',
  invalidation: 'Requires a stop below structure so 1% risk sizing can compute shares.',
  catalyst: 'Fails if earnings are within 5 calendar days.',
  wash: 'Fails if a taxable sell is still inside the 30-day wash window.',
}

type AdvisorySelected = {
  symbol: string
  intelState: IntelState
  action: string
  reason: string
  desk: DeskRow | undefined
  analyst: any
  mandate: ReEntryMandate
  classified: ClassificationState
  latest: ExitEvidenceRow
  latestEvent: ReturnType<typeof normalizedEvent>
  avgExit: number | null
  proceeds: number
  rows: ExitEvidenceRow[]
  events: Record<string, ReEntryEvent>
}

function AdvisoryBody({
  selected,
  compact,
  sizeHint,
  onFull,
  onClose,
}: {
  selected: AdvisorySelected
  compact: boolean
  sizeHint: number | null
  onFull?: () => void
  onClose?: () => void
}) {
  const d = selected.desk
  const a = d?.advisory
  const sz = a?.sizing
  const tone = stateTone(selected.intelState)
  const cta = ctaForState(selected.intelState, a?.confirmations_complete)
  const rec = text(selected.analyst?.rec, selected.analyst?.recommendation, 'unavailable').replace(/_/g, ' ').toUpperCase()
  const account = selected.latest.account || selected.mandate.targetAccount || 'account unset'
  const eventType = selected.latestEvent.eventType.replace(/_/g, ' ').toUpperCase()
  const vsExit = d?.price != null && selected.avgExit != null && selected.avgExit > 0
    ? ((d.price - selected.avgExit) / selected.avgExit) * 100
    : null
  const rr = a?.rr ?? d?.rr ?? null
  const riskBand = a?.risk_per_share_low != null || a?.risk_per_share_high != null
    ? `${money(a?.risk_per_share_low ?? a?.risk_per_share_high)} – ${money(a?.risk_per_share_high ?? a?.risk_per_share_low)}`
    : money(sz?.risk_per_share ?? null)
  const rewardBand = a?.reward_low != null || a?.reward_high != null
    ? `${money(a?.reward_low ?? a?.reward_high)} – ${money(a?.reward_high ?? a?.reward_low)}`
    : '—'
  const criteria = a?.criteria ?? []
  const metN = criteria.filter(c => c.met === true).length
  const labelW = compact ? '148px' : '180px'
  const fs = compact ? 11.5 : 13
  const row = (k: ReactNode, v: ReactNode) => (
    <div style={{ display: 'grid', gridTemplateColumns: `${labelW} 1fr`, gap: compact ? 8 : 10, padding: compact ? '4px 0' : '6px 0', borderBottom: '1px solid var(--border)', fontSize: fs }}>
      <span>{k}</span>
      <span style={{ fontWeight: 650 }}>{v}</span>
    </div>
  )

  return <>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
      <div style={{ fontSize: compact ? 13 : 16, fontWeight: 900, color: tone }}>ADVISORY DETAILS</div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <Chip label="ADVISORY ONLY" tone={BB.text3} tip="Desk never places broker orders. Review → Watch/Rotation → you execute." />
        {onFull ? <button onClick={onFull} style={button(true)} title="Open full-page advisory">OPEN FULL PAGE</button> : null}
      </div>
    </div>

    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
      <Chip label={selected.intelState.replace(' TO REVIEW', '')} tone={tone} tip="Deterministic desk state from zone + RSI + hard gates. LLM never sets READY." />
      <Chip
        label={a?.confirmations_complete ? 'CONFIRMATIONS OK' : 'CONFIRMATIONS GAP'}
        tone={a?.confirmations_complete ? BB.green : BB.amber}
        tip="MA, volume/money-flow, R:R, stop, and wash must be green for clean READY. Amber/red downgrades READY → NEAR."
      />
      <Chip label={`R:R ${rr == null ? '—' : `${rr}:1`}`} tone={rrTone(rr)} tip="Reward ÷ risk from mid-entry to target vs stop. Prefer ≥2:1; 3:1 ideal." />
      <Chip label={ageLabel(d?.price_age_h, d?.price_as_of)} tone={ageTone(d?.price_age_h)} tip="Quote age from the data broker. >24h amber; >96h too stale for READY." />
    </div>

    <div style={{ padding: compact ? '8px 10px' : '10px 12px', borderRadius: 5, border: `1px solid ${cta.tone}`, background: toneDim(cta.tone), marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <b style={{ color: cta.tone, fontSize: compact ? 12 : 14 }}>{cta.label}</b>
        <HelpTip text={cta.detail} />
        <span style={{ color: BB.text2, fontSize: compact ? 10.5 : 12 }}>{a?.action || selected.action}</span>
      </div>
      <div style={{ color: BB.text3, fontSize: 10, marginTop: 3 }}>{cta.detail}</div>
    </div>

    <div>
      {row(<TipLabel tip="Calendar date of this advisory snapshot (UTC day).">Date</TipLabel>, a?.date || new Date().toISOString().slice(0, 10))}
      {row(
        <TipLabel tip="Suggested operator action from desk state. Green = review a buy limit; amber/red = wait or refresh.">Action</TipLabel>,
        <span style={{ color: tone, fontWeight: 850 }}>{a?.action || selected.intelState}</span>,
      )}
      {row(
        <TipLabel tip="Symbol and sector/industry label from symbol profiles when available.">Ticker</TipLabel>,
        <><b style={{ fontSize: compact ? 15 : 18 }}>{selected.symbol}</b>{a?.company || d?.company ? <span style={{ color: BB.text3 }}> ({a?.company || d?.company})</span> : null}</>,
      )}
      {row(
        <TipLabel tip="Last broker quote. Color on age: green &lt;24h, amber 24–96h, red &gt;96h.">Live Price</TipLabel>,
        <>
          <b>{money(d?.price)}</b>{' '}
          <span style={{ color: ageTone(d?.price_age_h), fontSize: compact ? 10 : 11, fontWeight: 750 }}>
            {ageLabel(d?.price_age_h, d?.price_as_of)}
          </span>
          <span style={{ color: BB.text3, fontSize: compact ? 10 : 11 }}> · {d?.price_source || '—'}</span>
        </>,
      )}
      {row(
        <TipLabel tip="Validated re-entry zone from the entry plan. Price inside zone is a hard READY gate.">Re-entry Range</TipLabel>,
        d?.entry_low == null
          ? <span style={{ color: BB.red }}>unavailable — build entry plan</span>
          : <b style={{ color: d.price != null && d.price >= d.entry_low && d.price <= (d.entry_high ?? d.entry_low) ? BB.green : BB.amber }}>
              {money(d.entry_low)} – {money(d.entry_high)}
            </b>,
      )}
      {row(
        <TipLabel tip="Invalidation stop below structure. Risk band = entry − stop across the zone. Required for 1% sizing.">Stop-Loss (Invalidation)</TipLabel>,
        <>
          <b style={{ color: BB.red }}>{money(a?.stop_loss ?? d?.stop)}</b>
          {riskBand !== '—' ? <span style={{ color: BB.text3 }}> (Risk: {riskBand})</span> : null}
        </>,
      )}
      {row(
        <TipLabel tip="Upside target for R:R. Reward band = target − entry across the zone.">Target Price</TipLabel>,
        <>
          <b style={{ color: BB.green }}>{money(a?.target ?? d?.target)}</b>
          {rewardBand !== '—' ? <span style={{ color: BB.text3 }}> (Reward: {rewardBand})</span> : null}
        </>,
      )}
      {row(
        <TipLabel tip="Reward ÷ risk. Green ≥2:1; amber 1.5–2; red &lt;1.5. Below 2:1 blocks clean READY.">Reward-to-Risk</TipLabel>,
        rr != null ? <b style={{ color: rrTone(rr), fontSize: compact ? 14 : 16 }}>{rr}:1</b> : '—',
      )}
      {row(
        <TipLabel tip="Exit account + mandate classification. Unclassified names should be tagged before large size.">Account / Mandate</TipLabel>,
        <>{account} · {selected.mandate.mandate.replace(/_/g, ' ').toUpperCase()} · <span style={{ color: selected.classified === 'UNCLASSIFIED' ? BB.amber : BB.text2 }}>{classificationLabel(selected.classified)}</span></>,
      )}
      {row(
        <TipLabel tip="Most recent exit evidence row. vs now compares live price to average exit price.">Last Exit</TipLabel>,
        <>
          {selected.latest.trade_date || '—'} ({daysSince(selected.latest.trade_date)}) · {eventType} · avg {money(selected.avgExit)} · vs now{' '}
          <b style={{ color: vsExit == null ? BB.text3 : vsExit >= 0 ? BB.green : BB.red }}>{pct(vsExit)}</b>
        </>,
      )}
    </div>

    <LookthroughBlock lookthrough={a?.lookthrough} compact={compact} />

    <div style={{ marginTop: compact ? 14 : 18 }}>
      <div style={sectionLabel}>
        Position sizing (1% risk · 10% alloc cap)
        <HelpTip text="shares = (book × 1%) / (entry − stop), then capped so allocation ≤ 10% of book. Suggestion only — you place the order." />
      </div>
      <div style={{ background: 'var(--bg2)', border: `1px solid ${cta.tone}`, borderRadius: 4, padding: compact ? 9 : 12, fontSize: compact ? 11 : 13, lineHeight: 1.55 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(110px,1fr))', gap: 8 }}>
          <div><span style={{ color: BB.text3, fontSize: 10 }}>BOOK</span><br /><b>{sz ? `$${Number(sz.book_equity).toLocaleString()}` : '—'}</b></div>
          <div><span style={{ color: BB.text3, fontSize: 10 }}>MAX $ RISK</span><br /><b style={{ color: BB.amber }}>{sz ? money(sz.max_dollar_risk) : '—'}</b></div>
          <div><span style={{ color: BB.text3, fontSize: 10 }}>RISK / SHARE</span><br /><b>{money(sz?.risk_per_share ?? null)}</b></div>
          <div><span style={{ color: BB.text3, fontSize: 10 }}>SHARES</span><br /><b style={{ color: cta.tone, fontSize: compact ? 16 : 18 }}>{sz?.shares == null ? '—' : sz.shares.toLocaleString()}</b></div>
          <div><span style={{ color: BB.text3, fontSize: 10 }}>ALLOCATION</span><br /><b>{money(sz?.allocation ?? null)}</b></div>
        </div>
        <div style={{ color: BB.text3, fontSize: 10, marginTop: 6 }}>{sz?.formula || 'shares = (book × 1%) / (entry − stop)'} · {sz?.note || ''}</div>
        {sizeHint != null && selected.mandate.targetWeightPct != null && (
          <div style={{ color: BB.text3, fontSize: 10, marginTop: 2 }}>Mandate weight alt: {sizeHint.toLocaleString()} sh @ {selected.mandate.targetWeightPct}%</div>
        )}
      </div>
    </div>

    <div style={{ marginTop: compact ? 14 : 18 }}>
      <div style={sectionLabel}>
        Mandatory parameters & filters ({metN}/{criteria.length})
        <HelpTip text="Green MET / amber CHECK / red NOT MET. Amber or red on MA, volume, R:R, stop, or wash means not clean READY." />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: compact ? 5 : 8 }}>
        {criteria.map(c => {
          const ct = c.met === true ? BB.green : c.met === false ? BB.red : BB.amber
          const tag = c.met === true ? 'MET' : c.met === false ? 'NOT MET' : 'CHECK'
          return (
            <div key={c.id} style={{ display: 'grid', gridTemplateColumns: compact ? '64px 1fr' : '72px 1fr', gap: 8, padding: compact ? '6px 7px' : '8px 10px', borderRadius: 4, border: `1px solid ${ct}`, background: toneDim(ct), fontSize: compact ? 10.5 : 12 }}>
              <b style={{ color: ct }}>{tag}</b>
              <div>
                <b>{c.label}<HelpTip text={CRITERIA_TIPS[c.id] || c.detail} /></b>
                <div style={{ color: BB.text3, marginTop: 1 }}>{c.detail}</div>
              </div>
            </div>
          )
        })}
        {!criteria.length && <div style={{ color: BB.text3, fontSize: 10 }}>Refresh desk for advisory criteria.</div>}
      </div>
    </div>

    <div style={{ marginTop: compact ? 14 : 18 }}>
      <div style={sectionLabel}>
        Technicals & rationale
        <HelpTip text="Broker indicators from the data cache. Hover chips for thresholds. Rationale bullets are deterministic — no LLM prose." />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        <Chip label={`RSI ${d?.rsi == null ? '—' : d.rsi.toFixed(1)}`} tone={rsiTone(d?.rsi)} tip="40–65 green; 65–70 amber (near overbought); ≥70 or &lt;30 red; &lt;40 amber." />
        <Chip label={`MACD ${d?.macd_signal || '—'}`} tone={signalTone(d?.macd_signal)} tip="Momentum confirmation. Neutral is allowed; bearish fails the MACD criterion." />
        <Chip label={`ATR ${d?.atr == null ? '—' : Number(d.atr).toFixed(2)}`} tone={BB.blue} tip="Average True Range — volatility context for stop distance, not a hard gate." />
        <Chip label={`OBV ${d?.obv_signal || '—'} (${d?.obv_trend || '—'})`} tone={signalTone(d?.obv_signal || d?.obv_trend)} tip="On-Balance Volume. Bullish/up supports money-flow confirmation." />
        <Chip label={`CMF ${d?.cmf_signal || '—'}`} tone={signalTone(d?.cmf_signal)} tip="Chaikin Money Flow. Positive/bullish supports accumulation." />
        <Chip label={`Align ${d?.alignment || '—'}`} tone={signalTone(d?.alignment)} tip="SMA structure alignment (bullish/bearish). Used with SMA20 hold for MA criterion." />
        <Chip
          label={`Res ${d?.resistance?.state || '—'} ${money(d?.resistance?.level)}`}
          tone={signalTone(d?.resistance?.state)}
          tip="Closed-session resistance cache. ABOVE = reclaimed; BELOW = still overhead."
        />
        <Chip
          label={d?.catalyst?.verified ? 'Catalyst verified' : d?.catalyst ? 'Catalyst unverified' : 'Catalyst —'}
          tone={d?.catalyst?.verified ? BB.green : d?.catalyst ? BB.amber : BB.text3}
          tip={d?.catalyst?.headline || 'Catalyst record from the data broker when present.'}
        />
        <Chip
          label={`Earnings ${a?.earnings_date || d?.earnings_date || 'none'}${a?.earnings_days != null ? ` (${a.earnings_days}d)` : ''}`}
          tone={a?.earnings_days != null && a.earnings_days <= 5 ? BB.red : a?.earnings_days != null && a.earnings_days <= 14 ? BB.amber : BB.green}
          tip="Fails catalyst criterion if earnings are within 5 days."
        />
        <Chip label={`Analyst ${rec}`} tone={signalTone(rec)} tip="Street consensus pill. Not a hard READY gate — context only." />
        <Chip
          label={`Target ${selected.analyst?.target == null ? '—' : money(Number(selected.analyst.target))}`}
          tone={BB.blue}
          tip="Mean Street target when available."
        />
      </div>
      <div style={{ fontSize: compact ? 10.5 : 12.5, color: BB.text2, lineHeight: 1.55, marginBottom: 8 }}>
        <b>SMA20/50/200</b> {money(d?.sma_20 ?? null)} / {money(d?.sma_50 ?? null)} / {money(d?.sma_200 ?? null)}{' '}
        <span style={{ color: BB.text3 }}>({pct(d?.sma20_pct)} / {pct(d?.sma50_pct)} / {pct(d?.sma200_pct)})</span>
        <br />
        <b>Thesis</b> {selected.mandate.thesis || <span style={{ color: BB.amber }}>None saved — classify to add narrative reason.</span>}
        {d?.catalyst?.headline ? <><br /><b>Headline</b> {d.catalyst.headline}</> : null}
      </div>
      <ol style={{ margin: 0, paddingLeft: 20, fontSize: compact ? 11 : 12.5, lineHeight: 1.55 }}>
        {(a?.rationale?.length ? a.rationale : (d?.why?.length ? d.why : [selected.reason])).map(line => <li key={line}>{line}</li>)}
      </ol>
    </div>

    <div style={{ marginTop: compact ? 14 : 18 }}>
      <div style={sectionLabel}>Exit history<HelpTip text="Authoritative exit rows for this symbol. Qty/price sources are audited on the Exit Evidence boards." /></div>
      {(compact ? selected.rows.slice(0, 5) : selected.rows).map(exit => {
        const event = normalizedEvent(exit, selected.events[exit.event_key])
        return (
          <div key={exit.event_key} style={{ display: 'grid', gridTemplateColumns: compact ? '72px 1fr 70px 60px' : '88px 1fr 90px 80px', gap: compact ? 6 : 8, padding: compact ? '5px 0' : '6px 0', borderBottom: '1px solid var(--border)', fontSize: compact ? 10 : 12 }}>
            <b>{exit.trade_date ?? '—'}</b>
            <span>{exit.account ?? '—'} · {event.eventType.replace(/_/g, ' ')}{!compact && event.reason ? ` — ${event.reason}` : ''}</span>
            <span>{rowShares(exit) == null ? '—' : `${Number(rowShares(exit)).toLocaleString(undefined, { maximumFractionDigits: 2 })} sh`}</span>
            <span>{money(rowPrice(exit))}</span>
          </div>
        )
      })}
      {compact && <div style={{ fontSize: 9, color: BB.text3, marginTop: 4 }}>qty src {sourceFor(selected.latest, 'quantity')} · proceeds {money(selected.proceeds)}</div>}
    </div>

    <div style={{ display: 'flex', gap: 8, marginTop: compact ? 14 : 18, flexWrap: 'wrap' }}>
      <button
        onClick={() => openWatch(selected.symbol)}
        style={{ ...button(true), borderColor: cta.tone, background: toneDim(cta.tone), color: cta.tone }}
        title="Open Watch ticket to review chart and place the order yourself"
      >
        {selected.intelState === 'READY TO REVIEW' && a?.confirmations_complete !== false ? 'REVIEW LIMIT ON WATCH →' : 'OPEN WATCH →'}
      </button>
      <button onClick={() => classify([selected.symbol])} style={button(false)} title="Classify mandate / save thesis">CLASSIFY / THESIS</button>
      {!compact && (
        <button onClick={() => { window.location.href = `/v3/rotation?symbol=${encodeURIComponent(selected.symbol)}` }} style={button(false)} title="Open rotation workspace for this symbol">ROTATION</button>
      )}
      {onFull ? <button onClick={onFull} style={button(false)}>OPEN FULL PAGE</button> : null}
      {onClose ? <button onClick={onClose} style={{ ...button(false), marginLeft: 'auto' }}>CLOSE ×</button> : null}
    </div>
  </>
}

export default function ReEntryCurrentIntelligence() {
  const evidence = useReEntryExitEvidence(365)
  const mandatesPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const regime = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const analyst = useApi<any>('/api/v2/pro-analyst/pills?map=1', 300_000)
  const [desk, setDesk] = useState<any>(null)
  const [deskError, setDeskError] = useState('')
  const [deskLoading, setDeskLoading] = useState(false)
  const [resistanceBusy, setResistanceBusy] = useState(false)
  const [search, setSearch] = useState('')
  // Default: money queue only — READY + NEAR. Click EXITED for full audit list.
  const [stateFilter, setStateFilter] = useState<StateFilter>('ACTIONABLE')
  const [classificationFilter, setClassificationFilter] = useState('ALL')
  const [queueFilter, setQueueFilter] = useState<'ACTIVE' | 'SUPPRESSED' | 'ALL'>('ACTIVE')
  const [selectedSymbol, setSelectedSymbol] = useState('')
  const [fullOpen, setFullOpen] = useState(false)
  const [deskReload, setDeskReload] = useState(0)
  const [listPage, setListPage] = useState(0)

  const mandates: Record<string, ReEntryMandate> = prefMap(mandatesPref.data) as Record<string, ReEntryMandate>
  const events: Record<string, ReEntryEvent> = prefMap(eventsPref.data) as Record<string, ReEntryEvent>
  const dispositions: Record<string, ReEntryDisposition> = prefMap(dispositionsPref.data) as Record<string, ReEntryDisposition>

  const summaries = useMemo(() => {
    const groups = new Map<string, ExitEvidenceRow[]>()
    for (const row of evidence.rows) {
      const symbol = String(row.symbol || '').toUpperCase()
      if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), row])
    }
    return [...groups.entries()].map(([symbol, rows]) => {
      const sorted = rows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let shares = 0; let weighted = 0; let proceeds = 0; let known = false
      for (const row of sorted) {
        const quantity = rowShares(row); const price = rowPrice(row); const cash = finite(row.proceeds_usd)
        if (quantity !== null) { known = true; shares += quantity; if (price !== null) weighted += quantity * price }
        if (cash !== null) proceeds += Math.abs(cash)
      }
      return { symbol, rows: sorted, latest: sorted[0], shares: known ? shares : null, avgExit: shares > 0 && weighted > 0 ? weighted / shares : null, proceeds, eventGapCount: sorted.reduce((sum, row) => sum + (row.evidence_gaps?.length ?? 0), 0), derivedCount: sorted.reduce((sum, row) => sum + (row.derived_fields?.length ?? 0), 0) } satisfies Summary
    })
  }, [evidence.rows])

  // Full exited universe for desk + search (was capped at 80 — hid names like V).
  const symbols = useMemo(() => summaries.map(s => s.symbol), [summaries])

  useEffect(() => {
    let dead = false
    const load = async () => {
      setDeskLoading(true); setDeskError('')
      try {
        const qs = symbols.length ? `?symbols=${encodeURIComponent(symbols.join(','))}` : ''
        const response = await fetch(`/api/v2/reentry/decision-desk${qs}`, { cache: 'no-store' })
        const payload = unwrap(await response.json())
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `HTTP ${response.status}`)
        if (!dead) setDesk(payload)
      } catch (error: any) {
        if (!dead) { setDesk(null); setDeskError(String(error?.message || error)) }
      } finally {
        if (!dead) setDeskLoading(false)
      }
    }
    void load()
    return () => { dead = true }
  }, [symbols.join('|'), deskReload])

  useEffect(() => { setListPage(0) }, [search, stateFilter, queueFilter, classificationFilter])

  useEffect(() => {
    if (!fullOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setFullOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullOpen])

  const deskBySymbol = useMemo(() => {
    const map: Record<string, DeskRow> = {}
    for (const row of (desk?.rows ?? []) as DeskRow[]) {
      if (row?.symbol) map[String(row.symbol).toUpperCase()] = row
    }
    return map
  }, [desk])

  const analystMap: Record<string, any> = unwrap(analyst.data)?.map ?? {}

  const rows = useMemo(() => summaries.map(summary => {
    const mandate = normalizedMandate(mandates[summary.symbol])
    const deskRow = deskBySymbol[summary.symbol]
    const intelState = (deskRow?.intel?.state || 'MISSING MARKET') as IntelState
    const classified = classificationState(mandate, summary.rows, events, dispositions)
    const flags = REENTRY_FLAGS.filter(flag => mandate.flags[flag])
    const suppressedCount = summary.rows.filter(row => normalizedDisposition(dispositions[row.event_key]).state === 'suppressed').length
    const suppressed = summary.rows.length > 0 && suppressedCount === summary.rows.length
    const latestEvent = normalizedEvent(summary.latest, events[summary.latest.event_key])
    return {
      ...summary,
      mandate,
      desk: deskRow,
      intelState,
      action: deskRow?.intel?.action || 'Refresh market evidence',
      reason: deskRow?.intel?.reason || 'Waiting for decision-desk broker payload.',
      chips: deskRow?.intel?.chips ?? [],
      classified,
      flags,
      suppressedCount,
      suppressed,
      analyst: analystMap[summary.symbol] ?? null,
      latestEvent,
    }
  }), [summaries, mandatesPref.data, eventsPref.data, dispositionsPref.data, deskBySymbol, analyst.data])

  const searchQ = search.trim().toUpperCase()
  // Typing in search expands beyond ACTIONABLE so exited names (e.g. V) are findable.
  const effectiveStateFilter: StateFilter = searchQ ? 'ALL' : stateFilter
  const filtered = rows.filter(row => {
    if (searchQ && !`${row.symbol} ${row.intelState} ${row.action} ${row.classified} ${row.mandate.mandate} ${row.flags.join(' ')}`.toUpperCase().includes(searchQ)) return false
    if (queueFilter === 'ACTIVE' && row.suppressed) return false
    if (queueFilter === 'SUPPRESSED' && !row.suppressed) return false
    if (!matchesStateFilter(row.intelState, effectiveStateFilter)) return false
    if (classificationFilter !== 'ALL' && row.classified !== classificationFilter) return false
    return true
  }).sort((a, b) => (STATE_ORDER[a.intelState] ?? 50) - (STATE_ORDER[b.intelState] ?? 50)
    || (a.mandate.priority === 'HIGH' ? -1 : 0) - (b.mandate.priority === 'HIGH' ? -1 : 0)
    || String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || '')))
  const totalPages = Math.max(1, Math.ceil(filtered.length / LIST_PAGE))
  const safePage = Math.min(listPage, totalPages - 1)
  const pageStart = safePage * LIST_PAGE
  const pageSlice = filtered.slice(pageStart, pageStart + LIST_PAGE)
  // listPage < 0 means "show all in one scroll"
  const displayRows = listPage < 0 ? filtered : pageSlice
  const pageCountLabel = listPage < 0
    ? `all ${filtered.length}`
    : `${filtered.length ? pageStart + 1 : 0}–${Math.min(pageStart + LIST_PAGE, filtered.length)} of ${filtered.length}`

  useEffect(() => {
    if (listPage >= 0 && listPage > totalPages - 1) setListPage(Math.max(0, totalPages - 1))
  }, [listPage, totalPages])

  useEffect(() => {
    if (!filtered.length) { setSelectedSymbol(''); return }
    if (!selectedSymbol || !filtered.some(row => row.symbol === selectedSymbol)) {
      const prefer = filtered.find(row => row.intelState === 'READY TO REVIEW' || row.intelState === 'NEAR ENTRY') || filtered[0]
      setSelectedSymbol(prefer.symbol)
    }
  }, [filtered.map(row => row.symbol).join('|'), selectedSymbol])

  const selected = filtered.find(row => row.symbol === selectedSymbol) || null
  const suppressedTotal = rows.filter(row => row.suppressed).length
  const counts = {
    actionable: rows.filter(row => row.intelState === 'READY TO REVIEW' || row.intelState === 'NEAR ENTRY').length,
    ready: rows.filter(row => row.intelState === 'READY TO REVIEW').length,
    near: rows.filter(row => row.intelState === 'NEAR ENTRY').length,
    oversold: rows.filter(row => row.intelState === 'OVERSOLD REVIEW').length,
    wash: rows.filter(row => row.intelState === 'WASH BLOCK').length,
    wait: rows.filter(row => row.intelState === 'WAIT').length,
    symbols: rows.length,
  }
  const freshness = desk?.freshness || {}
  const criteria = desk?.criteria || {}
  const regimeLabel = text(unwrap(regime.data)?.regime_label, unwrap(regime.data)?.label, 'unknown').replace(/_/g, ' ').toUpperCase()
  const priceAge = freshness.price_age_h_median ?? freshness.price_age_h_max_actionable
  const staleStrip = (priceAge != null && priceAge > 96) || (selected?.desk?.price_age_h != null && selected.desk.price_age_h > 96)

  const refresh = () => {
    evidence.refetch(); regime.refetch(); analyst.refetch(); mandatesPref.refetch(); eventsPref.refetch(); dispositionsPref.refetch()
    setDeskReload(value => value + 1)
  }

  const refreshResistance = async () => {
    setResistanceBusy(true)
    try {
      const response = await fetch('/api/v2/reentry/resistance/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `HTTP ${response.status}`)
      setDeskReload(value => value + 1)
    } catch (error: any) {
      setDeskError(String(error?.message || error))
    } finally {
      setResistanceBusy(false)
    }
  }

  const sizeHint = selected ? suggestedShares(selected.mandate, selected.desk?.price ?? null, selected.shares) : null
  const ticketTone = selected ? stateTone(selected.intelState) : BB.text3
  const vsExit = selected?.desk?.price != null && selected.avgExit != null && selected.avgExit > 0
    ? ((selected.desk.price - selected.avgExit) / selected.avgExit) * 100
    : null

  const filterButtons: [string, number, StateFilter][] = [
    ['ACTIONABLE', counts.actionable, 'ACTIONABLE'],
    ['READY', counts.ready, 'READY TO REVIEW'],
    ['NEAR', counts.near, 'NEAR ENTRY'],
    ['OVERSOLD', counts.oversold, 'OVERSOLD REVIEW'],
    ['WASH', counts.wash, 'WASH BLOCK'],
    ['WAIT', counts.wait, 'WAIT'],
    ['ALL EXITED', counts.symbols, 'ALL'],
  ]

  return <div style={{ ...panel, padding: 10 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div>
        <div style={{ fontSize: 18, fontWeight: 900 }}>RE-ENTRY DECISION DESK <HelpTip text="Deterministic READY/NEAR from Data Broker. Default queue = READY+NEAR. RSI band matches rotation: 40 ≤ RSI < 70. LLM never sets READY/BLOCK." /></div>
        <div style={{ fontSize: 10.5, color: BB.text3 }}>
          Regime {regimeLabel} · criteria {criteria.rsi_ready || '40 ≤ RSI < 70'} · list {pageCountLabel} · {counts.symbols} exited · advisory only
          {searchQ ? ' · search spans ALL EXITED' : ''}
        </div>
      </div>
      <button onClick={refresh} style={{ ...button(false), marginLeft: 'auto' }}>{deskLoading || evidence.loading ? 'REFRESHING…' : 'REFRESH DESK'}</button>
      <button onClick={() => void refreshResistance()} disabled={resistanceBusy} style={{ ...button(false), opacity: resistanceBusy ? 0.6 : 1 }}>{resistanceBusy ? 'RESISTANCE…' : 'REFRESH RESISTANCE'}</button>
    </div>

    <div style={{ ...panel, marginTop: 8, padding: 8, background: staleStrip ? 'rgba(239,68,68,.08)' : 'var(--bg2)', borderColor: staleStrip ? BB.red : 'var(--border)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 8, fontSize: 10.5 }}>
      <div><span style={{ color: BB.text3 }}>Actionable quote age</span><br /><b style={{ color: staleStrip ? BB.red : BB.text0 }}>{priceAge == null ? '—' : ageLabel(priceAge)}</b></div>
      <div><span style={{ color: BB.text3 }}>Selected quote</span><br /><b>{selected?.desk ? ageLabel(selected.desk.price_age_h, selected.desk.price_as_of) : '—'}</b></div>
      <div><span style={{ color: BB.text3 }}>Resistance cache</span><br /><b>{freshness.resistance_generated_at ? ageLabel(null, freshness.resistance_generated_at) : '—'}</b></div>
      <div><span style={{ color: BB.text3 }}>Heat</span><br /><b>{freshness.heat_pct == null ? '—' : `${Number(freshness.heat_pct).toFixed(1)}%`}</b></div>
      <div><span style={{ color: BB.text3 }}>Stale symbols</span><br /><b style={{ color: (freshness.stale_symbol_count || 0) > 0 ? BB.amber : BB.text0 }}>{freshness.stale_symbol_count ?? 0} / {freshness.symbol_count ?? 0}</b></div>
    </div>
    {(deskError || evidence.errors.length > 0) && <div style={{ marginTop: 7, color: BB.red, fontSize: 10 }}>{deskError || evidence.errors.join(' · ')}</div>}

    <div style={{ fontSize: 10, color: BB.text3, marginTop: 8, marginBottom: 4 }}>QUEUE FILTER — click to narrow the list</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,minmax(90px,1fr))', gap: 6 }}>{filterButtons.map(([name, value, key]) => {
      const active = stateFilter === key
      return <button key={String(name)} onClick={() => setStateFilter(key)} style={{ ...panel, padding: '8px 9px', textAlign: 'left', cursor: 'pointer', background: active ? BB.blueDim : 'var(--bg2)', borderColor: active ? BB.blue : 'var(--border)', color: 'var(--text0)' }}>
        <span style={{ color: active ? BB.blue : BB.text3, fontSize: 9, fontWeight: 800 }}>{active ? 'FILTER ON' : 'FILTER'}</span>
        <br /><span style={{ fontSize: 10, color: BB.text3 }}>{String(name)}</span>
        <br /><b style={{ fontSize: 20 }}>{String(value)}</b>
      </button>
    })}</div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px,1fr) minmax(360px,1.05fr)', gap: 10, marginTop: 10 }}>
      <div style={{ ...panel, padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px,1fr) 150px 140px', gap: 7, padding: 8, borderBottom: '1px solid var(--border)' }}>
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search any exited symbol (e.g. V)…" style={field} />
          <select value={queueFilter} onChange={event => setQueueFilter(event.target.value as 'ACTIVE' | 'SUPPRESSED' | 'ALL')} style={field}>
            <option value="ACTIVE">ACTIVE QUEUE</option>
            <option value="SUPPRESSED">SUPPRESSED{suppressedTotal ? ` (${suppressedTotal})` : ''}</option>
            <option value="ALL">ACTIVE + SUPPRESSED</option>
          </select>
          <select value={classificationFilter} onChange={event => setClassificationFilter(event.target.value)} style={field}>
            <option value="ALL">ALL CLASSIFICATIONS</option>
            <option>CLASSIFIED</option>
            <option>AUTO-TAGGED</option>
            <option>UNCLASSIFIED</option>
          </select>
        </div>
        {searchQ && stateFilter !== 'ALL' && (
          <div style={{ padding: '5px 9px', fontSize: 10, color: BB.amber, borderBottom: '1px solid var(--border)' }}>
            Search “{search.trim()}” spans all {counts.symbols} exited names (not just ACTIONABLE).
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: '64px 110px 88px 56px 1fr', gap: 6, padding: '6px 9px', fontSize: 10, color: BB.text3, textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>
          <span>Symbol</span><span>State</span><span>Price/zone</span><span>RSI</span><span>Exit / chips</span>
        </div>
        <div style={{ maxHeight: 480, overflowY: 'auto' }}>
          {displayRows.map(row => {
            const tone = stateTone(row.intelState)
            const d = row.desk
            const zone = d?.entry_low == null ? '—' : `${money(d.entry_low)}–${money(d.entry_high)}`
            const active = row.symbol === selectedSymbol
            return <div key={row.symbol} role="button" tabIndex={0} onClick={() => { setSelectedSymbol(row.symbol); setFullOpen(true) }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedSymbol(row.symbol); setFullOpen(true) } }} style={{ display: 'grid', gridTemplateColumns: '64px 110px 88px 56px 1fr', gap: 6, padding: '8px 9px', borderBottom: '1px solid var(--border)', cursor: 'pointer', background: active ? BB.blueDim : 'transparent', boxShadow: active ? `inset 3px 0 0 ${tone}` : undefined, fontSize: 10.5 }}>
              <div><b style={{ fontSize: 13 }}>{row.symbol}</b><div style={{ color: BB.text3, fontSize: 9 }}>{daysSince(row.latest.trade_date)}</div></div>
              <div><b style={{ color: tone, fontSize: 10 }}>{row.intelState.replace(' TO REVIEW', '')}</b><div style={{ color: BB.text3, fontSize: 9 }}>{row.mandate.priority}</div></div>
              <div><b>{money(d?.price)}</b><div style={{ color: BB.text3, fontSize: 9 }}>{zone}</div></div>
              <div><b>{d?.rsi == null ? '—' : d.rsi.toFixed(0)}</b><div style={{ color: BB.text3, fontSize: 9 }}>{pct(d?.intel?.distance_pct)}</div></div>
              <div style={{ fontSize: 9 }}><span style={{ color: BB.text3 }}>avg exit {money(row.avgExit)}</span><div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 2 }}>{(row.chips || []).slice(0, 2).map(chip => <span key={chip.label} style={{ fontWeight: 700, padding: '1px 4px', borderRadius: 3, border: `1px solid ${chipTone(chip.tone)}`, color: chipTone(chip.tone) }}>{chip.label}</span>)}</div></div>
            </div>
          })}
          {!displayRows.length && <div style={{ padding: 14, color: BB.text3 }}>No symbols match. Clear search or click <b>ALL EXITED</b>.</div>}
        </div>
        <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border)', background: 'var(--bg2)', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          <b style={{ fontSize: 11, color: BB.text2 }}>Showing {pageCountLabel}</b>
          <button
            disabled={listPage < 0 || safePage <= 0}
            onClick={() => setListPage(p => Math.max(0, (p < 0 ? 0 : p) - 1))}
            style={{ ...button(false), opacity: listPage < 0 || safePage <= 0 ? 0.45 : 1 }}
            title="Previous page"
          >← PREV</button>
          <button
            disabled={listPage < 0 || safePage >= totalPages - 1}
            onClick={() => setListPage(p => (p < 0 ? 0 : p) + 1)}
            style={{ ...button(false), opacity: listPage < 0 || safePage >= totalPages - 1 ? 0.45 : 1 }}
            title="Next page"
          >NEXT →</button>
          <span style={{ fontSize: 10, color: BB.text3 }}>page {listPage < 0 ? 'all' : `${safePage + 1}/${totalPages}`}</span>
          {listPage < 0 ? (
            <button onClick={() => setListPage(0)} style={button(false)} title="Back to paged view">PAGE 15</button>
          ) : (
            <button
              onClick={() => setListPage(-1)}
              style={button(true)}
              title="Show every symbol in the current filter"
              disabled={!filtered.length}
            >SHOW ALL {filtered.length || ''}</button>
          )}
          {stateFilter !== 'ALL' && (
            <button
              onClick={() => { setStateFilter('ALL'); setListPage(-1) }}
              style={{ ...button(true), borderColor: BB.amber, color: BB.amber, background: BB.amberDim }}
              title="Switch filter to all exited symbols and show every row"
            >ALL EXITED ({counts.symbols})</button>
          )}
        </div>
      </div>

      <div style={{ ...panel, padding: 12, borderColor: ticketTone, maxHeight: 680, overflowY: 'auto' }}>
        {!selected && <div style={{ color: BB.text3, fontSize: 11 }}>No actionable names in this filter. Click READY / NEAR / ALL EXITED.</div>}
        {selected && (
          <AdvisoryBody
            selected={{ ...selected, events }}
            compact
            sizeHint={sizeHint}
            onFull={() => setFullOpen(true)}
          />
        )}
      </div>
    </div>

    {fullOpen && selected && <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 1400, background: 'rgba(2,6,16,.92)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', borderBottom: '1px solid var(--border)', background: 'var(--bg1)' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 900, color: stateTone(selected.intelState) }}>{selected.symbol} · FULL ADVISORY</div>
          <div style={{ fontSize: 11, color: BB.text3 }}>{selected.intelState} · {selected.desk?.advisory?.action || selected.action} · confirmations {selected.desk?.advisory?.confirmations_complete ? 'COMPLETE' : 'INCOMPLETE'} · advisory only · Esc to close</div>
        </div>
        <button onClick={() => setFullOpen(false)} title="Close" aria-label="Close" style={{ ...button(false), fontSize: 22, fontWeight: 900, width: 42, height: 38, padding: 0, lineHeight: 1 }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
        <div style={{ ...panel, padding: 16, borderColor: stateTone(selected.intelState), maxWidth: 980, margin: '0 auto' }}>
          <AdvisoryBody
            selected={{ ...selected, events }}
            compact={false}
            sizeHint={sizeHint}
            onClose={() => setFullOpen(false)}
          />
        </div>
      </div>
    </div>}
  </div>
}
