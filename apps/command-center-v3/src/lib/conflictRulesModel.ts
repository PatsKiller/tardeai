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

/** RuleProposal@v1 / RuleProposalCollection@v1 — contract in docs/ops/CONFLICT_RULE_PROPOSALS.md (branch
 *  feat/conflict-rule-proposals-20261025). Fields are read tolerantly: a missing field shows "not supplied", never a guess. */
export type ProposalSide = {source?: string | null; source_label?: string | null; value: unknown; as_of?: string | null}
export type UnmatchedExample = {key: string; summary?: string | null; sides?: ProposalSide[]; subject?: {kind?: string; id?: string; label?: string | null} | null}
export type UnmatchedRow = {
  signature: string; summary?: string | null; examples?: UnmatchedExample[]; first_seen?: string | null; last_seen?: string | null
  proposal_status?: string | null; proposal_id?: string | null
  policy?: {tier?: string; never_auto?: boolean} | null
  last_failure?: {at?: string; reason?: string; detail?: string} | null
}
export type RuleProposal = {
  schema?: string; proposal_id: string; status?: string | null; revision?: number; signature?: string | null
  summary?: string | null; plain_rule?: string | null; tier?: string | null
  never_auto?: boolean; never_auto_implications?: string | null; auto_resolvable?: boolean
  proposed_resolution?: {finding_key?: string; resolution?: string}[] | string | null
  example_findings?: string[] | null; risks?: string[] | null; test_cases?: unknown[] | null
  model?: {model_id?: string | null; provider?: string | null; mock?: boolean} | string | null
  created_at?: string | null; confidence?: number | null
  decision?: {decision?: string; reason?: string; actor?: string; at?: string; amendment_id?: string | null} | null
}
export type ProposalCollection = {
  schema?: string; proposals?: RuleProposal[]; unmatched?: UnmatchedRow[]; total?: number
  counts?: {pending?: number; approved?: number; rejected?: number; unmatched_awaiting_ai?: number}
  decisions_enabled?: boolean
  rulebook?: {version?: string | number; base_version?: number; amendment_count?: number; status?: string} | null
}
export type DecisionAction = 'approve' | 'edit-and-approve' | 'reject'
export const TIERS = ['T0', 'T1', 'T2', 'T3', 'T4'] as const

export function isPending(proposal: RuleProposal): boolean {
  return String(proposal.status || '').toUpperCase() === 'PENDING'
}

export function pendingProposals(collection: ProposalCollection | null | undefined): RuleProposal[] {
  return (collection?.proposals || []).filter(isPending)
}

export function proposalTestCount(proposal: RuleProposal): number | null {
  return Array.isArray(proposal.test_cases) ? proposal.test_cases.length : null
}

export function proposalResolutions(proposal: RuleProposal): string[] {
  const raw = proposal.proposed_resolution
  if (typeof raw === 'string') return raw.trim() ? [raw] : []
  return Array.isArray(raw) ? raw.map(item => item?.resolution || '').filter(Boolean) : []
}

export function proposalModel(proposal: RuleProposal): string {
  const raw = proposal.model
  if (typeof raw === 'string') return raw || 'model not recorded'
  if (!raw) return 'model not recorded'
  const name = [raw.provider, raw.model_id].filter(Boolean).join(' · ') || 'model not recorded'
  return raw.mock ? `${name} (mock)` : name
}

/** Example cases for a proposal: the collection's unmatched pattern with the same signature. */
export function proposalCases(proposal: RuleProposal, collection: ProposalCollection | null | undefined): UnmatchedExample[] {
  const row = (collection?.unmatched || []).find(u => u.signature && u.signature === proposal.signature)
  return row?.examples || []
}

/** Unmatched rows still waiting for the AI (no proposal yet). The status words are the server's, never inferred. */
export function awaitingAi(collection: ProposalCollection | null | undefined): UnmatchedRow[] {
  return (collection?.unmatched || []).filter(row => !row.proposal_id)
}

export function unmatchedStatus(row: UnmatchedRow): string {
  const words = row.proposal_status || (row.proposal_id ? 'Proposal status not supplied' : 'AI proposal pending')
  return row.last_failure?.reason ? `${words} · last attempt failed: ${row.last_failure.reason.replace(/_/g, ' ')}` : words
}

export type Edited = {plain_rule: string; tier: string}

export function decisionBody(action: DecisionAction, reason: string, proposal: RuleProposal, edited: Edited, applyCurrentCase: boolean) {
  const why = reason.trim()
  if (!why) return {ok: false as const, error: 'Write a short reason. It is recorded with your decision.'}
  if (typeof proposal.revision !== 'number') return {ok: false as const, error: 'The proposal revision is missing. Refresh the page and try again.'}
  const base = {decision: action, reason: why, expected_revision: proposal.revision}
  if (action === 'reject') return {ok: true as const, body: base}
  if (action === 'edit-and-approve') {
    const text = edited.plain_rule.trim()
    if (!text) return {ok: false as const, error: 'The edited rule text is empty.'}
    const change: {plain_rule?: string; tier?: string} = {}
    if (text !== (proposal.plain_rule || '').trim()) change.plain_rule = text
    if (edited.tier && edited.tier !== proposal.tier) change.tier = edited.tier
    if (!Object.keys(change).length) return {ok: false as const, error: 'Nothing was edited. Use Approve, or change the rule first.'}
    return {ok: true as const, body: {...base, edited: change, apply_current_case: applyCurrentCase}}
  }
  return {ok: true as const, body: {...base, apply_current_case: applyCurrentCase}}
}

/** Error envelope → words. NEVER_AUTO_REFUSED's reason is shown verbatim (contract §5). */
export function decisionError(status: number, envelope: {error?: string; reason?: string} | null): string {
  const code = envelope?.error || `HTTP ${status}`
  const words: Record<string, string> = {
    PROPOSAL_DECISIONS_NOT_ACTIVATED: 'Approval activation is pending',
    PROPOSAL_CHANGED: 'The proposal changed since you opened it. Refresh and review it again',
    PROPOSAL_NOT_PENDING: 'This proposal was already decided',
    AGENT_CALLER_REFUSED: 'Only the operator can decide rule proposals',
    CSRF_REFUSED: 'The request was refused by the same-origin check',
  }
  if (code === 'NEVER_AUTO_REFUSED') return envelope?.reason || 'This rule can never be resolved automatically'
  return words[code] ? `${words[code]} (${code})` : `${code}${envelope?.reason ? `: ${envelope.reason}` : ''}`
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
