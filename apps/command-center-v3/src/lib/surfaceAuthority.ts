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
 * Resolve one route's verdict from the server authority payload.
 *
 * An absent payload, an absent row, or an unrecognised mode all resolve to
 * UNKNOWN with a banner — never to LIVE, and never to the fixture's own opinion.
 */
export function surfaceVerdict(
  authority: SurfaceAuthority | null | undefined,
  route: string,
): SurfaceVerdict {
  const rows = Array.isArray(authority?.surfaces) ? authority!.surfaces! : []
  const row = rows.find(r => r?.route === route)

  if (!authority || authority.status === 'UNAVAILABLE') {
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
    }
  }

  if (!row) {
    return {
      route,
      mode: UNKNOWN,
      reason: `the server authority lists no row for ${route}`,
      bannerRequired: true,
      dismissible: false,
      label: LABELS[UNKNOWN],
      isLive: false,
      fixtureBundled: false,
      fixturePath: null,
    }
  }

  const mode = normaliseMode(row.data_mode)
  return {
    route,
    mode,
    reason: row.reason || 'no reason supplied by the server',
    bannerRequired: mode !== LIVE_GOVERNED,
    dismissible: false,
    label: LABELS[mode],
    isLive: mode === LIVE_GOVERNED,
    fixtureBundled: Boolean(row.bundled_fixture?.bundled),
    fixturePath: row.bundled_fixture?.path ?? null,
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
