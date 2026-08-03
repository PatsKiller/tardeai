/**
 * MAIN Setup Desk — visual + logic redesign (2026-07-31).
 * Default surface is MAIN admission GO/WAIT/NOGO with ticket truth as badges.
 * Hard FAIL → NOGO. Missing critics do NOT empty the GO lane (that broke ops).
 * Street Strong Buy / Buy+ and CIO buy-side filters live here too (not only card desk).
 */
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, heatRamp } from '../lib/watchTokens'
import { terminalButton } from '../lib/watchlistTerminalTokens'
import { laneLabel } from '../lib/laneLabels'
import ProAnalystPill, { useProAnalystMap } from './ProAnalystPill'
import { HelpTip } from './reentry/ReEntryHelpGuide'
import { cioBlocksEntry, cioTrustBlocksPropose, diligenceFromWatchlistItem } from '../lib/watchlistDiligence'

export const WATCH_OPERATOR_CONTRACT = 'watch-operator-v3-main'

/** Street consensus filter — same keys as WatchlistHub card-desk Analyst rating chips. */
type StreetRatingFilter = 'all' | 'strong_buy' | 'buy_plus' | 'buy' | 'hold' | 'underperform' | 'sell' | 'no_coverage'
/** Internal CIO / research-card recommendation filter. */
type CioFilter = 'all' | 'buy_side' | 'STRONG_BUY' | 'BUY' | 'ADD' | 'ADD_ON_PULLBACK' | 'HOLD' | 'RESEARCH_MORE' | 'TRIM' | 'avoid_side' | 'AVOID' | 'IGNORE' | 'none'

const STREET_REC_COLOR: Record<string, string> = {
  strong_buy: BB.green,
  buy: BB.green,
  hold: BB.amber,
  underperform: BB.red,
  sell: BB.red,
  no_coverage: BB.text3,
}

const STREET_FILTER_OPTS: { key: StreetRatingFilter; label: string; color: string }[] = [
  { key: 'all', label: 'All', color: BB.text3 },
  { key: 'strong_buy', label: 'Strong Buy', color: BB.green },
  { key: 'buy_plus', label: 'Buy+', color: BB.green },
  { key: 'hold', label: 'Hold', color: BB.amber },
  { key: 'no_coverage', label: 'No coverage', color: BB.text3 },
]

const CIO_FILTER_OPTS: { key: CioFilter; label: string }[] = [
  { key: 'all', label: 'All CIO' },
  { key: 'buy_side', label: 'Buy-side' },
  { key: 'STRONG_BUY', label: 'STRONG_BUY' },
  { key: 'BUY', label: 'BUY' },
  { key: 'ADD', label: 'ADD' },
  { key: 'ADD_ON_PULLBACK', label: 'ADD_ON_PULLBACK' },
  { key: 'HOLD', label: 'HOLD' },
  { key: 'RESEARCH_MORE', label: 'RESEARCH_MORE' },
  { key: 'avoid_side', label: 'Avoid-side' },
  { key: 'none', label: 'No CIO' },
]

function streetRecOf(pa: any): string {
  const rec = String(pa?.rec || '').toLowerCase().trim()
  if (!pa || pa.has === false) return 'no_coverage'
  if (!rec || rec === 'none') return 'no_coverage'
  return rec
}

function streetRecLabel(rec: string): string {
  if (rec === 'no_coverage') return 'Street —'
  // Always prefix Street so it never reads as the same signal as CIO BLOCK/AVOID
  return `Street ${rec.replace(/_/g, ' ')}`
}

function cioVerdicts(item: any): string[] {
  return [item?.latest_recommendation, item?.synthesis_recommendation]
    .map(v => String(v || '').toUpperCase().trim())
    .filter(Boolean)
}

function matchesStreetFilter(rec: string, filter: StreetRatingFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'buy_plus') return rec === 'strong_buy' || rec === 'buy'
  if (filter === 'no_coverage') return rec === 'no_coverage'
  return rec === filter
}

function matchesCioFilter(verdicts: string[], filter: CioFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'buy_side') {
    return verdicts.some(c => ['BUY', 'STRONG_BUY', 'ADD', 'ADD_ON_PULLBACK'].includes(c))
  }
  if (filter === 'avoid_side') {
    return verdicts.some(c => ['AVOID', 'IGNORE', 'SELL', 'TRIM'].includes(c))
  }
  if (filter === 'none') return verdicts.length === 0
  return verdicts.includes(filter)
}

function cioColor(verdict: string): string {
  const u = verdict.toUpperCase()
  if (['BUY', 'STRONG_BUY', 'ADD', 'ADD_ON_PULLBACK', 'ACCUMULATE'].some(k => u.includes(k))) return BB.green
  if (['AVOID', 'IGNORE', 'SELL', 'TRIM'].some(k => u.includes(k))) return BB.red
  if (u.includes('HOLD') || u.includes('RESEARCH')) return BB.amber
  return BB.text3
}

function levelHeat(distancePct: number | null): string {
  if (distancePct === null || !Number.isFinite(distancePct)) return BB.text3
  return heatRamp(Math.max(-3, Math.min(3, (distancePct / 8) * 3)))
}
function signedPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}
const VAL_TIP = {
  pe: 'Trailing P/E — evidence only, not a signal.',
  fwd: 'Forward P/E estimate.',
  pb: 'Price-to-book.',
  ps: 'Price-to-sales.',
}

const shell: CSSProperties = {
  background: `linear-gradient(165deg, ${BB.bgElevated} 0%, ${BB.bg} 55%, ${BB.bgPanel} 100%)`,
  border: `1px solid ${BB.border}`,
  borderRadius: 10,
  margin: '8px 0 14px',
  overflow: 'hidden',
  boxShadow: '0 10px 32px rgba(0,0,0,.45)',
}
const chip = (active: boolean, color: string): CSSProperties => ({
  fontSize: 12,
  fontWeight: 800,
  padding: '10px 16px',
  borderRadius: 8,
  cursor: 'pointer',
  border: `2px solid ${active ? color : BB.border}`,
  background: active ? `${color}22` : 'rgba(0,0,0,.28)',
  color: active ? color : BB.text2,
  minWidth: 88,
  textAlign: 'center',
})
const btn = (active = false): CSSProperties => ({
  fontSize: 11,
  fontWeight: 800,
  padding: '7px 11px',
  borderRadius: 6,
  cursor: 'pointer',
  border: `1px solid ${active ? T.link : BB.border}`,
  background: active ? `${T.link}18` : 'rgba(0,0,0,.2)',
  color: active ? T.link : BB.text2,
})
const primaryBtn: CSSProperties = { ...terminalButton('primary'), minWidth: 120, textAlign: 'center' } as CSSProperties
const successBtn: CSSProperties = { ...terminalButton('success'), minWidth: 120, textAlign: 'center' } as CSSProperties
const dangerBtn: CSSProperties = { ...terminalButton('danger'), minWidth: 120, textAlign: 'center' } as CSSProperties
const PAGE_SIZE = 15

const DESK_TIPS = {
  propose: 'Ticket PASS + price present — propose bridge eligible. Deterministic validation remains authoritative over any model review.',
  pending: `MAIN GO but ticket critics not finished — run critics (${laneLabel('deepseek-flash')} / Local / ${laneLabel('grok')} / ${laneLabel('chatgpt')}). Street rating does not unlock propose.`,
  gap: 'Price or RSI missing from Data Broker indicator snapshot — health agent remediates via data_broker_indicator_refresh (fills indicator_confluence_cache for all consumers).',
  stale: 'Quote older than weekend-safe TTL — refresh before acting. Session-hold quotes on Sat/Sun can still be fresh.',
  wait: 'MAIN WAIT — fill entry plan / ticket shape before GO. Not the same as CIO HOLD (advisory) or Street Buy (external consensus).',
  nogo: 'Not proposeable — ticket FAIL, CIO AVOID/SELL, or admission park. Street Buy can still show as context only.',
  main: 'MAIN is the ~60-name setup desk. Street = external analyst consensus (context). CIO = internal research/synthesis (can block propose). They are allowed to disagree.',
  street: 'Street = Yahoo/professional-analyst consensus. Advisory only — never MAIN admission and never a propose unlock.',
  cio: 'CIO = internal research card and/or final synthesis. AVOID/SELL parks propose. HOLD is advisory; TRUST DEGRADED blocks buy-side propose-ready until dual/Street gates recover.',
  trust: 'TRUST HIGH needs dual lane AGREE + fresh Street evidence + QA/safety. DEGRADED means those gates failed — not a second Street rating.',
}

