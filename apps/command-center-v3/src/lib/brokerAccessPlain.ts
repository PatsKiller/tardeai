// Broker access rows in ordinary words, with the codes kept behind Diagnostics (FQ-066).
//
// The page printed what the read model carries: `DEGRADED_STALE_SOURCE` as the Reason, `rc=3` chips in the operator log,
// and readiness field identifiers in the normal view. A reader could see that something was wrong and still not know
// which connection it was or what to do.
//
// Nothing is deleted. Each row gains a sentence — which connection, what it is doing, what that costs the reader, what
// the last read did — and every raw field (state code, reason code, flags, step name, exit code, signals) is returned by
// `diagnosticsOf` for the Diagnostics disclosure.
import type { Tone } from './designTokens'

export type BrokerStateName = 'OK' | 'STALE' | 'DEGRADED' | 'PAUSED' | 'NEEDS_REAUTH'

export type Step = { name?: string | null; rc?: number | null; signals?: string[] | null }
export type RowInput = {
  id: string; label: string; state?: string | null; reason?: string | null
  flags?: string[] | null; operator_log_step?: Step | null; last_success_at?: string | null; note?: string | null
}

/** What each state means for the person reading, in words that do not need the code beside them. */
const PLAIN: Record<BrokerStateName, { words: string; meaning: string; nextStep: string; tone: Tone }> = {
  OK: { words: 'Working', tone: 'success',
    meaning: 'Reads are current for this connection.',
    nextStep: 'Nothing to do.' },
  STALE: { words: 'Out of date', tone: 'warning',
    meaning: 'The last successful read is old, so figures from this connection may be behind.',
    nextStep: 'Open Diagnostics to see when it last read successfully and what the source reported.' },
  DEGRADED: { words: 'Degraded', tone: 'danger',
    meaning: 'The source reports this connection as degraded, so treat its figures as incomplete.',
    nextStep: 'Open Diagnostics to see which signals the source reported before relying on these figures.' },
  PAUSED: { words: 'Paused', tone: 'info',
    meaning: 'Sync is paused on purpose, so nothing new is being read from this connection.',
    nextStep: 'Nothing to do until it is resumed.' },
  NEEDS_REAUTH: { words: 'Login expired', tone: 'danger',
    meaning: 'Reads stop until the broker login is renewed.',
    nextStep: 'Renew the login from the re-login section on this page, then check this row again.' },
}

const UNKNOWN = {
  words: 'Unknown state', tone: 'warning' as Tone,
  meaning: 'This page has no meaning recorded for the reported state, so it is not reported as working.',
  nextStep: 'Open Diagnostics for the reported state and reason code.',
}

const clean = (v: unknown) => String(v ?? '').replace(/\s+/g, ' ').trim()

export function plainState(state: string | null | undefined): { words: string; meaning: string; nextStep: string; tone: Tone } {
  const k = clean(state).toUpperCase() as BrokerStateName
  return PLAIN[k] ?? UNKNOWN
}

/** What the last read did — recorded as recorded, never upgraded to success and never downgraded to failure. */
export function lastReadSentence(step: Step | null | undefined): string {
  if (!step) return 'No read is logged for this connection.'
  if (step.rc == null) return 'The last read did not record a result.'
  return step.rc === 0 ? 'The last read completed.' : 'The last read did not complete.'
}

/**
 * The operator-run summary, in words. A step whose exit code was never recorded is *unrecorded*, never "completed":
 * calling it completed is exactly the overstatement FQ-066 exists to remove. "every step completed" requires every
 * step to carry a zero exit code; when none recorded a result the sentence says so.
 */
export function operatorLogSummary(steps: Step[] | null | undefined): string {
  const all = steps ?? []
  if (!all.length) return 'The operator log holds no steps.'
  const bad = all.filter(st => st.rc != null && st.rc !== 0).length
  const missing = all.filter(st => st.rc == null).length
  const completed = all.length - bad - missing
  const lead = bad ? `${bad} did not complete`
    : !missing ? 'every step completed'
    : !completed ? 'no step recorded a result'
    : `${completed} completed`
  return `${all.length} step${all.length === 1 ? '' : 's'} logged; ${lead}${missing ? `, ${missing} without a recorded result` : ''}.`
}

export function brokerRowSentence(row: RowInput): { headline: string; nextStep: string } {
  const p = plainState(row.state)
  const label = clean(row.label) || 'This connection'
  return {
    headline: `${label}: ${p.words}. ${p.meaning} ${lastReadSentence(row.operator_log_step)}`,
    nextStep: p.nextStep,
  }
}

export type Diagnostic = { label: string; value: string }

/** Every raw field, for the Diagnostics disclosure. Empty means "not recorded", never "nothing was wrong". */
export function diagnosticsOf(row: RowInput): Diagnostic[] {
  const step = row.operator_log_step
  const signals = (step?.signals ?? []).filter(Boolean)
  const flags = (row.flags ?? []).filter(Boolean)
  return [
    { label: 'Reported state', value: clean(row.state) || 'not recorded' },
    { label: 'Reason code', value: clean(row.reason) || 'not recorded' },
    { label: 'Flags', value: flags.length ? flags.join(', ') : 'none reported' },
    { label: 'Last read step', value: clean(step?.name) || 'not recorded' },
    { label: 'Exit code', value: step?.rc == null ? 'not recorded' : String(step.rc) },
    { label: 'Signals', value: signals.length ? signals.join(', ') : 'none reported' },
    { label: 'Last success', value: clean(row.last_success_at) || 'not recorded' },
  ]
}
