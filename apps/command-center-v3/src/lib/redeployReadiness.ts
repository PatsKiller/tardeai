/**
 * Redeploy plan readiness — fail closed (RR-014).
 *
 * Why (2026-11-14, sprint 8H-2): the server readiness state machine is authoritative
 * (`scripts/lib/redeploy_plan_engine.readiness_state`, persisted on the plan snapshot), but the
 * page carried a client fallback: when a plan arrived without `readiness` it re-derived a state
 * from its own checks and returned `{state:'OPERATOR_READY', operator_ready:true}` whenever that
 * list happened to be empty. A response that simply did not carry readiness — an older row, a
 * truncated payload, a route that stopped attaching it — was therefore painted operator-ready.
 * Unknown beats wrong: with no server readiness the only honest state is UNAVAILABLE, and it can
 * never be operator-ready.
 *
 * The client checks are kept, but only as *evidence* shown beneath the unavailable state. They
 * never select a state, and an empty evidence list never upgrades anything.
 */

export type PlanReadiness = {
  state: string
  reasons: string[]
  operator_ready: boolean
  display: string
  /** True only when the state came from the server's readiness object. */
  authoritative: boolean
  /** Client-side observations, shown as evidence. Never selects a state. */
  evidence: string[]
}

export const READINESS_UNAVAILABLE = 'READINESS_UNAVAILABLE'
export const READINESS_UNAVAILABLE_DISPLAY = 'READINESS UNAVAILABLE'

const asReasonList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.trim() !== '') : []

const isNonEmptyString = (v: unknown): v is string => typeof v === 'string' && v.trim() !== ''

/**
 * @param plan   a plan row as served (or a cached copy of one)
 * @param evidence client-side checks from the page, shown only when readiness is unavailable
 */
export function readinessFromPlan(plan: unknown, evidence: string[] = []): PlanReadiness {
  const p = (plan ?? {}) as { readiness?: unknown }
  const r = (p.readiness ?? null) as { state?: unknown; reasons?: unknown; operator_ready?: unknown; display?: unknown } | null

  if (r && isNonEmptyString(r.state)) {
    return {
      state: r.state,
      reasons: asReasonList(r.reasons),
      // Strict `=== true`: a string "false", a 1, or a missing flag is not operator-ready.
      operator_ready: r.operator_ready === true,
      display: isNonEmptyString(r.display) ? r.display : r.state.replace(/_/g, ' '),
      authoritative: true,
      evidence: [],
    }
  }

  return {
    state: READINESS_UNAVAILABLE,
    reasons: ['the server did not return a readiness state for this plan'],
    operator_ready: false,
    display: READINESS_UNAVAILABLE_DISPLAY,
    authoritative: false,
    evidence: evidence.filter(x => typeof x === 'string' && x.trim() !== ''),
  }
}

/** Exact next review action for a readiness result. Advisory wording only — no broker action. */
export function nextReadinessAction(r: PlanReadiness): string {
  if (!r || r.state === READINESS_UNAVAILABLE) {
    return 'Readiness unavailable — reload this plan to get the server readiness state'
  }
  const reasons = r.reasons || []
  if (r.state === 'QUOTES_STALE' || reasons.some(x => /stale|fresh quotes/i.test(x))) return 'Refresh quotes'
  if (r.state === 'OVERSIGHT_PENDING' || reasons.some(x => /oversight pending/i.test(x))) return 'Run oversight'
  if (r.state === 'OVERSIGHT_FAILED') return 'Review oversight findings'
  if (r.operator_ready) return 'Review comparison, approve plan for operator implementation review'
  return reasons.length ? `Resolve: ${reasons.join(', ')}` : 'Review plan readiness'
}

/** One line of evidence for the unavailable state, or null when the server answered. */
export function readinessEvidenceLine(r: PlanReadiness): string | null {
  if (!r || r.authoritative) return null
  if (!r.evidence.length) return 'No client checks returned a blocker either — that does not make the plan operator-ready.'
  return `Client checks also flag: ${r.evidence.join(', ')}.`
}
