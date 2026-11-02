// Releases & schedules → Deploy in flight: the typed frontend model for GET /api/v2/ops/in-flight.
//
// The backend projection (DeployInFlight@v1) gained two ADDITIVE keys (codex wire contract 2026-11-02):
// a top-level `coordination` envelope (agent/task view) and a per-row `work` block (owner, review, CI,
// publication). Old backends send neither; both degrade to UNKNOWN with a stated reason.
//
// Rules this module enforces, so the board cannot invent a status:
//   • `mergeable` is a GitHub enum STRING (MERGEABLE | CONFLICTING | UNKNOWN) or a legacy boolean.
//     UNKNOWN never becomes CONFLICTING and never renders as "auto-rebase".
//   • `review` and `ci` count only when their receipt names the SAME head SHA as the row. A receipt for
//     another head is UNKNOWN with `head_changed`, never a stale verdict presented as current.
//   • A missing field is UNKNOWN plus a reason — never `0`, never green, never "unknown" as if it were data.
//   • Free-text review is display only; nothing here enables or disables an operator action.
import type { Tone } from './designTokens'

export const IN_FLIGHT_PATH = '/api/v2/ops/in-flight'
export const ACTION_PATH = '/api/v2/ops/in-flight/action'
export const IN_FLIGHT_SCHEMA = 'DeployInFlight@v1'
export const IN_FLIGHT_SCHEMA_V2 = 'DeployInFlight@v2'
export const KNOWN_SCHEMAS = [IN_FLIGHT_SCHEMA, IN_FLIGHT_SCHEMA_V2] as const

export type Mergeable = 'MERGEABLE' | 'CONFLICTING' | 'UNKNOWN'
export type ReviewState = 'MERGE' | 'CHANGES' | 'NONE' | 'UNKNOWN'
export type CiState = 'GREEN' | 'RED' | 'PENDING' | 'SKIPPED' | 'UNKNOWN'
export type PublicationState = 'local_only' | 'published' | 'merged' | 'live' | 'unknown'
export type AgentState = 'working' | 'blocked' | 'waiting' | 'idle' | 'unknown'
export type LegacyNext = 'auto-merge' | 'coordinator' | 'auto-rebase' | 'blocked-shard-hints'

export type Blocker = { text: string; kind: string | null; owner: string | null; as_of: string | null; source: string | null }

/** One head-bound fact: state as reported, the head it was measured on, when, from where, and why not. */
export type Factor<S extends string> = {
  state: S | 'UNKNOWN'
  reported: string | null
  head_sha: string | null
  as_of: string | null
  source: string | null
  reason: string | null
}

export type WorkBlock = {
  present: boolean
  owner: string | null
  current_task: string | null
  publication_state: PublicationState
  local_head: string | null
  published_head: string | null
  review: Factor<ReviewState>
  ci: Factor<CiState>
  blockers: Blocker[]
  next_action: string | null
  as_of: string | null
  source: string | null
  reason: string | null
}

export type CoordinationAgent = {
  session: string
  agent: string | null
  task: string | null
  state: AgentState
  branch: string | null
  pr: number | null
  blocker: string | null
  next_action: string | null
  as_of: string | null
  source: string | null
}

export type CoordinationBlock = {
  present: boolean
  status: 'OK' | 'PARTIAL' | 'UNAVAILABLE'
  as_of: string | null
  source: string | null
  reason: string | null
  agents: CoordinationAgent[]
}

export type InFlightPr = {
  number: number
  title: string
  url: string
  head_sha: string
  head_sha_short: string
  branch: string
  has_operator_merge: boolean
  mergeable: Mergeable
  merge_state: string
  is_draft: boolean
  why_held: string | null
  next: LegacyNext
  work: WorkBlock
}

export type DeployInFlightWire = {
  schema?: string
  authority?: string
  generated_at?: string
  repo?: string
  prs?: InFlightPr[] | null
  count?: number | null
  status?: string
  freshness?: 'OK' | 'STALE' | 'UNAVAILABLE'
  source?: string
  reason?: string | null
  coordination?: CoordinationBlock
}

