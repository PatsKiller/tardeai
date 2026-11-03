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

import type { PipelineStage } from './workPipeline'

export type Mergeable = 'MERGEABLE' | 'CONFLICTING' | 'UNKNOWN'
export type ReviewState = 'MERGE' | 'CHANGES' | 'NONE' | 'UNKNOWN'
export type CiState = 'GREEN' | 'RED' | 'PENDING' | 'SKIPPED' | 'UNKNOWN'
export type PublicationState = 'local_only' | 'published' | 'merged' | 'live' | 'unknown'
export type AgentState = 'assigned' | 'working' | 'blocked' | 'waiting' | 'idle' | 'unknown'
export type LegacyNext = 'auto-merge' | 'coordinator' | 'auto-rebase' | 'blocked-shard-hints'

export type Blocker = { text: string; kind: string | null; owner: string | null; as_of: string | null; source: string | null }

/** One head-bound fact: state as reported, the head it was measured on, when, from where, and why not. */
export type Factor<S extends string> = {
  state: S | 'UNKNOWN'
  reported: string | null
  head_sha: string | null
  as_of: string | null
  /** Which field the time came from. `observed_at` is the explicit old-ledger fallback, kept honest. */
  as_of_basis: 'as_of' | 'observed_at' | null
  source: string | null
  reason: string | null
  /** Present when the review was aggregated from several reviewers' verdicts. */
  verdicts?: ReviewVerdict[]
}

/** One reviewer's verdict at one head. Two verdicts for the same reviewer: the later one wins. */
export type ReviewVerdict = {
  verdict: ReviewState
  reviewer: string
  head_sha: string | null
  as_of: string | null
  source: string | null
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
  /** GitHub's own view of this head (cc2 review B1). The coordinator ledger is often UNKNOWN; without this
   *  the page told the operator nobody had reviewed anything on a PR whose checks were RED or GREEN. */
  github_evidence?: { ci?: { state?: string | null; source?: string | null; reason?: string | null }
    review?: { state?: string | null; source?: string | null; reason?: string | null } } | null
  evidence_state?: EvidenceState | null
  evidence_sources?: string[]
  blockers: Blocker[]
  next_action: string | null
  /** Where the next step came from (`worklog`, `claims`, `board_open_prs`, `none`). Display only. */
  next_action_source: string | null
  /** The BOARD's Open PRs owner, when the claim board has none. Context, never a verdict. */
  board_owner: string | null
  as_of: string | null
  source: string | null
  reason: string | null
}

