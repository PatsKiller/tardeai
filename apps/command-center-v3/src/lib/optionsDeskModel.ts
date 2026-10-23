/** Options desk model (2026-10-22 redesign, operator-approved Gate 3 mockup).
 *
 *  Pure functions that turn the served payloads into the desk layout: the truth sentence, the
 *  freshness chips, the 7-step lifecycle row, one merged row per idea, the detail panel (economics,
 *  scenarios, checklist), and the plan cards. No fetches, no writes.
 *
 *  Reading rules (audit 2026-10-22):
 *   - Read every field defensively. Absent → null, and the view shows "—" with NOT_SERVED.
 *   - Never say "market closed" unless the served market_session is present and not REGULAR.
 *   - Show each quote's own time.
 *   - A cash-secured put shows premium/collateral and simple annualized, never reward/risk.
 *   - Hide edge when the liquidity gate fails.
 *   - On an earnings-date conflict, show both dates.
 *  Every glossary key this module emits is checked by optionsDeskModel.test.ts.
 *
 *  Served accuracy fields (FIELD_CONTRACT.md, branch fix/options-desk-accuracy-20261022) are read
 *  first when present; older servers fall back to the derivations below:
 *    top: execution_state_text, market_session(_as_of), snapshot{…}, intent_conflicts, coverage.not_scanned
 *    card: quote_age_s, quote_session, quote_stale, underlying_price_time(_basis), chain_age_s,
 *          lifecycle_stage, review_failures, review_failure_reason, edge_status, edge_withheld_reason,
 *          premium_over_collateral_pct, simple_annualized_yield_pct, yield_basis, not_applicable_metrics,
 *          intent_conflict, group_key, earnings_dates
 *    intents: held, watch_only, shares_held_total, earnings_dates, conflicts, CSP rows' bid-based yields
 */
import {
  breakevenPerShare, cspCollateral, premiumOverCollateralPct, premiumTotal, protectivePutFloor, simpleAnnualizedPct,
} from './optionsGlossary.ts'

type Any = Record<string, any>
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const num = (v: unknown): number | null => (v == null || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : null))
const arr = <T = Any>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])
const unwrap = (v: Any | null | undefined): Any | null => (v && typeof v === 'object' ? (v.data && typeof v.data === 'object' && !Array.isArray(v.data) ? v.data : v) : null)

export const usd = (v: number | null | undefined, signed = false): string => {
  if (!fin(v)) return '—'
  const s = `$${Math.abs(Math.round(v)).toLocaleString('en-US')}`
  if (signed) return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s
  return v < 0 ? `−${s}` : s
}
export const usd2 = (v: number | null | undefined): string => (fin(v) ? `$${v.toFixed(2)}` : '—')
const pct = (v: number | null | undefined, d = 1): string => (fin(v) ? `${v.toFixed(d)}%` : '—')

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** "2026-11-20" → "Nov 20" (adds the year when it differs from `nowYear`). */
export function shortDate(iso: string | null | undefined, nowYear?: number): string {
  const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return '—'
  const y = Number(m[1])
  const base = `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`
  return nowYear != null && y !== nowYear ? `${base} ${y}` : base
}

/** ISO timestamp → "10:45 ET" (or "Oct 21 16:00 ET" when not today in New York). */
export function etTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const fmt = (x: Date, o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ...o }).format(x)
  const day = fmt(d, { year: 'numeric', month: '2-digit', day: '2-digit' })
  const today = fmt(now, { year: 'numeric', month: '2-digit', day: '2-digit' })
  const hm = fmt(d, { hour: '2-digit', minute: '2-digit', hour12: false })
  return day === today ? `${hm} ET` : `${fmt(d, { month: 'short', day: 'numeric' })} ${hm} ET`
}

export function ageText(seconds: number | null | undefined): string {
  if (!fin(seconds)) return '—'
  if (seconds < 90) return `${Math.round(seconds)} s old`
  const m = seconds / 60
  if (m < 120) return `${Math.round(m)} min old`
  const h = m / 60
  if (h < 48) return `${Math.round(h)} h old`
  return `${Math.round(h / 24)} d old`
}

export const STRATEGY_LABEL: Record<string, string> = {
  protective_put: 'Protective put', cash_secured_put: 'Cash-secured put', covered_call: 'Covered call',
  long_call: 'Long call', long_put: 'Long put', credit_spread: 'Credit spread', debit_spread: 'Debit spread',
  collar: 'Collar', leap_call: 'LEAP call', deep_itm_call: 'Deep ITM call', atm_call: 'ATM call', atm_put: 'ATM put',
}
export const strategyLabel = (s: string | null | undefined) => STRATEGY_LABEL[String(s || '')] || String(s || '—').replace(/_/g, ' ')
export const strategyGlossaryKey = (s: string | null | undefined): string => {
  const k = `strategy.${String(s || '')}`
  return ['strategy.covered_call', 'strategy.cash_secured_put', 'strategy.protective_put', 'strategy.long_call', 'strategy.long_put',
    'strategy.leap_call', 'strategy.credit_spread', 'strategy.debit_spread', 'strategy.collar'].includes(k) ? k : 'strategy.long_call'
}

// ── Truth header ─────────────────────────────────────────────────────────────────────────────────

/** One sentence on execution state. Served `execution_state_text` wins when present. */
export function truthSentence(proposals: Any | null, execStatus: Any | null, liveEligible: number): string {
  const p = unwrap(proposals)
  const served = p?.execution_state_text ?? p?.execution_state?.text
  if (typeof served === 'string' && served.trim()) return served.trim()
  const ex = unwrap(execStatus)
  if (!ex || typeof ex.armed_for_execution !== 'boolean') {
    return 'Execution status could not be read, so treat every idea as advisory. Nothing is placed without your decision and per-order 2FA.'
  }
  if (!ex.armed_for_execution) return 'Options execution is off: this desk is advisory and cannot send an order.'
  if (liveEligible <= 0) return 'The broker route is open, but no idea on this desk is eligible yet. Nothing is placed without your decision, a fresh preflight and per-order 2FA.'
  return `The broker route is open and ${liveEligible} idea${liveEligible === 1 ? ' is' : 's are'} eligible. You place each order yourself, after a fresh preflight and per-order 2FA.`
}

// ── Freshness chips ──────────────────────────────────────────────────────────────────────────────

export type Chip = { key: string; label: string; value: string; tone: Tone; detail: string; glossaryKey: string }

const SESSION_LABEL: Record<string, string> = {
  REGULAR: 'Open · regular session', PRE_MARKET: 'Pre-market', AFTER_HOURS: 'After hours', POST_MARKET: 'After hours',
  CLOSED: 'Closed', HOLIDAY: 'Closed · holiday', WEEKEND: 'Closed · weekend',
}

/** The page's own label for the served session. Never "closed" unless the server says a non-REGULAR session. */
export function sessionLabel(session: unknown): string | null {
  if (session == null || String(session).trim() === '') return null
  const s = String(session).toUpperCase()
  return SESSION_LABEL[s] || s.toLowerCase().replace(/_/g, ' ')
}

export const DEFAULT_CHAIN_CAP_S = 300
export const DEFAULT_QUOTE_CAP_S = 120
/** The page's own threshold for calling the open-position monitor stale (a day). */
export const OPEN_MONITOR_STALE_S = 24 * 3600

