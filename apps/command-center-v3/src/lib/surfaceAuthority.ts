/**
 * surfaceAuthority.ts — the server decides what a surface is showing, not the page.
 *
 * Eleven /v3/control-plane/* pages carried a hard-coded "PREVIEW"/"FIXTURE" label
 * while live domains answered behind seven of them, and two that the label called
 * previewable were in fact UNAVAILABLE. A label compiled into the bundle is an
 * assertion; only the server can make it a fact.
 *
 * This module holds the client half of ControlPlaneSurfaceAuthority@v1. It never
 * invents a mode: an unreachable or unparseable authority endpoint yields UNKNOWN,
 * which still requires a banner. A compiled fixture is never a fallback for a
 * failed live read.
 *
 * Pure functions. No network, no React, no side effects.
 */

export const LIVE_GOVERNED = 'LIVE_GOVERNED'
export const PREVIEW_FIXTURE = 'PREVIEW_FIXTURE'
export const FROZEN_SNAPSHOT = 'FROZEN_SNAPSHOT'
export const UNAVAILABLE = 'UNAVAILABLE'
export const UNKNOWN = 'UNKNOWN'

export type DataMode =
  | typeof LIVE_GOVERNED
  | typeof PREVIEW_FIXTURE
  | typeof FROZEN_SNAPSHOT
  | typeof UNAVAILABLE
  | typeof UNKNOWN

export type SurfaceAuthorityRow = {
  route: string
  tranche?: string | null
  data_mode?: string | null
  reason?: string | null
  banner_required?: boolean | null
  banner_dismissible?: boolean | null
  live_domain?: string | null
  live?: Record<string, unknown> | null
  bundled_fixture?: { bundled?: boolean; path?: string | null } | null
}

export type SurfaceAuthority = {
  schema?: string
  decided_by?: string
  surfaces?: SurfaceAuthorityRow[]
  status?: string
  reason?: string | null
  // LQ-1789: the server answered from its last known-good result because the live recompute missed its deadline
  // (scripts/lib/request_isolation.py `_serve_last_known`). Those rows are real, so they are rendered — never
  // replaced by UNKNOWN — but the banner must say how old they are and why the live read did not answer.
  served_last_known?: boolean
  // `served_stale` alone is the ordinary stale-while-revalidate answer (LQ-259): the recompute is running on
  // schedule, not failing. It carries no age sentence and must not be labelled a failure.
  served_stale?: boolean
  /** Age of the last known answer, seconds, as measured by the server. */
  stale_age_sec?: number | null
  /** ISO instant the last known answer was computed. */
  stale_as_of?: string | null
  /** Why the live recompute did not answer: TIMEOUT | UNAVAILABLE | BUSY. */
  live_status?: string | null
  live_reason?: string | null
}

const KNOWN: ReadonlySet<string> = new Set([
  LIVE_GOVERNED,
  PREVIEW_FIXTURE,
  FROZEN_SNAPSHOT,
  UNAVAILABLE,
  UNKNOWN,
])

export type SurfaceVerdict = {
  route: string
  mode: DataMode
  /** Server sentence for why this surface is in this mode. Never invented here. */
  reason: string
  /** True for every mode except LIVE_GOVERNED. */
  bannerRequired: boolean
  /** Always false: a banner a user can dismiss is a banner they will dismiss. */
  dismissible: false
  /** Operator-facing label. */
  label: string
  /** True only when the server said the surface is live. */
  isLive: boolean
  /** True when a fixture is compiled into the bundle for this route. */
  fixtureBundled: boolean
  fixturePath: string | null
  /** True when these rows came from the server's last known answer, not a live compute. */
  lastKnown: boolean
  /** How old that answer is, seconds; null when the answer is live. */
  asOfAgeSec: number | null
  /** Operator-facing age sentence, e.g. "last known 12 min ago — the live recompute timed out"; null when live. */
  asOf: string | null
}

