/**
 * Client projection for the residual surfaces and the financial-conflict state.
 *
 * Every one of these endpoints answers with the same envelope: a single declared
 * `state`, the reason it landed there, and the authority and calculation version
 * behind it. The projection's whole job is to make it impossible to render a
 * surface as if it had data when it does not, and impossible to render a disputed
 * financial value as a number.
 *
 * The rule that matters: a failed read has measured nothing. It must never
 * project a count, because a count of zero is a measurement, and an outage that
 * renders identically to a quiet market is the defect this replaces.
 */

export type SurfaceState =
  | 'POPULATED'
  | 'LEGITIMATE_EMPTY'
  | 'STALE'
  | 'PARTIAL'
  | 'DEGRADED'
  | 'DISCONNECTED'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'MALFORMED'
  | 'ERROR'
  | 'LOADING'

export interface SurfaceEnvelope {
  state?: string
  state_reason?: string
  schema?: string
  authority?: string
  calculation_version?: string
  as_of?: string
}

/** States in which the surface did not successfully measure anything. */
const NO_MEASUREMENT: ReadonlySet<string> = new Set([
  'DISCONNECTED',
  'UNAUTHORIZED',
  'FORBIDDEN',
  'MALFORMED',
  'ERROR',
  'LOADING',
])

/** States a person should be told about rather than left to infer from a blank. */
const NEEDS_NOTICE: ReadonlySet<string> = new Set([
  'STALE',
  'PARTIAL',
  'DEGRADED',
  'DISCONNECTED',
  'UNAUTHORIZED',
  'FORBIDDEN',
  'MALFORMED',
  'ERROR',
])

export interface SurfaceProjection {
  state: SurfaceState
  reason: string
  /** True only when the surface actually measured something. */
  hasMeasurement: boolean
  /** True when a count may be rendered. Never true for a failed read. */
  countsRenderable: boolean
  /** Operator-facing label. */
  label: string
  /** Whether to show a notice rather than a silent empty area. */
  showNotice: boolean
  authority: string
  calculationVersion: string
}

const LABELS: Record<string, string> = {
  POPULATED: 'Live',
  LEGITIMATE_EMPTY: 'Empty (real answer)',
  STALE: 'Stale',
  PARTIAL: 'Partial',
  DEGRADED: 'Degraded',
  DISCONNECTED: 'Disconnected',
  UNAUTHORIZED: 'Sign-in required',
  FORBIDDEN: 'Not permitted',
  MALFORMED: 'Unreadable response',
  ERROR: 'Error',
  LOADING: 'Loading',
}

export function projectSurface(env: SurfaceEnvelope | null | undefined): SurfaceProjection {
  if (!env || typeof env.state !== 'string') {
    return {
      state: 'ERROR',
      reason: 'the surface returned no envelope, so nothing about it is known',
      hasMeasurement: false,
      countsRenderable: false,
      label: LABELS.ERROR,
      showNotice: true,
      authority: 'UNKNOWN',
      calculationVersion: 'UNKNOWN',
    }
  }
  const state = env.state as SurfaceState
  const measured = !NO_MEASUREMENT.has(state)
  return {
    state,
    reason: env.state_reason || 'no reason was supplied',
    hasMeasurement: measured,
    countsRenderable: measured,
    label: LABELS[state] || state,
    showNotice: NEEDS_NOTICE.has(state),
    authority: env.authority || 'UNKNOWN',
    calculationVersion: env.calculation_version || 'UNKNOWN',
  }
}

/**
 * A count is only ever rendered when the surface measured one. Everything else
 * returns null, which callers must render as a dash and never as 0.
 */
export function renderableCount(
  env: SurfaceEnvelope | null | undefined,
  value: number | null | undefined,
): number | null {
  const p = projectSurface(env)
  if (!p.countsRenderable) return null
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

// ── financial conflicts ──────────────────────────────────────────────────────

export interface ConflictRecord {
  store?: string
  record_key?: string
  render_as?: string
  reason?: string
  blocks?: string[]
  both_originals_preserved?: boolean
}

export interface ConflictProjection {
  unresolvedCount: number
  /** Field identifiers that must render UNVERIFIED instead of a value. */
  unverifiedFields: string[]
  /** Calculations that fail closed. Deliberately narrow. */
  blockedCalculations: string[]
  bothOriginalsPreserved: boolean
}

/**
 * Scope is per record, never per store and never global. One disputed historical
 * tax lot blocks the basis calculation that reads it -- and nothing else. Watch,
 * Closed Loop and the other records in the same store stay live.
 */
export function projectConflicts(
  env: (SurfaceEnvelope & { conflicts?: ConflictRecord[] | null }) | null | undefined,
): ConflictProjection {
  const conflicts = env && Array.isArray(env.conflicts) ? env.conflicts : []
  const blocked: string[] = []
  const fields: string[] = []
  let preserved = true
  for (const c of conflicts) {
    const key = `${c.store || 'unknown'}:${c.record_key || 'unknown'}`
    fields.push(key)
    for (const b of c.blocks || []) blocked.push(b)
    if (c.both_originals_preserved === false) preserved = false
  }
  return {
    unresolvedCount: conflicts.length,
    unverifiedFields: fields,
    blockedCalculations: blocked,
    bothOriginalsPreserved: preserved,
  }
}

/** True when this specific field must render UNVERIFIED rather than a number. */
export function isFieldUnverified(proj: ConflictProjection, store: string, recordKey: string): boolean {
  return proj.unverifiedFields.includes(`${store}:${recordKey}`)
}
