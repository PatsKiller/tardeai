// Ops › Jobs & n8n › Scheduler checks (operator 2026-11-06: "See what's missing on the page you just built. Merge
// what's missing from this one on there, and then retire this page" — Coordination › Automation). Wire types for
// GET /api/v2/scheduler-operations?view=checks (SchedulerChecks@v1) and ?lane=<id> (SchedulerLane@v1), and the pure
// helpers that put them in plain words. No React, no fetch.
import type { SchedulerRow } from './schedulerOperations.ts'

export const SCHEDULER_CHECKS_API = '/api/v2/scheduler-operations?view=checks'
export const schedulerLaneApi = (laneId: string) => `/api/v2/scheduler-operations?lane=${encodeURIComponent(laneId)}`

export type CheckRow = Omit<SchedulerRow, 'timeline'> & { declared_in_registry?: boolean | null; timeline?: SchedulerRow['timeline'] }
export interface ChecksWire {
  schema: string; status: string | null; as_of: string | null; source_sha?: string | null
  sources?: Record<string, { measured?: boolean; as_of?: string | null; reason?: string | null }> | null
  total: number; state_counts: Record<string, number>; unregistered: number; duplicate: number; drift: number; rows: CheckRow[]
}
export interface LaneWire { schema: string; as_of: string | null; source_sha?: string | null; row: SchedulerRow | null }

export type CheckKind = 'failed' | 'silent' | 'orphaned' | 'drift' | 'duplicate' | 'slow' | 'lock' | 'no_proof' | 'slo'
export const CHECK_KINDS: ReadonlyArray<readonly [CheckKind, string, string]> = [
  ['failed', 'Run failed', 'The last host run exited with an error.'],
  ['silent', 'Output went quiet', 'The job is scheduled, but the file or table it should write is stale or missing.'],
  ['orphaned', 'Not in the registry', 'Something runs on the host (cron line, systemd unit or n8n workflow) that no registered job owns, or a registered n8n job whose workflow is off.'],
  ['drift', 'Scheduler drift', 'Where the job actually runs does not match where the registry says it runs (for example a retired job still running).'],
  ['duplicate', 'Scheduled twice', 'The same command is scheduled in more than one place.'],
  ['slow', 'Slow', 'Runs take longer than they should.'],
  ['lock', 'Skipped by lock', 'A run was skipped because the previous one still held the lock.'],
  ['no_proof', 'No output proof', 'The job declares no output to check, so a run cannot be proven.'],
  ['slo', 'Over its limits', 'p95 runtime is longer than the cadence, or more than 5% of runs were skipped by the lock.'],
] as const
const KIND_LABEL = Object.fromEntries(CHECK_KINDS.map(([k, l]) => [k, l])) as Record<CheckKind, string>
export const checkLabel = (k: CheckKind) => KIND_LABEL[k]

const STATE_KIND: Record<string, CheckKind> = {
  RUN_FAILED: 'failed', SILENT: 'silent', ORPHANED: 'orphaned', DRIFT: 'drift', SLOW: 'slow', RUN_SKIPPED_LOCK: 'lock', NO_SIGNAL: 'no_proof',
}

/** Every check a row trips, worst first (its state, then duplicate / drift / SLO flags it also carries). */
export function checkKinds(r: Pick<CheckRow, 'runtime_state' | 'duplicate_scheduler' | 'scheduler_drift' | 'slo_verdict'>): CheckKind[] {
  const out: CheckKind[] = []
  const s = STATE_KIND[r.runtime_state]
  if (s) out.push(s)
  if (r.duplicate_scheduler === true) out.push('duplicate')
  if (r.scheduler_drift === true && !out.includes('drift')) out.push('drift')
  if (r.slo_verdict && r.slo_verdict !== 'OK' && r.slo_verdict !== 'NOT_MEASURED') out.push('slo')
  return out
}
export const checkTone = (k: CheckKind): 'danger' | 'warning' | 'info' =>
  k === 'failed' ? 'danger' : k === 'no_proof' || k === 'duplicate' ? 'info' : 'warning'

