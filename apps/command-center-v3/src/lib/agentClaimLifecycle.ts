// Coordination → Who's working: the claim lifecycle whiteboard (operator 2026-10-23: "what each agent is working on,
// when it's implemented and when it's finished", so agents don't step on each other). The server
// (scripts/lib/agent_claim_board.py + agent_claim_lifecycle.py, GET /api/v2/coordination/claims) sends each claim's
// stage and a timestamp per stage; this module groups, filters, labels and explains them. Pure module: no React, no
// DOM, no fetch. Nothing here claims, stages or releases: agents use scripts/agent_claim.py.

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type Stage = 'claimed' | 'building' | 'pr_open' | 'ci_green' | 'merged' | 'released' | 'abandoned'
export const STAGES: Stage[] = ['claimed', 'building', 'pr_open', 'ci_green', 'merged', 'released', 'abandoned']

export type CiInfo = {
  state?: 'green' | 'pending' | 'failing' | 'unknown' | string
  basis?: string; required?: string[]; failing?: string[]; pending?: string[]
  completed_at?: string | null; head_sha?: string; checked_at?: string
}

export type ClaimCard = {
  claim_id: string
  state: 'live' | 'stale' | 'done' | 'abandoned'
  status?: string
  stage?: Stage | string
  stages?: Partial<Record<Stage, string>>
  locks_held?: boolean
  vendor?: string | null
  session?: string | null
  agent?: string | null
  task?: string | null
  paths?: string[]
  branch?: string | null
  pr?: string | null
  pr_number?: number | null
  pr_url?: string | null
  pr_state?: 'open' | 'closed' | 'merged' | string | null
  pr_draft?: boolean | null
  pr_base?: string | null
  merge_sha?: string | null
  ci?: CiInfo | null
  released?: { at?: string | null; sha?: string; basis?: string } | null
  started_at?: string | null
  heartbeat_at?: string | null
  ended_at?: string | null
  heartbeat_age_minutes?: number | null
  age_minutes?: number | null
  stale_warning?: string | null
  warnings?: string[]
  observe_warnings?: string[]
  note?: string | null
  takeover_of?: string[]
  taken_over_by?: string[]
}

export const STAGE_LABEL: Record<Stage, string> = {
  claimed: 'Claimed', building: 'Building', pr_open: 'PR open', ci_green: 'CI green',
  merged: 'Merged', released: 'Released (live)', abandoned: 'Abandoned',
}

// Fallback when the server omits stage_help (older server): same wording as agent_claim_lifecycle.STAGE_HELP.
export const STAGE_HELP: Record<Stage, string> = {
  claimed: 'Files claimed; work not started or not yet declared.',
  building: 'The agent declared it is implementing (agent_claim.py stage <id> building).',
  pr_open: 'A pull request is open for this work (declared with --pr, or found on GitHub by branch).',
  ci_green: "Every required check on the PR's head commit passed (GitHub, read-only).",
  merged: 'The PR is merged. File locks are released; the card stays until the merge is live.',
  released: 'The merge commit is an ancestor of a release SHA this host served (release receipts).',
  abandoned: 'Released without finishing, or lost a simultaneous-claim race.',
}

export const STAGE_TONE: Record<Stage, Tone> = {
  claimed: 'neutral', building: 'info', pr_open: 'info', ci_green: 'success',
  merged: 'success', released: 'success', abandoned: 'neutral',
}

export function stageOf(c: ClaimCard): Stage {
  const s = String(c.stage || '')
  if ((STAGES as string[]).includes(s)) return s as Stage
  // older server (no lifecycle): derive from status + PR
  if (c.status === 'abandoned' || c.state === 'abandoned') return 'abandoned'
  return c.pr ? 'pr_open' : 'claimed'
}

export function groupByStage(cards: ClaimCard[]): Record<Stage, ClaimCard[]> {
  const out = Object.fromEntries(STAGES.map(s => [s, [] as ClaimCard[]])) as Record<Stage, ClaimCard[]>
  for (const c of cards) out[stageOf(c)].push(c)
  for (const s of STAGES) out[s].sort((a, b) => String(b.stages?.[s] || b.started_at || '').localeCompare(String(a.stages?.[s] || a.started_at || '')))
  return out
}

export type ClaimFilter = { vendor?: string; stage?: Stage | 'all'; showFinished?: boolean }

