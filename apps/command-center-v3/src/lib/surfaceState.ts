/**
 * SurfaceState@v1 — the honest-state contract for Command Center data surfaces (BOARD row 36, 2026-11-04).
 *
 * The defect it ends: /agents rendered "Agents unavailable" and "Loading the desk projection." at the same time, and
 * /approvals rendered "Queue unavailable" beside "Loading the latest queue.". Both came from branching on `!data`
 * (or on a separate `error` boolean) instead of deriving ONE state. `!data` is true while loading, true after a
 * failure, and true after a read that returned nothing usable — three different facts, one boolean.
 *
 * The rule: a surface derives exactly one state here, and every word it renders about data comes from
 * `surfaceGap(state)`. The "must never say" table below is the testable half of the contract: each state names the
 * vocabulary it may not use, and `surfaceState.test.ts` + `honestState.view.test.mjs` assert it.
 *
 * Pure: no React, no I/O, no clock (a caller passes what the hook already knows).
 */

/** Exactly one of these is true for a surface's data region at any moment. */
export type SurfaceStateName =
  | 'loading'      // first read in flight, nothing retained
  | 'refreshing'   // data retained, a re-read is in flight (a marker, never a full-page state)
  | 'ready'        // data present and complete
  | 'partial'      // data present, the envelope names gaps: some sources unavailable
  | 'empty'        // a successful read that returned nothing — a fact, not a failure
  | 'stale'        // last-good data still shown after a failed re-read
  | 'unavailable'  // the read failed and nothing is retained
  | 'unreadable'   // the read answered, but the payload cannot be used

/** What the fetch hook already knows. `useApi` returns exactly this shape (plus receipts we do not need here). */
export type SurfaceReading<T> = {
  data: T | null | undefined
  error?: string | null
  loading?: boolean
  refreshing?: boolean
  stale?: boolean
}

/** Per-surface facts the envelope must supply. Anything omitted is treated conservatively (see derive()). */
export type SurfaceShape<T> = {
  /** Plain-English name used in the banner: "the desk projection", "the latest queue". */
  what: string
  /** True when a successful read returned nothing. Omitted = a present payload is never "empty". */
  isEmpty?: (data: T) => boolean
  /** Named gaps from the envelope. Omitted = treat a present payload as COMPLETE (state ready). */
  gaps?: (data: T) => readonly string[]
  /** False when the payload is the wrong shape. Omitted = a present payload is assumed usable. */
  usable?: (data: T) => boolean
}

export type SurfaceState<T> = {
  state: SurfaceStateName
  /** The payload a surface may render. Null unless state is ready/partial/empty/stale. */
  data: T | null
  /** Named gaps (partial only). */
  gaps: readonly string[]
  /** False when a total derived from this surface would look complete but is not. Callers MUST NOT print a number. */
  totalKnown: boolean
  /** A re-read is in flight while data is retained. Never a state of its own. */
  refreshing: boolean
}

/**
 * The one derivation. Order matters and is the contract:
 *   unusable payload -> unreadable
 *   no payload + error -> unavailable
 *   no payload + loading -> loading
 *   no payload + neither -> unreadable  (a read that finished with nothing usable is NOT loading, and saying
 *                                        "loading" forever is the trap this module exists to close)
 *   payload + gaps -> partial
 *   payload + empty -> empty
 *   payload + stale -> stale
 *   payload -> ready
 */
export function deriveSurfaceState<T>(reading: SurfaceReading<T>, shape: SurfaceShape<T>): SurfaceState<T> {
  const data = reading.data ?? null
  const refreshing = reading.refreshing === true
  const hasData = data !== null && data !== undefined
  const base = { data: null as T | null, gaps: [] as readonly string[], totalKnown: true, refreshing }
  const unreadable = (): SurfaceState<T> => ({ ...base, state: 'unreadable', refreshing: false })
  // F3 (review, 2026-11-04): a caller's extractor assumes a shape. If the payload is malformed, the extractor THROWS —
  // and a contract that crashes instead of reporting "could not be read" is not a contract. A throw is therefore the
  // UNREADABLE state, never a silent fallback (a fallback would report "no gaps" about a payload we could not read)
  // and never an exception out of render.
  const extract = <R>(fn: (d: T) => R): { ok: true; value: R } | { ok: false } => {
    try { return { ok: true, value: fn(data as T) } } catch { return { ok: false } }
  }
  if (hasData && shape.usable) {
    const u = extract(d => shape.usable!(d))
    if (!u.ok || !u.value) return unreadable()
  }
  let gaps: string[] = []
  if (hasData && shape.gaps) {
    const g = extract(d => [...shape.gaps!(d)])
    if (!g.ok) return unreadable()
    gaps = g.value
  }
  if (!hasData) {
    if (reading.error) return { ...base, state: 'unavailable', refreshing: false }
    if (reading.loading) return { ...base, state: 'loading', refreshing: false }
    return unreadable()
  }
  if (gaps.length) return { ...base, state: 'partial', data, gaps, totalKnown: false }
  if (shape.isEmpty) {
    const e = extract(d => shape.isEmpty!(d))
    if (!e.ok) return unreadable()
    if (e.value) return { ...base, state: 'empty', data }
  }
  if (reading.stale) return { ...base, state: 'stale', data }
  return { ...base, state: 'ready', data }
}