/** Kind counts over the rows (only kinds that occur, in CHECK_KINDS order). */
export function kindCounts(rows: CheckRow[]): Array<{ kind: CheckKind; label: string; count: number }> {
  const n: Partial<Record<CheckKind, number>> = {}
  for (const r of rows) for (const k of checkKinds(r)) n[k] = (n[k] ?? 0) + 1
  return CHECK_KINDS.filter(([k]) => n[k]).map(([k, l]) => ({ kind: k, label: l, count: n[k]! }))
}

export const SCHEDULER_PILLS = ['all', 'cron', 'systemd', 'n8n', 'openclaw', 'event'] as const
export type SchedulerPill = typeof SCHEDULER_PILLS[number]
export const schedulerPillLabel = (p: SchedulerPill) =>
  ({ all: 'All', cron: 'Host cron', systemd: 'systemd', n8n: 'n8n', openclaw: 'OpenClaw', event: 'Event' } as const)[p]

export function filterChecks(rows: CheckRow[], o: { kind?: CheckKind | null; scheduler?: SchedulerPill; q?: string }): CheckRow[] {
  const q = (o.q ?? '').trim().toLowerCase()
  return rows.filter(r => (!o.kind || checkKinds(r).includes(o.kind))
    && (!o.scheduler || o.scheduler === 'all' || r.scheduler_type.toLowerCase() === o.scheduler)
    && (!q || [r.lane_id, r.domain, r.owner, r.health_reason].filter(Boolean).join(' ').toLowerCase().includes(q)))
}

/** Rows the job registry does not know (unregistered cron / unit / n8n, OpenClaw jobs, n8n infra workflows): they have
 *  no Jobs & n8n run-history page, so their card does not link there. */
export const isUnregistered = (r: Pick<CheckRow, 'declared_in_registry' | 'lane_id'>) =>
  r.declared_in_registry === false || /^unregistered-/.test(r.lane_id)

/** "12 m", "3 h 5 m", "2 d": an age in seconds. null → null (the caller says "not measured"). */
export function ageWords(seconds: number | null | undefined): string | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} m`
  const h = Math.floor(m / 60)
  if (h < 48) return m % 60 ? `${h} h ${m % 60} m` : `${h} h`
  return `${Math.floor(h / 24)} d`
}

/** Where the job's output proof lives: a path, a table, "no output declared", or null when unknown. */
export function outputText(sig: CheckRow['output_signal']): string | null {
  if (!sig) return null
  if (sig.path) return sig.path
  if (sig.table) return `table ${sig.table}`
  if (sig.kind === 'none') return sig.reason ? `No output declared (${sig.reason})` : 'No output declared'
  return null
}

const FRESH_WORD: Record<string, string> = { FRESH: 'fresh', AGING: 'aging', STALE: 'stale', ABSENT: 'missing' }
/** "stale · written 3 h ago"; the freshness word alone when no age; null when not measured. */
export function freshnessText(r: Pick<CheckRow, 'freshness' | 'output_age'>): string | null {
  const w = FRESH_WORD[r.freshness]
  if (!w) return null
  const age = ageWords(r.output_age)
  return age ? `${w} · written ${age} ago` : w
}

/** "aligned", "drift", "scheduled twice", or both; null when not measured. */
export function driftText(r: Pick<CheckRow, 'scheduler_drift' | 'duplicate_scheduler'>): string | null {
  const parts: string[] = []
  if (r.scheduler_drift === true) parts.push('drift')
  if (r.duplicate_scheduler === true) parts.push('scheduled twice')
  if (!parts.length && r.scheduler_drift === false) parts.push('aligned')
  return parts.length ? parts.join(' · ') : null
}

/** A measured observation is only current for five minutes; older (or future-dated) reads as not measured. */
export function observationExpired(asOf: string | null | undefined, nowMs = Date.now()): boolean {
  const t = asOf ? Date.parse(asOf) : NaN
  return !Number.isFinite(t) || nowMs - t > 300_000 || t > nowMs + 5_000
}
