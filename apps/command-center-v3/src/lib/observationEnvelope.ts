/**
 * One observation envelope per semantic question.
 *
 * The Command Center's stale-date defect was never a single wrong number. It was
 * a *current* value rendered beside an *unrelated* date, with a third component
 * computing its own age in a third unit. Backend Phase 1B proved the server side:
 * `overview()` builds one payload from four stores, and only one of them is
 * synchronised to the served root (see outputs/claude-backend/
 * HOME_STALE_BACKEND_TRACE.md, finding F1). This module is the client-side half
 * of the fix: a value, its clock, and its freshness travel together or they do
 * not render as a fact.
 *
 * Four distinct clocks, never collapsed into one "updated" word:
 *
 *   businessDate  the trading/session calendar date the observation belongs to.
 *                 A DATE, not an instant. Never local midnight -- see
 *                 businessDateToSessionInstant below.
 *   observedAt    when the provider/upstream actually observed the value.
 *   lastRefreshAt when our side last SUCCEEDED in refreshing it.
 *   receivedAt    when this browser received these bytes (transport receipt).
 *
 * A 304 or a retained last-good body updates `receivedAt` and nothing else.
 * That is the whole point: transport liveness is not data freshness, and the
 * old surfaces conflated them.
 */

/** Server-authored freshness verdict. The client never recomputes this. */
export type FreshnessStatus = 'FRESH' | 'STALE' | 'UNKNOWN'

/**
 * Transport/composition state. Ordered by severity; `worstTransport` relies on
 * this order, so keep it ascending.
 */
export type TransportState =
  | 'OK'
  | 'RETAINED'   // served from last-good after a failed/304 refresh
  | 'FALLBACK'   // a secondary producer supplied the value
  | 'PARTIAL'    // envelope incomplete -- some fields absent
  | 'UNKNOWN'    // we cannot tell; never render as a fact
  | 'ERROR'      // transport or producer failed outright

const SEVERITY: Record<TransportState, number> = {
  OK: 0, RETAINED: 1, FALLBACK: 2, PARTIAL: 3, UNKNOWN: 4, ERROR: 5,
}

export type ObservationEnvelope<T = unknown> = {
  /**
   * Identity of the observation this value came from. Value, clocks and
   * freshness share it. Two fields with different identities must NOT be
   * rendered as one coherent fact -- see `coalesceEnvelopes`.
   */
  identity: string
  /** Which endpoint + response field produced `value`. Rendered, not implied. */
  sourceLabel: string
  value: T | null
  businessDate: string | null      // 'YYYY-MM-DD'
  observedAt: string | null        // ISO-8601 with zone
  lastRefreshAt: string | null     // ISO-8601 with zone
  receivedAt: string | null        // ISO-8601 with zone
  freshness: FreshnessStatus
  transport: TransportState
  /** Operator-facing note; null when nothing needs saying. */
  note: string | null
}

const ET = 'America/New_York'

/**
 * Convert a business date to the instant of that session's close in the
 * MARKET's zone, independent of the host's zone.
 *
 * The bug this replaces: `new Date('2026-09-01T12:00:00')` (BookTreemap) and
 * `new Date('2026-09-01T00:00:00')` (surfaceFreshness) both bind to the
 * BROWSER's zone. The same payload then dates differently in Los Angeles and
 * Frankfurt, and a date-only value silently acquires a time it never had.
 *
 * We anchor to 16:00 America/New_York -- the session close the business date
 * actually refers to -- and resolve the correct UTC instant by measuring the
 * zone offset for that specific date (so DST is handled without a table).
 */
export function businessDateToSessionInstant(
  businessDate: string,
  hourET = 16,
): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate)) return null
  const [y, m, d] = businessDate.split('-').map(Number)
  if (!y || !m || !d) return null
  // First guess: treat the wall clock as UTC, then correct by the measured
  // offset at that instant. One correction pass is sufficient because the
  // offset is locally constant except within the DST transition hour, which
  // 16:00 never falls inside for US markets.
  const guess = Date.UTC(y, m - 1, d, hourET, 0, 0)
  const offsetMin = etOffsetMinutes(new Date(guess))
  const corrected = guess + offsetMin * 60_000
  const dt = new Date(corrected)
  return Number.isNaN(dt.getTime()) ? null : dt
}

/**
 * The market-session calendar date for an instant, as 'YYYY-MM-DD' in ET.
 *
 * Business dates must be compared as DATES in the market's zone. Decomposing a
 * Date with getFullYear()/getMonth()/getDate() reads the HOST's calendar, so at
 * 16:50Z a Tokyo browser is already on tomorrow and yesterday's scan appears
 * "prior" -- a false stale badge produced entirely by the reader's location.
 */
