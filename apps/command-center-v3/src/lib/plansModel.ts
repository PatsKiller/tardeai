/** Plan registry view model — read-only. Mirrors PlanRegistryView@v1 served by /api/v2/plans. */

export type PlanStep = {done: boolean; text: string}

export type PlanRow = {
  id: string
  title?: string
  status?: string
  vendor?: string
  approved_at?: string
  updated_at?: string
  claim?: string | null
  branch?: string | null
  pr?: number | null
  steps_done?: number
  steps_left?: number
  steps?: PlanStep[]
  body?: string
  operator_quote?: string
  /** `"claim:<id>"` or `"self-declared"`; absent when the server recorded nothing. */
  author_proof?: string
  stalled_since?: string | null
}

/** The registry store's own health, separate from the payload's schema. A store that could not be
 *  listed must never be rendered as an authoritative empty registry. */
export type PlanStore = {state?: string; reason?: string | null}

export type PlansView = {
  schema?: string; plans?: PlanRow[]; plan?: PlanRow; ok?: boolean; error?: string
  store?: PlanStore; as_of?: string
}

export const PLANS_SCHEMA = 'PlanRegistryView@v1'

export const STATUS_WORDS: Record<string, string> = {
  approved: 'Approved — nobody has picked it up',
  // Registration is not approval: a newly registered plan has an explicit, separate status word.
  registered: 'Registered — approval not recorded',
  in_progress: 'In progress',
  done: 'Done',
  abandoned: 'Abandoned',
  stalled: 'Stalled — no activity',
}

/** The provenance the registry recorded. `self-declared` is not an approval, and an absent field is
 *  not "nobody registered it" — it is simply not recorded. Never invent an approval step. */
export function provenanceLabel(plan: PlanRow): string {
  const proof = plan.author_proof
  if (!proof) return 'Provenance: not recorded'
  if (proof === 'self-declared') return 'Provenance: self-declared — no approval recorded'
  if (proof.startsWith('claim:')) return `Provenance: claim ${proof.slice('claim:'.length)}`
  return `Provenance: ${proof}`
}

/** The stalled clock, only when the registry recorded both the status and the instant it stalled.
 *  A bare "stalled" status must not invent a start date. */
export function stalledLine(plan: PlanRow): string | null {
  if (plan.status !== 'stalled' || !plan.stalled_since) return null
  return `Stalled since ${String(plan.stalled_since).slice(0, 10)}`
}

/** A plan is "picked up" when a claim, a branch or a PR is linked — the registry leaves the status
 *  at `approved` after link(), so the status alone must not claim nobody owns it. */
export function pickedUp(plan: PlanRow): boolean {
  return Boolean(plan.claim || plan.branch || plan.pr)
}

export function statusWord(status?: string, plan?: PlanRow): string {
  const s = String(status || '')
  if (s === 'approved' && plan && pickedUp(plan)) return 'Approved · picked up'
  return STATUS_WORDS[s] || 'Unknown'
}

/** A step count is real only when it is a non-negative integer. The registry is a server payload,
 *  so a string, a float, a negative or NaN must never be coerced into a total we invent. */
function stepCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}

/** Progress is shown only when both counts are present and valid. A lone `steps_done: 5` used to
 *  render "5 of 5 steps done · 0 left" — a fabricated 100% — so a missing or invalid count now
 *  reads "steps unknown" instead of a derived total. A plan with no counts at all is listed as such. */
export function stepSummary(plan: PlanRow): string {
  // An unreadable plan is a known gap, not "no steps": say so rather than implying the plan listed none.
  if ((plan as unknown as { status?: unknown }).status === 'unreadable') return 'steps unknown'
  const doneRaw: unknown = plan.steps_done
  const leftRaw: unknown = plan.steps_left
  const donePresent = doneRaw !== undefined && doneRaw !== null
  const leftPresent = leftRaw !== undefined && leftRaw !== null
  if (!donePresent && !leftPresent) return 'no steps listed'
  const done = stepCount(doneRaw)
  const left = stepCount(leftRaw)
  if (done === null || left === null) return 'steps unknown'
  const total = done + left
  if (!total) return 'no steps listed'
  return `${done} of ${total} step${total === 1 ? '' : 's'} done · ${left} left`
}

export function prUrl(plan: PlanRow): string | null {
  const n = Number(plan.pr || 0)
  return n > 0 ? `https://github.com/PatsKiller/tardeai/pull/${n}` : null
}

/** Claims live on the Coordination page; the registry only knows the claim id. */
export function claimHref(plan: PlanRow): string | null {
  return plan.claim ? '/coordination' : null
}

export function plansFrom(view: PlansView | null): PlanRow[] {
  if (!view || view.schema !== PLANS_SCHEMA || !Array.isArray(view.plans)) return []
  return [...view.plans].sort((a, b) => String(b.approved_at || '').localeCompare(String(a.approved_at || '')))
}

export function planFrom(view: PlansView | null): PlanRow | null {
  return view && view.schema === PLANS_SCHEMA && view.plan ? view.plan : null
}

/** A wrong or missing schema is an unreadable registry, not an authoritative empty one. */
function schemaGap(view: PlansView): string | null {
  if (view.schema === PLANS_SCHEMA) return null
  return view.schema ? `unrecognised plan registry schema (${String(view.schema)})` : 'plan registry schema missing'
}

/** Why a listing cannot be treated as an empty registry, or null when it is a usable view.
 *  useApi unwraps `{ok,data}` but leaves an `{ok:false,error}` body in `data`, so both shapes are
 *  checked here: the page must never paint "No plans registered yet." from an unparsed payload.
 *  A schema-valid payload can still describe a store that could not be read (`store.state` not
 *  `"ok"`): that is a gap with the server's reason, never an authoritative empty list. */
export function plansGap(view: PlansView | null): string | null {
  if (!view) return 'no plan registry response'
  if (view.ok === false) return String(view.error || 'Plan store unreadable')
  const schema = schemaGap(view)
  if (schema) return schema
  if (!Array.isArray(view.plans)) return 'plan registry returned no plan list'
  const storeState = view.store?.state
  if (storeState !== undefined && storeState !== 'ok') return String(view.store?.reason || 'the plan store could not be read')
  return null
}

/** Why a detail payload cannot be shown, or null when it carries a plan. A 200 `{ok:false}` detail
 *  (a deleted id through a proxy that keeps the envelope) is a gap, never a silent empty sheet. */
export function detailGap(view: PlansView | null, id: string | null): string | null {
  if (!view) return 'no plan registry response'
  if (view.ok === false) return String(view.error || 'Plan store unreadable')
  const schema = schemaGap(view)
  if (schema) return schema
  if (!view.plan) return id ? `plan ${id} not found` : 'plan not found'
  return null
}

/** The Decisions line. It must never claim an empty, healthy queue while the listing is still
 *  loading or could not be read — that is an unknown, not "nothing waiting". */
export function waitingDecision(waiting: number, state: {loading: boolean; known: boolean}): string {
  if (state.loading) return 'Waiting plans unknown — the plan registry is still loading.'
  if (!state.known) return 'Waiting plans unknown — the plan registry could not be read.'
  if (waiting) return `${waiting} approved plan${waiting === 1 ? '' : 's'} nobody has picked up yet.`
  return 'Nothing approved and unclaimed right now.'
}

/** Open step count, or null when the server value is not a real count. Same rule as stepSummary:
 *  never coerce a missing/invalid value into a number, even for callers that only need the raw count. */
export function openStepCount(plan: PlanRow): number | null {
  return stepCount((plan as unknown as { steps_left?: unknown }).steps_left)
}