export function freshnessChips(proposals: Any | null, ideasRaw: Any[], now: Date = new Date(), openPositions: Any | null = null): Chip[] {
  const p = unwrap(proposals) || {}
  const chips: Chip[] = []
  // 1 · Market session — served only.
  const sess = p.market_session
  const sl = sessionLabel(sess)
  const sessAt = p.market_session_as_of || p.generated_at
  const snap = p.snapshot && typeof p.snapshot === 'object' ? p.snapshot : null
  const snapLine = snap ? ` Ideas snapshot written ${etTime(snap.generated_at, now)}${fin(num(snap.age_s)) ? ` (${ageText(num(snap.age_s))})` : ''}${snap.session_at_generation ? ` during ${String(snap.session_at_generation).toLowerCase().replace(/_/g, ' ')}` : ''}.`
    + (snap.refresh_paused ? ` Refresh PAUSED since ${snap.refresh_paused.since ?? '—'}${snap.refresh_paused.note ? ` (${snap.refresh_paused.note})` : ''}.`
      : snap.next_scheduled_refresh ? ` Next scheduled refresh ${etTime(snap.next_scheduled_refresh, now)}${snap.refresh_schedule_source === 'lane_registry' ? ' (registered schedule; crontab unreadable)' : ''}.` : ' No active refresh schedule found.') : ''
  chips.push({
    key: 'market', label: 'Market', glossaryKey: 'fresh.market',
    value: sl ? `${sl}${sessAt ? ` · ${etTime(sessAt, now)}` : ''}` : '—',
    tone: !sl ? 'neutral' : String(sess).toUpperCase() === 'REGULAR' ? 'success' : 'warning',
    detail: sl ? `Server-reported session: ${String(sess)}, computed ${etTime(sessAt, now)}.${snapLine}` : 'not provided by this server version',
  })
  // 2 · Stock quotes — oldest per-idea stock price time; each idea shows its own in the panel.
  const stockTimes = ideasRaw.map(i => ({ sym: i.symbol, at: i.underlying_price_time ?? i.price_source?.quote_time ?? i.price_source?.as_of ?? null,
    fetchOnly: i.underlying_price_time_basis === 'fetch_time' })).filter(x => x.at)
  const servedStock = p.stock_quotes_as_of ?? p.freshness?.stock_quotes_as_of
  if (servedStock || stockTimes.length) {
    const oldest = servedStock || stockTimes.map(x => x.at).sort()[0]
    chips.push({ key: 'stock', label: 'Stock quotes', glossaryKey: 'fresh.stock_quotes', value: `oldest ${etTime(oldest, now)}`,
      tone: 'neutral', detail: stockTimes.length ? stockTimes.map(x => `${x.sym} ${etTime(x.at, now)}${x.fetchOnly ? ' (fetch time; provider time not recorded)' : ''}`).join(' · ') : `As of ${etTime(oldest, now)}` })
  } else {
    chips.push({ key: 'stock', label: 'Stock quotes', glossaryKey: 'fresh.stock_quotes', value: '—', tone: 'neutral', detail: 'not provided by this server version' })
  }
  // 3 · Option chain age — the oldest chain behind any idea, against the cap.
  const ages = ideasRaw.map(i => num(i.chain_age_s ?? i.chain_age_seconds)).filter(fin)
  const cap = num(p.enterprise?.config?.hard_chain_max_age_seconds) ?? DEFAULT_CHAIN_CAP_S
  if (ages.length) {
    const worst = Math.max(...ages)
    chips.push({ key: 'chain', label: 'Option chains', glossaryKey: 'fresh.option_chain', value: ageText(worst),
      tone: worst > cap ? 'warning' : 'success',
      detail: `Oldest chain ${Math.round(worst).toLocaleString('en-US')} s; cap ${cap} s.${worst > cap ? ' Re-quote before deciding.' : ''}` })
  } else {
    chips.push({ key: 'chain', label: 'Option chains', glossaryKey: 'fresh.option_chain', value: '—', tone: 'neutral', detail: 'not provided by this server version' })
  }
  // 4 · Holdings — a served freshness field wins; else the coverage holdings receipt.
  const hf = p.holdings_freshness
  const receipt = p.coverage?.source_receipts?.holdings
  if (hf && typeof hf === 'object') {
    const verified = hf.verified ?? hf.ok
    chips.push({ key: 'holdings', label: 'Holdings', glossaryKey: 'fresh.holdings',
      value: verified === false ? 'unverified' : `synced ${etTime(hf.as_of ?? hf.observed_at, now)}`,
      tone: verified === false ? 'danger' : 'success', detail: String(hf.reason || hf.detail || hf.note || `As of ${hf.as_of ?? hf.observed_at ?? '—'}`) })
  } else if (receipt && typeof receipt === 'object') {
    const ok = String(receipt.status || '').toUpperCase() === 'COMPLETE'
    const at = receipt.observed_at || receipt.as_of
    const dateOnly = typeof at === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(at)
    chips.push({ key: 'holdings', label: 'Holdings', glossaryKey: 'fresh.holdings',
      value: `${ok ? 'synced' : String(receipt.status || 'unknown').toLowerCase()} ${dateOnly ? at.slice(5) : etTime(at, now)}`,
      tone: ok ? 'success' : 'warning',
      detail: `Holdings receipt ${receipt.status || 'unknown'}${at ? `, observed ${at}` : ''}${dateOnly ? ' (date only: intraday fills such as stops may not be reflected)' : ''}.${receipt.reason ? ` ${receipt.reason}` : ''}` })
  } else {
    chips.push({ key: 'holdings', label: 'Holdings', glossaryKey: 'fresh.holdings', value: '—', tone: 'neutral', detail: 'not provided by this server version' })
  }
  // 5 · Scan coverage — evaluated of inventory.
  const inv = num(p.coverage?.inventory_count ?? p.universe_census?.inventory_count)
  const evald = num(p.coverage?.status_counts?.EVALUATED)
  if (inv != null && evald != null) {
    const partial = /PARTIAL/i.test(String(p.scan_status || '')) || evald < inv
    chips.push({ key: 'scan', label: 'Scan coverage', glossaryKey: 'fresh.scan_coverage',
      value: `${evald.toLocaleString('en-US')} of ${inv.toLocaleString('en-US')} evaluated`, tone: partial ? 'warning' : 'success',
      detail: `Scan status ${p.scan_status || 'unknown'}.${p.scan_capacity?.status ? ` Expanded scan ${String(p.scan_capacity.status).toLowerCase()}.` : ''}`
        + (p.coverage?.not_scanned?.count != null ? ` ${Number(p.coverage.not_scanned.count).toLocaleString('en-US')} ${p.coverage.not_scanned.reason || 'not scanned'}.` : '')
        + (p.coverage?.pending_evaluation_count != null ? ` ${p.coverage.pending_evaluation_count} pending evaluation.` : '') })
  } else {
    chips.push({ key: 'scan', label: 'Scan coverage', glossaryKey: 'fresh.scan_coverage', value: '—', tone: 'neutral', detail: 'not provided by this server version' })
  }
  // 6 · Open positions — when the monitor last ran over the broker legs.
  const op = unwrap(openPositions)
  if (op?.monitored_at) {
    const age = Math.max(0, (now.getTime() - new Date(op.monitored_at).getTime()) / 1000)
    const stale = fin(age) && age > OPEN_MONITOR_STALE_S
    chips.push({ key: 'open', label: 'Open positions', glossaryKey: 'fresh.open_positions', value: `monitored ${etTime(op.monitored_at, now)}`,
      tone: stale ? 'warning' : 'success',
      detail: `${num(op.position_count) ?? arr(op.positions).length} open leg(s); monitor run ${ageText(age)}${stale ? ' (older than a day: marks and P/L may be stale)' : ''}. Status ${op.status || 'not served'}.` })
  } else {
    chips.push({ key: 'open', label: 'Open positions', glossaryKey: 'fresh.open_positions', value: '—', tone: 'neutral', detail: 'not provided by this server version' })
  }
  return chips
}

// ── Blockers ─────────────────────────────────────────────────────────────────────────────────────

export type Blocker = { key: string; text: string; raw: string }

const CODE_KEY: Record<string, string> = {
  awaiting_cio_decision: 'blocker.awaiting_cio_decision', quote_stale: 'blocker.quote_stale', option_chain_stale: 'blocker.option_chain_stale',
  quote_age_unknown: 'blocker.quote_age_unknown', chain_age_unknown: 'blocker.chain_age_unknown',
  market_session_unknown: 'blocker.market_session_unknown', market_closed: 'blocker.market_closed', liquidity_unknown: 'blocker.liquidity_unknown',
  thesis_required: 'blocker.thesis_required', thesis_unavailable: 'blocker.thesis_required', earnings_blackout: 'blocker.earnings_blackout',
  portfolio_risk: 'blocker.portfolio_risk', max_net_delta_pct: 'blocker.portfolio_risk', max_symbol_notional_pct: 'blocker.portfolio_risk',
  max_per_strategy_notional: 'blocker.portfolio_risk', max_contracts_per_order: 'blocker.portfolio_risk',
  buying_power_unknown: 'blocker.buying_power', min_buying_power: 'blocker.buying_power', no_resolved_occ: 'blocker.no_resolved_occ',
  holdings_unverified: 'blocker.holdings_unverified',
}

/** Every known blocker glossary key (the test proves each one resolves). */
export const BLOCKER_KEYS = [...new Set([...Object.values(CODE_KEY), 'blocker.wide_spread', 'blocker.low_open_interest',
  'blocker.low_volume', 'blocker.thesis_missing', 'blocker.cio_review_failed', 'blocker.not_staged', 'blocker.other'])]