export function etCalendarDate(at: Date): string {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: ET, year: 'numeric', month: '2-digit', day: '2-digit',
  })
  return fmt.format(at)   // en-CA yields YYYY-MM-DD
}

/** Minutes to ADD to an ET wall-clock reading to reach UTC (e.g. 240 in EDT). */
function etOffsetMinutes(at: Date): number {
  // Intl gives us the ET wall clock for a known instant; the difference between
  // that reading and the instant is the offset. No host-zone dependency.
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: ET, hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
  const parts = Object.fromEntries(
    fmt.formatToParts(at).filter(p => p.type !== 'literal').map(p => [p.type, p.value]),
  ) as Record<string, string>
  const asUTC = Date.UTC(
    Number(parts.year), Number(parts.month) - 1, Number(parts.day),
    Number(parts.hour === '24' ? '00' : parts.hour), Number(parts.minute), Number(parts.second),
  )
  return Math.round((at.getTime() - asUTC) / 60_000)
}

/**
 * Human label for a business date. Explicitly says it is a session date, so a
 * reader never reads it as "last updated".
 */
export function formatBusinessDate(businessDate: string | null): string {
  return businessDate ? `session ${businessDate}` : 'session UNDATED'
}

/**
 * Prefer the backend canonical observation block when present.
 * Maps server surface_status (FRESH|STALE|UNKNOWN|…) onto the client enum;
 * fails closed to UNKNOWN for any unrecognised or absent verdict.
 */
export function freshnessFromOverviewObservation(
  observation: { surface_status?: string | null } | null | undefined,
  fallback?: FreshnessStatus,
): FreshnessStatus {
  const raw = (observation?.surface_status ?? '').toString().trim().toUpperCase()
  if (raw === 'FRESH' || raw === 'STALE' || raw === 'UNKNOWN') return raw
  return fallback ?? 'UNKNOWN'
}

/** Build an envelope, failing closed on absence. */
export function makeEnvelope<T>(input: {
  identity: string
  sourceLabel: string
  value: T | null | undefined
  businessDate?: string | null
  observedAt?: string | null
  lastRefreshAt?: string | null
  receivedAt?: string | null
  freshness?: FreshnessStatus | null
  transport?: TransportState
  note?: string | null
}): ObservationEnvelope<T> {
  const value = input.value === undefined ? null : input.value
  const businessDate = normDate(input.businessDate)
  const freshness: FreshnessStatus = input.freshness ?? 'UNKNOWN'
  let transport: TransportState = input.transport ?? 'OK'
  let note = input.note ?? null

  // Fail closed. A value with no clock at all is not a fact we may render as
  // current; it is PARTIAL and must say so.
  if (value !== null && !businessDate && !input.observedAt && !input.lastRefreshAt) {
    if (SEVERITY[transport] < SEVERITY.PARTIAL) transport = 'PARTIAL'
    note = note ?? 'value has no clock'
  }
  if (value === null && transport === 'OK') {
    transport = 'UNKNOWN'
    note = note ?? 'value absent'
  }
  return {
    identity: input.identity,
    sourceLabel: input.sourceLabel,
    value,
    businessDate,
    observedAt: normIso(input.observedAt),
    lastRefreshAt: normIso(input.lastRefreshAt),
    receivedAt: normIso(input.receivedAt),
    freshness,
    transport,
    note,
  }
}

function normDate(v: unknown): string | null {
  if (typeof v !== 'string') return null
  const s = v.trim()
  if (!s) return null
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/)
  return m ? m[1] : null
}

function normIso(v: unknown): string | null {
  if (typeof v !== 'string') return null
  const s = v.trim()
  return s ? s : null
}

/** The more severe of two transport states. */
export function worstTransport(a: TransportState, b: TransportState): TransportState {
  return SEVERITY[a] >= SEVERITY[b] ? a : b
}

/**
 * Combine envelopes that a card intends to render as ONE coherent fact.
 *
 * If they do not share an identity the result is PARTIAL: the card may still
 * render, but it must show the state rather than present a mixed-source value
 * as complete. This is the direct fix for "a card coalesces unrelated endpoint
 * results into an apparently complete value".
 */