export type CoordinationAgent = {
  session: string
  agent: string | null
  task: string | null
  state: AgentState
  /** The source's own word (BOARD "assigned", claim "building", …), kept so nothing is retyped into a nicer state. */
  reported_state: string | null
  /** What the claim proves about execution, when the source states it separately from assignment. */
  execution_state: AgentState | null
  /** Why execution is not `working`: no heartbeat, a stale one, or a clock-skewed one. */
  execution_reason: string | null
  /** More than one source row for this session: newest kept, count stated (never silently merged). */
  duplicate_rows: number
  branch: string | null
  pr: number | null
  blocker: string | null
  next_action: string | null
  as_of: string | null
  /** The claim's own heartbeat — present even when the BOARD row carries no time. */
  claim_as_of?: string | null
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

/** How a review/CI fact is known, in the operator's words (row 05; cc3's wire contract, 2026-11-03).
 *
 *  `UNKNOWN` on the page is a symptom, not an answer: four different situations produced it and the operator could
 *  not tell "we never looked" from "we looked at a different version". Each state gets one plain sentence, and an
 *  unrecognised state is never silently turned into a pass. */
/** Which pipeline stage a PR row is at, from its own facts — then `operatorStage()` gives the plain-English group.
 *
 *  Deliberately conservative: an unknown fact lands in the earliest stage that is still TRUE ("being built"), never in
 *  "ready" or "live", because telling the operator something is ready when we cannot see its review is the failure this
 *  page exists to stop. */
export function prPipelineStage(pr: Pick<InFlightPr, 'has_operator_merge' | 'is_draft' | 'mergeable' | 'work'>): PipelineStage {
  const pub = pr.work?.publication_state
  if (pub === 'merged' || pub === 'live') return pub === 'merged' ? 'merged' : 'released'
  if (pr.has_operator_merge) return 'in_batch'
  if (pr.is_draft || pub === 'local_only') return 'building'
  if (pr.mergeable === 'CONFLICTING') return 'pr_open'
  const review = pr.work?.review?.state
  const ci = pr.work?.ci?.state
  if (review === 'MERGE' && ci === 'GREEN') return 'approved'
  return 'pr_open'
}

export type EvidenceState = 'OBSERVED' | 'PARTIAL' | 'STALE_OTHER_HEAD' | 'TARGET_HEAD_MISSING' | 'NOT_RECORDED'
  | 'SOURCE_UNAVAILABLE'

/** The served wire states (cc3 contract, 2026-11-03) plus the local SOURCE_UNAVAILABLE kept for older payloads. */
export const EVIDENCE_SENTENCE: Record<EvidenceState, string> = {
  OBSERVED: 'checked',
  PARTIAL: 'partly checked — one of the sources did not answer',
  STALE_OTHER_HEAD: 'checked, but for an older version of the change',
  TARGET_HEAD_MISSING: 'the check refers to a version that is no longer the one proposed',
  NOT_RECORDED: 'no check is recorded',
  SOURCE_UNAVAILABLE: 'the record of the check could not be read',
}

export function evidenceState(v: unknown): EvidenceState | null {
  const raw = String(v ?? '').trim().toUpperCase()
  return raw in EVIDENCE_SENTENCE ? (raw as EvidenceState) : null
}

/** The sentence for a raw state; null when the state is not one we know (callers say "unknown, and why"). */
export function evidenceSentence(v: unknown): string | null {
  const st = evidenceState(v)
  return st ? EVIDENCE_SENTENCE[st] : null
}

/** What the OPERATOR may do on this row, as the server decided it (row 05, cc3 contract 2026-11-03).
 *  `eligible` is the authority: a button is rendered only when its action is listed there. `withheld` explains an
 *  action that exists but is not the operator's, so a missing button can say why instead of vanishing. */
export type OperatorActions = {
  required: boolean
  eligible: Array<'approve' | 'hold' | 'push'>
  reason: string | null
  withheld?: Array<{ action: string; why: string | null }>
}

function normalizeOperatorActions(raw: unknown): OperatorActions | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const eligible = Array.isArray(o.eligible) ? o.eligible.filter((a): a is 'approve' | 'hold' | 'push' =>
    a === 'approve' || a === 'hold' || a === 'push') : []
  const withheld = Array.isArray(o.withheld) ? o.withheld.filter((w): w is { action: string; why: string | null } =>
    !!w && typeof w === 'object').map(w => ({ action: String((w as any).action ?? ''), why: (w as any).why ? String((w as any).why) : null })) : []
  return { required: o.required === true, eligible, reason: o.reason ? String(o.reason) : null, withheld }
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
  operator_actions?: OperatorActions | null
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
  const s = asString(sha).trim()
  return s ? s.slice(0, 9) : '—'
}

/**
 * A JSON value → a primitive string WITHOUT coercing an object. `String({toString: "x"})` throws
 * "Cannot convert object to primitive value", so every untrusted state/word goes through this guard at
 * normalization time — before any String(), trim() or toUpperCase() can reach it.
 */
const asString = (v: unknown): string =>
  typeof v === 'string' ? v
    : typeof v === 'number' ? (Number.isFinite(v) ? String(v) : '')
      : typeof v === 'boolean' ? String(v)
        : ''

const asText = (v: unknown): string | null => {
  if (typeof v !== 'string') return null
  const s = v.trim()
  return s && s.toLowerCase() !== 'unknown' ? s : null
}

/** GitHub's `mergeable` is an enum STRING; older mocks/backends sent a boolean. UNKNOWN stays UNKNOWN. */
export function normalizeMergeable(v: unknown): Mergeable {
  if (v === true) return 'MERGEABLE'
  if (v === false) return 'CONFLICTING'
  const s = asString(v).trim().toUpperCase()
  if (s === 'MERGEABLE') return 'MERGEABLE'
  if (s === 'CONFLICTING') return 'CONFLICTING'
  return 'UNKNOWN'
}

