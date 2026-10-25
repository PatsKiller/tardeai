// Self-heal fix log model for Ops → Releases & schedules → Fixes (operator 2026-10-25: "a logger that tracks what was
// fixed"). Wire: GET /api/v2/ops/self-heal-fixes (scripts/lib/self_heal_fixes_view.py, SelfHealFixes@v1). Pure; no
// React. A missing log is UNAVAILABLE with its reason, never an empty green list.
import type { Tone } from './designTokens'

export const SELF_HEAL_FIXES_PATH = '/api/v2/ops/self-heal-fixes'
export type FixFilter = 'all' | 'open' | 'fixed' | 'escalated'
export const FIX_FILTERS: ReadonlyArray<readonly [FixFilter, string]> = [
  ['all', 'All'], ['open', 'Open'], ['fixed', 'Fixed'], ['escalated', 'Escalated'],
]

export interface FixRow {
  fix_id: string; at: string | null; event: string | null; mode: string | null; detected_at: string | null
  source: string | null; kind: string | null; signature: string | null; title: string | null; evidence_refs: string[] | null
  remediation_kind: string | null; attempts: number | null; model_cost_usd: number | null; pr_number: number | null
  pr_head: string | null; outcome: string | null; released_sha: string | null; verified_at: string | null; detail: string | null
}
export interface SelfHealFixesWire {
  schema: string; as_of: string; status: 'OK' | 'UNAVAILABLE'; reason: string | null; source: string
  monitor: { mode: string | null; ok_at: string | null; stale: boolean; policy_why: string | null; ci: string | null }
  summary: { total: number; open: number; fixed: number; escalated: number; proposed: number; model_cost_usd: number }
  rows: FixRow[]; total: number; offset: number; limit: number; has_more: boolean; history: FixRow[] | null
}

const LABELS: Record<string, [string, Tone]> = {
  'detected': ['Detected', 'warning'],
  'shadow-proposed': ['Proposed (shadow)', 'neutral'],
  'remediating': ['Remediating', 'info'],
  'fixer-queued': ['Queued for fixer', 'info'],
  'fix-PR-open': ['Fix PR open', 'info'],
  'fixed-released-pending': ['Released · verifying', 'info'],
  'fixed-released': ['Fixed · released', 'success'],
  'fixed-no-release': ['Fixed', 'success'],
  'escalated': ['Escalated', 'danger'],
  'gave-up': ['Gave up', 'danger'],
  'cleared': ['Cleared by itself', 'neutral'],
}

export function outcomeLabel(outcome: string | null | undefined): { label: string; tone: Tone } {
  const hit = outcome ? LABELS[outcome] : undefined
  return hit ? { label: hit[0], tone: hit[1] } : { label: outcome ? `Unknown (${outcome})` : 'Unknown', tone: 'warning' }
}

const SOURCES: Record<string, string> = { ci: 'Main CI', train: 'Release train', tester: 'Post-release test', sweep: 'Nightly sweep', lane: 'Lane' }
export const sourceLabel = (s: string | null | undefined): string => (s && SOURCES[s]) || (s ? s : 'Unknown source')

export function remediationLabel(kind: string | null | undefined): string {
  if (!kind) return 'Not decided'
  if (kind === 'claude_code') return 'Claude Code fix PR'
  if (kind === 'coordinator') return 'Coordinator task'
  if (kind.startsWith('deterministic:')) return `Deterministic: ${kind.slice('deterministic:'.length).replace(/_/g, ' ')}`
  if (kind.startsWith('refused:')) return `Refused scope: ${kind.slice('refused:'.length).replace(/_/g, ' ')}`
  return kind
}

/** "$3.25", "no model" for a deterministic / unspent fix (null is not "$0": nothing was measured). */
export function costText(usd: number | null | undefined): string {
  return typeof usd === 'number' && Number.isFinite(usd) ? (usd === 0 ? '$0.00' : `$${usd.toFixed(2)}`) : 'no model cost'
}

export function shortSha(sha: string | null | undefined): string { return sha ? sha.slice(0, 9) : '—' }

/** Header line: is the monitor itself running, and in which mode? Stale or missing heartbeat is a warning. */
export function monitorLine(w: SelfHealFixesWire | null | undefined): { text: string; tone: Tone } {
  if (!w || w.schema !== 'SelfHealFixes@v1') return { text: 'Monitor status unavailable', tone: 'warning' }
  const m = w.monitor
  if (!m.ok_at) return { text: 'Monitor has not run (no heartbeat)', tone: 'warning' }
  if (m.stale) return { text: `Monitor heartbeat is stale (last ${m.ok_at})`, tone: 'warning' }
  const mode = m.mode === 'live' ? 'LIVE' : m.mode === 'shadow' ? 'SHADOW — detects and proposes, fixes nothing' : (m.mode ?? 'unknown')
  return { text: `Monitor ${mode}${m.policy_why ? ` · ${m.policy_why}` : ''}`, tone: m.mode === 'live' ? 'success' : 'neutral' }
}
