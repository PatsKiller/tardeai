/** Portfolio v002 (operator-approved with amendments 2026-11-11, design/pages/portfolio/v002) — the page model.
 *
 *  Engineering Constitution: unknown beats wrong. Pure functions only; the page owns fetching.
 *
 *  Protection rule (DECISIONS-20261111):
 *    - OK only when every counted position was read and has a verified resting stop
 *      (a pending_activation resting GTC stop counts, G1);
 *    - GAP when a good read shows a counted position with no resting stop;
 *    - WARN (D1) when the only protection was a stop that expired (protection existed, no longer active);
 *    - UNKNOWN whenever protection cannot be verified. UNKNOWN is never drawn as NO STOP and never as OK.
 *  The per-row verdict is the backend's (cio_truth.protection_for -> holdings `protection_state`, LQ-2165).
 *  This module never re-derives a row's state from stop fields. It applies only the operator's time rules to it
 *  (2026-11-12, R1/R2, config/protection_verdict.json in LQ-2412) and rolls the rows up GAP > UNKNOWN > WARN > OK,
 *  the order of the backend rollups (LQ-2412 protection_verdict, LQ-2415). No served rollup is read yet (G2), so
 *  the verdict is marked NEEDS BACKEND; until one is, the client verdict errs to UNKNOWN, never to OK (LQ-2460):
 *    - an unknown value is never small: an unpriced non-exempt, non-cash row counts even when the wire says
 *      counted:false (LQ-2469, the cio_truth rule after LQ-2431). Only a KNOWN value under $100 is listed, not
 *      counted, not hidden (DECISIONS-20261111);
 *    - no counted position reads UNKNOWN unless the position count independently confirms zero;
 *    - R1: a GAP whose only stop expired is UNKNOWN in the regular session, WARN after the close (D1);
 *    - R2: a GAP whose stop read is older than the freshness limit is UNKNOWN; the last-known GAP stays listed.
 *      The limit itself is fresh (age > limit is stale). The session is 09:30:00 <= ET < 16:00:00, Mon-Fri.
 *  One verdict for one book (LQ-2483, LQ-2708). The owner of the served verdict is protection_verdict.headline
 *  (LQ-2412/2436, lead ruling); no route serves it yet (G2). Until one does, this module applies the owner's rules to
 *  the rows it has, and the shared fixture tests/fixtures/portfolio_protection_books_lq2708.json is read by both sides:
 *  the Python test runs each book's positions through cio_truth.protection_for (the wire) and stops_protection.summary;
 *  the page test runs the same wire through this module. Invariants on every book: the page never reads GAP where the
 *  backend reads OK, and never OK where it reads anything else. Membership agrees because this branch carries LQ-2431
 *  (e5afdf19d) and LQ-2436 (c280ec89d): an unpriced or <= 0 row is counted on the wire too.
 *  Declared splits, all with the page on the owner's side and never less alarmed than OK:
 *    - zero counted, count not confirmed: summary OK, page UNKNOWN with its cause (owner: UNKNOWN, LQ-2412 21083f476);
 *    - R1 expired stop in session and R2 stale GAP read: summary GAP (no clock), page UNKNOWN with the last-known GAP
 *      kept as a P0 row (owner: UNKNOWN). R1 reads protection.expired_stop (LQ-2412) or stop_state 'expired'.
 *  Not mirrored: the owner's 2169 counted set (an operator-exempt class) and its per-broker read ages. The rows carry
 *  neither, so the page cannot see them; rendering the served verdict (G2) is what closes that.
 *  I1/I2 defaults: unreadable -> UNKNOWN; no source -> UNKNOWN + NEEDS BACKEND; timeout (30 s) -> TIMED OUT;
 *  missing data -> UNKNOWN. Missing is never healthy. No /api/v2/overview read. */

export const PORTFOLIO_V002_TIMEOUT_MS = 30_000
export const API = {
  holdings: '/api/v2/portfolio/holdings',
  incidents: '/api/v2/home/incidents',
  /** LQ-2467: portfolio.last_seen, same server-stamped contract as Home's home.last_seen (write is gated). */
  lastSeen: '/api/v2/ui/prefs/get?key=portfolio.last_seen',
  prefs: '/api/v2/ui/prefs',
} as const
export const PORTFOLIO_LAST_SEEN_KEY = 'portfolio.last_seen'

export type ReadState = 'OK' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
export interface Read<T> { state: ReadState; data: T | null; error: string | null; at: string | null; source: string }
export const loadingRead = <T,>(source: string): Read<T> => ({ state: 'LOADING', data: null, error: null, at: null, source })

/** One GET with a hard 30 s timeout. Never throws: the result says what happened. A `{ok, data}` envelope is unwrapped. */
export async function readOnce<T>(source: string, timeoutMs = PORTFOLIO_V002_TIMEOUT_MS, fetchImpl: typeof fetch = fetch): Promise<Read<T>> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; ctl?.abort() }, timeoutMs)
  const at = new Date().toISOString()
  try {
    const r = await fetchImpl(source, { signal: ctl?.signal, cache: 'no-store', credentials: 'same-origin' })
    if (!r.ok) return { state: 'UNKNOWN', data: null, error: `HTTP ${r.status}`, at, source }
    const body = (await r.json()) as unknown
    return { state: 'OK', data: unwrap(body) as T, error: null, at, source }
  } catch (e) {
    if (timedOut) return { state: 'TIMED OUT', data: null, error: `no answer after ${Math.round(timeoutMs / 1000)} s`, at, source }
    return { state: 'UNKNOWN', data: null, error: e instanceof Error ? e.message : String(e), at, source }
  } finally {
    clearTimeout(timer)
  }
}

export function unwrap(body: unknown): unknown {
  if (body && typeof body === 'object' && 'data' in body && 'ok' in body) {
    const b = body as { ok?: unknown; data?: unknown }
    if (b.data && typeof b.data === 'object') return b.data
  }
  return body
}

// ── wire shapes (only the fields this page reads) ─────────────────────────────────────────────────────
export interface ProtectionWire { state?: string; reason?: string | null; cause?: string | null; source?: string | null; as_of?: string | null; counted?: boolean; expired_stop?: boolean; price_missing?: boolean }
export interface HoldingWire {
  symbol?: string; account?: string; account_id?: string; account_label?: string; broker?: string
  quantity?: number | null; shares?: number | null; market_value?: number | null; price?: number | null
  price_as_of?: string | null; price_stale?: boolean | null; price_source?: string | null; quote_source?: string | null
  market_value_as_of?: string | null; market_value_source?: string | null; shares_synced_at?: string | null
  day_change?: number | null; day_change_pct?: number | null; prior_close?: number | null
  cost_basis?: number | null; cost_basis_source?: string | null; basis_status?: string | null
  is_cash?: boolean; asset_type?: string | null
  stop_state?: string | null; stop_price?: number | null; stop_qty?: number | null; stop_captured_at?: string | null; stop_source?: string | null
  stop_order_id?: string | null; order_id?: string | null; stop_note?: string | null
  protection_state?: string | null; protection?: ProtectionWire | null
}

/** PortfolioMeasures@v1 (LQ-20261113-3124R, cc-deepseek-7). The writer materializes this block; GET never computes.
 *  Only the fields the page draws are typed. A value is drawn only when the projection published it with a status;
 *  the page never adds, subtracts or re-derives one measure from another (operator Q1, 2026-11-13: the broker store
 *  is the accounting anchor and a broker->Finviz re-mark is an estimate beside it, never inside it). */