const PUBLICATION: PublicationState[] = ['local_only', 'published', 'merged', 'live', 'unknown']
const AGENT_STATES: AgentState[] = ['assigned', 'working', 'blocked', 'waiting', 'idle', 'unknown']
/** Source words → an honest state. A claim stage is a DECLARATION, never proof of execution: only a fresh
 *  heartbeat yields `working`, so `building` reads as `assigned` until execution is proven. */
const AGENT_STATE_MAP: Record<string, AgentState> = {
  ASSIGNED: 'assigned', CLAIMED: 'assigned', TAKEN: 'assigned', QUEUED: 'assigned',
  BUILDING: 'assigned', WORKING: 'assigned', IN_PROGRESS: 'assigned', ACTIVE: 'assigned',
  BLOCKED: 'blocked', BLOCKER: 'blocked', FAILED: 'blocked',
  WAITING: 'waiting', PR_OPEN: 'waiting', REVIEW: 'waiting',
  IDLE: 'idle', DONE: 'idle', MERGED: 'idle', ABANDONED: 'idle', ENDED: 'idle',
}

function emptyWork(reason: string): WorkBlock {
  const unknown = <S extends string>(r: string): Factor<S> => ({ state: 'UNKNOWN', reported: null, head_sha: null, as_of: null, as_of_basis: null, source: null, reason: r })
  return {
    present: false, owner: null, current_task: null, publication_state: 'unknown', local_head: null, published_head: null,
    next_action_source: null, board_owner: null,
    review: unknown<ReviewState>(reason), ci: unknown<CiState>(reason), blockers: [], next_action: null,
    as_of: null, source: null, reason,
  }
}

/** The time a factor was measured. `observed_at` is the old-ledger field: accepted, and labelled as such. */
function pickAsOf(r: Record<string, unknown>): { as_of: string | null; as_of_basis: 'as_of' | 'observed_at' | null } {
  const direct = asText(r.as_of)
  if (direct) return { as_of: direct, as_of_basis: 'as_of' }
  const observed = asText(r.observed_at)
  if (observed) return { as_of: observed, as_of_basis: 'observed_at' }
  return { as_of: null, as_of_basis: null }
}

/** A CI factor, bound to the row's exact head. Any mismatch or missing head is UNKNOWN, never edited-in. */
export function normalizeFactor<S extends string>(
  raw: unknown, allowed: readonly S[], rowHead: string, label: string,
): Factor<S> {
  const unknown = (reason: string, extra: Partial<Factor<S>> = {}): Factor<S> =>
    ({ state: 'UNKNOWN', reported: null, head_sha: null, as_of: null, as_of_basis: null, source: null, reason, ...extra })
  if (!raw || typeof raw !== 'object') return unknown(`no typed ${label} receipt`)
  const r = raw as Record<string, unknown>
  const reportedRaw = asString(r.state).trim().toUpperCase()
  const reported = reportedRaw || null
  const head = asText(r.head_sha)
  const { as_of, as_of_basis } = pickAsOf(r)
  const base = { reported, head_sha: head, as_of, as_of_basis, source: asText(r.source) }
  const gap = asText(r.source_gap) ?? asText(r.gap)
  // The backend states UNKNOWN and its own gap; that gap is a better reason than "names no head".
  if (reported === 'UNKNOWN' && gap) return { ...unknown(gap, base) }
  if (!rowHead) return { ...unknown('row head not stated — cannot bind', base) }
  if (!head) return { ...unknown(`${label} receipt names no head`, base) }
  if (head !== rowHead) return { ...unknown(`head_changed: receipt ${shortSha(head)} ≠ row ${shortSha(rowHead)}${gap ? ` (${gap})` : ''}`, base) }
  if (!reported || !allowed.includes(reported as S)) {
    return { ...unknown(`unrecognised ${label} state ${reported ? `"${reportedRaw}"` : '(missing or non-text value)'}`, base) }
  }
  if (gap) return { ...unknown(gap, base) }
  return { state: reported as S, ...base, reason: null }
}

const VERDICT: Record<string, ReviewState> = {
  MERGE: 'MERGE', MERGED: 'MERGE', APPROVE: 'MERGE', APPROVED: 'MERGE', LGTM: 'MERGE',
  BLOCK: 'CHANGES', BLOCKED: 'CHANGES', CHANGES: 'CHANGES', 'REQUEST_CHANGES': 'CHANGES', 'CHANGES_REQUESTED': 'CHANGES', REJECT: 'CHANGES',
  NONE: 'NONE', COMMENT: 'NONE', COMMENTS: 'NONE',
}