export function shortSha(sha: string | null | undefined): string {
  const s = String(sha ?? '').trim()
  return s ? s.slice(0, 9) : '—'
}

const asText = (v: unknown): string | null => {
  if (typeof v !== 'string') return null
  const s = v.trim()
  return s && s.toLowerCase() !== 'unknown' ? s : null
}

/** GitHub's `mergeable` is an enum STRING; older mocks/backends sent a boolean. UNKNOWN stays UNKNOWN. */
export function normalizeMergeable(v: unknown): Mergeable {
  if (v === true) return 'MERGEABLE'
  if (v === false) return 'CONFLICTING'
  const s = String(v ?? '').trim().toUpperCase()
  if (s === 'MERGEABLE') return 'MERGEABLE'
  if (s === 'CONFLICTING') return 'CONFLICTING'
  return 'UNKNOWN'
}

const PUBLICATION: PublicationState[] = ['local_only', 'published', 'merged', 'live', 'unknown']
const AGENT_STATES: AgentState[] = ['working', 'blocked', 'waiting', 'idle', 'unknown']

function emptyWork(reason: string): WorkBlock {
  const unknown = <S extends string>(r: string): Factor<S> => ({ state: 'UNKNOWN', reported: null, head_sha: null, as_of: null, source: null, reason: r })
  return {
    present: false, owner: null, current_task: null, publication_state: 'unknown', local_head: null, published_head: null,
    review: unknown<ReviewState>(reason), ci: unknown<CiState>(reason), blockers: [], next_action: null,
    as_of: null, source: null, reason,
  }
}

/** A review/CI factor, bound to the row's exact head. Any mismatch or missing head is UNKNOWN, never edited-in. */
export function normalizeFactor<S extends string>(
  raw: unknown, allowed: readonly S[], rowHead: string, label: string,
): Factor<S> {
  const unknown = (reason: string, extra: Partial<Factor<S>> = {}): Factor<S> =>
    ({ state: 'UNKNOWN', reported: null, head_sha: null, as_of: null, source: null, reason, ...extra })
  if (!raw || typeof raw !== 'object') return unknown(`no typed ${label} receipt`)
  const r = raw as Record<string, unknown>
  const reportedRaw = String(r.state ?? '').trim().toUpperCase()
  const reported = reportedRaw || null
  const head = asText(r.head_sha)
  const base = { reported, head_sha: head, as_of: asText(r.as_of), source: asText(r.source) }
  const gap = asText(r.source_gap)
  if (!rowHead) return { ...unknown('row head not stated — cannot bind', base) }
  if (!head) return { ...unknown(`${label} receipt names no head`, base) }
  if (head !== rowHead) return { ...unknown(`head_changed: receipt ${shortSha(head)} ≠ row ${shortSha(rowHead)}${gap ? ` (${gap})` : ''}`, base) }
  if (!reported || !allowed.includes(reported as S)) {
    return { ...unknown(`unrecognised ${label} state ${reported ? `"${reportedRaw}"` : '(missing)'}`, base) }
  }
  if (gap) return { ...unknown(gap, base) }
  return { state: reported as S, ...base, reason: null }
}

function normalizeBlockers(raw: unknown): Blocker[] {
  if (!Array.isArray(raw)) return []
  const out: Blocker[] = []
  for (const b of raw) {
    if (typeof b === 'string' && b.trim()) out.push({ text: b.trim(), kind: null, owner: null, as_of: null, source: null })
    else if (b && typeof b === 'object') {
      const o = b as Record<string, unknown>
      const text = asText(o.text) ?? asText(o.detail) ?? asText(o.reason) ?? null
      if (text) out.push({ text, kind: asText(o.kind), owner: asText(o.owner), as_of: asText(o.as_of), source: asText(o.source) })
    }
  }
  return out
}