export interface FinvizEstimateWire {
  label?: string; basis?: string; value?: number | null; marks_at?: string | null; delta?: number | null
  note?: string | null; total_with_broker_nav?: number | null; delta_vs_broker?: number | null; delta_note?: string | null
}
export interface MeasureWire {
  measure?: string; label?: string; value?: number | null; status?: string | null; basis?: string | null
  as_of?: string | null; definition?: string | null; gap?: { reason?: string | null; requires?: string | null; unvalued_rows?: unknown[]; start_unknown?: unknown[] } | null
  finviz_estimate?: FinvizEstimateWire | null
  coverage?: { measured_rows?: number | null; unknown_rows?: number | null; row_count?: number | null; unknown?: unknown[] | null } | null
  rows?: number | null
  start?: { equity_usd?: number | null; as_of?: string | null; source?: string | null; note?: string | null } | null
  end?: { equity_usd?: number | null; as_of?: string | null; source?: string | null } | null
  drill_down?: {
    price_move_estimate?: number | null; closed_today_trade_effect?: number | null; closed_today_rows?: unknown[] | null
    fees_today?: number | null; income_today?: number | null; external_flows_today?: number | null; reconciles?: boolean | null
  } | null
  candidate?: number | null
  known_components?: { price_move_estimate?: number | null; closed_today_trade_effect?: number | null; fees_today?: number | null; income_today?: number | null; external_flows_today?: number | null; note?: string | null } | null
  source?: string | null
}
export interface MeasuresBlockWire {
  contract_version?: string; status?: string; materialized?: boolean
  generated_at?: string | null; as_of?: string | null
  gap?: { reason?: string | null } | null
  measures?: Partial<Record<string, MeasureWire>> | null
  labels?: Partial<Record<string, string>> | null
  basis?: { applied?: string | null; why?: string | null } | null
  finviz_estimates_are_separate?: boolean
}
export interface HoldingsWire {
  holdings?: HoldingWire[] | null; total_value?: number | null; today_change?: number | null
  positions_as_of?: string | null; valuation_as_of?: string | null; quote_as_of?: string | null
  /** PositionCountAuthority@v1 (`scripts/lib/position_count_authority.py` counts_for_rows). `position_count` is the
   *  HEADLINE scope (`holdings.non_cash_over_100`), never "the count"; `agree` is the cross-scope flag — false on
   *  every real book, because cash / under-the-floor / unpriced rows are different populations — so it is never read
   *  as a comparison or as a finding (C5/C6, REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2). Findings are the contract's. */
  position_counts?: {
    agree?: boolean; position_count?: number; all_rows?: number; held_count?: number; primary_scope?: string
    scopes?: Record<string, number>; distinct_values?: number[]; summary?: string
    findings?: { code?: string; detail?: string }[]; [k: string]: unknown
  } | null
  /** PortfolioMeasures@v1. Present only once the writer has materialized it; absent is UNKNOWN, never computed here. */
  measures?: MeasuresBlockWire | null
}
export interface IncidentsWire { counts?: { P0?: number; P1?: number } | null; served_at?: string | null; items?: unknown[] | null }

// ── formatting ────────────────────────────────────────────────────────────────────────────────────────
export function fmtET(iso: string | null | undefined, withDay = false): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const opts: Intl.DateTimeFormatOptions = { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }
  if (withDay) opts.weekday = 'short'
  return d.toLocaleString('en-US', opts).replace(',', '')
}
export function fmtAge(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return '—'
  const m = Math.max(0, Math.round(ms / 60_000))
  if (m < 60) return `${m} m`
  const h = Math.round(m / 60)
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} d`
}
export function fmtUsd(v: number | null | undefined, signed = false): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
  const sign = v < 0 ? '−' : signed && v > 0 ? '+' : ''
  return `${sign}$${s}`
}
export function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`
}
export function fmtShares(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
function ageMs(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? Math.max(0, nowMs - t) : null
}
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// ── per-row protection (display only; the verdict is the backend's) ──────────────────────────────────
export type RowProtection = 'PROTECTED' | 'GAP' | 'WARN' | 'UNKNOWN' | 'EXEMPT'
export const STOP_OWNER = 'stop_health_check / Stop Management'

export interface PositionModel {
  key: string; symbol: string; account: string; accountKey: string; broker: string
  shares: number | null; value: number | null; price: number | null; dayPct: number | null; dayUsd: number | null
  isCash: boolean; counted: boolean; underFloor: boolean; unpriced: boolean
  /** R2: the backend said GAP but its stop read is past the freshness limit; the row reads UNKNOWN, the GAP stays listed. */
  lastKnownGap: boolean
  protection: RowProtection; chip: string; reason: string; cause: string | null; source: string; verifiedAt: string | null
  stopPrice: number | null; priceStale: boolean | null
  /** Resting stop quantity from the wire (`stop_qty`), never a derived number; null when the read did not publish it. */
  restingShares: number | null
  /** Display-only coverage classification (covered/partial/uncovered/planned-only/exempt/unverifiable). It never
   *  changes the backend's protection verdict or the rollup. */
  coverage: CoverageView
  raw: HoldingWire
}

/** Display-only stop coverage (campaign vocabulary, 2026-11-14). The backend's protection_state stays the verdict;
 *  this class answers "how much of the holding does a resting stop actually cover", which the verdict does not say.
 *  COVERED     a resting stop and no evidence of a shortfall in the read
 *  PARTIAL     a resting stop exists but its quantity is less than the held shares (resting vs held is drawn)
 *  UNCOVERED   a good read shows no resting stop (GAP), or the only stop expired (WARN)
 *  PLANNED_ONLY the stop exists only as a plan at the broker; counts as unprotected
 *  EXEMPT      policy-exempt (cash / money market / sweep)
 *  UNVERIFIABLE protection could not be read; never drawn as uncovered
 *  Never derived from arithmetic the projection owns: resting/held are wire values, drawn side by side. */
export type CoverageCategory = 'COVERED' | 'PARTIAL' | 'UNCOVERED' | 'PLANNED_ONLY' | 'EXEMPT' | 'UNVERIFIABLE'
export interface CoverageView {
  category: CoverageCategory; chip: string; label: string
  restingShares: number | null; heldShares: number | null; detail: string
}
export const COVERAGE_ORDER: CoverageCategory[] = ['COVERED', 'PARTIAL', 'UNCOVERED', 'PLANNED_ONLY', 'EXEMPT', 'UNVERIFIABLE']

function coverageFor(pr: Pick<PositionModel, 'protection' | 'chip' | 'reason'>, h: HoldingWire, held: number | null): CoverageView {
  const resting = num(h.stop_qty)
  const planned = String(h.stop_source || '').toLowerCase() === 'planned' || String(h.stop_state || '').toLowerCase() === 'planned'
  const shares = held != null && held > 0 ? held : null
  if (pr.protection === 'EXEMPT') {
    return { category: 'EXEMPT', chip: 'EXEMPT', label: 'Exempt from stop coverage', restingShares: resting, heldShares: shares,
      detail: 'Cash / money-market / sweep rows are exempt by policy; no stop is expected.' }
  }
  if (pr.protection === 'UNKNOWN') {
    return { category: 'UNVERIFIABLE', chip: 'UNKNOWN', label: 'Coverage cannot be verified', restingShares: resting, heldShares: shares,
      detail: `${pr.reason}. A stop quantity in an unread book is not coverage; this is never drawn as NO STOP.` }
  }
  if (pr.protection === 'GAP' || pr.protection === 'WARN') {
    if (planned && pr.protection === 'GAP') {
      return { category: 'PLANNED_ONLY', chip: 'PLANNED ONLY', label: 'Planned only', restingShares: resting, heldShares: shares,
        detail: 'The level exists only as a plan at the broker; no resting order protects the position, so it counts as unprotected.' }
    }
    return { category: 'UNCOVERED', chip: pr.protection === 'WARN' ? 'EXPIRED' : 'NO STOP', label: pr.protection === 'WARN' ? 'Expired stop' : 'Uncovered',
      restingShares: resting, heldShares: shares,
      detail: pr.protection === 'WARN' ? 'Protection existed but the stop expired; nothing rests at the broker now.' : 'The broker read succeeded and shows no resting stop.' }
  }
  // PROTECTED: a resting stop. Draw the quantities the read published; call it partial only when both are known.
  if (shares != null && resting != null && resting < shares) {
    return { category: 'PARTIAL', chip: `PARTIAL ${fmtShares(resting)}/${fmtShares(shares)}`, label: 'Partial coverage',
      restingShares: resting, heldShares: shares,
      detail: `The resting stop covers ${fmtShares(resting)} of ${fmtShares(shares)} held shares. The backend verdict stays PROTECTED; the uncovered remainder is drawn, not hidden.` }
  }
  return { category: 'COVERED', chip: pr.chip, label: 'Covered', restingShares: resting, heldShares: shares,
    detail: resting == null || shares == null
      ? 'A resting stop is present. This read did not publish both the resting quantity and the held quantity, so full coverage is not proven.'
      : `The resting stop covers ${fmtShares(resting)} of ${fmtShares(shares)} held shares.` }
}
export function coverageOf(p: PositionModel): CoverageView { return p.coverage }

/** Stop-read freshness limits: config/data_source_authority.json domain `broker_stops` (stale_after_hours 0.25,
 *  stale_after_hours_closed 72), read by cio_truth.stop_freshness_contract() and by the owner rollup
 *  protection_verdict.headline (LQ-2436 F1). The LQ-2708 contract test pins this to the same file. */
export const STOP_READ_MAX_AGE_MS = { session: 900_000, offHours: 72 * 3_600_000 } as const

/** R1: what an expired-only stop reads while the regular session is open. config/protection_verdict.json
 *  `protection_verdict.expired_day_stop_open_session` (LQ-2412, shipped UNKNOWN); UNKNOWN is also the owner's fallback
 *  when that file is absent or invalid. The LQ-2708 contract test pins this to the file when it exists. */
export const R1_EXPIRED_OPEN_SESSION: 'UNKNOWN' | 'GAP' | 'WARN' = 'UNKNOWN'

/** No usable value: missing, not a number, or <= 0 (a feed that writes 0 for no quote). Never "under the floor".
 *  The value alone decides, exactly as the owner does (protection_verdict.price_missing_of, LQ-2436 F3) and as
 *  cio_truth.protection_for sets protection.price_missing. A wire flag beside a known positive value (the row was
 *  repriced after the protection read) is not used: the owner and the summary both list that row, so counting it
 *  here would draw a GAP the served verdict reads OK (LQ-2708). */
export function priceMissing(h: HoldingWire): boolean {
  const v = num(h.market_value)
  return v == null || v <= 0
}

/** Regular US equity session, 09:30-16:00 ET Mon-Fri. No holiday calendar: a holiday reads as open, which picks the
 *  stricter limit (R2) and UNKNOWN over WARN (R1), the safe side of both rules. */
export function sessionOpenET(nowMs: number): boolean {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date(nowMs))
  const get = (t: string) => parts.find(x => x.type === t)?.value || ''
  if (get('weekday') === 'Sat' || get('weekday') === 'Sun') return false
  const m = Number(get('hour')) * 60 + Number(get('minute'))
  return m >= 9 * 60 + 30 && m < 16 * 60
}

