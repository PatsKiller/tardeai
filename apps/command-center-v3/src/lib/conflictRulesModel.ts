/** Conflict rules page model. Formatting and validation only: the engine and the rulebook decide,
 *  every threshold arrives from GET /api/v3/conflicts/rulebook (No Hardcoded Values). */

export type CodeRef = {path: string; match: string; found: boolean}
export type TestRef = {path: string; name: string; found: boolean}
export type RuleCoverage = {status: 'IMPLEMENTED' | 'MISSING' | string; code: CodeRef[]; tests: TestRef[]; gap_note?: string | null}
export type MatrixRule = {
  id: string; title: string; means: string; example: string; clears: string; owner: string
  exact_text: string; limits_from?: string | null; coverage: RuleCoverage
}
export type Tier = {id: string; name: string; means: string; example: string}
export type ScaleStep = {step: number; primary: string; labels: string[]}
export type ConcentrationRow = {key: string; label: string; limit_pct: number | null; near_limit_pct: number | null; detection: string | null}
export type LifecycleState = {state: string; means: string; who: string}
export type Gap = {reason?: string; [key: string]: unknown} | null

export type RulebookView = {
  schema: 'ConflictRulebookView@v1'
  rulebook: {
    status: string | null; version: number | null; approval: unknown; live_enabled: boolean; matrix_sha256: string | null
    matrix_check: {verified: boolean | null; reason: string | null; actual_sha256?: string}
    rulebook_sha256: string; source?: string | null; engine_version?: string | null; matrix_source?: string | null
  }
  text_gap: Gap
  tiers: Tier[]
  t4_order: {key: string; rank: number; label: string}[]
  rules: MatrixRule[]
  coverage_summary: {implemented: number; missing: number; total: number}
  never_auto: {id: string; label: string | null}[]
  never_auto_matrix_text?: string | null
  action_scale: {held: ScaleStep[]; not_held: ScaleStep[]; text: {held?: string; not_held?: string; rule?: string}}
  thresholds: Record<string, unknown>
  concentration: {rows: ConcentrationRow[]; near_limit_fraction?: number | null; midrange_note?: string | null; scope?: string | null
    approval_ref?: string | null; as_of?: string | null; source?: string; gap: Gap}
  lifecycle: {states: LifecycleState[]; active_states: string[]; terminal_states: string[]; cadence_design?: string | null
    last_run: {phase?: string; status?: string; finished_at?: string | null; findings_count?: number} | null}
  live: {by_kind: Record<string, number>; by_state: Record<string, number>; open_total: number | null; gap: Gap; as_of?: string | null}
}

/** Assumed RuleProposal@v1 shape (backend: feat/conflict-rule-proposals-20261025, docs/ops/CONFLICT_RULE_PROPOSALS.md).
 *  Every field is optional-tolerant so a missing field shows "not supplied" rather than an invented value. */
export type UnmatchedCase = {key: string; summary?: string | null; subject_label?: string | null
  sides?: {source?: string | null; source_label?: string | null; value: unknown; as_of?: string | null}[]}
export type RuleProposal = {
  schema?: string; id: string; state?: string | null; created_at?: string | null; model?: string | null; revision?: number
  unmatched_cases?: UnmatchedCase[]
  proposed_rule?: {id?: string | null; title?: string | null; text?: string | null; tier?: string | null} | null
  proposed_resolution?: string | {summary?: string | null; text?: string | null} | null
  risks?: string[] | null; test_cases?: unknown[] | null; test_case_count?: number | null
  decision?: {decision?: string; reason?: string; actor?: string; at?: string} | null
}
export type ProposalCollection = {proposals?: RuleProposal[]; gap?: Gap}
export type DecisionAction = 'approve' | 'edit-and-approve' | 'reject'

const PENDING = new Set(['PENDING', 'PROPOSED', 'AWAITING_APPROVAL', 'AWAITING_OPERATOR'])

export function isPending(proposal: RuleProposal): boolean {
  return PENDING.has(String(proposal.state || '').toUpperCase())
}

export function pendingProposals(collection: ProposalCollection | null | undefined): RuleProposal[] {
  return (collection?.proposals || []).filter(isPending)
}

export function proposalTestCount(proposal: RuleProposal): number | null {
  if (Array.isArray(proposal.test_cases)) return proposal.test_cases.length
  return typeof proposal.test_case_count === 'number' && Number.isFinite(proposal.test_case_count) ? proposal.test_case_count : null
}