const CRITERIA_TIPS: Record<string, string> = {
  ticket: 'Deterministic ticket validator must PASS before propose.',
  critics: `Free critics (${laneLabel('deepseek-flash')} + Local + ${laneLabel('grok')} + ${laneLabel('chatgpt')}) should run at least once.`,
  zone: 'Price in entry zone or structure reclaimed.',
  ma_bounce: 'Hold or bounce on SMA20/50/200.',
  rsi_reset: 'RSI 40–70 band for setup quality.',
  macd: 'MACD not bearish.',
  volume: 'Volume or money-flow confirmation; N/A for funds/ETFs.',
  rr: 'Reward-to-risk ≥2:1 preferred.',
  invalidation: 'Stop on entry plan required for sizing.',
  catalyst: 'Near-term earnings within 5d flags caution.',
  fresh: 'Quote age ≤96h (weekend/session hold OK) for actionable desk.',
}

function deskStateTone(state: string): string {
  if (state === 'PROPOSE-READY') return BB.green
  if (state === 'TICKET PENDING') return BB.amber
  if (state === 'DATA GAP' || state === 'STALE') return BB.red
  if (state === 'GO') return BB.green
  if (state === 'WAIT') return BB.amber
  return BB.red
}

function ctaForDeskState(state: string): { label: string; tone: string; detail: string; style: CSSProperties } {
  if (state === 'PROPOSE-READY') {
    return { label: 'PROPOSE-READY', tone: BB.green, detail: DESK_TIPS.propose, style: successBtn }
  }
  if (state === 'TICKET PENDING') {
    return { label: 'TICKET PENDING', tone: BB.amber, detail: DESK_TIPS.pending, style: primaryBtn }
  }
  if (state === 'DATA GAP') {
    return { label: 'DATA GAP', tone: BB.red, detail: DESK_TIPS.gap, style: dangerBtn }
  }
  if (state === 'STALE') {
    return { label: 'STALE', tone: BB.red, detail: DESK_TIPS.stale, style: dangerBtn }
  }
  if (state === 'WAIT') {
    return { label: 'REFRESH PLAN', tone: BB.amber, detail: DESK_TIPS.wait, style: primaryBtn }
  }
  if (state === 'NOGO') {
    return { label: 'REVIEW / PARK', tone: BB.red, detail: DESK_TIPS.nogo, style: dangerBtn }
  }
  return { label: 'RUN CRITICS', tone: BB.amber, detail: DESK_TIPS.pending, style: primaryBtn }
}

function ageLabel(hours: number | null | undefined, asOf?: string | null): string {
  if (hours != null && Number.isFinite(hours)) {
    if (hours < 1) return 'current'
    if (hours < 48) return `${Math.round(hours)}h old`
    return `${Math.round(hours / 24)}d old`
  }
  return age(asOf)
}

function chipTone(tone: string): string {
  if (tone === 'green') return BB.green
  if (tone === 'amber') return BB.amber
  if (tone === 'red') return BB.red
  return BB.text3
}

function LookthroughBlock({ lookthrough, compact }: { lookthrough: any; compact?: boolean }) {
  if (!lookthrough) return null
  const lt = lookthrough
  return (
    <div style={{ marginTop: compact ? 10 : 14, padding: compact ? 9 : 12, borderRadius: 8, border: `1px solid ${BB.border}`, background: 'rgba(0,0,0,.18)' }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: BB.text3, letterSpacing: '.06em' }}>
        Fund look-through<HelpTip text="Sector weights + top holdings from fund_lookthrough.json — same as Re-Entry desk for FCNTX-style advisories." />
      </div>
      {!lt.available ? (
        <div style={{ fontSize: 11, color: BB.text3, marginTop: 6 }}>{lt.note || 'Look-through not on file yet.'}</div>
      ) : (
        <>
          <div style={{ fontSize: 12, fontWeight: 800, marginTop: 4 }}>{lt.fund_name || 'Fund/ETF'}</div>
          {lt.sectors?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
              {lt.sectors.slice(0, 6).map((s: any) => (
                <span key={s.name} style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, border: `1px solid ${BB.border}`, color: BB.text2 }}>
                  {s.name} {s.pct}%
                </span>
              ))}
            </div>
          )}
          {lt.top_holdings?.length > 0 && (
            <div style={{ fontSize: 10, color: BB.text3, marginTop: 6 }}>
              Top: {lt.top_holdings.slice(0, 5).map((h: any) => `${h.ticker} ${h.pct ?? '—'}%`).join(' · ')}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function WatchAdvisoryBody({
  row,
  deskRow,
  compact,
  onFull,
}: {
  row: any
  deskRow: any
  compact?: boolean
  onFull?: () => void
}) {
  const a = deskRow?.advisory
  const cta = ctaForDeskState(String(deskRow?.desk_state || row.now))
  const criteria = a?.criteria ?? []
  const metN = criteria.filter((c: any) => c.met === true).length
  const fs = compact ? 11 : 12
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ fontSize: compact ? 12 : 14, fontWeight: 900, color: deskStateTone(String(deskRow?.desk_state || row.now)) }}>
          SETUP ADVISORY<HelpTip text={DESK_TIPS.main} />
        </div>
        {onFull ? <button type="button" onClick={onFull} style={btn(true)} title="Open full-page advisory">OPEN FULL PAGE</button> : null}
      </div>
      <div style={{ padding: compact ? 8 : 10, borderRadius: 6, border: `1px solid ${cta.tone}`, background: `${cta.tone}14`, marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <b style={{ color: cta.tone, fontSize: compact ? 12 : 13 }}>{cta.label}</b>
          <HelpTip text={cta.detail} />
        </div>
        <div style={{ fontSize: 10, color: BB.text3, marginTop: 3 }}>{a?.action || row.next}</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: fs, marginBottom: 8 }}>
        <div><span style={{ color: BB.text3, fontSize: 10 }}>RANGE</span><br /><b>{deskRow?.entry_low == null ? '—' : `${money(deskRow.entry_low)} – ${money(deskRow.entry_high)}`}</b></div>
        <div><span style={{ color: BB.text3, fontSize: 10 }}>STOP / TARGET</span><br /><b style={{ color: BB.red }}>{money(deskRow?.stop)}</b> / <b style={{ color: BB.green }}>{money(deskRow?.target)}</b></div>
        <div><span style={{ color: BB.text3, fontSize: 10 }}>R:R</span><br /><b>{deskRow?.rr == null ? '—' : `${deskRow.rr}:1`}</b></div>
        <div><span style={{ color: BB.text3, fontSize: 10 }}>QUOTE AGE</span><br /><b>{ageLabel(deskRow?.price_age_h, deskRow?.price_as_of)}</b></div>
      </div>
      {(deskRow?.chips?.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
          {deskRow.chips.map((chip: any) => (
            <span key={chip.label} title={chip.detail} style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4, border: `1px solid ${chipTone(chip.tone)}`, color: chipTone(chip.tone) }}>
              {chip.label}
            </span>
          ))}
        </div>
      )}
      <LookthroughBlock lookthrough={a?.lookthrough} compact={compact} />
      <div style={{ marginTop: compact ? 10 : 12 }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: BB.text3, letterSpacing: '.06em', marginBottom: 6 }}>
          Criteria ({metN}/{criteria.length})<HelpTip text="Green MET / amber CHECK / red NOT MET — mapped from ticket validation + technicals, not a second LLM." />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: compact ? 4 : 6 }}>
          {criteria.map((c: any) => {
            const ct = c.met === true ? BB.green : c.met === false ? BB.red : BB.amber
            const tag = c.met === true ? 'MET' : c.met === false ? 'NOT' : 'CHECK'
            return (
              <div key={c.id} style={{ display: 'grid', gridTemplateColumns: '52px 1fr', gap: 6, padding: 6, borderRadius: 4, border: `1px solid ${ct}`, fontSize: 10.5 }}>
                <b style={{ color: ct }}>{tag}</b>
                <div><b>{c.label}<HelpTip text={CRITERIA_TIPS[c.id] || c.detail} /></b><div style={{ color: BB.text3 }}>{c.detail}</div></div>
              </div>
            )
          })}
        </div>
      </div>
      {a?.rationale?.length > 0 && (
        <ul style={{ margin: '10px 0 0', paddingLeft: 16, fontSize: 10.5, color: BB.text2, lineHeight: 1.45 }}>
          {a.rationale.map((line: string, i: number) => <li key={i}>{line}</li>)}
        </ul>
      )}
    </>
  )
}

type Lane = 'go' | 'wait' | 'nogo' | 'favorites' | 'legacy'
type QueueFilter = 'all' | 'needs_review' | 'deterministic_fail' | 'data_gaps' | 'actionable'