export interface RowContext { nowMs: number; sessionOpen?: boolean }
type RowView = Pick<PositionModel, 'protection' | 'chip' | 'reason' | 'cause' | 'source' | 'verifiedAt' | 'stopPrice' | 'lastKnownGap'>

export function rowProtection(h: HoldingWire, ctx: RowContext = { nowMs: Date.now() }): RowView {
  const r = rowView(h, ctx)
  return { lastKnownGap: false, ...r }
}

function rowView(h: HoldingWire, ctx: RowContext): Omit<RowView, 'lastKnownGap'> & { lastKnownGap?: boolean } {
  const p = h.protection || {}
  const st = String(h.protection_state || p.state || '').toUpperCase()
  const stopPrice = num(h.stop_price)
  const verifiedAt = p.as_of ?? h.stop_captured_at ?? null
  const source = p.source || h.stop_source || 'none'
  if (st === 'PROTECTED') {
    return { protection: 'PROTECTED', chip: stopPrice != null && stopPrice > 0 ? `STOP $${stopPrice.toFixed(2)}` : 'STOP · price not recorded',
      reason: p.reason || 'Resting stop', cause: null, source, verifiedAt, stopPrice }
  }
  if (st === 'GAP') {
    const open = ctx.sessionOpen ?? sessionOpenET(ctx.nowMs)
    // R1/D1: the backend keeps an expired-only stop as GAP and marks it (LQ-2412 protection.expired_stop).
    if (p.expired_stop === true || String(h.stop_state || '').toLowerCase() === 'expired') {
      return open
        ? { protection: R1_EXPIRED_OPEN_SESSION, chip: 'EXPIRED',
          reason: `The stop expired and the session is open; protection cannot be verified (R1: ${R1_EXPIRED_OPEN_SESSION})`,
          cause: 'Expired Stop', source, verifiedAt, stopPrice }
        : { protection: 'WARN', chip: 'EXPIRED', reason: 'The stop expired after the close; protection existed but is no longer active (D1: WARN, never OK)',
          cause: 'Expired Stop', source, verifiedAt, stopPrice }
    }
    // R2: a GAP from a read past the freshness limit is UNKNOWN; the last-known GAP stays visible. A GAP row with no
    // as_of carries no age to judge (the book-level read age is the served rollup's, G2) and stays GAP.
    const age = ageMs(verifiedAt, ctx.nowMs)
    const limit = open ? STOP_READ_MAX_AGE_MS.session : STOP_READ_MAX_AGE_MS.offHours
    if (age != null && age > limit) {
      return { protection: 'UNKNOWN', chip: 'UNKNOWN', lastKnownGap: true,
        reason: `Last known: no resting stop, but the stop read is ${fmtAge(age)} old (limit ${fmtAge(limit)}); R2: UNKNOWN`,
        cause: 'Stale Stop Read', source, verifiedAt, stopPrice }
    }
    return { protection: 'GAP', chip: 'NO STOP', reason: p.reason || 'Stop read succeeded and shows no resting stop',
      cause: 'Unprotected Position', source, verifiedAt, stopPrice }
  }
  if (st === 'EXEMPT') return { protection: 'EXEMPT', chip: 'EXEMPT', reason: p.reason || 'Exempt', cause: null, source: 'policy', verifiedAt: null, stopPrice }
  if (st === 'UNKNOWN') {
    return { protection: 'UNKNOWN', chip: 'UNKNOWN', reason: p.reason || 'Protection cannot be verified', cause: p.cause || 'Protection Unknown',
      source, verifiedAt, stopPrice }
  }
  // No verdict on the row: never guess from stop fields (I1/I2: no source -> UNKNOWN + NEEDS BACKEND).
  return { protection: 'UNKNOWN', chip: 'UNKNOWN', reason: 'The row carries no protection_state', cause: 'No Protection Verdict',
    source: 'none', verifiedAt: null, stopPrice }
}

export function positionsFrom(w: HoldingsWire | null, nowMs: number = Date.now()): PositionModel[] {
  const rows = Array.isArray(w?.holdings) ? w!.holdings! : []
  const ctx: RowContext = { nowMs, sessionOpen: sessionOpenET(nowMs) }
  return rows.map((h, i) => {
    const value = num(h.market_value)
    const isCash = !!h.is_cash
    const pr = rowProtection(h, ctx)
    const countedFlag = h.protection?.counted
    // F1 (REVIEW-2448, folded from LQ-2469): an unknown value is never small. An unpriced row (no value, or <= 0) stays
    // counted even when the wire says counted:false, so an unpriced GAP stays a GAP. Only a KNOWN positive value under
    // the floor is listed, not counted (operator DECISIONS-20261111: "under $100: listed, not counted, not hidden").
    const unpriced = priceMissing(h)
    const counted = pr.protection !== 'EXEMPT' && !isCash && ((countedFlag ?? true) || unpriced)
    const symbol = String(h.symbol || '?').toUpperCase()
    const account = String(h.account_label || h.account || h.account_id || '—')
    const accountKey = String(h.account || h.account_id || h.account_label || '—')
    const heldShares = num(h.shares) ?? num(h.quantity)
    return {
      key: `${h.account_id || h.account || i}:${symbol}`, symbol, account, accountKey, broker: String(h.broker || '—'),
      shares: heldShares, value, price: num(h.price), dayPct: num(h.day_change_pct), dayUsd: num(h.day_change),
      isCash, counted, unpriced: unpriced && !isCash, underFloor: pr.protection !== 'EXEMPT' && !isCash && !counted,
      ...pr, priceStale: h.price_stale ?? null, restingShares: num(h.stop_qty), coverage: coverageFor(pr, h, heldShares), raw: h,
    }
  }).sort((a, b) => (b.value ?? -1) - (a.value ?? -1))
}