/**
 * The review state for one head, from whatever the ledger sent: a single `state`, or a `verdicts`/`records`
 * array. BLOCK / CHANGES dominate — a single block makes the review not-green even beside MERGE verdicts.
 * The latest verdict per reviewer wins (ledger order, then as_of). A record COUNT is not a verdict: a
 * response that only carries `count` stays UNKNOWN, because counting "merge" records is not review.
 */
export function normalizeReview(raw: unknown, rowHead: string): Factor<ReviewState> {
  const unknown = (reason: string, extra: Partial<Factor<ReviewState>> = {}): Factor<ReviewState> =>
    ({ state: 'UNKNOWN', reported: null, head_sha: null, as_of: null, as_of_basis: null, source: null, reason, ...extra })
  if (!raw || typeof raw !== 'object') return unknown('no typed review receipt')
  const r = raw as Record<string, unknown>

  const listed = Array.isArray(r.records) ? r.records : Array.isArray(r.verdicts) ? r.verdicts : null
  const envelopeHead = asText(r.head_sha)
  const { as_of, as_of_basis } = pickAsOf(r)
  const source = asText(r.source)
  const gap = asText(r.source_gap) ?? asText(r.gap)
  if (!rowHead) return unknown('row head not stated — cannot bind', { head_sha: envelopeHead, as_of, as_of_basis, source })
  // An envelope that names a different head contradicts any member that names this one. Contradiction is
  // UNKNOWN — the two claims cannot both be the review of this head.
  if (envelopeHead && envelopeHead !== rowHead) {
    return unknown(`head_changed: review envelope ${shortSha(envelopeHead)} ≠ row ${shortSha(rowHead)}`, { head_sha: envelopeHead, as_of, as_of_basis, source })
  }
  if (!listed && asString(r.state).toUpperCase() === 'UNKNOWN' && gap) {
    return unknown(gap, { head_sha: envelopeHead, as_of, as_of_basis, source })
  }

  if (listed) {
    const parsed: ReviewVerdict[] = []
    let unrecognised = 0
    for (const v of listed) {
      const o = (v && typeof v === 'object' ? v : { verdict: v }) as Record<string, unknown>
      const word = asString(o.verdict ?? o.state).trim().toUpperCase()
      const st = VERDICT[word]
      if (!st) { unrecognised++; continue }               // remembered, never silently dropped
      const head = asText(o.head_sha) ?? envelopeHead
      if (head !== rowHead) continue                     // a verdict on another head is not this head's review
      const at = asText(o.as_of) ?? asText(o.observed_at)
      parsed.push({ verdict: st, reviewer: asText(o.reviewer) ?? asText(o.reviewer_session) ?? asText(o.by) ?? asText(o.session) ?? `#${parsed.length}`, head_sha: head, as_of: at, source: asText(o.source) ?? source })
    }
    if (!parsed.length) return unknown(gap ?? `no verdict on head ${shortSha(rowHead)}`, { head_sha: envelopeHead, as_of, as_of_basis, source })
    // Latest per reviewer: ledger order decides ties (a later record is appended later).
    const latest = new Map<string, ReviewVerdict>()
    parsed.forEach((v) => {
      const prev = latest.get(v.reviewer)
      if (!prev || !v.as_of || !prev.as_of || String(v.as_of) >= String(prev.as_of)) latest.set(v.reviewer, { ...v, reviewer: `${v.reviewer}` })
    })
    const verdicts = [...latest.values()]
    const blocks = verdicts.filter(v => v.verdict === 'CHANGES')
    const merges = verdicts.filter(v => v.verdict === 'MERGE')
    const envelope = asString(r.state).trim().toUpperCase()
    // BLOCK dominates — including a backend that reports blocked while its records disagree.
    const envelopeBlocked = ['BLOCK', 'BLOCKED', 'CHANGES', 'CHANGES_REQUESTED', 'REJECT'].includes(envelope)
    // Beyond that, a mixed or unrecognised set is UNKNOWN — never MERGE from the survivors alone, and never
    // an upgrade of an UNKNOWN the backend itself reported.
    const uncertain = unrecognised > 0 || envelope === 'UNKNOWN'
    const state: ReviewState = blocks.length || envelopeBlocked ? 'CHANGES' : uncertain || !merges.length ? 'UNKNOWN' : 'MERGE'
    const reason = blocks.length
      ? `${blocks.length} blocking verdict${blocks.length > 1 ? 's' : ''}${merges.length ? ` vs ${merges.length} merge (conflicting_verdicts)` : ''}: ${blocks.map(b => b.reviewer).join(', ')}`
      : envelopeBlocked
        ? `backend reports the review ${envelope}${merges.length ? ' while its records read merge — the backend verdict wins' : ''}`
        : uncertain
          ? `${unrecognised ? `${unrecognised} unrecognised verdict(s)` : 'backend reports the review UNKNOWN'}${merges.length ? ` beside ${merges.length} merge — mixed verdicts are not a pass` : ''}`
          : null
    const newest = verdicts.map(v => v.as_of).filter((x): x is string => !!x).sort().pop() ?? as_of
    return { state, reported: state, head_sha: envelopeHead ?? rowHead, as_of: newest, as_of_basis: newest === as_of ? as_of_basis : 'as_of', source, reason, verdicts }
  }

  // A bare count is not a verdict.
  if (r.count !== undefined && r.state === undefined) {
    return unknown('record count is not a review verdict', { head_sha: envelopeHead, as_of, as_of_basis, source })
  }
  return normalizeFactor<ReviewState>(raw, ['MERGE', 'CHANGES', 'NONE'], rowHead, 'review')
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

/** GitHub's check-rollup and review-decision words, in this module's factor states. */
const GH_CI: Record<string, string> = { GREEN: 'GREEN', RED: 'RED', PENDING: 'PENDING', UNAVAILABLE: 'UNKNOWN' }
const GH_REVIEW: Record<string, string> = {
  APPROVED: 'MERGE', CHANGES_REQUESTED: 'CHANGES', REVIEW_REQUIRED: 'NONE', NONE_REQUIRED: 'NONE', UNKNOWN: 'UNKNOWN',
}

/** GitHub observed this head: its verdict is the evidence, so it wins over a ledger that has no record. A ledger
 *  verdict that IS recorded still wins, because it is a review of the change by a person on the record. */
function withGithub<T extends { state: string; reason: string | null }>(ledger: T, gh: Record<string, unknown> | undefined,
  mapping: Record<string, string>): T {
  const raw = asString(gh?.state).trim().toUpperCase()
  const mapped = mapping[raw]
  if (!mapped) return ledger
  if (ledger.state !== 'UNKNOWN' && ledger.state !== 'NONE') return ledger
  const why = asString(gh?.reason).trim()
  // GitHub's own words matter: NONE_REQUIRED means no review is REQUIRED, not that nobody looked.
  const sentence = raw === 'NONE_REQUIRED' ? 'no review is required for this change'
    : mapped === 'UNKNOWN' && raw === 'UNAVAILABLE' ? 'CI not checked right now' : (why || null)
  return { ...ledger, state: mapped, reason: sentence }
}

/** One row's additive `work` block. Absent (old backend) is UNKNOWN with a reason, not a clean state. */
export function normalizeWork(raw: unknown, rowHead: string): WorkBlock {
  // An array is object-shaped to typeof but is not a work block: treat it as absent, never as facts.
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return emptyWork('work facts not in this response (backend predates the work block)')
  }
  const w = raw as Record<string, unknown>
  const gh = (w.github_evidence && typeof w.github_evidence === 'object'
    ? w.github_evidence as { ci?: Record<string, unknown>; review?: Record<string, unknown> } : null)
  const pub = asString(w.publication_state).trim().toLowerCase()
  const publication = (PUBLICATION as string[]).includes(pub) ? (pub as PublicationState) : 'unknown'
  return {
    present: true,
    owner: asText(w.owner),
    current_task: asText(w.current_task),
    publication_state: publication,
    local_head: asText(w.local_head),
    published_head: asText(w.published_head),
    review: withGithub(normalizeReview(w.review, rowHead), gh?.review, GH_REVIEW),
    ci: withGithub(normalizeFactor<CiState>(w.ci, ['GREEN', 'RED', 'PENDING', 'SKIPPED'], rowHead, 'ci'), gh?.ci, GH_CI),
    github_evidence: gh, evidence_state: evidenceState(w.evidence_state),
    evidence_sources: Array.isArray(w.evidence_sources) ? w.evidence_sources.map(String) : [],
    blockers: normalizeBlockers(w.blockers),
    next_action: asText(w.next_action),
    next_action_source: asText(w.next_action_source),
    board_owner: asText(w.board_owner),
    as_of: asText(w.as_of),
    source: asText(w.source),
    reason: asText(w.reason),
  }
}