/** One row's additive `work` block. Absent (old backend) is UNKNOWN with a reason, not a clean state. */
export function normalizeWork(raw: unknown, rowHead: string): WorkBlock {
  if (!raw || typeof raw !== 'object') {
    return emptyWork('work facts not in this response (backend predates the work block)')
  }
  const w = raw as Record<string, unknown>
  const pub = String(w.publication_state ?? '').trim().toLowerCase()
  const publication = (PUBLICATION as string[]).includes(pub) ? (pub as PublicationState) : 'unknown'
  return {
    present: true,
    owner: asText(w.owner),
    current_task: asText(w.current_task),
    publication_state: publication,
    local_head: asText(w.local_head),
    published_head: asText(w.published_head),
    review: normalizeFactor<ReviewState>(w.review, ['MERGE', 'CHANGES', 'NONE'], rowHead, 'review'),
    ci: normalizeFactor<CiState>(w.ci, ['GREEN', 'RED', 'PENDING', 'SKIPPED'], rowHead, 'ci'),
    blockers: normalizeBlockers(w.blockers),
    next_action: asText(w.next_action),
    as_of: asText(w.as_of),
    source: asText(w.source),
    reason: asText(w.reason),
  }
}

/** The whole row → typed view. Per-row `work` is always present after this, so the renderer has one shape. */
export function normalizeRow(pr: Record<string, unknown>): InFlightPr {
  const rawHead = String(pr.head_sha ?? pr.headRefOid ?? '')
  const head = rawHead.trim()
  const legacy = String(pr.next ?? '').trim() as LegacyNext
  return {
    number: Number(pr.number ?? 0),
    title: String(pr.title ?? ''),
    url: String(pr.url ?? ''),
    head_sha: head,
    head_sha_short: head ? head.slice(0, 9) : '—',
    branch: String(pr.branch ?? pr.headRefName ?? ''),
    has_operator_merge: pr.has_operator_merge === true,
    mergeable: normalizeMergeable(pr.mergeable),
    merge_state: String(pr.merge_state ?? pr.mergeStateStatus ?? '').toUpperCase() || 'UNKNOWN',
    is_draft: pr.is_draft === true || pr.isDraft === true,
    why_held: asText(pr.why_held),
    next: (['auto-merge', 'coordinator', 'auto-rebase', 'blocked-shard-hints'] as string[]).includes(legacy) ? legacy : 'coordinator',
    work: normalizeWork(pr.work, head),
  }
}

/** The next step the board shows. A stated backend answer wins; otherwise only a provable step is named. */
export function nextActionFor(p: InFlightPr): string {
  if (p.work.next_action) return p.work.next_action
  if (p.is_draft) return 'author: mark ready for review'
  if (p.mergeable === 'CONFLICTING') return 'coordinator: resolve conflict'
  if (p.mergeable === 'UNKNOWN') return 'unknown: mergeability not stated (not auto-rebase)'
  if (p.next === 'auto-merge' && p.mergeable === 'MERGEABLE') return 'auto-merge (Mergify queue)'
  if (p.next === 'blocked-shard-hints') return 'blocked: shard hints'
  if (p.next === 'coordinator') return 'coordinator'
  if (p.next === 'auto-rebase') return 'auto-rebase'
  return 'unknown: no next step stated'
}

/** Publication line: local-only vs published vs merged vs live. Never guesses from a branch name. */
export function publicationLabel(w: WorkBlock): { text: string; tone: Tone } {
  if (w.publication_state === 'local_only') return { text: 'LOCAL · unpublished work', tone: 'warning' }
  if (w.publication_state === 'published') {
    const differ = w.local_head && w.published_head && w.local_head !== w.published_head
    return { text: differ ? `PUBLISHED · local ${shortSha(w.local_head)} ahead` : 'PUBLISHED · on remote', tone: 'info' }
  }
  if (w.publication_state === 'merged') return { text: 'MERGED', tone: 'success' }
  if (w.publication_state === 'live') return { text: 'LIVE', tone: 'success' }
  return { text: 'UNKNOWN · publication not stated', tone: 'warning' }
}