// ── protection rollup (mirror of stops_protection.summary) ───────────────────────────────────────────
export type Verdict = 'OK' | 'GAP' | 'WARN' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
export interface BrokerInput { broker: string; state: 'OK' | 'UNKNOWN' | 'GAP' | 'WARN'; counted: number; protectedN: number; oldest: string | null; cause: string | null }
export interface ProtectionModel {
  verdict: Verdict; counted: number | null; protectedN: number | null; gap: number | null; warn: number | null; unknown: number | null
  listedNotCounted: number | null; exempt: number | null
  action: PositionModel[]; oldestRead: string | null; brokers: BrokerInput[]; cause: string | null
}

export function protectionModel(read: Read<HoldingsWire>, positions: PositionModel[]): ProtectionModel {
  const empty = { counted: null, protectedN: null, gap: null, warn: null, unknown: null, listedNotCounted: null, exempt: null, action: [], oldestRead: null, brokers: [] }
  if (read.state === 'LOADING') return { verdict: 'LOADING', ...empty, cause: null }
  if (read.state !== 'OK') return { verdict: read.state, ...empty, cause: `${read.source}: ${read.error || read.state}` }
  const counted = positions.filter(p => p.counted)
  // F2: no counted position is OK only when the position count independently confirms zero; otherwise UNKNOWN.
  if (counted.length === 0) {
    const pc = read.data?.position_counts
    const confirmedZero = pc?.agree === true && pc?.position_count === 0
    if (!confirmedZero || positions.length === 0) {
      return { verdict: 'UNKNOWN', ...empty,
        counted: positions.length ? 0 : null, listedNotCounted: positions.length ? positions.filter(p => p.underFloor).length : null,
        exempt: positions.length ? positions.filter(p => p.protection === 'EXEMPT' || p.isCash).length : null,
        cause: positions.length === 0 ? 'The holdings read returned no positions'
          : confirmedZero ? null : 'No counted position, and the position count does not confirm zero' }
    }
  }
  const n = { PROTECTED: 0, GAP: 0, WARN: 0, UNKNOWN: 0 }
  for (const p of counted) n[p.protection === 'EXEMPT' ? 'UNKNOWN' : p.protection]++
  // F3: GAP > UNKNOWN > WARN > OK, the order of the backend rollups (2412, 2415).
  const verdict: Verdict = n.GAP ? 'GAP' : n.UNKNOWN ? 'UNKNOWN' : n.WARN ? 'WARN' : 'OK'
  const rank: Record<RowProtection, number> = { GAP: 0, UNKNOWN: 1, WARN: 2, PROTECTED: 3, EXEMPT: 4 }
  const action = counted.filter(p => p.protection !== 'PROTECTED')
    .sort((a, b) => rank[a.protection] - rank[b.protection] || (b.value ?? -1) - (a.value ?? -1))
  let oldestRead: string | null = null
  for (const p of counted) if (p.protection === 'PROTECTED' && p.verifiedAt && (oldestRead == null || p.verifiedAt < oldestRead)) oldestRead = p.verifiedAt
  const byBroker = new Map<string, PositionModel[]>()
  for (const p of counted) byBroker.set(p.broker, [...(byBroker.get(p.broker) || []), p])
  const brokers: BrokerInput[] = [...byBroker.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([broker, ps]) => {
    const prot = ps.filter(p => p.protection === 'PROTECTED')
    const gap = ps.some(p => p.protection === 'GAP'), warn = ps.some(p => p.protection === 'WARN')
    const unk = ps.find(p => p.protection === 'UNKNOWN' || p.protection === 'EXEMPT')
    let oldest: string | null = null
    for (const p of prot) if (p.verifiedAt && (oldest == null || p.verifiedAt < oldest)) oldest = p.verifiedAt
    return { broker, state: gap ? 'GAP' : unk ? 'UNKNOWN' : warn ? 'WARN' : 'OK', counted: ps.length, protectedN: prot.length, oldest,
      cause: gap ? 'Unprotected Position' : unk ? unk.cause : warn ? 'Expired Stop' : null }
  })
  return {
    verdict, counted: counted.length, protectedN: n.PROTECTED, gap: n.GAP, warn: n.WARN, unknown: n.UNKNOWN,
    listedNotCounted: positions.filter(p => p.underFloor).length,
    exempt: positions.filter(p => p.protection === 'EXEMPT' || p.isCash).length,
    action, oldestRead, brokers, cause: null,
  }
}

// ── the four financial measures (PortfolioMeasures@v1, LQ-20261113-3124R) ─────────────────────────────
/** The page reads the projection; it never computes a measure. Three rules, from the operator's Q1 decision
 *  (2026-11-13) and the 3124R contract:
 *    1. a value is drawn only when the wire published it with a status — never defaulted, never summed here;
 *    2. the broker store is the anchor and the Finviz estimate is drawn BESIDE it with its delta and timestamp,
 *       never added into any 'today' figure (`finviz_estimates_are_separate`);
 *    3. a missing block is UNKNOWN with the writer's reason, and GET never computes one (absent -> four UNKNOWN).
 *  The four labels are the projection's own; no screen invents a fifth 'today' number. */
export const MEASURES_CONTRACT = 'PortfolioMeasures@v1'
export const MEASURE_KEYS = ['account_value', 'price_move_estimate', 'account_value_change_1d', 'verified_daily_pnl'] as const
export type MeasureKey = (typeof MEASURE_KEYS)[number]
export const MEASURE_LABELS: Record<MeasureKey, string> = {
  account_value: 'Account value',
  price_move_estimate: 'Estimated price movement of current holdings',
  account_value_change_1d: 'Account value change since prior close',
  verified_daily_pnl: 'Verified daily P&L',
}
/** measures_absent().gap.reason (scripts/lib/portfolio_measures.py, folded by 3124R). Quoted, not paraphrased. */
export const MEASURES_ABSENT_REASON = 'this holdings document was written before the measures were materialized; the writer must run once before the four measures are published (GET never computes)'
export const UNVERIFIED_NOTE = 'A verified figure requires a stored, signed, per-account reconciliation; GET never computes one.'
/** A6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): the closed set of statuses that assert a figure. The writer
 *  (`scripts/lib/portfolio_measures.py`, 3124R) emits exactly these; a future status such as GAP must be added here
 *  deliberately before it can draw a number. */
export const FIGURE_STATUSES: ReadonlySet<string> = new Set(['MEASURED', 'VERIFIED', 'PARTIAL'])

export interface MeasureComponent { key: string; label: string; value: number | null; note: string | null }
export interface MeasureView {
  key: MeasureKey; label: string; value: number | null; status: string
  statusClass: 'ok' | 'warn' | 'neutral' | 'bad'
  text: string; definition: string | null; gap: string | null; asOf: string | null
  estimate: { label: string; value: number | null; delta: number | null; at: string | null; note: string | null } | null
  components: MeasureComponent[]
  reconciles: boolean | null
  candidate: number | null
}
export interface MeasuresModel {
  state: 'LOADING' | 'ABSENT' | 'PRESENT' | 'UNREADABLE'
  contractVersion: string | null
  materialized: boolean
  asOf: string | null
  generatedAt: string | null
  reason: string | null
  basis: string | null
  basisWhy: string | null
  finvizSeparate: boolean
  /** The verified daily P&L is not a stored VERIFIED figure (it is UNKNOWN by contract today). */
  dayUnverified: boolean
  measures: MeasureView[]
}