/** The whole row → typed view. Per-row `work` is always present after this, so the renderer has one shape.
 *  A null or non-object member is rejected by the caller; anything object-shaped is projected defensively. */
export function normalizeRow(raw: unknown): InFlightPr {
  const pr = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const rawHead = asString(pr.head_sha ?? pr.headRefOid)
  const head = rawHead.trim()
  const legacy = asString(pr.next).trim() as LegacyNext
  return {
    number: Number(pr.number ?? 0),
    title: asString(pr.title),
    url: asString(pr.url),
    head_sha: head,
    head_sha_short: head ? head.slice(0, 9) : '—',
    branch: asString(pr.branch ?? pr.headRefName),
    has_operator_merge: pr.has_operator_merge === true,
    mergeable: normalizeMergeable(pr.mergeable),
    merge_state: asString(pr.merge_state ?? pr.mergeStateStatus).toUpperCase() || 'UNKNOWN',
    is_draft: pr.is_draft === true || pr.isDraft === true,
    // cc3 review F1 (2026-11-03): this object is explicit, so every served field must be named here or it is
    // silently lost. operator_actions was lost, so the page said 'Nothing needs you' while nine approvals waited.
    operator_actions: normalizeOperatorActions(pr.operator_actions),
    why_held: asText(pr.why_held),
    next: (['auto-merge', 'coordinator', 'auto-rebase', 'blocked-shard-hints'] as string[]).includes(legacy) ? legacy : 'coordinator',
    work: normalizeWork(pr.work, head),
  }
}

