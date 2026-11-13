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
} as const

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
  protection_state?: string | null; protection?: ProtectionWire | null
}
export interface HoldingsWire {
  holdings?: HoldingWire[] | null; total_value?: number | null; today_change?: number | null
  positions_as_of?: string | null; valuation_as_of?: string | null; quote_as_of?: string | null
  position_counts?: { agree?: boolean; position_count?: number; summary?: string; findings?: { code?: string; detail?: string }[] } | null
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
  key: string; symbol: string; account: string; broker: string
  shares: number | null; value: number | null; price: number | null; dayPct: number | null; dayUsd: number | null
  isCash: boolean; counted: boolean; underFloor: boolean; unpriced: boolean
  /** R2: the backend said GAP but its stop read is past the freshness limit; the row reads UNKNOWN, the GAP stays listed. */
  lastKnownGap: boolean
  protection: RowProtection; chip: string; reason: string; cause: string | null; source: string; verifiedAt: string | null
  stopPrice: number | null; priceStale: boolean | null
  raw: HoldingWire
}

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
    return {
      key: `${h.account_id || h.account || i}:${symbol}`, symbol, account, broker: String(h.broker || '—'),
      shares: num(h.shares) ?? num(h.quantity), value, price: num(h.price), dayPct: num(h.day_change_pct), dayUsd: num(h.day_change),
      isCash, counted, unpriced: unpriced && !isCash, underFloor: pr.protection !== 'EXEMPT' && !isCash && !counted,
      ...pr, priceStale: h.price_stale ?? null, raw: h,
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

// ── P0 (DECISIONS: Unprotected Position, Protection Gap, position count mismatch, missing read) ──────
export interface P0Item { category: string; detail: string }
export function p0Items(read: Read<HoldingsWire>, prot: ProtectionModel): P0Item[] | null {
  if (read.state !== 'OK') return null  // cannot be counted; never "0"
  const out: P0Item[] = []
  const gaps = prot.action.filter(p => p.protection === 'GAP')
  if (gaps.length) out.push({ category: 'Unprotected Position', detail: `${gaps.map(p => p.symbol).join(', ')}: no resting stop in a good read` })
  // R2: the last-known GAP and its P0 row stay visible while the verdict reads UNKNOWN.
  const lastKnown = prot.action.filter(p => p.lastKnownGap)
  if (lastKnown.length) out.push({ category: 'Unprotected Position (stale read)', detail: `${lastKnown.map(p => p.symbol).join(', ')}: last read showed no resting stop; the read is past its freshness limit` })
  const pc = read.data?.position_counts
  if (pc && pc.agree === false) {
    out.push({ category: 'Position Count Mismatch', detail: pc.findings?.[0]?.detail || pc.summary || 'position counts disagree' })
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
  if (hr.state !== 'OK') {
    const st = hr.state
    rows.push({ id: 'row-value', name: 'Value', state: st, text: st === 'LOADING' ? 'reading…' : `${hr.error || st}`, cause: st === 'LOADING' ? undefined : `Source: ${API.holdings}` })
    rows.push({ id: 'row-today', name: 'Today', state: st, text: st === 'LOADING' ? 'reading…' : 'no read' })
  } else {
    const a = ageMs(w?.positions_as_of, nowMs)
    const v = num(w?.total_value)
    const vs: StatusState = v == null || a == null ? 'UNKNOWN' : a > LIMITS.positionsMs ? 'STALE' : 'OK'
    rows.push({ id: 'row-value', name: 'Value', state: vs,
      text: v == null ? 'no total in the read' : `${fmtUsd(v)} · positions ${fmtAge(a)} old · limit 60 m`,
      cause: vs === 'OK' ? undefined : 'Cause: Positions Sync · Source: positions store · Owner: position sync lane' })
    const t = num(w?.today_change)
    rows.push({ id: 'row-today', name: 'Today', state: t == null ? 'UNKNOWN' : 'OK',
      text: t == null ? 'no day-change value in the read' : `${fmtUsd(t, true)} · ${fmtET(w?.quote_as_of)}` })
  }
  rows.push({ id: 'row-risk', name: 'Risk', state: 'UNKNOWN', text: 'risk score not defined yet (G7)', needsBackend: true })
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
export type HoldingsFilter = 'all' | 'unprotected' | 'unknown' | 'under100'
export function filterPositions(ps: PositionModel[], f: HoldingsFilter, account: string): PositionModel[] {
  return ps.filter(p => (account === 'all' || p.account === account) && (
    f === 'all' ? true
      : f === 'unprotected' ? p.counted && (p.protection === 'GAP' || p.protection === 'WARN')
        : f === 'unknown' ? p.counted && p.protection === 'UNKNOWN'
          : p.underFloor))
}

// ── position detail (value provenance, operator focus 2) ─────────────────────────────────────────────
export interface FieldRow { field: string; value: string; age: string; provenance: string; needsBackend?: boolean }
export function positionFields(p: PositionModel, w: HoldingsWire | null, nowMs: number): FieldRow[] {
  const h = p.raw
  const sharesAt = h.shares_synced_at || w?.positions_as_of || null
  const priceAt = h.price_as_of || w?.quote_as_of || null
  const valueAt = h.market_value_as_of || w?.valuation_as_of || null
  return [
    { field: 'Shares', value: fmtShares(p.shares), age: fmtAge(ageMs(sharesAt, nowMs)), provenance: `Source: positions store · Writer: position sync lane · as of ${fmtET(sharesAt, true)}` },
    { field: 'Price', value: p.price == null ? '—' : `$${p.price.toFixed(2)}`, age: fmtAge(ageMs(priceAt, nowMs)),
      provenance: `Source: ${h.price_source || h.quote_source || 'not named in the read'} · Writer: repricer lane${p.priceStale ? ' · STALE' : ''}` },
    { field: 'Value', value: fmtUsd(p.value), age: fmtAge(ageMs(valueAt, nowMs)),
      provenance: `Source: ${h.market_value_source || 'shares × price'} · per-field writer/refresh not served (G5)`, needsBackend: true },
    { field: 'Cost', value: fmtUsd(num(h.cost_basis)), age: '—', provenance: `Source: ${h.cost_basis_source || 'not named in the read'}${h.basis_status ? ` · ${h.basis_status}` : ''}` },
    { field: 'Today', value: p.dayUsd == null ? '—' : `${fmtUsd(p.dayUsd, true)} (${fmtPct(p.dayPct)})`, age: fmtAge(ageMs(priceAt, nowMs)),
      provenance: `Computed vs prior close${num(h.prior_close) != null ? ` $${num(h.prior_close)!.toFixed(2)}` : ''} · Source: quote cache` },
    { field: 'Stop', value: p.protection === 'PROTECTED' ? p.chip : p.protection === 'UNKNOWN' ? 'UNKNOWN' : p.protection === 'EXEMPT' ? 'exempt' : 'none resting',
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: `Source: ${p.source} · Writer: stop read lane · ${p.reason}` },
    { field: 'Risk', value: 'UNKNOWN', age: '—', provenance: 'no source today (G7)', needsBackend: true },
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