function measureStatusClass(status: string): MeasureView['statusClass'] {
  if (status === 'MEASURED' || status === 'VERIFIED') return 'ok'
  if (status === 'PARTIAL') return 'warn'
  return 'neutral'
}

function emptyMeasure(key: MeasureKey, status: string, text: string, gap: string | null = null): MeasureView {
  return { key, label: MEASURE_LABELS[key], value: null, status, statusClass: measureStatusClass(status), text,
    definition: null, gap, asOf: null, estimate: null, components: [], reconciles: null, candidate: null }
}

function componentValue(v: unknown): number | null {
  const n = num(v)
  return n == null ? null : n
}
function componentNote(v: unknown): string | null {
  return num(v) == null ? 'UNKNOWN — not zero' : null
}
const COMPONENT_LABELS: Record<string, string> = {
  price_move_estimate: 'Estimated price movement of current holdings',
  closed_today_trade_effect: 'Closed-today trade effect',
  fees_today: 'Fees today',
  income_today: 'Income today',
  external_flows_today: 'External flows today',
}

/** One measure from the wire. No arithmetic: every number is the projection's, or it is absent. */
function measureFrom(key: MeasureKey, m: MeasureWire | undefined, block: MeasuresBlockWire): MeasureView {
  if (!m || typeof m !== 'object') {
    return emptyMeasure(key, 'UNKNOWN', `The measures block carries no ${key}.`,
      `The projection published no ${key}; the page does not compute it.`)
  }
  const publishedStatus = typeof m.status === 'string' && m.status.trim() ? m.status.trim().toUpperCase() : null
  const status = publishedStatus ?? 'UNKNOWN'
  const wireValue = num(m.value)
  // C1 (REVIEW-CAMPAIGN8H-item1-...-cc-deepseek-6, F3): a number is drawn only when the wire published it under a
  // status that asserts a figure. A statusless value — or one the wire itself marks UNKNOWN — is not a figure: it is
  // null here, so it can never be drawn in a row or promoted to the header.
  const value = publishedStatus != null && FIGURE_STATUSES.has(publishedStatus) ? wireValue : null
  const label = (m.label && String(m.label)) || block.labels?.[key] || MEASURE_LABELS[key]
  const gap = m.gap && typeof m.gap === 'object' ? (m.gap.reason ?? null) : null
  const fields: string[] = []
  if (value != null) fields.push(fmtUsd(value, key !== 'account_value'))
  if (publishedStatus == null) fields.push('status not published — not a figure')
  else if (publishedStatus === 'UNKNOWN' && wireValue != null) fields.push('marked UNKNOWN — the wire value is not drawn')
  // A6: any other status outside the closed set is said out loud rather than swallowed by "no figure published".
  else if (value == null && wireValue != null) fields.push(`status ${publishedStatus} does not assert a figure — the wire value is not drawn`)
  if (key === 'account_value' && num(m.rows) != null) fields.push(`${m.rows} rows`)
  if (key === 'price_move_estimate' && m.coverage) {
    const mr = num(m.coverage.measured_rows), ur = num(m.coverage.unknown_rows), rc = num(m.coverage.row_count)
    if (mr != null && rc != null) fields.push(`${mr} of ${rc} rows measured${ur ? `, ${ur} unknown` : ''}`)
  }
  if (key === 'account_value_change_1d' || key === 'verified_daily_pnl') {
    const start = num(m.start?.equity_usd), end = num(m.end?.equity_usd)
    if (start != null || end != null) fields.push(`start ${fmtUsd(start)} → end ${fmtUsd(end)}`)
  }
  if (key === 'verified_daily_pnl' && value == null && num(m.candidate) != null) fields.push(`candidate ${fmtUsd(num(m.candidate), true)} (not verified)`)
  if (status === 'PARTIAL') fields.push('partial: at least one input is missing')
  if (gap) fields.push(gap)
  if (fields.length === 0) fields.push(status === 'UNKNOWN' ? (gap || 'the projection published no value') : 'no figure published')
  const fin = m.finviz_estimate && typeof m.finviz_estimate === 'object' ? m.finviz_estimate : null
  const estimate = fin
    ? { label: fin.label || 'Finviz mark estimate', value: num(fin.total_with_broker_nav) ?? num(fin.value),
        delta: num(fin.delta_vs_broker) ?? num(fin.delta), at: fin.marks_at ?? null,
        note: fin.delta_note || fin.note || null }
    : null
  const components: MeasureComponent[] = []
  const dd = m.drill_down || (key === 'verified_daily_pnl' ? m.known_components : null)
  if (dd && typeof dd === 'object') {
    for (const k of Object.keys(COMPONENT_LABELS)) {
      const raw = (dd as Record<string, unknown>)[k]
      if (raw === undefined) continue
      components.push({ key: k, label: COMPONENT_LABELS[k], value: componentValue(raw), note: componentNote(raw) })
    }
  }
  return {
    key, label, value, status, statusClass: measureStatusClass(status),
    text: fields.join(' · '), definition: m.definition ?? null, gap, asOf: m.as_of ?? null, estimate, components,
    reconciles: typeof m.drill_down?.reconciles === 'boolean' ? m.drill_down.reconciles : null,
    candidate: num(m.candidate),
  }
}

export function measuresModel(read: Read<HoldingsWire>): MeasuresModel {
  const base = { contractVersion: MEASURES_CONTRACT, materialized: false, asOf: null, generatedAt: null, reason: null,
    basis: null, basisWhy: null, finvizSeparate: true, dayUnverified: true }
  if (read.state === 'LOADING') {
    return { ...base, state: 'LOADING', measures: MEASURE_KEYS.map(k => emptyMeasure(k, 'LOADING', 'reading…')) }
  }
  if (read.state !== 'OK') {
    const why = `${read.source}: ${read.error || read.state}`
    return { ...base, state: 'UNREADABLE', reason: why, measures: MEASURE_KEYS.map(k => emptyMeasure(k, 'UNKNOWN', `Holdings not read: ${why}`)) }
  }
  const block = read.data?.measures
  const present = block && typeof block === 'object' && block.materialized !== false
  /** C1: only a value the wire published under a status that asserts a figure counts as a value in the block. */
  const assertsFigure = (m: MeasureWire | undefined): boolean => {
    if (!m || typeof m !== 'object') return false
    const s = typeof m.status === 'string' ? m.status.trim().toUpperCase() : ''
    return FIGURE_STATUSES.has(s) && num(m.value) != null
  }
  const anyValue = !!(present && block!.measures && Object.values(block!.measures).some(assertsFigure))
  if (!present || (String(block!.status || '').toUpperCase() === 'UNKNOWN' && !anyValue)) {
    const reason = block?.gap?.reason || MEASURES_ABSENT_REASON
    return { ...base, state: 'ABSENT', asOf: block?.as_of ?? null, generatedAt: block?.generated_at ?? null, reason,
      basis: block?.basis?.applied ?? null, basisWhy: block?.basis?.why ?? null,
      measures: MEASURE_KEYS.map(k => emptyMeasure(k, 'UNKNOWN', reason, reason)) }
  }
  const measures = MEASURE_KEYS.map(k => measureFrom(k, block!.measures?.[k], block!))
  const v = measures.find(m => m.key === 'verified_daily_pnl')
  return {
    ...base, state: 'PRESENT', contractVersion: block!.contract_version || MEASURES_CONTRACT, materialized: true,
    asOf: block!.as_of ?? null, generatedAt: block!.generated_at ?? null,
    basis: block!.basis?.applied ?? null, basisWhy: block!.basis?.why ?? null,
    finvizSeparate: block!.finviz_estimates_are_separate !== false,
    dayUnverified: !v || v.status !== 'VERIFIED',
    measures,
  }
}