/** Project the whole `prs` array. A null/non-object member is dropped and COUNTED — never a crash, never silence. */
export function normalizeRows(raw: unknown): { rows: InFlightPr[]; dropped: number } {
  if (!Array.isArray(raw)) return { rows: [], dropped: 0 }
  const rows: InFlightPr[] = []
  let dropped = 0
  for (const p of raw) {
    if (p && typeof p === 'object') rows.push(normalizeRow(p))
    else dropped++
  }
  return { rows, dropped }
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
  if (f.state === 'MERGE') return { text: 'REVIEW · passed', tone: 'success' }
  if (f.state === 'CHANGES') return { text: `REVIEW · blocked${f.reason ? ` · ${f.reason}` : ''}`, tone: 'danger' }
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
  if (s === 'assigned') return 'info'
  if (s === 'working') return 'success'
  if (s === 'blocked') return 'danger'
  if (s === 'waiting') return 'info'
  if (s === 'idle') return 'neutral'
  return 'warning'
}

/** A claim proves execution for at most this long; the claim board's own staleness default is 2 h. */
export const WORKING_MAX_MS = 2 * 3600 * 1000
/** Small tolerance for clock drift; a heartbeat further in the future is skew, not evidence. */
const FUTURE_TOLERANCE_MS = 5 * 60_000

/**
 * Execution is a claim, not a label: `working` counts only with a heartbeat that is present, parseable,
 * not in the future and no older than 2 h. Anything else degrades to UNKNOWN with the reason, so a
 * backend that hardcodes `working` for a stale or heartbeat-less claim cannot make the page say so.
 */
export function executionState(raw: unknown, asOf: string | null, nowMs: number): { state: AgentState | null; reason: string | null } {
  const word = asString(raw).trim().toUpperCase()
  if (!word || word === 'UNKNOWN') return { state: null, reason: null }
  const claimsWorking = word === 'WORKING' || word === 'IN_PROGRESS' || word === 'ACTIVE'
  if (!claimsWorking) return { state: AGENT_STATE_MAP[word] ?? null, reason: null }
  if (!asOf) return { state: null, reason: 'execution claimed working with no heartbeat time' }
  const at = Date.parse(asOf)
  if (!Number.isFinite(at)) return { state: null, reason: 'execution heartbeat time is unreadable' }
  if (at - nowMs > FUTURE_TOLERANCE_MS) return { state: null, reason: 'execution heartbeat is in the future (clock skew)' }
  if (nowMs - at > WORKING_MAX_MS) return { state: null, reason: 'execution heartbeat is older than 2h' }
  return { state: 'working', reason: null }
}