export function coalesceEnvelopes(
  parts: ObservationEnvelope<unknown>[],
): { transport: TransportState; freshness: FreshnessStatus; identities: string[]; note: string | null } {
  if (parts.length === 0) {
    return { transport: 'UNKNOWN', freshness: 'UNKNOWN', identities: [], note: 'no sources' }
  }
  const identities = Array.from(new Set(parts.map(p => p.identity)))
  let transport = parts.reduce<TransportState>((acc, p) => worstTransport(acc, p.transport), 'OK')
  let note: string | null = parts.find(p => p.note)?.note ?? null
  if (identities.length > 1) {
    transport = worstTransport(transport, 'PARTIAL')
    note = `mixed sources: ${identities.join(' + ')}`
  }
  const freshness: FreshnessStatus = parts.some(p => p.freshness === 'STALE')
    ? 'STALE'
    : parts.some(p => p.freshness === 'UNKNOWN') ? 'UNKNOWN' : 'FRESH'
  return { transport, freshness, identities, note }
}

/**
 * The visible chrome for a state. Returns null ONLY for a fully coherent,
 * server-fresh, single-identity observation -- every other case is labelled.
 */
export function stateLabel(
  transport: TransportState,
  freshness: FreshnessStatus,
): string | null {
  if (transport === 'ERROR') return 'ERROR'
  if (transport === 'UNKNOWN') return 'UNKNOWN'
  if (transport === 'PARTIAL') return 'PARTIAL'
  if (transport === 'RETAINED') return freshness === 'STALE' ? 'STALE · RETAINED' : 'RETAINED'
  if (transport === 'FALLBACK') return freshness === 'STALE' ? 'STALE · FALLBACK' : 'FALLBACK'
  if (freshness === 'STALE') return 'STALE'
  if (freshness === 'UNKNOWN') return 'UNKNOWN'
  return null
}

/**
 * Retain a last-good observation after a failed or 304 refresh.
 *
 * The whole envelope travels together: value, identity, sourceLabel, business
 * date, observation clock, last-refresh clock, freshness and note are preserved
 * verbatim — a 304 may advance `receivedAt` and nothing else. Dropping the
 * provider/observed-time/quality in favour of just the value is exactly the
 * defect this replaces: a retained number must not look like a fresh one.
 */
export function retainObservation<T>(
  env: ObservationEnvelope<T>,
  receivedAtIso: string,
): ObservationEnvelope<T> {
  return {
    ...env,
    receivedAt: normIso(receivedAtIso),
    transport: worstTransport(env.transport, 'RETAINED'),
    note: env.note ?? 'retained last-good body',
  }
}

/**
 * Age of an observation from its DATA clock, in hours; null when undatable.
 *
 * The data clock is observedAt → lastRefreshAt → business-date session instant
 * → receivedAt, in that order. A 304 only moves receivedAt, so the age keeps
 * growing from the original observation: transport liveness is not data
 * freshness.
 */
export function observationAgeHours<T>(
  env: ObservationEnvelope<T>,
  nowMs: number = Date.now(),
): number | null {
  const ts =
    env.observedAt
    || env.lastRefreshAt
    || (env.businessDate ? businessDateToSessionInstant(env.businessDate)?.toISOString() ?? null : null)
    || env.receivedAt
  if (!ts) return null
  const ms = nowMs - new Date(ts).getTime()
  return ms >= 0 ? ms / 3_600_000 : null
}

/**
 * Whether an observation has aged past a staleness threshold (hours) as of
 * `nowMs`, using its DATA clock. A retained observation ages with every 304;
 * once it crosses the threshold it is stale no matter how recently the 304
 * arrived.
 */
export function isObservationStale<T>(
  env: ObservationEnvelope<T>,
  nowMs: number = Date.now(),
  thresholdHours: number,
): boolean {
  const age = observationAgeHours(env, nowMs)
  return age != null && age >= thresholdHours
}

/**
 * Accessible description for the state chip. Screen readers get the same
 * distinction sighted users get from colour.
 */
export function stateAriaLabel(
  transport: TransportState,
  freshness: FreshnessStatus,
): string {
  const l = stateLabel(transport, freshness)
  if (!l) return 'data current'
  const spoken: Record<string, string> = {
    ERROR: 'data error, value not trustworthy',
    UNKNOWN: 'data state unknown',
    PARTIAL: 'partial data, some fields missing or from mixed sources',
    RETAINED: 'showing last known good data',
    'STALE · RETAINED': 'stale data, showing last known good',
    FALLBACK: 'value from a fallback source',
    'STALE · FALLBACK': 'stale data from a fallback source',
    STALE: 'data is stale',
  }
  return spoken[l] ?? l
}