// ── coverage counts (display vocabulary; never changes the verdict) ──────────────────────────────────
export interface CoverageCounts {
  covered: number; partial: number; uncovered: number; planned: number; exempt: number; unverifiable: number
  restingShares: number | null; heldShares: number | null
  /** F4 (REVIEW-CAMPAIGN8H-item1): true only when EVERY eligible row published both quantities. When false, the
   *  share totals are a partial sum and every consumer must say "published", never present them as a total. */
  totalsComplete: boolean
}
export function coverageCounts(ps: PositionModel[]): CoverageCounts {
  const c: CoverageCounts = { covered: 0, partial: 0, uncovered: 0, planned: 0, exempt: 0, unverifiable: 0, restingShares: null, heldShares: null, totalsComplete: false }
  let rest = 0, held = 0, restKnown = false, heldKnown = false, eligible = 0, both = 0
  for (const p of ps) {
    const cov = p.coverage
    if (cov.category === 'COVERED') c.covered++
    else if (cov.category === 'PARTIAL') c.partial++
    else if (cov.category === 'PLANNED_ONLY') c.planned++
    else if (cov.category === 'EXEMPT') c.exempt++
    else if (cov.category === 'UNVERIFIABLE') c.unverifiable++
    else c.uncovered++
    if (cov.category !== 'EXEMPT' && cov.category !== 'UNVERIFIABLE' && !p.isCash) {
      eligible++
      if (cov.restingShares != null) { rest += cov.restingShares; restKnown = true }
      if (cov.heldShares != null) { held += cov.heldShares; heldKnown = true }
      if (cov.restingShares != null && cov.heldShares != null) both++
    }
  }
  c.restingShares = restKnown ? rest : null
  c.heldShares = heldKnown ? held : null
  c.totalsComplete = eligible > 0 && both === eligible
  return c
}

// ── CSV export (client-side; served columns only, no computed P&L) ───────────────────────────────────
export const CSV_COLUMNS = ['symbol', 'account', 'broker', 'held_shares', 'resting_stop_shares', 'coverage', 'protection',
  'value_usd', 'day_pct', 'stop_price', 'stop_source', 'stop_order_id', 'verified_at', 'reason'] as const
function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
export function holdingsCsv(ps: PositionModel[]): string {
  const lines = [CSV_COLUMNS.join(',')]
  for (const p of ps) {
    lines.push([
      p.symbol, p.account, p.broker, p.shares, p.restingShares, p.coverage.category, p.protection,
      p.value, p.dayPct, p.stopPrice, p.raw.stop_source ?? p.source, p.raw.stop_order_id ?? p.raw.order_id ?? null,
      p.verifiedAt, p.reason,
    ].map(csvCell).join(','))
  }
  return lines.join('\r\n')
}

export interface P0Item { category: string; detail: string }
export function p0Items(read: Read<HoldingsWire>, prot: ProtectionModel): P0Item[] | null {
  if (read.state !== 'OK') return null  // cannot be counted; never "0"
  const out: P0Item[] = []
  const gaps = prot.action.filter(p => p.protection === 'GAP')
  if (gaps.length) out.push({ category: 'Unprotected Position', detail: `${gaps.map(p => p.symbol).join(', ')}: no resting stop in a good read` })
  // R2: the last-known GAP and its P0 row stay visible while the verdict reads UNKNOWN.
  const lastKnown = prot.action.filter(p => p.lastKnownGap)
  if (lastKnown.length) out.push({ category: 'Unprotected Position (stale read)', detail: `${lastKnown.map(p => p.symbol).join(', ')}: last read showed no resting stop; the read is past its freshness limit` })
  // C6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): a P0 comes only from a finding the count contract PUBLISHED.
  // `agree === false` is the cross-scope flag — false on every real book — and raising a P0 from it put "1 P0" on
  // a healthy, fully protected page (and in the served v002 build).
  const pcRows = read.data?.position_counts
  const finding = Array.isArray(pcRows?.findings) ? pcRows!.findings!.find(f => f && (f.detail || f.code)) : null
  if (finding) {
    out.push({ category: 'Position Count Mismatch', detail: String(finding.detail || finding.code) })
  }
  return out
}

// ── status rows ───────────────────────────────────────────────────────────────────────────────────────
export type StatusState = 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING' | 'WARN'
export interface StatusRow { id: string; name: string; state: StatusState | string; text: string; cause?: string; needsBackend?: boolean }
export const LIMITS = { positionsMs: 60 * 60_000, pricesMs: 30 * 60_000, alertsMs: 15 * 60_000 }

export function statusRows(hr: Read<HoldingsWire>, ir: Read<IncidentsWire>, positions: PositionModel[], nowMs: number): StatusRow[] {
  const rows: StatusRow[] = []
  const w = hr.data
  // Value/Today are NOT drawn here: the four measures block (measuresModel) owns every financial figure, so the page
  // can never show a store number beside a projection number as if they were two candidates. This row is the
  // positions-store read health only (the mock's "Value OK · positions 28 m old").
  if (hr.state !== 'OK') {
    const st = hr.state
    rows.push({ id: 'row-value', name: 'Positions read', state: st, text: st === 'LOADING' ? 'reading…' : `${hr.error || st}`, cause: st === 'LOADING' ? undefined : `Source: ${API.holdings}` })
  } else {
    const a = ageMs(w?.positions_as_of, nowMs)
    const vs: StatusState = a == null ? 'UNKNOWN' : a > LIMITS.positionsMs ? 'STALE' : 'OK'
    rows.push({ id: 'row-value', name: 'Positions read', state: vs,
      text: a == null ? 'no positions timestamp in the read' : `positions ${fmtAge(a)} old · limit 60 m`,
      cause: vs === 'OK' ? undefined : 'Cause: Positions Sync · Source: positions store · Owner: position sync lane' })
  }
  rows.push({ id: 'row-risk', name: 'Risk', state: 'UNKNOWN', text: 'pending decision: no approved risk-score definition (G7)', needsBackend: true })
  if (hr.state === 'OK') {
    const priced = positions.filter(p => !p.isCash)
    const stale = priced.filter(p => p.priceStale === true)
    const unknownFresh = priced.filter(p => p.priceStale == null && !p.raw.price_as_of)
    const qa = ageMs(hr.data?.quote_as_of, nowMs)
    const st: StatusState = stale.length ? 'STALE' : unknownFresh.length || qa == null ? 'UNKNOWN' : qa > LIMITS.pricesMs ? 'STALE' : 'OK'
    rows.push({ id: 'row-prices', name: 'Prices', state: st,
      text: stale.length ? `${stale.length} of ${priced.length} stale · quotes ${fmtAge(qa)} old · limit 30 m`
        : `${priced.length} priced · quotes ${fmtAge(qa)} old · limit 30 m`,
      cause: stale.length ? `Cause: Market Feed (${stale.slice(0, 4).map(p => p.symbol).join(', ')}${stale.length > 4 ? '…' : ''}) · Source: quote cache · Owner: repricer lane` : undefined })
  } else {
    rows.push({ id: 'row-prices', name: 'Prices', state: hr.state, text: hr.state === 'LOADING' ? 'reading…' : 'no read' })
  }
  if (ir.state === 'OK') {
    const c = ir.data?.counts
    const a = ageMs(ir.data?.served_at || ir.at, nowMs)
    if (!c || (c.P0 == null && c.P1 == null)) rows.push({ id: 'row-alerts', name: 'Alerts', state: 'UNKNOWN', text: 'no counts in the read' })
    else rows.push({ id: 'row-alerts', name: 'Alerts', state: (c.P0 ?? 0) > 0 ? 'WARN' : 'OK',
      text: `${c.P0 ?? 0} P0 · ${c.P1 ?? 0} P1 open (all pages) · ${fmtAge(a)} old · limit 15 m` })
  } else {
    rows.push({ id: 'row-alerts', name: 'Alerts', state: ir.state, text: ir.state === 'LOADING' ? 'reading…' : `${ir.error || ir.state}` })
  }
  return rows
}

