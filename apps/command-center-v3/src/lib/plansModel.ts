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
}

export type PlansView = {schema?: string; plans?: PlanRow[]; plan?: PlanRow; ok?: boolean; error?: string}

export const STATUS_WORDS: Record<string, string> = {
  approved: 'Approved — nobody has picked it up',
  in_progress: 'In progress',
  done: 'Done',
  abandoned: 'Abandoned',
  stalled: 'Stalled — no activity',
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

export function stepSummary(plan: PlanRow): string {
  const done = Number(plan.steps_done || 0)
  const left = Number(plan.steps_left || 0)
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
  if (!view || view.schema !== 'PlanRegistryView@v1' || !Array.isArray(view.plans)) return []
  return [...view.plans].sort((a, b) => String(b.approved_at || '').localeCompare(String(a.approved_at || '')))
}

export function planFrom(view: PlansView | null): PlanRow | null {
  return view && view.schema === 'PlanRegistryView@v1' && view.plan ? view.plan : null
}

export function openStepCount(plan: PlanRow): number {
  return Number(plan.steps_left || 0)
}