/** Classify one served block (object with code, or a bare liquidity string such as "OI 9 < 50"). */
export function classifyBlock(b: unknown): Blocker {
  if (typeof b === 'string') {
    if (/^\s*spread\b/i.test(b)) return { key: 'blocker.wide_spread', text: `Quote too wide (${b.replace(/^\s*spread\s*/i, '')})`, raw: b }
    if (/^\s*OI\b/i.test(b)) return { key: 'blocker.low_open_interest', text: `Low open interest (${b})`, raw: b }
    if (/^\s*volume\b/i.test(b)) return { key: 'blocker.low_volume', text: `Low volume (${b})`, raw: b }
    return { key: 'blocker.other', text: b, raw: b }
  }
  const o = (b || {}) as Any
  const code = String(o.code || '')
  if (code.startsWith('thesis_missing')) {
    return { key: 'blocker.thesis_missing', text: `Thesis: ${code.replace('thesis_missing_', '').replace(/_/g, ' ')} missing`, raw: o.reason || code }
  }
  const key = CODE_KEY[code] || 'blocker.other'
  const age = num(o.snapshot?.quote_age_seconds ?? o.snapshot?.chain_age_seconds)
  const text = code === 'quote_stale' ? `Contract quote stale (${ageText(age)})`
    : code === 'option_chain_stale' ? `Chain stale (${ageText(age)})`
      : code === 'awaiting_cio_decision' ? 'No CIO decision yet'
        : key === 'blocker.other' ? String(o.reason || code || 'unlabelled block') : (o.reason ? String(o.reason) : code.replace(/_/g, ' '))
  return { key, text, raw: String(o.reason || code) }
}

export function cioFailures(p: Any): { count: number; reason: string | null; capped: boolean } {
  const capped = String(p?.lifecycle_stage || '') === 'REVIEW_FAILURE_CAP'
  if (num(p?.review_failures) != null) return { count: num(p.review_failures) as number, reason: p.review_failure_reason ?? null, capped }
  const tl = arr(p?.lifecycle?.timeline).filter(t => t?.stage === 'CIO_REVIEW_FAILED')
  return { count: tl.length, reason: tl.length ? String(tl[tl.length - 1]?.reason || tl[tl.length - 1]?.status || '') || null : null, capped }
}

export function blockersFor(p: Any): Blocker[] {
  const out: Blocker[] = []
  const seen = new Set<string>()
  const add = (b: Blocker) => { const k = `${b.key}|${b.text}`; if (!seen.has(k)) { seen.add(k); out.push(b) } }
  for (const b of arr(p?.enterprise?.blocks)) add(classifyBlock(b))
  for (const b of arr(p?.thesis_blocks)) add(classifyBlock(b))
  for (const f of arr<string>(p?.options_thesis?.missing_required)) add({ key: 'blocker.thesis_missing', text: `Thesis: ${String(f).replace(/_/g, ' ')} missing`, raw: String(f) })
  const cio = cioFailures(p)
  if (cio.count) add({ key: 'blocker.cio_review_failed', text: `CIO review ${cio.capped ? 'stopped after' : 'failed'} ${cio.count}×${cio.reason ? ` (${cio.reason})` : ''}${cio.capped ? ' · operator reopen needed' : ''}`, raw: cio.reason || 'CIO_REVIEW_FAILED' })
  if (p?.quote_stale === true && !out.some(b => b.key === 'blocker.quote_stale' || b.key === 'blocker.quote_age_unknown')) {
    add({ key: 'blocker.quote_stale', text: `Contract quote stale (${ageText(num(p.quote_age_s))})`, raw: 'quote_stale' })
  }
  if (p?.holdings_verified === false) add({ key: 'blocker.holdings_unverified', text: String(p.holdings_note || 'Holdings unverified'), raw: 'holdings_verified=false' })
  // Thesis-missing duplicates (code and field) collapse to one line.
  return out.filter((b, i) => b.key !== 'blocker.thesis_missing' || out.findIndex(x => x.key === 'blocker.thesis_missing') === i)
}

// ── Lifecycle ────────────────────────────────────────────────────────────────────────────────────

export type LaneKey = 'scan' | 'research' | 'data' | 'plan' | 'you' | 'place' | 'open'
export const LANES: Array<{ key: LaneKey; step: number; name: string; owner: string; glossaryKey: string }> = [
  { key: 'scan', step: 1, name: 'Found', owner: 'scanner', glossaryKey: 'lifecycle.found' },
  { key: 'research', step: 2, name: 'Needs research', owner: 'Research / CIO', glossaryKey: 'lifecycle.research' },
  { key: 'data', step: 3, name: 'Needs data', owner: 'quote validation', glossaryKey: 'lifecycle.data' },
  { key: 'plan', step: 4, name: 'Not staged', owner: 'you: pick account', glossaryKey: 'lifecycle.plan' },
  { key: 'you', step: 5, name: 'Your decision', owner: 'you', glossaryKey: 'lifecycle.you' },
  { key: 'place', step: 6, name: 'Ready to place', owner: 'you + 2FA', glossaryKey: 'lifecycle.place' },
  { key: 'open', step: 7, name: 'Open', owner: 'monitor', glossaryKey: 'lifecycle.open' },
]

/** Lane for one proposal, from the review_workflow state. The served `lifecycle_stage` is the CIO
 *  thesis stage (FIELD_CONTRACT §2): ARCHIVED_ABANDONED leaves the lanes; REVIEW_FAILURE_CAP needs the
 *  operator (reopen), so it is a decision for you. Null = not in flight. */
export function laneFor(p: Any): LaneKey | null {
  const served = String(p?.lifecycle_stage ?? '').toUpperCase()
  if (served === 'ARCHIVED_ABANDONED') return null
  if (served === 'REVIEW_FAILURE_CAP') return 'you'
  const st = String(p?.review_workflow?.state ?? p?.options_decision_packet?.review_workflow?.state ?? '')
  switch (st) {
    case 'NEEDS_RESEARCH': return 'research'
    case 'NEEDS_DATA': case 'APPROVED_AWAITING_QUOTES': return 'data'
    case 'READY_FOR_REVIEW': case 'BLOCKED': return 'you'
    case 'READY_FOR_PREFLIGHT': return 'place'
    case 'REJECTED_OR_EXPIRED': return null
    default: return 'data'
  }
}

const LANE_ORDER: LaneKey[] = ['scan', 'research', 'data', 'plan', 'you', 'place', 'open']

// ── Ideas (one row per idea, accounts merged) ────────────────────────────────────────────────────

export type NextStep =
  | { kind: 'review'; label: string; proposalId: string }
  | { kind: 'validate'; label: string; proposalId: string }
  | { kind: 'chain'; label: string; proposalId: string }
  | { kind: 'stage'; label: string; source: { directive_id?: number | string; play?: string; contract_guid?: string } }
  | { kind: 'view'; label: string; view: 'Lifecycle' | 'Open Options' }
  | { kind: 'none'; label: string; reason: string }

export type Scenario = { move: string; stockOnly: string; withThis: string; saved: string }
export type Check = { mark: '✓' | '✗' | '○'; text: string; glossaryKey: string }
export type Econ = { label: string; value: string; glossaryKey: string; note?: string }

export type Idea = {
  id: string
  groupKey: string
  lane: LaneKey
  symbol: string
  strategy: string
  strategyLabel: string
  contract: string
  accounts: string
  does: string
  cost: string
  costValue: number | null
  stuck: string
  stuckKey: string
  next: NextStep
  plain: string
  econ: Econ[]
  scenarios: Scenario[]
  scenarioNote: string
  checks: Check[]
  model: string
  quoteTimes: string
  memberIds: string[]
  raw: Any[]
  tier?: string | null
  sleeve?: string | null
  flags: string[]
  /** Freshness of the Cost cell's number: the quote (or monitor run) it came from, and its age. */
  costAge: string
  /** Open positions only: the monitor's urgency (protect = defend phase, act = harvest phase). */
  urgency?: OpenUrgency
  /** Open positions only: the monitor's rule line and run time. */
  monitor?: { criterion: string; note: string; monitoredAt: string | null; alerts: string[] }
}

/** Group key: a served `group_key` wins; else symbol·strategy·type·strike(s)·expiry. */
export function groupKey(p: Any): string {
  if (p?.group_key) return String(p.group_key)
  return [String(p?.symbol || '').toUpperCase(), p?.strategy, p?.option_type, p?.strike, p?.short_strike, p?.long_strike, p?.expiration]
    .map(x => (x == null ? '' : String(x))).join('|')
}