// ── filters ───────────────────────────────────────────────────────────────────────────────────────────
export type HoldingsFilter = 'all' | 'unprotected' | 'partial' | 'planned' | 'unknown' | 'exempt' | 'under100'
export function filterPositions(ps: PositionModel[], f: HoldingsFilter, account: string): PositionModel[] {
  return ps.filter(p => (account === 'all' || p.account === account) && (
    f === 'all' ? true
      : f === 'unprotected' ? p.counted && (p.protection === 'GAP' || p.protection === 'WARN')
        : f === 'partial' ? p.coverage.category === 'PARTIAL'
          : f === 'planned' ? p.coverage.category === 'PLANNED_ONLY'
            : f === 'unknown' ? p.counted && p.protection === 'UNKNOWN'
              : f === 'exempt' ? p.coverage.category === 'EXEMPT'
                : p.underFloor))
}

/** The classic stop desk link carries the full position identity (2026-11-14 campaign): symbol, the account key
 *  both as `account` (the lot the hub focuses) and `acct` (its account filter), the broker and the position key.
 *  The Stop Management tab consumes symbol+acct; the extra broker/position keys name the same row for the desk. */
export function stopDeskHref(p: PositionModel): string {
  const q = new URLSearchParams()
  q.set('tab', 'Stop Management')
  q.set('symbol', p.symbol)
  q.set('account', p.accountKey)
  q.set('acct', p.accountKey)
  q.set('broker', p.broker)
  q.set('position', p.key)
  q.set('drawerTab', 'stops')
  return `/portfolio-classic?${q.toString()}`
}

// ── position detail (value provenance, operator focus 2) ─────────────────────────────────────────────
export interface FieldRow { field: string; value: string; age: string; provenance: string; needsBackend?: boolean }
export function positionFields(p: PositionModel, w: HoldingsWire | null, nowMs: number): FieldRow[] {
  const h = p.raw
  const sharesAt = h.shares_synced_at || w?.positions_as_of || null
  const priceAt = h.price_as_of || w?.quote_as_of || null
  const valueAt = h.market_value_as_of || w?.valuation_as_of || null
  const cov = p.coverage
  return [
    { field: 'Shares', value: fmtShares(p.shares), age: fmtAge(ageMs(sharesAt, nowMs)), provenance: `Source: positions store · Writer: position sync lane · as of ${fmtET(sharesAt, true)}` },
    { field: 'Resting stop', value: cov.restingShares == null ? 'not published' : `${fmtShares(cov.restingShares)} of ${fmtShares(cov.heldShares)} held`,
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: `Source: ${p.source} · stop quantity from the broker read (stop_qty)` },
    { field: 'Coverage', value: `${cov.label}${cov.restingShares != null && cov.heldShares != null ? ` · ${fmtShares(cov.restingShares)} of ${fmtShares(cov.heldShares)} shares` : ''}`,
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: cov.detail },
    { field: 'Identity', value: `${p.accountKey} · ${p.broker}`, age: '—',
      provenance: `Position: ${p.symbol}${p.raw.stop_order_id || p.raw.order_id ? ` · order ${p.raw.stop_order_id || p.raw.order_id}` : ' · no order id in the read'}` },
    { field: 'Price', value: p.price == null ? '—' : `$${p.price.toFixed(2)}`, age: fmtAge(ageMs(priceAt, nowMs)),
      provenance: `Source: ${h.price_source || h.quote_source || 'not named in the read'} · Writer: repricer lane${p.priceStale ? ' · STALE' : ''}` },
    { field: 'Value', value: fmtUsd(p.value), age: fmtAge(ageMs(valueAt, nowMs)),
      provenance: `Source: ${h.market_value_source || 'shares × price'} · per-field writer/refresh not served (G5)`, needsBackend: true },
    { field: 'Cost', value: fmtUsd(num(h.cost_basis)), age: '—', provenance: `Source: ${h.cost_basis_source || 'not named in the read'}${h.basis_status ? ` · ${h.basis_status}` : ''}` },
    { field: 'Day change', value: p.dayUsd == null ? 'UNKNOWN' : `${fmtUsd(p.dayUsd, true)} (${fmtPct(p.dayPct)})`, age: fmtAge(ageMs(priceAt, nowMs)),
      provenance: `Served value vs prior close${num(h.prior_close) != null ? ` $${num(h.prior_close)!.toFixed(2)}` : ''} · Source: quote cache · the page computes no P&L` },
    { field: 'Stop', value: p.protection === 'PROTECTED' ? p.chip : p.protection === 'UNKNOWN' ? 'UNKNOWN' : p.protection === 'EXEMPT' ? 'exempt' : cov.chip,
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: `Source: ${p.source} · Writer: stop read lane · ${p.reason}` },
    { field: 'Risk', value: 'PENDING DECISION', age: '—', provenance: 'no approved risk-score definition (G7); nothing is scored here', needsBackend: true },
  ]
}

// ── audit categories (lifecycle labels need the validation_events store: NEEDS BACKEND) ──────────────
export interface AuditCategory { category: string; count: number; symbols: string[]; source: string; owner: string }
export function auditCategories(prot: ProtectionModel, p0: P0Item[] | null): AuditCategory[] {
  const out: AuditCategory[] = []
  const gap = prot.action.filter(p => p.protection === 'GAP'), warn = prot.action.filter(p => p.protection === 'WARN')
  const unk = prot.action.filter(p => p.protection === 'UNKNOWN')
  if (gap.length) out.push({ category: 'Unprotected Position', count: gap.length, symbols: gap.map(p => p.symbol), source: 'stop store', owner: STOP_OWNER })
  if (warn.length) out.push({ category: 'Expired Stop', count: warn.length, symbols: warn.map(p => p.symbol), source: 'stop store', owner: STOP_OWNER })
  if (unk.length) out.push({ category: 'Protection Unknown', count: unk.length, symbols: unk.map(p => p.symbol), source: 'stop store', owner: STOP_OWNER })
  for (const i of p0 || []) if (i.category === 'Position Count Mismatch') out.push({ category: i.category, count: 1, symbols: [], source: 'positions store', owner: 'position sync lane' })
  return out
}

// ── Since your last visit: the anchor (portfolio.last_seen, LQ-2467) ─────────────────────────────────
/** The anchor is readable today. The change LIST is not: it needs the change store (LQ-2143), so the block states
 *  the window it would cover and marks the list NEEDS BACKEND. A visit is recorded only after the page's reads
 *  settle, and the server stamps it (scripts/lib/home_last_seen.py) — the client never sends a time. */