const LABELS: Record<DataMode, string> = {
  LIVE_GOVERNED: 'LIVE',
  PREVIEW_FIXTURE: 'PREVIEW — BUILD-TIME FIXTURE, NOT LIVE DATA',
  FROZEN_SNAPSHOT: 'FROZEN SNAPSHOT — CAPTURED ONCE, NEVER REFRESHED',
  UNAVAILABLE: 'UNAVAILABLE — THE BACKING SOURCE HAS NO USABLE DATA',
  UNKNOWN: 'UNKNOWN — THE SERVER COULD NOT DETERMINE WHAT THIS PAGE IS SHOWING',
}

function normaliseMode(v: unknown): DataMode {
  const s = typeof v === 'string' ? v : ''
  return (KNOWN.has(s) ? s : UNKNOWN) as DataMode
}

/**
 * The age of a last-known answer, in the largest unit that still reads precisely.
 * Seconds below 90 s, whole minutes below 90 min, hours above.
 */
export function ageLabel(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return 'unknown age'
  if (seconds < 90) return `${Math.round(seconds)} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}

/**
 * Resolve one route's verdict from the server authority payload.
 *
 * An absent payload, an absent row, or an unrecognised mode all resolve to
 * UNKNOWN with a banner — never to LIVE, and never to the fixture's own opinion.
 *
 * A payload the server marked as a last-known answer (endpoint alive, live recompute missed its bound) resolves to
 * the row's own mode with its age attached: UNKNOWN is reserved for "the server has said nothing", never for "the
 * server has not finished saying it". A last-known answer is still an answer.
 */
export function surfaceVerdict(
  authority: SurfaceAuthority | null | undefined,
  route: string,
): SurfaceVerdict {
  const rows = Array.isArray(authority?.surfaces) ? authority!.surfaces! : []
  const row = rows.find(r => r?.route === route)
  // Only a failed live recompute earns the "last known" sentence. An ordinary stale-while-revalidate answer is
  // flagged served_stale too, and it is the healthy steady state — saying the recompute "did not answer" there
  // would put a failure sentence on every ordinary poll.
  const lastKnown = Boolean(authority?.served_last_known)
  const asOfAgeSec =
    lastKnown && typeof authority?.stale_age_sec === 'number' && authority.stale_age_sec >= 0
      ? authority.stale_age_sec
      : null
  const liveStatus = authority?.live_status ? String(authority.live_status) : null
  const asOf = lastKnown
    ? `last known ${ageLabel(asOfAgeSec)} ago — the live recompute did not answer${liveStatus ? ` (${liveStatus})` : ''}`
    : null

  if (!authority || (authority.status === 'UNAVAILABLE' && !lastKnown)) {
    return {
      route,
      mode: UNKNOWN,
      reason:
        authority?.reason ||
        'the surface-authority endpoint did not answer; the server has not said what this page is showing',
      bannerRequired: true,
      dismissible: false,
      label: LABELS[UNKNOWN],
      isLive: false,
      fixtureBundled: false,
      fixturePath: null,
      lastKnown: false,
      asOfAgeSec: null,
      asOf: null,
    }
  }

  if (!row) {
    return {
      route,
      mode: UNKNOWN,
      reason: lastKnown
        ? `the server's last known answer lists no row for ${route}`
        : `the server authority lists no row for ${route}`,
      bannerRequired: true,
      dismissible: false,
      label: LABELS[UNKNOWN],
      isLive: false,
      fixtureBundled: false,
      fixturePath: null,
      lastKnown,
      asOfAgeSec,
      asOf,
    }
  }

  const mode = normaliseMode(row.data_mode)
  return {
    route,
    mode,
    reason: row.reason || 'no reason supplied by the server',
    bannerRequired: mode !== LIVE_GOVERNED || lastKnown,
    dismissible: false,
    label: LABELS[mode],
    isLive: mode === LIVE_GOVERNED,
    fixtureBundled: Boolean(row.bundled_fixture?.bundled),
    fixturePath: row.bundled_fixture?.path ?? null,
    lastKnown,
    asOfAgeSec,
    asOf,
  }
}

/**
 * May this surface render a compiled fixture as its data? Never.
 *
 * The rule is absolute so that "the live read failed, show the fixture" cannot be
 * reintroduced as a convenience: a fixture rendered in place of live data is
 * indistinguishable from live data.
 */
export function fixtureMayRenderAsLive(): false {
  return false
}