export function draftLabel(p: InFlightPr): { text: string; tone: Tone } {
  return p.is_draft ? { text: 'DRAFT', tone: 'warning' } : { text: 'READY', tone: 'neutral' }
}

export function reviewLabel(f: Factor<ReviewState>): { text: string; tone: Tone } {
  if (f.state === 'MERGE') return { text: 'REVIEW · merge requested', tone: 'success' }
  if (f.state === 'CHANGES') return { text: 'REVIEW · changes requested', tone: 'danger' }
  if (f.state === 'NONE') return { text: 'REVIEW · none', tone: 'neutral' }
  return { text: `REVIEW · UNKNOWN${f.reason ? ` · ${f.reason}` : ''}`, tone: 'warning' }
}

export function ciLabel2(f: Factor<CiState>): { text: string; tone: Tone } {
  if (f.state === 'GREEN') return { text: 'CI · green', tone: 'success' }
  if (f.state === 'RED') return { text: 'CI · red', tone: 'danger' }
  if (f.state === 'PENDING') return { text: 'CI · pending', tone: 'info' }
  if (f.state === 'SKIPPED') return { text: 'CI · skipped', tone: 'neutral' }
  return { text: `CI · UNKNOWN${f.reason ? ` · ${f.reason}` : ''}`, tone: 'warning' }
}

export function agentStateTone(s: AgentState): Tone {
  if (s === 'working') return 'success'
  if (s === 'blocked') return 'danger'
  if (s === 'waiting') return 'info'
  if (s === 'idle') return 'neutral'
  return 'warning'
}

/** The coordination envelope. A partial read is labelled PARTIAL and never renders as a clean OK. */
export function normalizeCoordination(raw: unknown): CoordinationBlock {
  const missing: CoordinationBlock = {
    present: false, status: 'UNAVAILABLE', as_of: null, source: null,
    reason: 'agents/claims not in this response (backend predates the coordination envelope)', agents: [],
  }
  if (!raw || typeof raw !== 'object') return missing
  const c = raw as Record<string, unknown>
  const status = String(c.status ?? '').trim().toUpperCase()
  const known = status === 'OK' || status === 'PARTIAL' || status === 'UNAVAILABLE' ? status : 'UNAVAILABLE'
  const agentsRaw = Array.isArray(c.agents) ? c.agents : []
  const agents: CoordinationAgent[] = []
  for (const a of agentsRaw) {
    if (!a || typeof a !== 'object') continue
    const o = a as Record<string, unknown>
    const session = asText(o.session)
    if (!session) continue
    const st = String(o.state ?? '').trim().toLowerCase() as AgentState
    const pr = Number(o.pr)
    agents.push({
      session,
      agent: asText(o.agent),
      task: asText(o.task),
      state: (AGENT_STATES as string[]).includes(st) ? st : 'unknown',
      branch: asText(o.branch),
      pr: Number.isFinite(pr) && pr > 0 ? pr : null,
      blocker: asText(o.blocker),
      next_action: asText(o.next_action),
      as_of: asText(o.as_of),
      source: asText(o.source),
    })
  }
  return {
    present: true,
    status: known,
    as_of: asText(c.as_of),
    source: asText(c.source),
    reason: asText(c.reason) ?? (status && !known ? `unrecognised coordination status "${status}"` : null),
    agents,
  }
}

/** Facts the page shows for one row, all head-bound, for a single testable projection. */
export function rowFacts(p: InFlightPr) {
  return {
    owner: p.work.owner ?? 'UNKNOWN · owner not stated',
    task: p.work.current_task ?? 'UNKNOWN · task not stated',
    publication: publicationLabel(p.work),
    draft: draftLabel(p),
    review: reviewLabel(p.work.review),
    ci: ciLabel2(p.work.ci),
    blockers: p.work.blockers,
    next: nextActionFor(p),
    asOf: p.work.as_of ?? null,
    source: p.work.source ?? null,
  }
}
