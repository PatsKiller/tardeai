// Reader registry for the Wealth client (shell-owned). One row per canonical /api/ reader the
// Wealth app is allowed to call. The row says how long the shell will wait for that reader, whether
// it is too heavy to be fetched from anywhere but its own page, and which NESTED field says the read
// is not real even though HTTP said 200.
//
// Rules this file exists to enforce (lead GO 2026-11-14T2313Z, cc-deepseek-7 measurements):
//  * Never read the outer `ok`. /api/v2/rotation/summary and /api/v2/recovery both answer
//    {"ok": true, "data": {...}}: the outer flag is true when the read is unavailable or the projection
//    was never built. Only the declared nested path decides.
//  * Emptiness is not evidence. An empty list or count 0 renders EMPTY only when a fresh as_of backs it;
//    otherwise it is UNKNOWN (recovery count 0 with state "ok"; defense engine_gaps [] last checked
//    100 days ago).
//  * Heavy readers are fetched by their own page only, never fanned out from the shell.
//  * Every reader answers {"ok": true, "data": {...}}: every declared path starts with `data.`.
//  * A stamp that equals the request time is not freshness. Only `clock: 'producer'` rows declare
//    asOfAt; 'request-time' and 'none' rows never do, and the page shows "age UNKNOWN".
//
// Page owners may add rows; the shell only enforces what a row declares. No row → defaults
// (8 s timeout, not heavy, no declared unavailability, no as_of rule).

type Scalar = string | number | boolean | null

/** Exactly one of `equals` / `notEquals`. A missing value never satisfies `notEquals`'s healthy value. */
export type UnavailableRule =
  /** Dotted path into the JSON body, e.g. "data.publication.status". Never "ok". Arrays index by position. */
  | { at: string; equals: Scalar; notEquals?: never; staleFlag?: never }
  /** The read is real only when the value at `at` is exactly this (e.g. status must be "OK"). */
  | { at: string; notEquals: Scalar; equals?: never; staleFlag?: never }
  /** A `stale` field: true fires; false/missing do not. Any non-boolean fires too: `stale` is boolean on most
   *  payloads but a number on others (unit unconfirmed), so a non-boolean cannot be read as fresh. */
  | { at: string; staleFlag: true; equals?: never; notEquals?: never }

/** Where a row's freshness comes from. Only 'producer' may declare asOfAt. */
export type ClockKind = 'producer' | 'request-time' | 'none'

/** True when the rule says the read is not real. */
export function ruleFires(rule: UnavailableRule, value: unknown): boolean {
  if (rule.staleFlag === true) return value !== undefined && value !== null && value !== false
  return 'notEquals' in rule && rule.notEquals !== undefined ? value !== rule.notEquals : value === rule.equals
}

export interface ReaderSpec {
  /** Exact path, or a prefix ending in "/" that covers sub-paths. */
  path: string
  timeoutMs: number
  /** Fetched only by the page that owns it; the shell refuses to fetch it. */
  heavy: boolean
  unavailableWhen: UnavailableRule[]
  /** 'request-time': the payload's stamp equals the request (not evidence); 'none': no clock at all. */
  clock?: ClockKind
  /** Dotted path to a PRODUCER as_of. Absent → freshness cannot be proven ("age UNKNOWN"). */
  asOfAt?: string
  /** Older than this → UNKNOWN (stale), never OK. */
  maxAgeHours?: number
  /** Why the row exists (measurement reference). */
  note: string
}

export const DEFAULT_TIMEOUT_MS = 8000

const M = 'cc-deepseek-7 captures 2026-11-14 23:00-23:27Z (served R11)'

