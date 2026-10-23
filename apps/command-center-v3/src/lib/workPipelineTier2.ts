// Work pipeline Tier 2 (operator 2026-10-23, "both"): the risky acts, each one Ops → Controls request
// (kinds pipeline.*, scripts/lib/work_pipeline_tier2.py): create → a fresh passkey assertion + the typed phrase the
// server shows → approve → the host applier executes it. No sudo window yet (PR 1970): every act asserts again.
// Merge, release and package approval are OFF in config/ops_controls.json until an AGENTS.md clause ratifies them.

export type Tier2Kind = 'pipeline.approve_design' | 'pipeline.contract_reviewed' | 'pipeline.approve_item' | 'pipeline.merge_pr' | 'pipeline.release_now'
export type Tier2Action = { kind: Tier2Kind; label: string; params: Record<string, unknown>; enabled: boolean; policy_note?: string | null }

/** Kinds that record the operator's own words with the approval. */
export const NEEDS_WORDS: Tier2Kind[] = ['pipeline.approve_design', 'pipeline.contract_reviewed']

export function needsWords(kind: Tier2Kind): boolean {
  return NEEDS_WORDS.includes(kind)
}

/** The params sent to /api/v2/ops/controls/requests: the card's params plus the operator's words when needed. */
export function requestParams(a: Tier2Action, words: string): Record<string, unknown> {
  return needsWords(a.kind) ? { ...a.params, words: words.trim() } : { ...a.params }
}

export function canCreate(a: Tier2Action, words: string): boolean {
  if (!a.enabled) return false
  return !needsWords(a.kind) || words.trim().length >= 4
}

/** Same rule as the server (ops_controls_core.phrase_matches): whitespace collapsed, otherwise exact. */
export function phraseMatches(typed: string, phrase?: string | null): boolean {
  if (!phrase) return false
  return typed.split(/\s+/).filter(Boolean).join(' ') === phrase.split(/\s+/).filter(Boolean).join(' ')
}

export function disabledReason(a: Tier2Action): string | null {
  return a.enabled ? null : (a.policy_note || 'off in config/ops_controls.json')
}