const acctName = (a: unknown) => String(a || '').replace(/^schwab_/, '').replace(/_/g, ' ')

function contractText(p: Any, contracts: number, nowYear?: number): string {
  const typ = p.option_type === 'put' ? 'P' : p.option_type === 'call' ? 'C' : ''
  const strikes = p.strategy === 'credit_spread' && fin(num(p.short_strike)) && fin(num(p.long_strike))
    ? `$${num(p.short_strike)}/$${num(p.long_strike)}${typ}` : `$${num(p.strike) ?? '—'}${typ}`
  return `${shortDate(p.expiration, nowYear)} ${strikes} × ${contracts}`
}

function doesText(p: Any, contracts: number, sharesHeld: number | null, cost: number | null): string {
  const k = num(p.strike)
  const sh = contracts * 100
  const dte = num(p.dte)
  switch (p.strategy) {
    case 'protective_put':
      return `Insures ${sharesHeld != null && sharesHeld > sh ? `${sh.toLocaleString('en-US')} of ${Math.floor(sharesHeld).toLocaleString('en-US')}` : sh.toLocaleString('en-US')} shares below $${k}${dte != null ? ` for ${dte} days` : ''}`
    case 'cash_secured_put':
      return `Paid ${usd(cost)} to agree to buy ${sh.toLocaleString('en-US')} sh at $${k}`
    case 'covered_call':
      return `Paid ${usd(cost)} to agree to sell ${sh.toLocaleString('en-US')} sh at $${k}`
    case 'long_call':
      return `Pays ${usd(cost)} for the right to buy ${sh.toLocaleString('en-US')} sh at $${k}`
    case 'long_put':
      return `Pays ${usd(cost)} for the right to sell ${sh.toLocaleString('en-US')} sh at $${k}`
    case 'credit_spread':
      return `Collects ${usd(cost)}; the most it can lose is capped by the spread width`
    default:
      return String(p.recommended_action || strategyLabel(p.strategy))
  }
}

const isCredit = (strategy: string) => ['cash_secured_put', 'covered_call', 'credit_spread'].includes(strategy)

function nextFor(lane: LaneKey, lead: Any, blockers: Blocker[]): NextStep {
  const id = String(lead.id)
  if (lane === 'research') return { kind: 'review', label: 'Open thesis', proposalId: id }
  if (lane === 'data') {
    if (blockers.some(b => b.key === 'blocker.low_open_interest' || b.key === 'blocker.low_volume')) return { kind: 'chain', label: 'Pick another strike', proposalId: id }
    const na = String(lead.review_workflow?.next_action || '')
    if (/after the open/i.test(na)) return { kind: 'none', label: '—', reason: na }
    return { kind: 'validate', label: 'Re-quote now', proposalId: id }
  }
  if (lane === 'you') return { kind: 'review', label: 'Decide', proposalId: id }
  if (lane === 'place') return { kind: 'review', label: 'Review to place', proposalId: id }
  return { kind: 'none', label: '—', reason: 'No step on this page for this stage.' }
}

/** The quote behind an idea's numbers and its age now. The contract's own quote_time wins (age
 *  computed against now); else the served request-time quote_age_s; else the generation-time
 *  quote_age_seconds (labelled "at generation"); else the chain fetch time. Never invented. */
export function quoteFreshness(p: Any, now: Date = new Date()): { text: string; seconds: number | null } {
  const qt = p?.quote_time
  if (qt) {
    const t = new Date(qt).getTime()
    if (!Number.isNaN(t)) {
      const s = Math.max(0, (now.getTime() - t) / 1000)
      return { text: `quote ${etTime(qt, now)} · ${ageText(s)}`, seconds: s }
    }
  }
  const served = num(p?.quote_age_s)
  if (served != null) return { text: `quote ${ageText(served)}`, seconds: served }
  const gen = num(p?.quote_age_seconds)
  if (gen != null) return { text: `quote ${ageText(gen)} at generation`, seconds: gen }
  if (p?.chain_fetched_at) return { text: `chain ${etTime(p.chain_fetched_at, now)} (contract quote time not served)`, seconds: null }
  return { text: 'quote time not provided by this server version', seconds: null }
}

/** Liquidity gate result for edge display: false hides the edge. Unknown keeps it with its basis. */
const liquidityPass = (p: Any): boolean | null => (typeof p?.enterprise?.liquidity?.pass === 'boolean' ? p.enterprise.liquidity.pass : null)

function econFor(members: Any[], contracts: number, shares: number | null, cost: number | null, now: Date): Econ[] {
  const p = members[0]
  const k = num(p.strike), prem = num(p.premium), dte = num(p.dte), spot = num(p.underlying_price)
  const q = quoteFreshness(p, now)
  const qNote = (basis?: string) => [basis, q.text].filter(Boolean).join(' · ')
  const qs = p.quote_session ?? p.market_session
  const spotStale = qs && String(qs).toUpperCase() !== 'REGULAR'
  const spotAt = p.underlying_price_time ?? p.price_source?.quote_time ?? p.price_source?.as_of
  const e: Econ[] = [{ label: 'Spot', value: `${usd2(spot)}${spotStale ? ' ⚠' : ''}`, glossaryKey: 'term.spot', note: spotAt ? `read ${etTime(spotAt, now)}` : 'time not provided by this server version' },
    { label: 'Strike', value: k != null ? `$${k}` : '—', glossaryKey: 'term.strike' }]
  if (p.strategy === 'protective_put') {
    const floorServed = members.map(m => num(m.floor_value ?? m.economics?.floor_value_after_premium))
    const floor = floorServed.every(fin) ? floorServed.reduce((a, b) => a + (b as number), 0) : null
    e.push({ label: 'Premium', value: usd2(prem), glossaryKey: 'term.premium', note: qNote(p.premium_basis ? `${p.premium_basis} price` : undefined) },
      { label: 'Total cost', value: usd(cost), glossaryKey: 'term.total_cost', note: qNote() },
      { label: 'Floor', value: usd(floor), glossaryKey: 'term.floor', note: floor == null ? undefined : `served per account, summed · ${q.text}` },
      { label: 'Days', value: dte != null ? String(dte) : '—', glossaryKey: 'term.dte', note: dte != null ? `to ${p.expiration ?? 'expiry'}` : undefined })
  } else if (p.strategy === 'cash_secured_put') {
    const coll = k != null ? cspCollateral(k, contracts) : null
    const poc = num(p.premium_over_collateral_pct) ?? (prem != null && k != null ? premiumOverCollateralPct(prem, k) : null)
    const ann = num(p.simple_annualized_yield_pct) ?? (poc != null && dte != null ? simpleAnnualizedPct(poc / 100, dte) : null)
    e.push({ label: 'Credit', value: usd2(prem), glossaryKey: 'term.premium', note: qNote(p.premium_basis ? `${p.premium_basis} price` : undefined) },
      { label: 'Cash held', value: usd(num(p.economics?.cash_committed) ?? coll), glossaryKey: 'term.collateral', note: 'strike × 100 × contracts' },
      { label: 'Cost if assigned', value: usd(num(p.economics?.net_cost_if_assigned_total)), glossaryKey: 'term.breakeven', note: qNote('total, after the premium') },
      { label: 'Breakeven', value: usd2(num(p.economics?.net_cost_if_assigned_per_share) ?? (k != null && prem != null ? breakevenPerShare('cash_secured_put', k, prem) : null)), glossaryKey: 'term.breakeven', note: qNote() },
      { label: 'Premium / collateral', value: pct(poc, 2), glossaryKey: 'term.premium_over_collateral', note: qNote() },
      { label: 'Simple annualized', value: pct(ann, 1), glossaryKey: 'term.simple_annualized', note: qNote('not repeatable') },
      { label: 'Days', value: dte != null ? String(dte) : '—', glossaryKey: 'term.dte', note: dte != null ? `to ${p.expiration ?? 'expiry'}` : undefined })
  } else {
    const be = num(p.economics?.breakeven ?? p.breakeven)
    e.push({ label: isCredit(p.strategy) ? 'Credit' : 'Premium', value: usd2(prem), glossaryKey: 'term.premium', note: qNote(p.premium_basis ? `${p.premium_basis} price` : undefined) },
      { label: isCredit(p.strategy) ? 'Total credit' : 'Total cost', value: usd(cost), glossaryKey: 'term.total_cost', note: qNote() },
      { label: 'Breakeven', value: usd2(be ?? (k != null && prem != null ? breakevenPerShare(p.strategy, k, prem, num(p.short_strike)) : null)), glossaryKey: 'term.breakeven', note: qNote() },
      { label: 'Days', value: dte != null ? String(dte) : '—', glossaryKey: 'term.dte', note: dte != null ? `to ${p.expiration ?? 'expiry'}` : undefined })
  }
  const edge = num(p.edge_score)
  const withheld = liquidityPass(p) === false || p.edge_status === 'WITHHELD_LIQUIDITY'
  const conv = p.edge_inputs?.conviction_basis
  e.push({ label: 'Edge', value: withheld || edge == null ? '—' : edge.toFixed(1), glossaryKey: 'term.edge',
    note: withheld ? `hidden: ${p.edge_withheld_reason || 'liquidity gate failed'}` : edge == null ? 'not provided by this server version'
      : `heuristic, not a return${num(p.edge_liquidity_penalty) ? ` · −${num(p.edge_liquidity_penalty)} liquidity penalty` : ''}${conv ? ` · ${conv}` : ''}${p.chain_fetched_at ? ` · inputs from the chain read ${etTime(p.chain_fetched_at, now)}` : ''}` })
  void shares
  return e
}