export interface LastSeenReadWire {
  status?: string; window_basis?: string; last_visit_recorded?: boolean; fallback_window_hours?: number; fallback_text?: string
  seen_at?: string | null; previous_seen_at?: string | null; age_sec?: number | null; device?: string | null; schema?: string; reason?: string
}
export interface LastSeenWire { ok?: boolean; key?: string; value?: unknown; updated_at?: string | null; read?: LastSeenReadWire | null }
export type VisitRecord = 'PENDING' | 'RECORDED' | 'REFUSED' | 'FAILED'
export interface SinceVisitModel {
  status: 'RECORDED' | 'NOT_RECORDED' | 'UNKNOWN' | 'LOADING'
  windowBasis: string; windowText: string
  seenAt: string | null; previousSeenAt: string | null; device: string | null; reason: string | null
  changesNeedBackend: true
}
export function sinceVisitModel(read: Read<LastSeenWire>): SinceVisitModel {
  const base = { windowBasis: 'fallback_24h', seenAt: null, previousSeenAt: null, device: null, reason: null, changesNeedBackend: true as const }
  if (read.state === 'LOADING') return { ...base, status: 'LOADING', windowText: 'reading…' }
  if (read.state !== 'OK') return { ...base, status: 'UNKNOWN', reason: `${read.source}: ${read.error || read.state}`,
    windowText: `The last-visit read did not complete (${read.error || read.state}); the window is unknown.` }
  const r = read.data?.read
  if (!r || typeof r !== 'object') return { ...base, status: 'UNKNOWN', reason: 'the prefs route returned no reading',
    windowText: 'The prefs route returned no reading; the window is unknown.' }
  const raw = String(r.status || 'UNKNOWN').toUpperCase()
  const status: SinceVisitModel['status'] = raw === 'RECORDED' || raw === 'NOT_RECORDED' ? raw : 'UNKNOWN'
  const windowBasis = String(r.window_basis || 'fallback_24h')
  const seenAt = r.seen_at ?? null
  const age = num(r.age_sec)
  const windowText = status === 'RECORDED' && seenAt
    ? `Since your last visit ${fmtET(seenAt, true)} ET${age != null ? ` (${fmtAge(age * 1000)} ago)` : ''}`
    : status === 'NOT_RECORDED' ? (r.fallback_text || 'Your last visit is not recorded; the window is the last 24 h.')
      : `The last-visit record is unreadable (${r.reason || 'no valid seen_at'}); the window is unknown.`
  return { status, windowBasis, windowText, seenAt, previousSeenAt: r.previous_seen_at ?? null,
    device: r.device ?? null, reason: r.reason ?? null, changesNeedBackend: true }
}
export function deviceOf(width: number): 'phone' | 'desktop' { return width < 768 ? 'phone' : 'desktop' }
/** Stamp this visit (same route and gate as Home): server owns the times; only the device is sent. */
export async function recordPortfolioVisit(width: number, fetchImpl: typeof fetch = fetch): Promise<VisitRecord> {
  try {
    const r = await fetchImpl(API.prefs, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: PORTFOLIO_LAST_SEEN_KEY, value: { device: deviceOf(width) } }),
    })
    if (r.status === 401 || r.status === 403) return 'REFUSED'
    if (!r.ok) return 'FAILED'
    const body = (await r.json().catch(() => null)) as { ok?: boolean } | null
    return body && body.ok === false ? 'REFUSED' : 'RECORDED'
  } catch {
    return 'FAILED'
  }
}

// ── gate evidence (no served portfolio gate store: LQ-2141) ──────────────────────────────────────────
/** Each gate the design expects, with the evidence THIS page can see and what the served gate would need. The
 *  evidence is page-computed and labelled as such; a gate is never reported open or closed without the store. */
export interface GateEvidence {
  gate: string; blocks: string; blocksTrading: boolean; threshold: string; pageEvidence: string
  servedStatus: 'NOT AVAILABLE'; needs: string; owner: string
}
export function gateEvidence(prot: ProtectionModel, measures: MeasuresModel, positions: PositionModel[],
  holdings: HoldingsWire | null = null): GateEvidence[] {
  const cov = coverageCounts(positions)
  const accounts = new Set(positions.filter(p => !p.isCash).map(p => p.broker))
  // A7 (REVIEW-CAMPAIGN8H-item1-fix): a broker whose rows are all EXEMPT carries no counted position, so it must not
  // read as covered by the stop read this page observed. Counted brokers are named against the non-cash set.
  const countedBrokers = new Set(positions.filter(p => p.counted).map(p => p.broker))
  const priced = positions.filter(p => !p.isCash)
  const stale = priced.filter(p => p.priceStale === true).length
  // The holdings document does carry the position-count block; a gate must not claim it cannot see what the read
  // published (UI may not contradict reality). C5: compare LIKE WITH LIKE — the block's holdings.all_rows scope
  // against the rows this read drew — quote its own summary, name the headline as a named scope, and never read the
  // cross-scope `agree` flag as a comparison (it is false on every real book by construction).
  const pc = holdings?.position_counts
  const scopeCount = (k: string): number | null => {
    const s = pc?.scopes
    return s && typeof s[k] === 'number' ? s[k] : null
  }
  const allRows = num(pc?.all_rows) ?? scopeCount('holdings.all_rows')
  const headline = num(pc?.position_count)
  const headlineScope = typeof pc?.primary_scope === 'string' && pc.primary_scope ? pc.primary_scope : 'holdings.non_cash_over_100'
  const blockSummary = typeof pc?.summary === 'string' && pc.summary.trim() ? pc.summary.trim() : null
  const countEvidence = pc == null
    ? 'the position count block is not in this read'
    : allRows == null
      ? `the count block names no all-rows scope; ${positions.length} rows are drawn in this read and nothing here compares them`
      : [
        `the block's holdings.all_rows scope counts ${allRows}; this read drew ${positions.length} row${positions.length === 1 ? '' : 's'}; ${allRows === positions.length ? 'they match' : 'they differ'}`,
        headline != null ? `the block's headline ${headline} is its ${headlineScope} scope` : null,
        blockSummary ? `its own summary: ${blockSummary}` : null,
      ].filter(Boolean).join(' · ')
  return [
    { gate: 'Stop read covers every broker', blocks: 'Protection: OK', blocksTrading: true, threshold: 'every broker read inside 900 s (session) / 72 h (closed)', owner: 'stops lane',
      pageEvidence: prot.counted == null ? 'no counted book was read' : `${prot.counted} counted position${prot.counted === 1 ? '' : 's'} in ${countedBrokers.size} of ${accounts.size} broker${accounts.size === 1 ? '' : 's'} with non-cash rows; ${prot.protectedN ?? '—'} protected, ${cov.partial} partial`,
      servedStatus: 'NOT AVAILABLE', needs: 'a served protection rollup with a per-broker read state (G2/G3)' },
    { gate: 'Price check · 5 sessions clean', blocks: 'VALIDATED on Price Mismatch', blocksTrading: false, threshold: '5 sessions, not one read', owner: 'repricer lane',
      pageEvidence: `${stale} stale of ${priced.length} priced rows in this read; one read cannot show a five-session window`,
      servedStatus: 'NOT AVAILABLE', needs: 'a served check result with a five-session window (gate store, LQ-2141)' },
    { gate: 'Position count agrees', blocks: 'VALIDATED on Count Mismatch', blocksTrading: false, threshold: "the rows drawn this read = the count block's holdings.all_rows scope; no published tolerance", owner: 'position sync lane',
      pageEvidence: countEvidence,
      servedStatus: 'NOT AVAILABLE', needs: 'the gate store row for count agreement (the page can see the block, not the gate)' },
    { gate: 'Value reconciles to the accounting anchor', blocks: 'VALIDATED on Value Mismatch', blocksTrading: false, threshold: 'a stored signed reconciliation', owner: 'portfolio lane',
      pageEvidence: measures.state === 'PRESENT'
        ? `account value ${measures.measures.find(m => m.key === 'account_value')?.status ?? 'UNKNOWN'}; day figures ${measures.dayUnverified ? 'UNVERIFIED' : 'verified'}`
        : 'no measures block in this holdings document',
      servedStatus: 'NOT AVAILABLE', needs: 'a stored signed reconciliation (measure 4) plus the gate store row' },
  ]
}

// ── risk score: an isolated pending decision (G7) ────────────────────────────────────────────────────
/** RISK-SCORE-SPEC-20261111 is STATUS: PROPOSED, awaiting operator sign-off; nothing is implemented. This page
 *  therefore draws no score, no letter and no colour for risk, and says why in one place. */
export const RISK_SCORE = {
  status: 'PENDING DECISION' as const,
  spec: 'RISK-SCORE-SPEC-20261111 (design/pages/portfolio/v002)',
  text: 'The risk score is proposed, not approved: no definition has been signed off and no backend computes one. '
    + 'The page draws no number and no band, and the holdings column stays empty until an approved definition exists.',
}

