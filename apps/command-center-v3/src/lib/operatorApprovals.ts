import { useCallback, useEffect, useState } from 'react'

export const GOVERNANCE = '/api/v2/governance'
export type Change = { id: string; section: string; before: string; after: string; kind: string; plain: string | null; reason: string | null; before_offset?: number | null; after_offset?: number | null }
export type ReviewDocument = { text: string; base_text: string; source_sha: string; version: string; document_sha: string; source_verified: boolean; changes: Change[]; sections: string[]; prechecks: { sensitive_sections: string[]; removed_blocks: number; weakens_rules: string; policy_tests: { state?: string; reason?: string } } }
export type ApprovalItem = { id: string; title: string; kind: string; proposed_by: string | null; created_at: string | null; source: string; governed_href: string | null; decision_mode: string; document?: ReviewDocument; document_sha?: string; version?: string; pr?: number | null }
export type Decision = { actor: string; item_id: string; decision: string; document_sha: string; at: string; policy_token?: string; comment?: string }
export type ApprovalQueue = { items: ApprovalItem[]; pending_count: number | null; known_pending_count: number; complete: boolean; gaps: { source: string; reason: string }[]; as_of: string; recent: Decision[]; filtered_count: number; offset: number }
export type Rule = { id: string; section: string; text: string; plain: string | null; status: string; reason: string | null; evidence: Record<string, unknown> }
export type PolicyVersionDecision = { decision: string; actor: string; at: string; policy_token?: string | null; effect?: string; relay?: string }
export type PendingPolicyVersion = { id: string; pr: number; title: string; proposed_by: string | null; created_at: string | null; version: string; status: string; row_status: string | null; classification: string | null; awaits_token: boolean; head_sha: string; document_sha: string; changes: number; sensitive_sections: string[]; token: string | null; decision: PolicyVersionDecision | null; earlier_head_decisions: number; review: { started: boolean; read: number; total: number; expired: boolean } | null; can_approve: boolean }
export type PolicyVersions = { current: { version: string | null; status: string | null; effective_date: string | null; supersedes: string | null; row_status: string | null; source_sha: string; consistent: boolean; errors: string[] }; pending: PendingPolicyVersion[]; pending_count: number | null; known_pending_count: number; complete: boolean; gaps: { source: string; reason: string }[]; as_of: string; operator: boolean; github_write_path: string | null; approval_rule: string }
export type Policy = { source_sha: string; document_sha: string; sections: string[]; rules: Rule[]; counts: Record<string, number>; total_rules: number; section_total: number; offset: number; positions: { position: string; rule_id: string }[]; audit: { state: string; last_audit: string | null; scope?: string; mapped_count?: number; unmapped_count?: number; reviewer_called?: boolean; findings?: { title: string; detail: string }[] } }

const messages: Record<string, string> = {
  STORE_APPROVAL_PENDING: 'Decision recording is awaiting the operator’s data-source sign-off.',
  DOCUMENT_CHANGED: 'This document changed. Reload it and read the new changes before deciding.',
  REVIEW_EXPIRED: 'Your reading session expired. Start reading this version again.',
  CHANGES_UNREAD: 'Read every highlighted change before approving.',
  GOVERNED_ACTION_REQUIRED: 'Continue to the existing operator controls to complete this decision.',
  POLICY_BINDING_REQUIRED: 'The exact policy PR and commit must be verified before approval.',
  CSRF_REFUSED: 'This request could not be verified. Reload the page and try again.',
  AGENT_CALLER_REFUSED: 'Only your authenticated operator session can record a decision.',
  TOKEN_MISMATCH: 'The approval token does not match this exact PR head. Reload and try again.',
  NOT_PROPOSED: 'This PR no longer proposes a new version.',
  ALREADY_DECIDED: 'A decision is already recorded for this exact version.',
}

/** Decision/question request ids. crypto.randomUUID exists only in secure contexts; getRandomValues works everywhere
 *  (an http:// fixture or a non-TLS tailnet hop must not turn Approve into "randomUUID is not a function"). */
export function governanceRequestId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  c?.getRandomValues(bytes)
  return 'req-' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

export async function governanceRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal })
  const envelope = await response.json()
  if (!response.ok || envelope.ok !== true) throw new Error(messages[envelope.error] ?? 'The latest evidence is unavailable. Please try again.')
  return envelope.data as T
}

export function useGovernance<T>(path: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(n => n + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError('')
    governanceRequest<T>(path, undefined, controller.signal).then(setData).catch(err => {
      if (!controller.signal.aborted) setError(err.message)
    })
    return () => controller.abort()
  }, [path, revision])
  return { data, error, refresh }
}

export function waitingSince(value: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Waiting time unavailable'
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 60000))
  return minutes < 60 ? `${minutes} min` : minutes < 1440 ? `${Math.floor(minutes / 60)} h` : `${Math.floor(minutes / 1440)} d`
}

export const KIND_LABEL: Record<string, string> = { POLICY: 'Policy', RELEASE: 'Release', SPEND: 'Spending', ACTIVATE: 'Activation', DESIGN: 'Design', CONFLICT: 'Conflict', FINDING: 'Finding', FINANCIAL: 'Trade review' }

export async function askAboutRule(question: string, section: string, text: string, documentSha: string, sourceSha: string): Promise<string | null> {
  const answer = await governanceRequest<{ thread_id?: string }>('/api/v2/cio/ask', {
    question: `${question}\n\nAttached rule: ${section}\nDocument SHA: ${documentSha}\nCommit: ${sourceSha}\n${text}`,
    client_request_id: governanceRequestId(),
  })
  return answer.thread_id ?? null
}