export function isFinished(c: ClaimCard): boolean {
  const s = stageOf(c)
  if (s === 'released' || s === 'abandoned') return true
  // released by its agent with nothing left to chase (no PR on its way to production)
  return c.state === 'done' && (s === 'claimed' || s === 'building')
}

export function filterCards(cards: ClaimCard[], f: ClaimFilter): ClaimCard[] {
  return cards.filter(c =>
    (!f.vendor || f.vendor === 'all' || (c.vendor || 'unknown') === f.vendor)
    && (!f.stage || f.stage === 'all' || stageOf(c) === f.stage)
    && (f.showFinished || (f.stage && f.stage !== 'all') || !isFinished(c)))
}

export function vendorsOf(cards: ClaimCard[]): string[] {
  return Array.from(new Set(cards.map(c => c.vendor || 'unknown'))).sort()
}

export function ciView(c: ClaimCard): { label: string; tone: Tone; title: string } {
  const ci = c.ci
  if (!ci || !ci.state) {
    const s = stageOf(c)
    if (s === 'merged' || s === 'released') return { label: 'merged', tone: 'neutral', title: 'Merged: CI is no longer tracked for this PR.' }
    return { label: c.pr_number || c.pr ? 'CI —' : 'no PR', tone: 'neutral', title: c.pr_number || c.pr ? 'CI not observed yet (GitHub not consulted or unavailable).' : 'No pull request yet.' }
  }
  const req = (ci.required || []).join(', ')
  const basis = ci.basis === 'required' ? `required checks (${req})` : `all checks (no required checks readable)`
  if (ci.state === 'green') return { label: 'CI green', tone: 'success', title: `All ${basis} passed on head ${shortSha(ci.head_sha)}.` }
  if (ci.state === 'failing') return { label: 'CI failing', tone: 'danger', title: `Failing: ${(ci.failing || []).join(', ')} — on head ${shortSha(ci.head_sha)}; ${basis}.` }
  if (ci.state === 'pending') return { label: 'CI pending', tone: 'warning', title: `Waiting on: ${(ci.pending || []).join(', ')} — ${basis}.` }
  return { label: 'CI unknown', tone: 'neutral', title: 'Check runs could not be read from GitHub.' }
}

export function shortSha(v: unknown): string {
  const s = String(v || '')
  return s ? s.slice(0, 9) : '—'
}

export function prLabel(c: ClaimCard): string {
  const n = c.pr_number ?? (c.pr ? Number(String(c.pr).replace(/\D+/g, '')) || null : null)
  if (!n) return '—'
  const st = c.pr_state === 'merged' ? ' merged' : c.pr_state === 'closed' ? ' closed' : c.pr_draft ? ' draft' : ''
  return `#${n}${st}`
}

// Timeline: every reached stage with its time, in lifecycle order (abandoned last).
export function timeline(c: ClaimCard): Array<{ stage: Stage; at: string }> {
  const out: Array<{ stage: Stage; at: string }> = []
  for (const s of STAGES) {
    const at = c.stages?.[s] || (s === 'claimed' ? c.started_at : null)
    if (at) out.push({ stage: s, at })
  }
  return out
}

export function ageLabel(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes < 0) return '—'
  if (minutes < 60) return `${Math.round(minutes)}m`
  if (minutes < 48 * 60) return `${(minutes / 60).toFixed(1)}h`
  return `${Math.round(minutes / 1440)}d`
}

export function lockView(c: ClaimCard): { label: string; title: string } {
  if (stageOf(c) === 'abandoned' || c.state === 'done' || c.state === 'abandoned') return { label: 'files free', title: 'Released by its agent: the files are free.' }
  if (c.locks_held === false) return { label: 'files free', title: 'The PR merged: these files are free for other agents. The card stays until the merge is live.' }
  if (c.state === 'stale') return { label: 'not protected', title: 'No heartbeat inside the stale window: another agent may take these files over (recorded).' }
  return { label: 'files held', title: 'Other agents are refused on these paths until this claim merges or is released.' }
}

export function warningOf(c: ClaimCard): string | null {
  return c.stale_warning || (c.warnings && c.warnings[0]) || null
}

export function stageCounts(cards: ClaimCard[]): Record<Stage, number> {
  const g = groupByStage(cards)
  return Object.fromEntries(STAGES.map(s => [s, g[s].length])) as Record<Stage, number>
}
