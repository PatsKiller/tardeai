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
//
// Page owners may add rows; the shell only enforces what a row declares. No row → defaults
// (8 s timeout, not heavy, no declared unavailability, no as_of rule).

export interface UnavailableRule {
  /** Dotted path into the JSON body, e.g. "data.publication.status". Never "ok". */
  at: string
  /** The value at `at` that marks the read as not real. */
  equals: string | number | boolean | null
}

export interface ReaderSpec {
  /** Exact path, or a prefix ending in "/" that covers sub-paths. */
  path: string
  timeoutMs: number
  /** Fetched only by the page that owns it; the shell refuses to fetch it. */
  heavy: boolean
  unavailableWhen: UnavailableRule[]
  /** Dotted path to the as_of stamp that proves freshness. Absent → freshness cannot be proven. */
  asOfAt?: string
  /** Older than this → UNKNOWN (stale), never OK. */
  maxAgeHours?: number
  /** Why the row exists (measurement reference). */
  note: string
}

export const DEFAULT_TIMEOUT_MS = 8000

export const READERS: ReaderSpec[] = [
  {
    path: '/api/v2/rotation/summary', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false,
    unavailableWhen: [
      { at: 'data.ok', equals: false },
      { at: 'data.publication.status', equals: 'UNAVAILABLE' },
    ],
    asOfAt: 'data.generated_at',
    note: 'cc-deepseek-7 2307Z: HTTP 200 + outer ok:true while data.ok=false, publication UNAVAILABLE (unbound_cache_inputs)',
  },
  {
    path: '/api/v2/recovery', timeoutMs: DEFAULT_TIMEOUT_MS, heavy: false,
    unavailableWhen: [{ at: 'data.ok', equals: false }],
    // recovery_cases.generated_at is request time (not evidence of a materialised projection) and the
    // payload has no top-level as_of, so no freshness path is declared: count 0 can never read EMPTY.
    note: 'cc-deepseek-7 2307Z F4: recovery_cases.count 0 + state ok while 16 legacy items are active; writer has no scheduler',
  },
  {
    path: '/api/v2/defense/posture', timeoutMs: 12000, heavy: true,
    unavailableWhen: [{ at: 'stale', equals: true }],
    asOfAt: 'as_of', maxAgeHours: 26,
    note: 'cc-deepseek-7 2307Z: 7.341 s cold; 29,268 B; stale_after_hours 26',
  },
  {
    path: '/api/v2/reentry/decision-desk', timeoutMs: 6000, heavy: true,
    unavailableWhen: [],
    asOfAt: 'computed_at',
    note: 'cc-deepseek-7 2307Z: 629,823 B; up to 2.411 s',
  },
  {
    path: '/api/v2/risk/protection-truth', timeoutMs: 4000, heavy: true,
    unavailableWhen: [],
    note: 'cc-deepseek-7 2307Z: recomputes a second risk build per request; one 3.653 s tail; as_of = request time (not evidence)',
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