export const READERS: ReaderSpec[] = [
  // ---- protection ----
  {
    path: '/api/v2/risk', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'producer',
    unavailableWhen: [{ at: 'data.truth.stale', staleFlag: true }, { at: 'data._product.status', equals: 'FAILED' }],
    asOfAt: 'data._product.as_of', maxAgeHours: 2.5,
    note: `${M}: 140,325 B; no data.ok; _product stale_after_s 9000. Page: _product.status != OK → DEGRADED with reason; greyed → banner. Do not take protection from pct_protected.`,
  },
  {
    path: '/api/v2/risk/protection-truth', timeoutMs: 8000, heavy: true, clock: 'request-time',
    unavailableWhen: [{ at: 'data.status', notEquals: 'OK' }],
    note: `${M}: 4,698 B; 77 ms median, 3.653 s tail (8 s = 2.2x); data.as_of is request time. Second population (11) over a risk build the route does not serve; never the same rows as /risk.`,
  },
  {
    path: '/api/v2/defense/posture', timeoutMs: 12000, heavy: true, clock: 'producer',
    unavailableWhen: [{ at: 'data.stale', staleFlag: true }],
    asOfAt: 'data.as_of', maxAgeHours: 26,
    note: `${M}: 29,268 B; 7.341 s cold (61 % of 12 s); stale_after_hours 26`,
  },
  {
    path: '/api/v2/defense/recommendations', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: true, clock: 'producer',
    unavailableWhen: [{ at: 'data.ok', equals: false }],
    asOfAt: 'data.recommendations.generated_at', maxAgeHours: 26,
    note: `${M}: 487,200 B; mode SHADOW: label it, never live advice. recommendations.as_of is date-only and not a clock.`,
  },
  {
    path: '/api/v2/market-risk/latest', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: true, clock: 'producer',
    unavailableWhen: [{ at: 'data.state', notEquals: 'evaluated' }, { at: 'data.stale', staleFlag: true }],
    asOfAt: 'data.as_of', maxAgeHours: 1,
    note: `${M}: 243,946 B; score is not a probability. maxAgeHours 1: the producer's own stale_after_hours 1.0 (cc-deepseek-7 ADDENDUM v2a 0ab2c54a); hourly producer, so expect UNKNOWN near the hour boundary. Strict > (age exactly 1.0 h is fresh). Gate on data.stale, never the SWR cache_stale/cache_as_of annotations. Health: data.state "evaluated" + data.stale (cc-deepseek-5 DELTA-G13 e7fd59f8).`,
  },
  {
    path: '/api/v2/market-event/active', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: true, clock: 'producer',
    unavailableWhen: [{ at: 'data.stale', staleFlag: true }],
    asOfAt: 'data.inputs_as_of.market_risk', maxAgeHours: 26,
    note: `${M}: 263,626 B MarketEvent@v1. Clock: inputs_as_of.market_risk (cc-deepseek-7 v2a 0ab2c54a); computed_at follows the request and is not a clock. maxAgeHours 26 = the producer's STALE_SNAPSHOT_HOURS (scripts/lib/market_event_api.py, strict >; v2b dc7bcb5a). data.stale is the complete rule: daily bars (4 days) and candidate updated_at (26 h) carry their own producer rules inside it.`,
  },
  // ---- reposition ----
  {
    path: '/api/v2/rotation/summary', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'producer',
    unavailableWhen: [
      { at: 'data.ok', equals: false },
      { at: 'data.publication.status', equals: 'UNAVAILABLE' },
      { at: 'data.stale', staleFlag: true },
    ],
    asOfAt: 'data.generated_at',
    note: `cc-deepseek-7 2307Z: HTTP 200 + outer ok:true while data.ok=false, publication UNAVAILABLE (unbound_cache_inputs). Page: candidates only when publication.status is OK; on UNAVAILABLE show reasons + producer_ok.`,
  },
  {
    path: '/api/v2/recovery', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'none',
    unavailableWhen: [{ at: 'data.ok', equals: false }],
    // recovery_cases.generated_at is request time and the payload has no top-level as_of: count 0 can never read EMPTY.
    note: 'cc-deepseek-7 2307Z F4: recovery_cases.count 0 + state ok while 16 legacy items are active; writer has no scheduler',
  },
  {
    path: '/api/v2/reentry/status', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'request-time',
    unavailableWhen: [{ at: 'data.state', notEquals: 'POPULATED' }],
    note: `${M}: 87,080 B ReentryStatus@v1; data.as_of matched the request minute. READY/HELD/BLOCKED is its own population, never merged with the decision desk's actionable count.`,
  },
  {
    path: '/api/v2/reentry/decision-desk', timeoutMs: 6000, heavy: true, clock: 'producer',
    unavailableWhen: [],
    asOfAt: 'data.freshness.resistance_generated_at', maxAgeHours: 96,
    note: `${M}: 629,823 B; up to 2.411 s. computed_at follows the request (with a cache lag), so it is not a clock; resistance_generated_at with the desk's own 96 h rule (cc-deepseek-7 ADDENDUM v2a 0ab2c54a). Page shows freshness.price_age_h_median, price_age_h_max and stale_symbol_count beside it (26 h prices with 0 stale symbols is not calm; cc-deepseek-5). No reader threshold is invented for them. Actionable count is its own population.`,
  },
  {
    path: '/api/v2/stops/reentry-watch', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'none',
    unavailableWhen: [],
    note: `${M}: 95,099 B; no clock anywhere; reviews count is a third population.`,
  },
  {
    path: '/api/v2/journal/exit-intelligence', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'none',
    unavailableWhen: [{ at: 'data.ok', equals: false }],
    note: `${M}: 11,845 B; no clock; paper/unknown_sync rows are labelled or excluded, never blended into live totals.`,
  },
  {
    path: '/api/v2/time-exit-proposals', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'none',
    unavailableWhen: [],
    note: `${M}: 212 B; empty and clockless → UNKNOWN, never EMPTY; no approval control (paper-only interlock); POST /api/v2/time-exit-proposals/decide is never offered. Path per route table (cc-deepseek-7 ADDENDUM v2a 0ab2c54a: /time-exit/proposals is 404).`,
  },
  {
    path: '/api/v2/cio/capital-plan', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: true, clock: 'request-time',
    unavailableWhen: [{ at: 'data.ok', equals: false }],
    note: `${M}: 311,188 B; computed_at and as_of equal the request; cash_as_of is day precision. Show the earmark warning verbatim.`,
  },
  {
    path: '/api/v2/redeploy/capital-pools', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, clock: 'request-time',
    unavailableWhen: [{ at: 'data.ok', equals: false }],
    note: `${M}: 5,745 B; data.as_of is request time; pools under data.pools. open_event_remaining_usd is prospective proceeds: never added to visible cash.`,
  },
]

export function specFor(path: string, registry: ReaderSpec[] = READERS): ReaderSpec {
  const bare = path.split('?')[0]
  const hit = registry.find(r => (r.path.endsWith('/') ? bare.startsWith(r.path) : bare === r.path))
  return hit ?? { path: bare, timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false, unavailableWhen: [], note: 'default' }
}

/** Read a dotted path. Returns `undefined` when any segment is missing. */
export function readPath(body: unknown, dotted: string): unknown {
  let cur: unknown = body
  for (const seg of dotted.split('.')) {
    if (cur === null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[seg]
  }
  return cur
}