/** The coordination envelope. A partial read is labelled PARTIAL and never renders as a clean OK. */
export function normalizeCoordination(raw: unknown, nowMs: number = Date.now()): CoordinationBlock {
  const missing: CoordinationBlock = {
    present: false, status: 'UNAVAILABLE', as_of: null, source: null,
    reason: 'agents/claims not in this response (backend predates the coordination envelope)', agents: [],
  }
  if (!raw || typeof raw !== 'object') return missing
  const c = raw as Record<string, unknown>
  const status = asString(c.status).trim().toUpperCase()
  const known = status === 'OK' || status === 'PARTIAL' || status === 'UNAVAILABLE' ? status : 'UNAVAILABLE'
  const agentsRaw = Array.isArray(c.agents) ? c.agents : []
  // One row per session: keep the newest as_of and say how many rows were folded, so a duplicate claim
  // cannot quietly keep an older branch/task (the multiclaim-join class).
  const bySession = new Map<string, CoordinationAgent>()
  const order: string[] = []
  for (const a of agentsRaw) {
    if (!a || typeof a !== 'object') continue
    const o = a as Record<string, unknown>
    const session = asText(o.session)
    if (!session) continue
    const reportedRaw = asString(o.state).trim()
    const st = reportedRaw.toUpperCase()
    // Execution is proven by the CLAIM's own heartbeat. On a BOARD row `as_of` is the BOARD's updated-at,
    // so using it would make a five-day-old claim look fresh (independent review, 2026-11-02).
    const claimAsOf = asText(o.claim_as_of)
    const sourceWord = asString(o.source).trim().toLowerCase()
    const heartbeat = claimAsOf ?? (sourceWord === 'claims' ? asText(o.as_of) : null)
    const { state: exec, reason: execReason } = executionState(o.execution_state, heartbeat, nowMs)
    const mapped = AGENT_STATE_MAP[st] ?? ((AGENT_STATES as string[]).includes(st.toLowerCase()) ? (st.toLowerCase() as AgentState) : 'unknown')
    // The chip may say WORKING only when execution is proven by a fresh heartbeat.
    const chipState: AgentState = mapped === 'working' && exec !== 'working' ? 'assigned' : mapped
    const pr = Number(o.pr)
    const row: CoordinationAgent = {
      session,
      agent: asText(o.agent),
      task: asText(o.task),
      state: chipState,
      reported_state: reportedRaw ? reportedRaw.toLowerCase() : null,
      execution_state: exec,
      execution_reason: execReason,
      duplicate_rows: 1,
      branch: asText(o.branch) ?? asText(o.branch_or_pr),
      pr: Number.isFinite(pr) && pr > 0 ? pr : null,
      blocker: asText(o.blocker),
      next_action: asText(o.next_action),
      as_of: asText(o.as_of),
      claim_as_of: claimAsOf,
      source: asText(o.source),
    }
    const prior = bySession.get(session)
    if (!prior) { bySession.set(session, row); order.push(session); continue }
    const newer = !prior.as_of && row.as_of ? true
      : prior.as_of && row.as_of ? Date.parse(row.as_of) >= Date.parse(prior.as_of) : false
    const kept = newer ? row : prior
    kept.duplicate_rows = prior.duplicate_rows + 1
    bySession.set(session, kept)
  }
  const agents = order.map(s => bySession.get(s)!).filter(Boolean)
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
    owner: p.work.owner ?? (p.work.board_owner ? `${p.work.board_owner} · BOARD context` : 'UNKNOWN · owner not stated'),
    task: p.work.current_task ?? 'UNKNOWN · task not stated',
    publication: publicationLabel(p.work),
    draft: draftLabel(p),
    review: reviewLabel(p.work.review),
    ci: ciLabel2(p.work.ci),
    blockers: p.work.blockers,
    next: nextActionFor(p),
    nextSource: p.work.next_action ? (p.work.next_action_source ?? null) : (p.work.present ? 'derived here' : null),
    asOf: p.work.as_of ?? null,
    source: p.work.source ?? null,
  }
}