function num(...values: any[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}
function text(...values: any[]): string {
  for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  return ''
}
function dig(value: any, path: string): any {
  return path.split('.').reduce((current: any, key) => current?.[key], value)
}
function money(value: any): string {
  const parsed = num(value)
  return parsed === null ? '—' : `$${parsed.toFixed(2)}`
}
function age(value: any): string {
  if (!value) return 'as-of unavailable'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return String(value).slice(0, 16)
  const hours = Math.max(0, Math.round((Date.now() - time) / 36e5))
  return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old`
}
function valuation(item: any, fv: any, card: any) {
  const objects = [item, fv, card, item?.fundamentals, fv?.fundamentals, card?.fundamentals, item?.decision_packet?.fundamentals]
  const first = (paths: string[]) => {
    for (const object of objects) for (const path of paths) {
      const value = num(dig(object, path))
      if (value !== null) return value
    }
    return null
  }
  const pe = first(['pe', 'trailing_pe', 'trailingPe', 'valuation.pe'])
  const forwardPe = first(['forward_pe', 'forwardPe', 'fwd_pe', 'valuation.forward_pe'])
  const peg = first(['peg', 'peg_ratio', 'valuation.peg'])
  const pb = first(['pb', 'price_to_book', 'valuation.pb'])
  const ps = first(['ps', 'price_to_sales', 'valuation.ps'])
  const asOf = text(item?.fundamentals_as_of, fv?.fundamentals_as_of, card?.fundamentals_as_of, item?.last_enriched_at)
  const instrument = text(item?.instrument_type, item?.asset_type).toLowerCase()
  return {
    pe, forwardPe, peg, pb, ps, asOf,
    notApplicable: /etf|fund|mutual/.test(instrument),
    available: pe !== null || forwardPe !== null || peg !== null || pb !== null || ps !== null,
  }
}
function ticketState(item: any) {
  const packet = item?.decision_packet ?? {}
  const validation = packet?.current_actionable_plan?.ticket_validation ?? {}
  const review = packet?.ticket_review ?? {}
  const validated0 = Array.isArray(review?.tickets_validated) ? review.tickets_validated[0] : null
  const detRaw = text(validation.state, validated0?.state)
  const recRaw = text(review?.reconciled?.state)
  return {
    // Missing critics = NOT RUN (pending), not a hard fail / not UNVALIDATED-as-block
    deterministic: (detRaw || 'NOT RUN').toUpperCase(),
    reconciled: (recRaw || 'NOT RUN').toUpperCase(),
    local: text(review?.reviews?.local?.verdict, 'NOT RUN').toUpperCase(),
    'deepseek-flash': text(review?.reviews?.['deepseek-flash']?.verdict, 'NOT RUN').toUpperCase(),
    'deepseek-v4': text(review?.reviews?.['deepseek-v4']?.verdict, 'NOT RUN').toUpperCase(),
    grok: text(review?.reviews?.grok?.verdict, 'NOT RUN').toUpperCase(),
    chatgpt: text(review?.reviews?.chatgpt?.verdict, 'NOT RUN').toUpperCase(),
  }
}
function isFailure(value: string): boolean { return /FAIL|REJECT|BLOCK/.test(value) }
function isTicketPass(ticket: ReturnType<typeof ticketState>): boolean {
  return /^(PASS|PASS_WITH_WARNINGS|ADMITTED|OK)$/.test(ticket.deterministic)
}
function isTicketPending(ticket: ReturnType<typeof ticketState>): boolean {
  if (isFailure(ticket.deterministic) || isFailure(ticket.reconciled)) return false
  if (isTicketPass(ticket)) return false
  return (
    ticket.deterministic === 'NOT RUN'
    || /NOT RUN|UNVALIDATED|UNAVAILABLE|PENDING|REQUIRED|QUALITY_NOT_ASSESSED|REVIEW_UNAVAILABLE/.test(ticket.reconciled)
    || ticket.deterministic === 'REVIEW_REQUIRED'
  )
}
function originLabel(item: any): string {
  return item?.starred ? 'Operator favorite' : text(item?.origin_system, item?.source, 'system').replace(/_/g, ' ')
}
function updateReviewUrl(symbol: string, reviewOpen: boolean) {
  const url = new URL(window.location.href)
  if (symbol) url.searchParams.set('symbol', symbol); else url.searchParams.delete('symbol')
  if (reviewOpen) url.searchParams.set('review', '1'); else url.searchParams.delete('review')
  window.history.replaceState(window.history.state, '', url)
}

/** Server MAIN admission (lane membership). */
function admissionNow(item: any): 'GO' | 'WAIT' | 'NOGO' {
  const n = String(item?.now_status || '').toUpperCase()
  if (n === 'GO' || n === 'WAIT' || n === 'NOGO') return n as 'GO' | 'WAIT' | 'NOGO'
  if (item?.starred) return 'WAIT'
  return 'NOGO'
}

/**
 * Operator-visible NOW.
 * - Hard ticket FAIL → NOGO (never propose)
 * - Missing price (blocking) → WAIT
 * - Missing critics / QUALITY_NOT_ASSESSED → keep admission (badge: ticket pending)
 *   so the GO lane is not emptied when validation hasn't been run yet.
 */
function operatorNow(
  item: any,
  ticket: ReturnType<typeof ticketState>,
  price: number | null,
): 'GO' | 'WAIT' | 'NOGO' {
  const admitted = admissionNow(item)
  if (isFailure(ticket.deterministic) || isFailure(ticket.reconciled)) return 'NOGO'
  if (admitted === 'NOGO') return 'NOGO'
  // CIO AVOID/SELL (card or synthesis) — park; never propose-ready
  if (cioBlocksEntry(diligenceFromWatchlistItem(item))) return 'NOGO'
  if (price === null) return 'WAIT'
  if (admitted === 'GO') return 'GO'
  return admitted
}

function nextAction(
  ticket: ReturnType<typeof ticketState>,
  value: ReturnType<typeof valuation>,
  rsi: number | null,
  now: string,
  price: number | null,
  opts?: { cioBlocked?: boolean; trustBlocked?: boolean; deskState?: string },
): string {
  if (opts?.cioBlocked) return 'Park / suppress — CIO AVOID/SELL (advisory block). Street rating is separate context.'
  if (opts?.trustBlocked) return 'CIO TRUST DEGRADED — dual/Street gates not propose-grade (buy-side).'
  if (opts?.deskState === 'NOGO') return 'Park / suppress — not proposeable.'
  if (now === 'NOGO' && (isFailure(ticket.deterministic) || isFailure(ticket.reconciled))) {
    return 'Fix deterministic gate — not proposeable.'
  }
  if (now === 'NOGO') return 'Park / suppress — MAIN NOGO.'
  if (price === null) return 'Refresh quote / price before acting.'
  if (now === 'WAIT') return 'Refresh plan / fill data gaps — MAIN WAIT.'
  if (isTicketPending(ticket)) return 'Setup GO — run critics before propose (ticket pending).'
  if (rsi === null) return 'Refresh technical inputs before acting.'
  if (!value.notApplicable && !value.available) return 'Valuation is missing; review source coverage.'
  if (isTicketPass(ticket)) return 'Propose / open evidence — ticket validated.'
  return 'Propose / open evidence — MAIN GO setup.'
}
function needsUnvalidated(ticket: ReturnType<typeof ticketState>): boolean {
  return isTicketPending(ticket)
}

export default function WatchTruthAuditPanel() {
  const initialUrl = new URL(window.location.href)
  const [open, setOpen] = useState(() => initialUrl.searchParams.get('review') !== '0')
  const [lane, setLane] = useState<Lane>(() => {
    const q = (initialUrl.searchParams.get('now') || initialUrl.searchParams.get('op_lane') || 'go').toLowerCase()
    if (q === 'wait' || q === 'nogo' || q === 'favorites' || q === 'legacy') return q as Lane
    return 'go'
  })
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')
  const [streetFilter, setStreetFilter] = useState<StreetRatingFilter>(() => {
    const q = (initialUrl.searchParams.get('street') || initialUrl.searchParams.get('rating') || 'all').toLowerCase()
    if (q === 'strong_buy' || q === 'buy_plus' || q === 'buy' || q === 'hold' || q === 'underperform' || q === 'sell' || q === 'no_coverage') return q as StreetRatingFilter
    return 'all'
  })
  const [cioFilter, setCioFilter] = useState<CioFilter>(() => {
    const q = (initialUrl.searchParams.get('cio') || 'all')
    if (!q || q.toLowerCase() === 'all') return 'all'
    const allowed: CioFilter[] = ['buy_side', 'STRONG_BUY', 'BUY', 'ADD', 'ADD_ON_PULLBACK', 'HOLD', 'RESEARCH_MORE', 'TRIM', 'avoid_side', 'AVOID', 'IGNORE', 'none']
    return allowed.find(k => k.toLowerCase() === q.toLowerCase()) ?? 'all'
  })
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(() => initialUrl.searchParams.get('symbol')?.toUpperCase() ?? '')
  const [page, setPage] = useState(0)
  const [listPage, setListPage] = useState(0)
  const [fullOpen, setFullOpen] = useState(false)
  const [reviewBusy, setReviewBusy] = useState('')
  const [message, setMessage] = useState('')
  const [premium, setPremium] = useState<any>(null)
  const [confirmation, setConfirmation] = useState('')

  // One MAIN fetch; client splits ticket-honest GO/WAIT/NOGO. Legacy = old warehouse.
  const itemsPath = lane === 'legacy'
    ? '/api/v2/watchlist/items?sort=hermes&lane=legacy_hermes'
    : '/api/v2/watchlist/items?sort=hermes&lane=main'

  const { data: wl, refetch: refetchWatch } = useApi<any>(itemsPath, 60_000)
  const { data: qualityBoard } = useApi<any>('/api/v2/watchlist/quality-board', 120_000)
  const { data: fv } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: cards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const { data: lv } = useApi<any>('/api/v2/ui/prefs/get?key=portfolio.reentry.resistance.v1', 300_000)
  const paMap = useProAnalystMap()
  const levelMap: Record<string, any> = lv?.data?.value?.symbols ?? lv?.value?.symbols ?? {}

  const items: any[] = wl?.items ?? wl?.data?.items ?? []
  const quality = wl?.quality ?? wl?.data?.quality ?? qualityBoard?.main_lane ?? qualityBoard?.data?.main_lane
  const fvMap = fv?.map ?? fv?.data?.map ?? {}
  const cardMap = cards?.cards ?? cards?.data?.cards ?? {}

  const unique = useMemo(() => {
    const map = new Map<string, any>()
    for (const item of items) {
      const symbol = text(item?.symbol).toUpperCase()
      if (!symbol) continue
      const prior = map.get(symbol)
      const rich = (item.starred ? 1e12 : 0) + (item.directive_id ? 1e9 : 0) + (num(item.score) ?? 0)
      const priorRich = prior ? (prior.starred ? 1e12 : 0) + (prior.directive_id ? 1e9 : 0) + (num(prior.score) ?? 0) : -1
      if (!prior || rich > priorRich) map.set(symbol, item)
    }
    return [...map.values()]
  }, [items])

  const classified = useMemo(() => unique.map(item => {
    const symbol = String(item.symbol).toUpperCase()
    const value = valuation(item, fvMap[symbol], cardMap[symbol])
    const ticket = ticketState(item)
    const rsi = num(item.rsi, item.rsi_14, fvMap[symbol]?.rsi)
    const price = num(item.price, item.last_price, item.price_live)
    const priceAt = text(item.price_as_of, item.last_enriched_at)
    const lvl = levelMap[symbol] ?? null
    const level = lvl ? {
      resistance: num(lvl.resistance), resistancePct: num(lvl.distance_pct),
      support: num(lvl.support), supportPct: num(lvl.support_distance_pct),
      resistanceState: text(lvl.state), supportState: text(lvl.support_state),
    } : null
    const pa = paMap[symbol] ?? paMap[item.symbol] ?? null
    const streetRec = streetRecOf(pa)
    const cioList = cioVerdicts(item)
    // Prefer avoid-side label when either research card or synthesis blocks
    const diligence = diligenceFromWatchlistItem(item)
    const cioBlocked = cioBlocksEntry(diligence)
    const trustBlocked = cioTrustBlocksPropose(item)
    const cioPrimary = (
      cioBlocked
        ? (cioList.find(c => ['AVOID', 'IGNORE', 'SELL', 'REBALANCE_TRIM'].includes(c)) || cioList[0])
        : cioList[0]
    ) || ''
    const hasDataGap = price === null || rsi === null || (!value.notApplicable && !value.available)
    const needsReview = needsUnvalidated(ticket)
    const ticketPending = isTicketPending(ticket)
    const now = operatorNow(item, ticket, price)
    // Propose-ready = GO + ticket pass + price + CIO not blocking + trust not DEGRADED
    const actionable = (
      now === 'GO'
      && isTicketPass(ticket)
      && price !== null
      && !cioBlocked
      && !trustBlocked
    )
    return {
      item, symbol, value, ticket, rsi, price, priceAt, level, pa, streetRec, cioList, cioPrimary,
      hasDataGap, needsReview, ticketPending, actionable, now,
      cioBlocked, trustBlocked,
      admitted: admissionNow(item),
      next: nextAction(ticket, value, rsi, now, price, { cioBlocked, trustBlocked }),
    }
  }), [unique, fv, cards, lv, paMap])

  const deskSymbols = useMemo(
    () => classified.map(r => r.symbol).filter(Boolean).join(','),
    [classified],
  )
  const { data: deskPayload } = useApi<any>(
    deskSymbols ? `/api/v2/watch/decision-desk?symbols=${encodeURIComponent(deskSymbols)}` : '/api/v2/watch/decision-desk',
    60_000,
    { enabled: classified.length > 0 },
  )
  const deskBySymbol: Record<string, any> = deskPayload?.by_symbol ?? deskPayload?.data?.by_symbol ?? {}
  const deskFreshness = deskPayload?.freshness ?? deskPayload?.data?.freshness ?? {}

  const trueGo = classified.filter(r => r.now === 'GO')
  const trueWait = classified.filter(r => r.now === 'WAIT')
  const trueNogo = classified.filter(r => r.now === 'NOGO')
  const favorites = classified.filter(r => Boolean(r.item.starred))
  const demotedFromAdmissionGo = classified.filter(r => r.admitted === 'GO' && r.now !== 'GO').length
  const ticketPendingGo = trueGo.filter(r => r.ticketPending).length
  const proposeReadyGo = trueGo.filter(r => r.actionable).length

  const laneRows = classified.filter(row => {
    if (lane === 'go') return row.now === 'GO'
    if (lane === 'wait') return row.now === 'WAIT'
    if (lane === 'nogo') return row.now === 'NOGO'
    if (lane === 'favorites') return Boolean(row.item.starred)
    return true
  })

  const filtered = laneRows.filter(row => {
    if (search.trim() && !`${row.symbol} ${row.item.source ?? ''} ${row.item.profile_sector ?? ''} ${row.ticket.deterministic} ${row.next} ${row.now} ${row.streetRec} ${row.cioPrimary}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    if (queueFilter === 'needs_review' && !row.needsReview) return false
    if (queueFilter === 'deterministic_fail' && !isFailure(row.ticket.deterministic)) return false
    if (queueFilter === 'data_gaps' && !row.hasDataGap) return false
    if (queueFilter === 'actionable' && !row.actionable) return false
    if (!matchesStreetFilter(row.streetRec, streetFilter)) return false
    if (!matchesCioFilter(row.cioList, cioFilter)) return false
    return true
  })

  // Lane-scoped counts for rating chips (ignore rating filters so chips stay useful as toggles)
  const streetCounts = useMemo(() => {
    const counts: Record<string, number> = { all: laneRows.length, strong_buy: 0, buy: 0, buy_plus: 0, hold: 0, no_coverage: 0 }
    for (const row of laneRows) {
      counts[row.streetRec] = (counts[row.streetRec] ?? 0) + 1
      if (row.streetRec === 'strong_buy' || row.streetRec === 'buy') counts.buy_plus += 1
    }
    return counts
  }, [laneRows])

  // GO lane: propose-ready first, then ticket-pending, then hermes rank
  const sorted = useMemo(() => {
    const list = [...filtered]
    list.sort((a, b) => {
      if (a.actionable !== b.actionable) return a.actionable ? -1 : 1
      if (a.ticketPending !== b.ticketPending) return a.ticketPending ? -1 : 1
      if (isFailure(a.ticket.deterministic) !== isFailure(b.ticket.deterministic)) return isFailure(a.ticket.deterministic) ? 1 : -1
      // Within same ticket state, Strong Buy / Buy bubble slightly
      const streetRank = (r: string) => (r === 'strong_buy' ? 0 : r === 'buy' ? 1 : r === 'hold' ? 2 : 3)
      const sr = streetRank(a.streetRec) - streetRank(b.streetRec)
      if (sr !== 0) return sr
      return (num(a.item.hermes_rank) ?? 9999) - (num(b.item.hermes_rank) ?? 9999)
    })
    return list
  }, [filtered])

  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const showAll = listPage < 0
  const safePage = showAll ? 0 : Math.min(page, pageCount - 1)
  const shown = showAll ? sorted : sorted.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)
  const totalPages = pageCount

  useEffect(() => { setPage(0); setListPage(0) }, [lane, queueFilter, streetFilter, cioFilter, search, itemsPath])
  useEffect(() => {
    if (selected && classified.some(r => r.symbol === selected)) return
    const first = (lane === 'go' ? trueGo[0] : null) ?? favorites[0] ?? classified[0]
    if (first) setSelected(first.symbol)
  }, [classified.length, lane, trueGo.length])

  const selectedRow = classified.find(row => row.symbol === selected)
  const selectedDesk = selectedRow ? deskBySymbol[selectedRow.symbol] : null
  const selectForReview = (symbol: string) => {
    setSelected(symbol); setOpen(true); setMessage(''); setPremium(null); updateReviewUrl(symbol, true)
  }
  const setDeskOpen = (next: boolean) => { setOpen(next); updateReviewUrl(selected, next) }

  const toggleStar = async (item: any) => {
    const symbol = String(item.symbol).toUpperCase()
    setMessage(`${symbol} — updating favorite…`)
    try {
      const response = await fetch('/api/v2/watchlist/star', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, starred: !item.starred }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'favorite update failed')
      setMessage(`${symbol} — ${item.starred ? 'unstarred' : 'starred'}`)
      window.setTimeout(() => refetchWatch(), 500)
    } catch (error: any) { setMessage(`${symbol} — ${String(error?.message || error)}`) }
  }
  const runReview = async (lanes: string, label: string) => {
    if (!selected || reviewBusy) return
    setReviewBusy(label); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selected, lanes }),
      })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'review failed')
      setMessage(`${selected} — ${label} queued.`)
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) }
    finally { setReviewBusy('') }
  }
  const estimatePremium = async () => {
    if (!selected || reviewBusy) return
    setReviewBusy('premium estimate'); setMessage(''); setPremium(null); setConfirmation('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/estimate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selected }),
      })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'estimate failed')
      setPremium(data)
      setMessage(data.available ? `${selected} — paid estimate ready.` : `${selected} — ${data.reason}`)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) }
    finally { setReviewBusy('') }
  }
  const runPremium = async () => {
    if (!selected || !premium?.available || reviewBusy) return
    setReviewBusy('premium run'); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selected, ticket_hash: premium.ticket_hash, confirmation }),
      })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'paid review failed')
      setMessage(`${selected} — paid review queued.`); setPremium(null); setConfirmation('')
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) }
    finally { setReviewBusy('') }
  }

  const mainCap = quality?.main_cap ?? 60
  const failures = classified.filter(r => isFailure(r.ticket.deterministic) || isFailure(r.ticket.reconciled)).length

  return (
    <section style={shell} aria-label="MAIN setup command desk">
      {/* HERO — dark elevated desk */}
      <div style={{
        padding: '16px 18px',
        background: 'linear-gradient(135deg, rgba(34,197,94,.14), rgba(8,14,24,.95) 42%, rgba(255,176,0,.08))',
        borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.12em', color: BB.green, textTransform: 'uppercase' }}>
              MAIN command desk
            </div>
            <div style={{ fontSize: 22, fontWeight: 900, color: BB.text0, marginTop: 4 }}>
              What do I do next?
            </div>
            <div style={{ fontSize: 12, color: BB.text3, marginTop: 4, maxWidth: 720, lineHeight: 1.45 }}>
              GO = MAIN admission setup. Ticket FAIL → NOGO. Missing critics stay in GO with a pending badge
              ({ticketPendingGo} ticket-pending · {proposeReadyGo} propose-ready · {demotedFromAdmissionGo} demoted this load).
              MAIN ≠ full warehouse — ETFs/funds live in RESEARCH/ToS unless promoted. Defense rotation stays on Defense unless you Watch-click.
              Contract {WATCH_OPERATOR_CONTRACT}.
            </div>
          </div>
          <button type="button" onClick={() => setDeskOpen(!open)} aria-expanded={open} style={primaryBtn}>
            {open ? 'Collapse' : 'Open desk'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14, alignItems: 'stretch' }}>
          {([
            { key: 'go' as Lane, n: trueGo.length, label: 'GO', color: BB.green, hint: `${proposeReadyGo} ready · ${ticketPendingGo} pending` },
            { key: 'wait' as Lane, n: trueWait.length, label: 'WAIT', color: BB.amber, hint: 'Data / plan gap' },
            { key: 'nogo' as Lane, n: trueNogo.length, label: 'NOGO', color: BB.red, hint: 'Fail / park' },
          ]).map(b => (
            <button
              key={b.key}
              type="button"
              onClick={() => { setLane(b.key); setDeskOpen(true) }}
              style={{ ...chip(lane === b.key, b.color), minWidth: 120 }}
            >
              <div style={{ fontSize: 28, fontWeight: 900, lineHeight: 1.1 }}>{b.n}</div>
              <div style={{ fontSize: 12, marginTop: 2 }}>{b.label}</div>
              <div style={{ fontSize: 10, fontWeight: 600, opacity: 0.85, marginTop: 2 }}>{b.hint}</div>
            </button>
          ))}
          <div style={{
            marginLeft: 'auto',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            gap: 4,
            fontSize: 11,
            color: BB.text3,
            minWidth: 170,
          }}>
            <div>MAIN pool {classified.length}/{mainCap}</div>
            <div>★ {favorites.length} · ticket fail {failures}</div>
            <div>propose-ready {proposeReadyGo}</div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
          <button type="button" style={chip(lane === 'go', BB.green)} onClick={() => { setLane('go'); setDeskOpen(true) }}>
            Review GO →
          </button>
          <button type="button" style={chip(lane === 'wait', BB.amber)} onClick={() => { setLane('wait'); setDeskOpen(true) }}>
            Fix WAIT →
          </button>
          <button type="button" style={chip(lane === 'nogo', BB.red)} onClick={() => { setLane('nogo'); setDeskOpen(true) }}>
            Cull NOGO →
          </button>
          <button type="button" style={btn(lane === 'favorites')} onClick={() => { setLane('favorites'); setDeskOpen(true) }}>
            ★ Favorites
          </button>
          <button type="button" style={btn(lane === 'legacy')} onClick={() => { setLane('legacy'); setDeskOpen(true) }}>
            Legacy top-200
          </button>
        </div>
      </div>

      {!open && selected && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px 16px', background: 'var(--bg2)', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: BB.text2 }}>Selected <b style={{ color: BB.text0 }}>{selected}</b></span>
          <button type="button" onClick={() => setDeskOpen(true)} style={btn(true)}>Review {selected}</button>
        </div>
      )}

      {open && (
        <div style={{ padding: 12, background: 'rgba(0,0,0,.18)' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))',
            gap: 10,
            marginBottom: 12,
            padding: '10px 12px',
            borderRadius: 8,
            border: `1px solid ${BB.border}`,
            background: 'rgba(0,0,0,.22)',
            fontSize: 11,
          }}>
            <div><span style={{ color: BB.text3 }}>Quote age (GO+WAIT median)</span><br /><b>{deskFreshness.price_age_h_median == null ? '—' : `${deskFreshness.price_age_h_median}h`}</b></div>
            <div><span style={{ color: BB.text3 }}>RSI cache age (median)</span><br /><b>{deskFreshness.rsi_age_h_median == null ? '—' : `${deskFreshness.rsi_age_h_median}h`}</b></div>
            <div><span style={{ color: BB.text3 }}>Data gaps</span><br /><b style={{ color: (deskFreshness.data_gap_count || 0) > 0 ? BB.red : BB.text0 }}>{deskFreshness.data_gap_count ?? 0}</b></div>
            <div><span style={{ color: BB.text3 }}>Ticket pending</span><br /><b style={{ color: (deskFreshness.ticket_pending_count || 0) > 0 ? BB.amber : BB.text0 }}>{deskFreshness.ticket_pending_count ?? ticketPendingGo}</b></div>
            <div><span style={{ color: BB.text3 }}>Propose-ready</span><br /><b style={{ color: BB.green }}>{deskFreshness.propose_ready_count ?? proposeReadyGo}</b></div>
            <div><span style={{ color: BB.text3 }}>Stale quotes</span><br /><b style={{ color: (deskFreshness.stale_symbol_count || 0) > 0 ? BB.amber : BB.text0 }}>{deskFreshness.stale_symbol_count ?? 0}</b></div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: BB.text0 }}>
              {lane === 'go' ? 'GO — MAIN setups' : lane === 'wait' ? 'WAIT — data / plan gaps' : lane === 'nogo' ? 'NOGO — fail / park' : lane === 'favorites' ? '★ Favorites' : 'Legacy Hermes top-200'}
            </span>
            <span style={{ fontSize: 11, color: BB.text3 }}>{sorted.length} rows</span>
            <select
              value={queueFilter}
              onChange={e => setQueueFilter(e.target.value as QueueFilter)}
              style={{ fontSize: 11, padding: '6px 8px', background: BB.bgShift, border: `1px solid ${BB.border}`, color: BB.text0, borderRadius: 4 }}
            >
              <option value="all">All ticket states</option>
              <option value="deterministic_fail">Deterministic fail</option>
              <option value="needs_review">Ticket pending</option>
              <option value="data_gaps">Data gaps</option>
              <option value="actionable">Propose-ready only</option>
            </select>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter symbol…"
              style={{ marginLeft: 'auto', minWidth: 180, fontSize: 11, padding: '6px 8px', background: BB.bgShift, border: `1px solid ${BB.border}`, color: BB.text0, borderRadius: 4 }}
            />
          </div>

          {/* Street Strong Buy / Buy+ + CIO filters — same semantics as card desk; live on MAIN */}
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 12,
            padding: '10px 12px', borderRadius: 8, border: `1px solid ${BB.border}`,
            background: 'rgba(0,0,0,.22)',
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.06em', color: BB.text3 }}>STREET RATING</span>
              <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {STREET_FILTER_OPTS.map(opt => {
                  const active = streetFilter === opt.key
                  const n = streetCounts[opt.key] ?? 0
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      title={opt.key === 'buy_plus' ? 'Strong Buy or Buy (Street consensus)' : `Filter by Street ${opt.label}`}
                      onClick={() => setStreetFilter(opt.key)}
                      style={{
                        fontSize: 10, fontWeight: active ? 800 : 600, padding: '5px 10px', borderRadius: 4, cursor: 'pointer',
                        border: `1px solid ${active ? opt.color : BB.border}`,
                        background: active ? `${opt.color}22` : 'rgba(0,0,0,.2)',
                        color: active ? opt.color : BB.text2,
                      }}
                    >
                      {opt.label}{opt.key !== 'all' ? ` ${n}` : ''}
                    </button>
                  )
                })}
              </span>
            </div>
            <div style={{ width: 1, alignSelf: 'stretch', background: BB.border, margin: '0 2px' }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 160 }}>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.06em', color: BB.text3 }}>CIO VIEW</span>
              <select
                value={cioFilter}
                onChange={e => setCioFilter(e.target.value as CioFilter)}
                title="Internal CIO / research-card recommendation"
                style={{ fontSize: 11, padding: '6px 8px', background: BB.bgShift, border: `1px solid ${BB.border}`, color: BB.text0, borderRadius: 4, minWidth: 160 }}
              >
                {CIO_FILTER_OPTS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
              </select>
            </div>
            {(streetFilter !== 'all' || cioFilter !== 'all') && (
              <button
                type="button"
                onClick={() => { setStreetFilter('all'); setCioFilter('all') }}
                style={{ ...btn(false), marginLeft: 'auto', alignSelf: 'flex-end' }}
              >
                Clear rating filters
              </button>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.2fr) minmax(300px,.8fr)', gap: 12, alignItems: 'start' }}>
            {/* Dark command list — elevated rows + CTA */}
            <div style={{ border: `1px solid ${BB.border}`, borderRadius: 10, overflow: 'hidden', background: BB.bgPanel, boxShadow: '0 8px 24px rgba(0,0,0,.35)' }}>
              {shown.map(row => {
                const isSelected = selected === row.symbol
                const deskRow = deskBySymbol[row.symbol]
                // Prefer broker desk state, but never show PROPOSE-READY when CIO/trust blocks
                let deskState = String(deskRow?.desk_state || (row.actionable ? 'PROPOSE-READY' : row.ticketPending ? 'TICKET PENDING' : row.hasDataGap ? 'DATA GAP' : row.now))
                if (row.cioBlocked || row.now === 'NOGO') {
                  if (deskState === 'PROPOSE-READY' || deskState === 'GO' || deskState === 'TICKET PENDING') {
                    deskState = 'NOGO'
                  }
                } else if (row.trustBlocked && deskState === 'PROPOSE-READY') {
                  // Trust is not quote-stale — demote propose only
                  deskState = row.ticketPending ? 'TICKET PENDING' : 'GO'
                }
                if (deskRow?.actionable === false && deskState === 'PROPOSE-READY') deskState = String(deskRow.desk_state || row.now)
                const nowColor = deskStateTone(deskState)
                const cta = ctaForDeskState(deskState)
                const ctaLabel = cta.label === 'PROPOSE-READY' ? 'Propose' : cta.label === 'TICKET PENDING' ? 'Validate' : cta.label === 'DATA GAP' ? 'Refresh' : (deskState === 'NOGO' || row.now === 'NOGO') ? 'Review' : 'Open'
                const ctaStyle = cta.style
                return (
                  <div
                    key={row.symbol}
                    role="button"
                    tabIndex={0}
                    onClick={() => selectForReview(row.symbol)}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectForReview(row.symbol) } }}
                    onDoubleClick={() => { selectForReview(row.symbol); setFullOpen(true) }}
                    className="wlc-card-dark"
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '80px 1fr auto',
                      gap: 10,
                      padding: '12px 14px',
                      borderBottom: `1px solid ${BB.border}`,
                      cursor: 'pointer',
                      background: isSelected
                        ? `linear-gradient(90deg, ${nowColor}18, rgba(20,30,48,.95))`
                        : 'linear-gradient(90deg, rgba(0,0,0,.15), transparent)',
                      boxShadow: isSelected ? `inset 4px 0 0 ${nowColor}` : `inset 3px 0 0 ${nowColor}55`,
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 16, fontWeight: 900, color: BB.text0, letterSpacing: '-0.02em' }}>{row.symbol}</div>
                      <div style={{ fontSize: 11, fontWeight: 800, color: nowColor, marginTop: 2 }}>{row.now}</div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: nowColor, marginTop: 2 }}>{deskState.replace('PROPOSE-READY', 'READY')}</div>
                      {(deskRow?.chips?.length > 0) && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 3 }}>
                          {deskRow.chips.slice(0, 2).map((chip: any) => (
                            <span key={chip.label} title={chip.detail} style={{ fontSize: 10, color: chipTone(chip.tone) }}>{chip.label}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: (row.cioBlocked || row.now === 'NOGO' || isFailure(row.ticket.deterministic) || isFailure(row.ticket.reconciled)) ? BB.red : BB.text1 }}>
                        {row.cioBlocked
                          ? row.next
                          : (deskRow?.advisory?.action || row.next)}
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 4 }}>
                        <span
                          title="Street professional-analyst consensus (advisory — not MAIN admission)"
                          style={{
                            fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
                            color: STREET_REC_COLOR[row.streetRec] || BB.text3,
                            border: `1px solid ${STREET_REC_COLOR[row.streetRec] || BB.border}`,
                            background: `${STREET_REC_COLOR[row.streetRec] || BB.text3}14`,
                            textTransform: 'capitalize',
                          }}
                        >
                          {streetRecLabel(row.streetRec)}
                        </span>
                        {row.cioPrimary && (
                          <span
                            title="Internal CIO / research-card view"
                            style={{
                              fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
                              color: cioColor(row.cioPrimary),
                              border: `1px solid ${cioColor(row.cioPrimary)}66`,
                              background: `${cioColor(row.cioPrimary)}14`,
                            }}
                          >
                            CIO {row.cioPrimary.replace(/_/g, ' ')}
                          </span>
                        )}
                        {row.pa?.divergence === 'divergent' && (
                          <span title={`Internal vs Street diverge`} style={{ fontSize: 10, fontWeight: 800, color: BB.red }}>≠ Street</span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: BB.text3, marginTop: 3 }}>
                        {money(row.price)} · {originLabel(row.item)} · ticket {row.ticket.deterministic}
                        {row.admitted === 'GO' && row.now === 'NOGO'
                          ? (row.cioBlocked ? ' · demoted (CIO block)' : row.trustBlocked ? ' · demoted (trust)' : ' · demoted (ticket FAIL)')
                          : ''}
                      </div>
                    </div>
                    <button
                      type="button"
                      title={cta.detail}
                      onClick={e => { e.stopPropagation(); selectForReview(row.symbol) }}
                      style={isSelected ? ctaStyle : { ...ctaStyle, opacity: 0.92 }}
                    >
                      {isSelected ? 'Selected' : ctaLabel}
                    </button>
                  </div>
                )
              })}
              {!shown.length && (
                <div style={{ padding: 24, color: BB.text3, fontSize: 13 }}>
                  {lane === 'go'
                    ? 'No MAIN GO setups in this filter. Clear filters or check WAIT/NOGO.'
                    : 'No symbols in this lane for the current filter.'}
                </div>
              )}
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 14px', fontSize: 11, color: BB.text3,
                background: 'linear-gradient(180deg, rgba(0,0,0,.35), rgba(0,0,0,.55))',
                borderTop: `1px solid ${BB.border}`,
                flexWrap: 'wrap',
                gap: 8,
              }}>
                <span>{sorted.length} matching · {showAll ? 'all rows' : `page ${safePage + 1}/${totalPages}`}</span>
                <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <button type="button" disabled={showAll || safePage === 0} onClick={() => { setListPage(p => Math.max(0, p - 1)); setPage(p => Math.max(0, p - 1)) }} style={terminalButton('secondary') as CSSProperties}>Prev</button>
                  <button type="button" disabled={showAll || safePage >= totalPages - 1} onClick={() => { setListPage(p => p + 1); setPage(p => p + 1) }} style={terminalButton('secondary') as CSSProperties}>Next</button>
                  {showAll ? (
                    <button type="button" onClick={() => { setListPage(0); setPage(0) }} style={btn(false)}>PAGE {PAGE_SIZE}</button>
                  ) : (
                    <button type="button" onClick={() => { setListPage(-1); setPage(0) }} style={btn(true)} disabled={!sorted.length}>SHOW ALL {sorted.length || ''}</button>
                  )}
                </span>
              </div>
            </div>

            <aside
              style={{
                border: `1px solid ${BB.border}`,
                borderRadius: 10,
                padding: 0,
                position: 'sticky',
                top: 8,
                background: `linear-gradient(165deg, ${BB.bgElevated} 0%, ${BB.bg} 100%)`,
                boxShadow: '0 10px 28px rgba(0,0,0,.4)',
                overflow: 'hidden',
              }}
              aria-live="polite"
            >
              {!selectedRow ? (
                <div style={{ color: BB.text3, fontSize: 12, padding: 14 }}>Select a symbol.</div>
              ) : (
                <>
                  <div style={{ padding: '12px 14px', borderBottom: `1px solid ${BB.border}`, background: 'rgba(0,0,0,.22)' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <b style={{ fontSize: 20, color: BB.text0 }}>{selectedRow.symbol}</b>
                      <span style={{
                        fontSize: 11, fontWeight: 800, padding: '3px 8px', borderRadius: 999,
                        color: selectedRow.now === 'GO' ? BB.green : selectedRow.now === 'WAIT' ? BB.amber : BB.red,
                        border: `1px solid currentColor`,
                        background: selectedRow.now === 'GO' ? 'rgba(34,197,94,.12)' : selectedRow.now === 'WAIT' ? 'rgba(255,176,0,.12)' : 'rgba(239,68,68,.12)',
                      }}>{selectedRow.now}</span>
                      {selectedRow.ticketPending && (
                        <span style={{ fontSize: 10, fontWeight: 800, color: BB.amber, letterSpacing: '.06em' }}>TICKET PENDING</span>
                      )}
                      {selectedRow.actionable && !(selectedDesk?.actionable === false) && (
                        <span style={{ fontSize: 10, fontWeight: 800, color: BB.green, letterSpacing: '.06em' }}>PROPOSE-READY</span>
                      )}
                      {(selectedRow.cioBlocked || selectedRow.trustBlocked || selectedDesk?.desk_state === 'NOGO') && (
                        <span style={{ fontSize: 10, fontWeight: 800, color: BB.red, letterSpacing: '.06em' }}>
                          {selectedRow.cioBlocked ? 'CIO BLOCK' : selectedRow.trustBlocked ? 'TRUST BLOCK' : 'NOT PROPOSEABLE'}
                        </span>
                      )}
                      <span
                        title="Street professional-analyst consensus (advisory)"
                        style={{
                          fontSize: 10, fontWeight: 800, padding: '3px 8px', borderRadius: 999,
                          color: STREET_REC_COLOR[selectedRow.streetRec] || BB.text3,
                          border: `1px solid ${STREET_REC_COLOR[selectedRow.streetRec] || BB.border}`,
                          background: `${STREET_REC_COLOR[selectedRow.streetRec] || BB.text3}14`,
                          textTransform: 'capitalize',
                        }}
                      >
                        {streetRecLabel(selectedRow.streetRec)}
                      </span>
                      {selectedRow.cioPrimary && (
                        <span
                          title="Internal CIO / research-card view"
                          style={{
                            fontSize: 10, fontWeight: 800, padding: '3px 8px', borderRadius: 999,
                            color: cioColor(selectedRow.cioPrimary),
                            border: `1px solid ${cioColor(selectedRow.cioPrimary)}66`,
                            background: `${cioColor(selectedRow.cioPrimary)}14`,
                          }}
                        >
                          CIO {selectedRow.cioPrimary.replace(/_/g, ' ')}
                        </span>
                      )}
                      {(() => {
                        const trust = selectedRow.item?.cio_trust
                        if (!trust?.level) return null
                        const hi = trust.level === 'HIGH'
                        const failed = (trust.failed_gates || []).join(', ') || 'dual/Street/QA'
                        const age = trust.ages?.synthesis_age_h
                        const tip = hi
                          ? `${DESK_TIPS.trust} This name is HIGH.`
                          : `${DESK_TIPS.trust} Failed: ${failed}.${age != null ? ` CIO synthesis age ${age}h.` : ''} Street Buy does not clear this.`
                        return (
                          <span title={tip} style={{
                            fontSize: 10, fontWeight: 800, padding: '3px 8px', borderRadius: 999,
                            color: hi ? BB.green : BB.amber,
                            border: `1px solid ${hi ? BB.green : BB.amber}`,
                            background: hi ? 'rgba(34,197,94,.12)' : 'rgba(255,176,0,.12)',
                          }}>
                            TRUST {trust.level}
                            {trust.dual_mode ? ` · ${trust.dual_mode}` : ''}
                            {age != null ? ` · CIO ${age}h` : ''}
                            <HelpTip text={tip} />
                          </span>
                        )
                      })()}
                      <button type="button" onClick={() => void toggleStar(selectedRow.item)} style={{ ...btn(Boolean(selectedRow.item.starred)), marginLeft: 'auto' }}>
                        {selectedRow.item.starred ? 'Unstar' : '★ Star'}
                      </button>
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: BB.text3 }}>
                      {text(selectedRow.item.profile_sector, '—')} · {money(selectedRow.price)} · RSI {selectedRow.rsi === null ? '—' : selectedRow.rsi.toFixed(1)}
                    </div>
                    <div style={{ marginTop: 8 }}>
                      <ProAnalystPill symbol={selectedRow.symbol} map={paMap} />
                    </div>
                  </div>
                  <div style={{ padding: '12px 14px' }}>
                    <div style={{ padding: 10, borderRadius: 8, background: 'rgba(0,0,0,.28)', border: `1px solid ${BB.border}` }}>
                      <div style={{ fontSize: 10, fontWeight: 800, color: BB.text3, letterSpacing: '.06em' }}>NEXT ACTION</div>
                      <div style={{ fontSize: 14, fontWeight: 800, marginTop: 4, color: (selectedRow.cioBlocked || selectedRow.now === 'NOGO' || isFailure(selectedRow.ticket.deterministic) || isFailure(selectedRow.ticket.reconciled)) ? BB.red : BB.text0 }}>
                        {selectedDesk?.advisory?.action || selectedRow.next}
                      </div>
                    </div>
                    <div style={{
                      marginTop: 10, padding: 10, borderRadius: 8, border: `1px solid ${BB.border}`,
                      background: 'rgba(0,0,0,.18)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
                    }}>
                      <div>
                        <div style={{ fontSize: 10, color: BB.text3, fontWeight: 800, letterSpacing: '.05em' }}>
                          STREET<HelpTip text={DESK_TIPS.street} />
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 800, color: STREET_REC_COLOR[selectedRow.streetRec] || BB.text1, textTransform: 'capitalize', marginTop: 2 }}>
                          {streetRecLabel(selectedRow.streetRec)}
                        </div>
                        <div style={{ fontSize: 10, color: BB.text3, marginTop: 2 }}>
                          {selectedRow.pa?.n != null ? `${selectedRow.pa.n} analysts` : '—'}
                          {selectedRow.pa?.upside != null ? ` · ${selectedRow.pa.upside > 0 ? '+' : ''}${selectedRow.pa.upside}%` : ''}
                          {selectedRow.pa?.target != null ? ` · tgt $${selectedRow.pa.target}` : ''}
                          {selectedRow.pa?.stale ? ' · Street data stale' : ''}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: BB.text3, fontWeight: 800, letterSpacing: '.05em' }}>
                          CIO<HelpTip text={DESK_TIPS.cio} />
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 800, color: selectedRow.cioPrimary ? cioColor(selectedRow.cioPrimary) : BB.text3, marginTop: 2 }}>
                          {selectedRow.cioPrimary ? selectedRow.cioPrimary.replace(/_/g, ' ') : '—'}
                        </div>
                        <div style={{ fontSize: 10, color: BB.text3, marginTop: 2 }}>
                          {selectedRow.pa?.divergence === 'divergent' ? '≠ Street (divergence OK — different advisors)' : 'advisory · does not mirror Street'}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 10, border: `1px solid ${BB.border}`, borderRadius: 8, overflow: 'hidden' }}>
                      {([
                        ['Deterministic', selectedRow.ticket.deterministic],
                        ['Reconciled', selectedRow.ticket.reconciled],
                        [laneLabel('deepseek-flash'), selectedRow.ticket['deepseek-flash']],
                        ['Local', selectedRow.ticket.local],
                        [laneLabel('grok'), selectedRow.ticket.grok],
                        [laneLabel('chatgpt'), selectedRow.ticket.chatgpt],
                        [laneLabel('deepseek-v4'), selectedRow.ticket['deepseek-v4']],
                        ['Valuation', selectedRow.value.notApplicable ? 'N/A' : selectedRow.value.available ? `P/E ${selectedRow.value.pe ?? '—'}` : '—'],
                      ] as const).map(([label, value]) => (
                        <div key={label} style={{ padding: 8, borderBottom: `1px solid ${BB.border}`, borderRight: `1px solid ${BB.border}`, background: 'rgba(0,0,0,.12)' }}>
                          <div style={{ fontSize: 10, color: BB.text3 }}>{label}</div>
                          <b style={{ fontSize: 12, color: isFailure(String(value)) ? BB.red : BB.text1 }}>{value}</b>
                        </div>
                      ))}
                    </div>
                    {!selectedRow.value.notApplicable && (
                      <div style={{ marginTop: 8, fontSize: 11, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        {([['P/E', selectedRow.value.pe, VAL_TIP.pe], ['Fwd', selectedRow.value.forwardPe, VAL_TIP.fwd], ['P/B', selectedRow.value.pb, VAL_TIP.pb], ['P/S', selectedRow.value.ps, VAL_TIP.ps]] as const).map(([label, value, tip]) => (
                          <span key={label} title={tip}><span style={{ color: BB.text3 }}>{label}</span> <b style={{ color: BB.text0 }}>{value === null ? '—' : Number(value).toFixed(2)}</b></span>
                        ))}
                      </div>
                    )}
                    {selectedRow.level && (selectedRow.level.resistance !== null || selectedRow.level.support !== null) && (
                      <div style={{ marginTop: 6, fontSize: 11, display: 'flex', gap: 12 }}>
                        <span style={{ color: levelHeat(selectedRow.level.resistancePct) }}>R {selectedRow.level.resistance === null ? '—' : `$${selectedRow.level.resistance.toFixed(2)}`} {signedPct(selectedRow.level.resistancePct)}</span>
                        <span style={{ color: levelHeat(selectedRow.level.supportPct) }}>S {selectedRow.level.support === null ? '—' : `$${selectedRow.level.support.toFixed(2)}`} {signedPct(selectedRow.level.supportPct)}</span>
                      </div>
                    )}
                    {selectedDesk && (
                      <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${BB.border}` }}>
                        <WatchAdvisoryBody row={selectedRow} deskRow={selectedDesk} compact onFull={() => setFullOpen(true)} />
                      </div>
                    )}
                  </div>
                  {/* CTA FOOTER — dark dominant actions */}
                  <div
                    className="wlc-card-cta-bar"
                    style={{
                      display: 'flex', flexDirection: 'column', gap: 8,
                      padding: '12px 14px',
                      borderTop: `1px solid ${BB.border}`,
                      background: 'linear-gradient(180deg, rgba(0,0,0,.35), rgba(0,0,0,.55))',
                    }}
                  >
                    <button
                      type="button"
                      disabled={Boolean(reviewBusy)}
                      onClick={() => void runReview('deepseek-flash,local,grok,chatgpt', 'All critics')}
                      style={{ ...successBtn, width: '100%' }}
                    >
                      {reviewBusy === 'All critics' ? '…' : selectedRow.ticketPending ? 'Run critics' : 'Re-run critics'}
                    </button>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
<button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('deepseek-flash', laneLabel('deepseek-flash'))} style={terminalButton('secondary') as CSSProperties}>{reviewBusy === laneLabel('deepseek-flash') ? '…' : laneLabel('deepseek-flash')}</button>
<button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('local', `${laneLabel('local')} critic`)} style={terminalButton('secondary') as CSSProperties}>{reviewBusy === `${laneLabel('local')} critic` ? '…' : `Run ${laneLabel('local')}`}</button>
                      <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('grok', laneLabel('grok'))} style={terminalButton('secondary') as CSSProperties}>{reviewBusy === laneLabel('grok') ? '…' : laneLabel('grok')}</button>
                      <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('chatgpt', laneLabel('chatgpt'))} style={terminalButton('secondary') as CSSProperties}>{reviewBusy === laneLabel('chatgpt') ? '…' : laneLabel('chatgpt')}</button>
                      <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('deepseek-v4', laneLabel('deepseek-v4'))} style={terminalButton('secondary') as CSSProperties}>{reviewBusy === laneLabel('deepseek-v4') ? '…' : laneLabel('deepseek-v4')}</button>
                      <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void estimatePremium()} style={terminalButton('secondary') as CSSProperties}>Paid…</button>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <button type="button" onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(selectedRow.symbol)}` }} style={primaryBtn}>Classify Re-Entry</button>
                      <button type="button" onClick={() => { window.location.href = `/v3/rotation?symbol=${encodeURIComponent(selectedRow.symbol)}` }} style={terminalButton('ghost') as CSSProperties}>Rotation</button>
                      {selectedDesk?.provenance?.sector && (
                        <button type="button" onClick={() => { window.location.href = '/v3/watch?tab=sectors' }} style={btn(false)} title="Sector universe — operator gate for Watch directives">Open Sectors</button>
                      )}
                      {(selectedDesk?.provenance?.origin_system || '').toLowerCase().includes('defense') && (
                        <button type="button" onClick={() => { window.location.href = '/v3/defense' }} style={btn(false)} title="Defense rotation destinations stay advisory until Watch-click">Open Defense</button>
                      )}
                    </div>
                    {message && <div style={{ fontSize: 11, color: /failed|error/i.test(message) ? BB.red : BB.text2 }}>{message}</div>}
                    {premium && (
                      <div style={{ paddingTop: 4, borderTop: `1px solid ${BB.border}` }}>
                        {premium.available ? (
                          <>
                            <div style={{ fontSize: 11, color: BB.text2 }}>{premium.provider}/{premium.model} · est ${Number(premium.est_cost_usd).toFixed(4)}</div>
                            <label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 6 }}>
                              Type: <code>{premium.confirm_with}</code>
                              <input value={confirmation} onChange={e => setConfirmation(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginTop: 4, fontSize: 11, padding: '6px 8px', background: BB.bgShift, border: `1px solid ${BB.border}`, color: BB.text0 }} />
                            </label>
                            <button type="button" disabled={confirmation !== premium.confirm_with || Boolean(reviewBusy)} onClick={() => void runPremium()} style={{ ...successBtn, marginTop: 6, opacity: confirmation === premium.confirm_with ? 1 : 0.5, width: '100%' }}>Confirm paid</button>
                          </>
                        ) : <div style={{ fontSize: 11, color: BB.text2 }}>{premium.reason}</div>}
                      </div>
                    )}
                  </div>
                </>
              )}
            </aside>
          </div>
        </div>
      )}

      {fullOpen && selectedRow && (
        <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 1400, background: 'rgba(2,6,16,.92)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', borderBottom: `1px solid ${BB.border}`, background: BB.bgElevated }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 20, fontWeight: 900, color: deskStateTone(String(selectedDesk?.desk_state || selectedRow.now)) }}>
                {selectedRow.symbol} · FULL SETUP ADVISORY
              </div>
              <div style={{ fontSize: 11, color: BB.text3 }}>
                {selectedDesk?.desk_state || selectedRow.now} · {selectedDesk?.advisory?.action || selectedRow.next} · advisory only · Esc to close
              </div>
            </div>
            <button type="button" onClick={() => setFullOpen(false)} title="Close" aria-label="Close" style={{ ...btn(false), fontSize: 22, fontWeight: 900, width: 42, height: 38, padding: 0, lineHeight: 1 }}>×</button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
            <div style={{ border: `1px solid ${BB.border}`, borderRadius: 10, padding: 16, maxWidth: 980, margin: '0 auto', background: BB.bgPanel }}>
              <WatchAdvisoryBody row={selectedRow} deskRow={selectedDesk || { desk_state: selectedRow.now }} compact={false} />
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