function scenariosFor(members: Any[], strategy: string): { rows: Scenario[]; note: string } {
  const ids = new Set(members.map(m => String(m.id)))
  const ce = members[0]?.combined_exposure
  const ceIds = arr(ce?.ideas).map(i => String(i?.id))
  if (strategy === 'protective_put') {
    if (ce && ceIds.length === ids.size && ceIds.every(i => ids.has(i))) {
      const rows = arr(ce.scenarios).filter(s => num(s?.move_pct) != null && (num(s.move_pct) as number) < 0)
        .sort((a, b) => (num(b.move_pct) as number) - (num(a.move_pct) as number))
        .map(s => ({ move: `${num(s.move_pct)}%`, stockOnly: usd(num(s.shares_pl), true), withThis: usd(num(s.whole_position_pl), true), saved: usd(num(s.options_only_pl), true) }))
      if (rows.length) return { rows, note: String(ce.scenario_basis || 'Shares marked from today\'s spot; no basis or fees.') }
    }
    // Sum each account's own protection scenarios when every member has them.
    const per = members.map(m => arr(m.economics?.protection_scenarios))
    if (per.every(x => x.length)) {
      const moves = [...new Set(per[0].map(s => num(s.move_pct)).filter(fin))].sort((a, b) => b - a)
      const rows = moves.map(mv => {
        const pick = per.map(list => list.find(s => num(s.move_pct) === mv))
        if (pick.some(x => !x)) return null
        const sum = (f: string) => pick.reduce((a, s) => a + (num(s![f]) ?? NaN), 0)
        return { move: `${mv}%`, stockOnly: usd(sum('stock_pl'), true), withThis: usd(sum('hedged_pl'), true), saved: usd(sum('loss_reduction'), true) }
      }).filter(Boolean) as Scenario[]
      if (rows.length) return { rows, note: 'Insured shares only, marked from today\'s spot; no cost basis, fees or slippage.' }
    }
    return { rows: [], note: 'Scenario rows not provided by this server version.' }
  }
  return { rows: [], note: 'No falling-stock scenario is served for this strategy.' }
}

function checksFor(p: Any, blockers: Blocker[], lane: LaneKey): Check[] {
  const has = (k: string) => blockers.some(b => b.key === k)
  const out: Check[] = []
  const missing = arr<string>(p.options_thesis?.missing_required)
  out.push(missing.length || has('blocker.thesis_missing') || has('blocker.thesis_required')
    ? { mark: '✗', text: `Thesis: ${missing.length ? missing.join(', ').replace(/_/g, ' ') : 'required fields'} missing → research`, glossaryKey: 'concept.thesis' }
    : p.thesis_state || p.options_thesis ? { mark: '✓', text: 'Thesis complete', glossaryKey: 'concept.thesis' }
      : { mark: '○', text: 'Thesis status not provided by this server version', glossaryKey: 'concept.thesis' })
  const liq = p.enterprise?.liquidity
  if (liq && typeof liq.pass === 'boolean') {
    out.push(liq.pass
      ? { mark: '✓', text: `Contract liquid (OI ${num(liq.oi) ?? '—'}, spread ${pct(num(liq.bid_ask_spread_pct))})`, glossaryKey: 'term.spread_pct' }
      : { mark: '✗', text: `Illiquid: ${arr<string>(liq.issues).join('; ') || 'liquidity gate failed'} → re-quote or pick another strike`, glossaryKey: 'term.spread_pct' })
  } else out.push({ mark: '○', text: 'Liquidity check not provided by this server version', glossaryKey: 'term.spread_pct' })
  const stale = blockers.find(b => b.key === 'blocker.option_chain_stale' || b.key === 'blocker.quote_stale' || b.key === 'blocker.quote_age_unknown' || b.key === 'blocker.chain_age_unknown')
  out.push(stale ? { mark: '✗', text: `${stale.text} → re-quote`, glossaryKey: stale.key }
    : num(p.chain_age_s ?? p.chain_age_seconds) != null ? { mark: '✓', text: `Quotes fresh (chain ${ageText(num(p.chain_age_s ?? p.chain_age_seconds))})`, glossaryKey: 'fresh.option_chain' }
      : { mark: '○', text: 'Quote age not provided by this server version', glossaryKey: 'fresh.option_chain' })
  if (['protective_put', 'covered_call'].includes(p.strategy)) {
    out.push(p.holdings_verified === false ? { mark: '✗', text: String(p.holdings_note || 'Holdings unverified → wait for the next sync'), glossaryKey: 'blocker.holdings_unverified' }
      : p.holdings_verified === true ? { mark: '✓', text: 'Holdings verified', glossaryKey: 'fresh.holdings' }
        : { mark: '○', text: 'Holdings check not provided by this server version', glossaryKey: 'fresh.holdings' })
  }
  const earn = p.enterprise?.earnings
  if (earn && typeof earn.in_blackout === 'boolean') {
    out.push(earn.in_blackout ? { mark: '✗', text: `Inside earnings blackout${earn.event_date ? ` (${earn.event_date})` : ''}`, glossaryKey: 'blocker.earnings_blackout' }
      : { mark: '✓', text: `Outside earnings blackout${earn.event_date ? ` (earnings ${earn.event_date})` : ''}`, glossaryKey: 'blocker.earnings_blackout' })
  }
  const cio = cioFailures(p)
  const approved = p.options_decision_packet?.cio_approved === true || lane === 'place'
  out.push(approved ? { mark: '✓', text: 'CIO decision recorded', glossaryKey: 'concept.cio_decision' }
    : cio.count ? { mark: '✗', text: cio.capped ? `CIO review stopped after ${cio.count} failures${cio.reason ? ` (${cio.reason})` : ''} → operator reopen needed`
      : `CIO review failed ${cio.count}×${cio.reason ? ` (${cio.reason})` : ''} → re-run review`, glossaryKey: 'blocker.cio_review_failed' }
      : { mark: '○', text: 'CIO decision', glossaryKey: 'concept.cio_decision' })
  out.push({ mark: '○', text: 'Your decision', glossaryKey: 'lifecycle.you' })
  out.push({ mark: '○', text: 'Fresh preflight + per-order 2FA (you, at the broker step)', glossaryKey: 'lifecycle.place' })
  return out
}

function modelLine(p: Any): string {
  const v = p.aegis_verdict || p.ensemble_verdict
  const st = p.aegis_status || p.ensemble_status
  const score = num(p.aegis_score ?? p.ensemble_score)
  const votes = p.ensemble_votes ?? p.aegis_votes
  if (v || st || score != null) {
    return [v ? String(v).toLowerCase() : null, score != null ? `${score.toFixed(1)} of 10` : null,
      votes && typeof votes === 'object' ? `${votes.approve ?? 0} of ${votes.total ?? '—'} approve` : null, st && !v ? String(st).toLowerCase() : null]
      .filter(Boolean).join(', ')
  }
  if (p.options_decision_packet?.model?.ensemble_present === false) return 'not reviewed yet'
  return 'not provided by this server version'
}