/**
 * Did the surface render data the operator can read? `empty` counts: the read succeeded and said so. `partial` counts:
 * some sources answered and the gaps are named. This is the ONE predicate the footer uses, so the shell and the page
 * cannot hold different opinions about the same render (F2 review, 2026-11-04).
 */
export function rendersData(state: SurfaceState<unknown> | null): boolean {
  if (!state) return false
  return state.state === 'ready' || state.state === 'partial' || state.state === 'stale' || state.state === 'empty'
}

/** The words a state may use, and — the testable half — the vocabulary it may never use. */
export type SurfaceGapText = { title: string; reason: string; action: 'retry' | 'none' }

export const MUST_NEVER_SAY: Record<SurfaceStateName, readonly RegExp[]> = {
  // Loading may not borrow the failure vocabulary. This pair is the /agents defect verbatim.
  loading: [/unavailable/i, /has not answered/i, /could not be read/i, /\bunreadable\b/i, /\bretry\b/i],
  // A failure may not borrow the loading vocabulary. This pair is the /approvals defect verbatim.
  // No COUNT may cross a failure. A timestamp in "last good read" is not a count, so the rule names the shape.
  unavailable: [/loading/i, /has not answered/i, /\b\d+\s+(waiting|items?|rows?|approvals?|reviews?)\b/i, /\b\d+\s+waiting for review\b/i],
  // "Nothing on file" is not a failure and not an unreadable payload.
  empty: [/unavailable/i, /could not be read/i, /\bretry\b/i, /loading/i],
  // A payload we cannot use is not "unavailable" (the read answered) and not empty.
  unreadable: [/\bunavailable\b/i, /loading/i, /nothing on file/i],
  // A partial surface may not present a total that looks complete.
  partial: [/\bwaiting for review\b/i, /^\s*\d+\s*$/],
  stale: [/loading/i],
  ready: [/unavailable/i, /loading/i, /could not be read/i],
  refreshing: [/unavailable/i, /has not answered/i],
}

/**
 * The ONE wording function. Every banner, source-row gap and decisions line a surface renders about data comes from
 * here, so three places cannot disagree about what is happening.
 */
export function surfaceGap<T>(s: SurfaceState<T>, shape: SurfaceShape<T>, opts: { lastGoodAt?: string | null } = {}): SurfaceGapText | null {
  const { what } = shape
  const when = opts.lastGoodAt ? ` Last good read ${opts.lastGoodAt}.` : ''
  switch (s.state) {
    case 'loading':
      return { title: `Loading the ${what}…`, reason: `The ${what} is still being read.`, action: 'none' }
    case 'partial':
      return {
        title: `Some sources for the ${what} are unavailable`,
        reason: `${s.gaps.length} source${s.gaps.length === 1 ? '' : 's'} did not answer (${s.gaps.join(', ')}). The total is not yet known — the rows below are what did answer.`,
        action: 'none',
      }
    case 'empty':
      return { title: `Nothing on file for the ${what}`, reason: `The ${what} was read successfully and returned no rows.`, action: 'none' }
    case 'stale':
      return { title: `Showing the last good ${what}`, reason: `A fresh read failed; these rows are the last good read.${when}`, action: 'retry' }
    case 'unavailable':
      return { title: `The ${what} is unavailable`, reason: `It could not be read.${when}`, action: 'retry' }
    case 'unreadable':
      return { title: `The ${what} could not be read`, reason: 'The server answered, but the response was not in a usable shape.', action: 'retry' }
    case 'ready':
    case 'refreshing': // a marker, not a data state: refreshMarker() carries it
      return null
  }
}

/**
 * The refresh marker is NOT a state: it rides on top of whatever the data is (ready, partial, stale, empty) and says
 * only "a fresh read is in flight". Keeping it separate is why "refreshing" can never be mistaken for loading.
 */
export function refreshMarker<T>(s: SurfaceState<T>, shape: SurfaceShape<T>): SurfaceGapText | null {
  if (!s.refreshing) return null
  return { title: `Updating the ${shape.what}…`, reason: 'Showing the last read while a fresh one arrives.', action: 'none' }
}

/** Who owns the footer's surface slot. Pure, so the ownership rule is testable without rendering the shell (F2). */
export type SurfaceReport = { name: string; dataLoaded: boolean }

/**
 * The next footer report given the current one and an incoming publish. A `null` (unmount) clears the slot ONLY when
 * the outgoing surface is the one that owns it; otherwise the incoming page's state survives a route change.
 */
export function nextSurfaceReport(prev: SurfaceReport | null, incoming: SurfaceReport | null, clearingFrom?: string): SurfaceReport | null {
  if (incoming !== null) return incoming
  return prev && clearingFrom && prev.name === clearingFrom ? null : prev
}