export function proposalResolution(proposal: RuleProposal): string {
  const raw = proposal.proposed_resolution
  if (typeof raw === 'string' && raw.trim()) return raw
  if (raw && typeof raw === 'object') return raw.summary || raw.text || 'Proposed resolution not supplied'
  return 'Proposed resolution not supplied'
}

/** Label for an open UNMATCHED conflict: only what the proposal store says, never inferred. */
export function unmatchedStatus(key: string, collection: ProposalCollection | null | undefined, available: boolean): string {
  if (!available) return 'AI proposal status unavailable'
  const linked = (collection?.proposals || []).filter(p => (p.unmatched_cases || []).some(c => c.key === key))
  if (linked.some(isPending)) return 'AI proposal pending — awaiting your approval'
  const decided = linked.find(p => p.state)
  if (decided) return `AI proposal ${String(decided.state).toLowerCase().replace(/_/g, ' ')}`
  return 'AI proposal pending — not drafted yet'
}

export function decisionBody(action: DecisionAction, reason: string, editedText: string, original: string | null | undefined, revision?: number) {
  const why = reason.trim()
  if (!why) return {ok: false as const, error: 'Write a short reason. It is recorded with your decision.'}
  if (action === 'edit-and-approve') {
    const text = editedText.trim()
    if (!text) return {ok: false as const, error: 'The edited rule text is empty.'}
    if (text === (original || '').trim()) return {ok: false as const, error: 'The rule text is unchanged. Use Approve, or edit the text first.'}
    return {ok: true as const, body: {decision: action, reason: why, edited_rule_text: text, ...(revision !== undefined ? {expected_revision: revision} : {})}}
  }
  return {ok: true as const, body: {decision: action, reason: why, ...(revision !== undefined ? {expected_revision: revision} : {})}}
}

export const ACTION_WORDS: Record<DecisionAction, {verb: string; confirm: string; done: string}> = {
  approve: {verb: 'Approve', confirm: 'Confirm approve', done: 'approved'},
  'edit-and-approve': {verb: 'Edit then approve', confirm: 'Confirm edit and approve', done: 'approved with your edit'},
  reject: {verb: 'Reject', confirm: 'Confirm reject', done: 'rejected'},
}

const KIND_ORDER = ['NEEDS_OPERATOR', 'GATE', 'CONFLICT', 'UNMATCHED', 'DATA_ERROR', 'SUPERSEDED', 'AGREEMENT']
const KIND_WORDS: Record<string, string> = {
  NEEDS_OPERATOR: 'Waiting on you', GATE: 'Blocked by a check', CONFLICT: 'Real conflicts', UNMATCHED: 'No rule matched',
  DATA_ERROR: 'Data errors', SUPERSEDED: 'Superseded', AGREEMENT: 'Agreements',
}

export function liveCountRows(byKind: Record<string, number>): {kind: string; label: string; count: number}[] {
  return Object.entries(byKind)
    .sort(([a], [b]) => (KIND_ORDER.indexOf(a) + 1 || 99) - (KIND_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b))
    .map(([kind, count]) => ({kind, label: KIND_WORDS[kind] || kind.replace(/_/g, ' ').toLowerCase(), count}))
}

export function statusWords(view: RulebookView['rulebook']): {headline: string; tone: 'warning' | 'success'; live: string} {
  const status = String(view.status || 'UNKNOWN').toUpperCase()
  const approved = status === 'APPROVED' || status === 'ACTIVE'
  return {
    headline: approved ? `Rulebook ${status.toLowerCase()}` : `Rulebook ${status.toLowerCase()} — not yet approved by you`,
    tone: approved && view.live_enabled ? 'success' : 'warning',
    live: view.live_enabled ? 'Live: the engine\'s findings drive the site' : 'Not live: findings are shown for review only',
  }
}

export function fingerprint(sha: string | null | undefined): string {
  return sha ? `${sha.slice(0, 12)}…` : 'not pinned'
}

export function pct(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString('en-US', {maximumFractionDigits: 2})}%` : 'not set'
}

export function coverageWord(status: string | null | undefined): {label: string; tone: 'success' | 'danger'} {
  return status === 'IMPLEMENTED' ? {label: 'Implemented', tone: 'success'} : {label: 'Missing', tone: 'danger'}
}