function quoteTimesFor(p: Any, now: Date): string {
  const stockAt = p.underlying_price_time ?? p.price_source?.quote_time ?? p.price_source?.as_of
  return [`stock ${etTime(stockAt, now)}${p.underlying_price_time_basis === 'fetch_time' ? ' (fetch time)' : ''}`,
    `contract quote ${etTime(p.quote_time, now)}${p.quote_session ? ` (${String(p.quote_session).toLowerCase().replace(/_/g, ' ')})` : ''}`,
    `chain ${etTime(p.chain_fetched_at, now)}`].join(' · ')
}

/** One row per idea. Per-account duplicates merge on the group key; contracts and cost are summed. */
export function buildIdeas(proposals: Any[], now: Date = new Date()): Idea[] {
  const groups = new Map<string, Any[]>()
  for (const p of proposals) {
    if (!p || p.educational_paper_model || p.paper_only || String(p.broker || '').toLowerCase() === 'alpaca') continue
    if (laneFor(p) == null) continue
    const k = groupKey(p)
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k)!.push(p)
  }
  const nowYear = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric' }).format(now))
  const ideas: Idea[] = []
  for (const [k, members] of groups) {
    // The least advanced member decides the lane: a merged row is only as far along as its slowest account.
    const lanes = members.map(laneFor).filter(Boolean) as LaneKey[]
    const lane = lanes.sort((a, b) => LANE_ORDER.indexOf(a) - LANE_ORDER.indexOf(b))[0] || 'data'
    const lead = members.find(m => laneFor(m) === lane) || members[0]
    const contracts = members.reduce((a, m) => a + (num(m.contracts) ?? 0), 0)
    const costs = members.map(m => num(m.premium_total) ?? (num(m.premium) != null && num(m.contracts) != null ? premiumTotal(num(m.premium)!, num(m.contracts)!) : null))
    const cost = costs.every(fin) ? costs.reduce((a, b) => a + (b as number), 0) : null
    const shares = members.every(m => num(m.shares_held) != null) ? members.reduce((a, m) => a + (num(m.shares_held) as number), 0) : null
    const blockers = blockersFor(lead)
    const ordered = [...blockers].sort((a, b) => rank(a.key) - rank(b.key))
    const first = ordered[0]
    const cio = cioFailures(lead)
    const stuck = lane === 'you'
      ? `Waiting on your decision${cio.count ? ` · CIO review ${cio.capped ? 'stopped after' : 'failed'} ${cio.count}×` : first ? ` · ${first.text}` : ''}`
      : first ? first.text : String(lead.review_workflow?.reason || '—')
    const accounts = members.map(m => `${acctName(m.account)}${num(m.shares_held) != null ? ` ${Math.floor(num(m.shares_held)!).toLocaleString('en-US')} sh` : ''}`).join(' + ')
    const sc = scenariosFor(members, lead.strategy)
    const plainServed = lead.committee_memo?.plain_summary || lead.plain_english?.premium_line
    ideas.push({
      id: String(lead.id), groupKey: k, lane, symbol: String(lead.symbol || '').toUpperCase(), strategy: String(lead.strategy || ''),
      strategyLabel: strategyLabel(lead.strategy), contract: contractText(lead, contracts, nowYear), accounts,
      does: doesText(lead, contracts, shares, cost),
      cost: cost == null ? '—' : isCredit(lead.strategy) ? `+${usd(cost)} credit` : usd(cost), costValue: cost,
      stuck, stuckKey: lane === 'you' && cio.count ? 'blocker.cio_review_failed' : first?.key || 'blocker.other',
      next: nextFor(lane, lead, blockers),
      plain: members.length > 1 && plainServed ? `${plainServed} (Shown for ${acctName(lead.account)}; the row merges ${members.length} accounts.)` : String(plainServed || doesText(lead, contracts, shares, cost)),
      econ: econFor(members, contracts, shares, cost, now), scenarios: sc.rows, scenarioNote: sc.note,
      checks: checksFor(lead, blockers, lane), model: modelLine(lead), quoteTimes: quoteTimesFor(lead, now),
      memberIds: members.map(m => String(m.id)), raw: members, tier: lead.desk_tier ?? null, sleeve: lead.sleeve ?? null,
      flags: arr(lead.flags).map(f => String(f?.key || '')).filter(Boolean),
      costAge: quoteFreshness(lead, now).text,
    })
  }
  return actFirstSort(ideas)
}

const BLOCK_RANK = ['blocker.thesis_missing', 'blocker.thesis_required', 'blocker.low_open_interest', 'blocker.wide_spread', 'blocker.low_volume',
  'blocker.holdings_unverified', 'blocker.option_chain_stale', 'blocker.quote_stale', 'blocker.cio_review_failed', 'blocker.awaiting_cio_decision']
const rank = (k: string) => { const i = BLOCK_RANK.indexOf(k); return i < 0 ? BLOCK_RANK.length : i }

// ── Plans (standing intents) ─────────────────────────────────────────────────────────────────────

export type PlanBest = { kind: string; glossaryKey: string; contract: string; note: string; cta: NextStep; does?: string; cost?: string; costValue?: number | null; quoteAt?: string }
export type Plan = { symbol: string; goal: string; facts: string; badges: string[]; warnings: string[]; best: PlanBest[]; directiveId?: number | string }

const PLAY_NAME: Record<string, string> = { cash_secured_put: 'Best cash-secured put', covered_call: 'Best covered call', leap_call: 'Best LEAP (stock substitute)' }
const PLAY_KEY: Record<string, string> = { cash_secured_put: 'strategy.cash_secured_put', covered_call: 'strategy.covered_call', leap_call: 'strategy.leap_call' }

export function buildPlans(intentFeed: Any | null, ideas: Idea[], now: Date = new Date()): Plan[] {
  const feed = unwrap(intentFeed)
  const nowYear = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric' }).format(now))
  return arr(feed?.intents).map((it: Any) => {
    const m = it.matches || {}
    const sym = String(it.symbol || '').toUpperCase()
    const goals = arr<string>(it.goals)
    const goal = [goals.map(g => g.charAt(0).toUpperCase() + g.slice(1)).join(' + ') || 'Track', it.thesis_target ? `toward $${it.thesis_target}` : '']
      .filter(Boolean).join(' ')
    const ed = it.earnings_dates && typeof it.earnings_dates === 'object' ? it.earnings_dates : null
    const deskEarn = ed ? (ed.provider_date || null) : (m.earnings?.provider_date || m.earnings?.date || null)
    const planEarn = ed ? (ed.operator_estimate || null) : (it.earnings_estimate || null)
    const earnConflict = ed && typeof ed.conflict === 'boolean' ? ed.conflict : !!(deskEarn && planEarn && String(deskEarn) !== String(planEarn))
    const facts = [`plan #${it.directive_id ?? '—'}`, `spot ${usd2(num(m.spot))} at ${etTime(m.quote_time || m.as_of, now)}`,
      earnConflict
        ? `earnings ⚠ desk ${deskEarn} vs plan "${planEarn}"${ed?.effective_date ? ` (matcher avoids the earlier: ${ed.effective_date})` : ''}`
        : deskEarn ? `earnings ${deskEarn}` : planEarn ? `earnings (plan) ${planEarn}` : 'earnings date not provided'].join(' · ')
    const badges: string[] = []
    const held = num(it.shares_held_total) ?? (m.shares_by_account && typeof m.shares_by_account === 'object' ? Object.values(m.shares_by_account).reduce((a: number, v: any) => a + (num(v) ?? 0), 0) : null)
    if (it.watch_only === true || (it.watch_only == null && held === 0)) badges.push('Not held · watch only')
    const warnings: string[] = []
    if (earnConflict) {
      warnings.push(`Earnings dates disagree: the desk earnings gate says ${deskEarn}; your plan text says ${planEarn}. Both are shown; check before relying on either.`)
    }
    const wantsMore = goals.some(g => /accumulat/i.test(g))
    const hedges = ideas.filter(i => i.symbol === sym && (i.strategy === 'protective_put' || i.flags.includes('INSURANCE')))
    const servedConflicts = arr(it.conflicts)
    if (servedConflicts.length) {
      for (const t of [...new Set(servedConflicts.map(c => String(c?.text || '')).filter(Boolean))]) warnings.push(`Conflict: ${t}`)
    } else if (wantsMore && hedges.length) warnings.push(`Conflict: this plan wants more ${sym}, while the desk proposes insuring (hedging) the same shares.`)
    if (arr(it.matches?.errors).length) warnings.push(`Matcher errors: ${arr(it.matches.errors).map(String).slice(0, 2).join('; ')}`)
    const plays = m.plays && typeof m.plays === 'object' ? m.plays : {}
    const playKeys = Object.keys(it.plays || plays)
    const best: PlanBest[] = playKeys.filter(pk => PLAY_NAME[pk]).map(pk => {
      const rows = arr(plays[pk])
      const r = rows[0]
      if (!r) return { kind: PLAY_NAME[pk], glossaryKey: PLAY_KEY[pk], contract: 'none', note: String(m.empty_reasons?.[pk] || 'no contract fits the plan rules'), cta: { kind: 'none', label: '—', reason: 'Nothing to stage.' } as NextStep }
      const typ = pk === 'cash_secured_put' ? 'P' : 'C'
      const contract = `${shortDate(r.exp, nowYear)} $${r.strike}${typ}`
      let note: string
      if (pk === 'cash_secured_put') {
        const poc = num(r.premium_over_collateral_pct ?? r.return_pct), ann = num(r.simple_annualized_yield_pct ?? r.annualized_pct)
        note = `+${usd(num(r.credit_per_contract))}${r.credit_basis ? ` at the ${r.credit_basis}` : ''} on ${usd(num(r.collateral_per_contract))} cash · ${pct(poc, 2)} premium/collateral · ${pct(ann, 1)} simple annualized (not repeatable) · buy at effective ${usd2(num(r.breakeven))} if assigned`
      } else if (pk === 'covered_call') {
        note = `+${usd(num(r.credit_per_contract))}/contract · keeps +${pct(num(r.upside_kept_pct), 0)} upside · ${pct(num(r.annualized_pct), 1)} simple annualized (not repeatable)`
      } else {
        const cost = num(r.cost_per_contract), stock = num(r.stock_cost_100)
        note = `${usd(cost)} vs ${usd(stock)} for 100 sh${cost != null && stock ? ` (${Math.round((cost / stock) * 100)}% of the stock price)` : ''} · Δ ${num(r.delta)?.toFixed(2) ?? '—'} · time value ${pct(num(r.time_value_pct), 1)}`
      }
      note += ` · quote ${etTime(r.quote_time, now)}`
      const credit = num(r.credit_per_contract), debit = num(r.cost_per_contract)
      const does = pk === 'cash_secured_put' ? `Paid ${usd(credit)} to agree to buy 100 sh at $${r.strike}`
        : pk === 'covered_call' ? `Paid ${usd(credit)} to agree to sell 100 sh at $${r.strike}`
          : `Pays ${usd(debit)} for the right to buy 100 sh at $${r.strike}`
      const costValue = pk === 'leap_call' ? debit : credit
      const cost = costValue == null ? '—' : pk === 'leap_call' ? usd(costValue) : `+${usd(costValue)} credit`
      return { kind: PLAY_NAME[pk], glossaryKey: PLAY_KEY[pk], contract, note, does, cost, costValue,
        quoteAt: r.quote_time ? `${etTime(r.quote_time, now)} · ${ageText(Math.max(0, (now.getTime() - new Date(r.quote_time).getTime()) / 1000))}` : undefined,
        cta: r.contract_guid ? { kind: 'stage', label: 'Stage ›', source: { directive_id: it.directive_id, play: pk, contract_guid: r.contract_guid } } as NextStep
          : { kind: 'none', label: '—', reason: 'This match has no contract id, so it cannot be staged.' } as NextStep }
    })
    return { symbol: sym, goal, facts, badges, warnings, best, directiveId: it.directive_id }
  })
}

/** Plan best matches as table rows in the "Not staged" lane. */
export function planIdeas(plans: Plan[]): Idea[] {
  const out: Idea[] = []
  for (const pl of plans) {
    for (const b of pl.best) {
      if (b.cta.kind !== 'stage') continue
      const strategy = b.glossaryKey.replace('strategy.', '')
      out.push({
        id: `plan:${pl.symbol}:${strategy}`, groupKey: `plan|${pl.symbol}|${strategy}`, lane: 'plan', symbol: pl.symbol, strategy,
        strategyLabel: strategyLabel(strategy), contract: `${b.contract} × 1`, accounts: 'needs an account', does: b.does || b.note.split(' · ')[0],
        cost: b.cost ?? '—', costValue: b.costValue ?? null, stuck: 'Not staged: pick account + size', stuckKey: 'blocker.not_staged', next: b.cta,
        plain: `From your ${pl.symbol} plan (${pl.goal}). ${b.note}.`, econ: [], scenarios: [], scenarioNote: 'Stage it to see account-specific numbers.',
        checks: [{ mark: '✓', text: `Matches your plan #${pl.directiveId ?? '—'}`, glossaryKey: 'concept.standing_plan' },
          { mark: '✗', text: 'Account and size not chosen → stage it', glossaryKey: 'blocker.not_staged' },
          { mark: '○', text: 'Thesis for this account', glossaryKey: 'concept.thesis' },
          { mark: '○', text: 'CIO decision', glossaryKey: 'concept.cio_decision' },
          { mark: '○', text: 'Your decision', glossaryKey: 'lifecycle.you' },
          { mark: '○', text: 'Fresh preflight + per-order 2FA (you, at the broker step)', glossaryKey: 'lifecycle.place' }],
        model: 'not reviewed yet', quoteTimes: b.note.split(' · ').pop() || '', memberIds: [], raw: [], flags: [],
        costAge: b.quoteAt ? `quote ${b.quoteAt}` : 'quote time not provided by this server version',
      })
    }
  }
  return out
}

// ── Open positions (Step 7) ──────────────────────────────────────────────────────────────────────

export type OpenUrgency = 'protect' | 'act' | 'calm'

/** Urgency from the monitor's own classification (scripts/options_engine.py:_monitor_position):
 *  the "defend" phase — or a position the monitor says is no longer working — is protect-first;
 *  "harvest" (take profit / expiry approaching) is act-first; everything else is calm. */
export function openUrgency(pos: Any): OpenUrgency {
  const phase = String(pos?.lifecycle_phase || '').toLowerCase()
  if (phase === 'defend' || pos?.still_working === false) return 'protect'
  if (phase === 'harvest') return 'act'
  return 'calm'
}

const OPEN_STRATEGY: Record<string, string> = { short_put: 'Short put', short_call: 'Short call', long_put: 'Long put', long_call: 'Long call' }

/** One row per open option leg from /api/v2/options/open-positions (broker legs only). Read-only:
 *  the next step opens the existing Lifecycle view, where close / roll live. */
export function openPositionRows(openPositions: Any | null, now: Date = new Date()): Idea[] {
  const op = unwrap(openPositions)
  const runAt = op?.monitored_at ?? null
  const alerts = arr(op?.alerts)
  const nowYear = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric' }).format(now))
  return arr(op?.positions).map((pos: Any, n: number) => {
    const sym = String(pos.underlying || pos.symbol || '').toUpperCase()
    const typ = String(pos.option_type || '').toLowerCase()
    const short = String(pos.side || '').toLowerCase() === 'short'
    const strategy = String(pos.strategy || `${short ? 'short' : 'long'}_${typ}`)
    const qty = num(pos.qty)
    const k = num(pos.strike), dte = num(pos.dte), mark = num(pos.mark), entry = num(pos.avg_entry), spot = num(pos.underlying_price)
    const pnl = num(pos.unrealized_pnl)
    const ecd = num(pos.entry_credit_debit)
    const at = pos.monitored_at ?? runAt
    const atAge = at ? Math.max(0, (now.getTime() - new Date(at).getTime()) / 1000) : null
    const fresh = at ? `monitored ${etTime(at, now)}${fin(atAge) ? ` · ${ageText(atAge)}` : ''}` : 'monitor time not provided by this server version'
    const urgency = openUrgency(pos)
    const typL = typ === 'put' ? 'P' : typ === 'call' ? 'C' : ''
    const contract = `${shortDate(pos.expiration, nowYear)} $${k ?? '—'}${typL} × ${qty ?? '—'}`
    const label = OPEN_STRATEGY[strategy] || strategyLabel(strategy)
    const does = `${short ? 'Sold' : 'Bought'} ${qty ?? '—'} ${typ || 'option'}${qty === 1 ? '' : 's'} at $${k ?? '—'} · ${pos.moneyness || '—'} · ${dte ?? '—'} days left · P/L ${pnl == null ? '—' : usd(pnl, true)}`
    const criterion = String(pos.action_criterion || '')
    const action = String(pos.recommended_action || '')
    const stuck = urgency === 'calm'
      ? (pos.maturity_note ? String(pos.maturity_note) : `Monitor: ${action || 'hold'}`)
      : `Monitor says ${action || 'act'}${criterion ? ` (${criterion})` : ''}`
    const symAlerts = alerts.filter(a => pos.id != null && String(a?.id) === String(pos.id)).map(a => String(a?.message || a?.title || a?.kind || '')).filter(Boolean)
    const markNote = `chain mid · ${fresh} · provider quote time not served`
    const econ: Econ[] = [
      { label: 'Spot', value: usd2(spot), glossaryKey: 'term.spot', note: fresh },
      { label: 'Mark', value: usd2(mark), glossaryKey: 'term.mark', note: mark == null ? 'no chain mark this run' : markNote },
      { label: 'Entry', value: usd2(entry), glossaryKey: 'term.entry_price', note: entry == null ? 'fill basis missing' : 'average fill, per share' },
      { label: 'Unrealized P/L', value: usd(pnl, true), glossaryKey: 'term.unrealized_pnl', note: pnl == null ? String(pos.pnl_unknown_reason || 'not computed') : `at the mark · ${fresh}` },
      { label: 'Days', value: dte != null ? String(dte) : '—', glossaryKey: 'term.dte', note: pos.expiration ? `to ${pos.expiration}` : undefined },
      { label: 'Moneyness', value: String(pos.moneyness || '—'), glossaryKey: 'term.moneyness', note: fresh },
      { label: short ? 'POP OTM' : 'Finish ITM', value: pct(num(short ? pos.pop_otm_pct : pos.pop_itm_pct), 0), glossaryKey: 'term.pop_monitor', note: `model estimate · ${fresh}` },
      { label: 'Delta', value: num(pos.delta) != null ? (num(pos.delta) as number).toFixed(2) : '—', glossaryKey: 'term.delta', note: fresh },
    ]
    if (short) econ.push({ label: 'Premium captured', value: pct(num(pos.profit_captured_pct), 0), glossaryKey: 'term.profit_captured', note: fresh })
    const checks: Check[] = [
      urgency === 'calm' ? { mark: '✓', text: `Still working: ${criterion || 'no close/roll rule fired'}`, glossaryKey: 'concept.monitor_rule' }
        : { mark: '✗', text: `${action || 'Act'}: ${criterion || 'monitor rule fired'}`, glossaryKey: 'concept.monitor_rule' },
      pnl == null ? { mark: '✗', text: `P/L unknown: ${pos.pnl_unknown_reason || 'not computed'}`, glossaryKey: 'term.unrealized_pnl' }
        : { mark: '✓', text: `P/L computed from the chain mark (${fresh})`, glossaryKey: 'term.unrealized_pnl' },
      { mark: '○', text: 'Close or roll: your decision, at the broker with per-order 2FA, then record it in the manual log', glossaryKey: 'lifecycle.open' },
    ]
    return {
      id: `open:${pos.unified_id || pos.id || `${sym}-${n}`}`, groupKey: `open|${pos.id || n}`, lane: 'open' as LaneKey, symbol: sym, strategy,
      strategyLabel: label, contract, accounts: acctName(pos.account_key) || 'account not served', does,
      cost: ecd == null ? '—' : ecd > 0 ? `+${usd(ecd)} credit` : usd(-ecd), costValue: ecd == null ? null : Math.abs(ecd),
      costAge: entry == null ? 'entry basis missing' : `at open · ${fresh}`,
      stuck, stuckKey: 'concept.monitor_rule', next: { kind: 'view', label: 'Manage in Lifecycle', view: 'Lifecycle' } as NextStep,
      plain: `${pos.rationale ? `${pos.rationale}. ` : ''}${pos.maturity_note || ''}`.trim() || does,
      econ, scenarios: [], scenarioNote: '', checks, model: 'not part of the open-position monitor',
      quoteTimes: fresh, memberIds: [], raw: [pos], flags: [], urgency,
      monitor: { criterion, note: String(pos.maturity_note || ''), monitoredAt: at, alerts: symAlerts },
    }
  })
}

// ── Act-first ordering ───────────────────────────────────────────────────────────────────────────

const PROTECT_STRATEGIES = new Set(['protective_put', 'collar'])

/** Bucket for the act-first order: protect an open position, then decisions only you can make,
 *  then open positions to act on, then ideas ready to place, then work owned by others (data,
 *  research), then plan matches to stage, then calm open positions, then found names. */
export function actBucket(i: Pick<Idea, 'lane' | 'urgency'>): number {
  if (i.lane === 'open') return i.urgency === 'protect' ? 0 : i.urgency === 'act' ? 2 : 7
  return { you: 1, place: 3, data: 4, research: 5, plan: 6, scan: 8 }[i.lane as Exclude<LaneKey, 'open'>] ?? 8
}

/** Act first: bucket, then protection (insuring held shares) before income or direction, then the
 *  larger dollar amount, then symbol. */
export function actFirstSort<T extends Pick<Idea, 'lane' | 'urgency' | 'strategy' | 'costValue' | 'symbol'>>(rows: T[]): T[] {
  return [...rows].sort((a, b) => actBucket(a) - actBucket(b)
    || (PROTECT_STRATEGIES.has(b.strategy) ? 1 : 0) - (PROTECT_STRATEGIES.has(a.strategy) ? 1 : 0)
    || Math.abs(b.costValue ?? 0) - Math.abs(a.costValue ?? 0)
    || a.symbol.localeCompare(b.symbol))
}

// ── Lane counts ──────────────────────────────────────────────────────────────────────────────────

export type LaneCount = { key: LaneKey; n: number | null; note: string }

export function laneCounts(proposals: Any | null, ideas: Idea[], intentFeed: Any | null, openPositions: Any | null, now: Date = new Date()): LaneCount[] {
  const p = unwrap(proposals)
  const feed = unwrap(intentFeed)
  const op = unwrap(openPositions)
  const count = (k: LaneKey) => ideas.filter(i => i.lane === k).length
  const inv = num(p?.coverage?.inventory_count ?? p?.universe_census?.inventory_count)
  const unstaged = num(feed?.unstaged_count)
  const open = num(op?.position_count ?? op?.unified_count) ?? (Array.isArray(op?.positions) ? op.positions.length : null)
  const ideasAt = p?.snapshot?.generated_at ?? p?.generated_at
  const asOf = (iso: unknown) => (iso ? `; as of ${etTime(String(iso), now)}` : '; time not provided by this server version')
  return LANES.map(l => {
    if (l.key === 'scan') return { key: l.key, n: inv, note: inv == null ? 'not provided by this server version' : `names in inventory, not ideas${asOf(ideasAt)}` }
    if (l.key === 'plan') return { key: l.key, n: unstaged ?? count('plan'), note: `${unstaged != null ? `${unstaged} contract matches; the table shows the best per strategy` : 'best plan matches'}${asOf(feed?.generated_at ?? feed?.as_of)}` }
    if (l.key === 'open') return { key: l.key, n: open, note: open == null ? 'not provided by this server version' : `open option legs at the broker; monitored${asOf(op?.monitored_at).replace('; as of', '')}` }
    return { key: l.key, n: count(l.key), note: `ideas (accounts merged)${asOf(ideasAt)}` }
  })
}

/** Every glossary key the model can emit, for the coverage test. */
export const MODEL_GLOSSARY_KEYS: string[] = [
  ...LANES.map(l => l.glossaryKey), ...BLOCKER_KEYS,
  'fresh.market', 'fresh.stock_quotes', 'fresh.option_chain', 'fresh.holdings', 'fresh.scan_coverage', 'fresh.open_positions', 'exec.state',
  'term.mark', 'term.entry_price', 'term.unrealized_pnl', 'term.moneyness', 'term.pop_monitor', 'term.delta', 'term.profit_captured',
  'concept.monitor_rule', 'concept.act_first', 'lifecycle.open',
  'term.spot', 'term.strike', 'term.premium', 'term.total_cost', 'term.floor', 'term.dte', 'term.collateral', 'term.breakeven',
  'term.premium_over_collateral', 'term.simple_annualized', 'term.edge', 'term.spread_pct',
  'concept.thesis', 'concept.cio_decision', 'concept.standing_plan',
  'strategy.cash_secured_put', 'strategy.covered_call', 'strategy.leap_call', 'strategy.protective_put', 'strategy.long_call',
  'strategy.long_put', 'strategy.credit_spread', 'strategy.debit_spread', 'strategy.collar',
]
