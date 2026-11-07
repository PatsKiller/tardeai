// /ops/jobs → Run history (operator 2026-11-06: "all of the jobs, when they ran, when they didn't run, when it had to
// be fixed"). Wire types for GET /api/v2/jobs-history (JobRunHistory@v1) and the pure helpers the view uses.
// Every time on the wire is the writer's own time; `computed_at` is when the page projection was computed.

export type HistoryStatus = 'ok' | 'ok_unverified' | 'failed' | 'missed' | 'late' | 'running' | 'not_measured'
  | 'paused' | 'retired' | 'never_scheduled'
export type RunResult = 'succeeded' | 'failed' | 'timed_out' | 'refused' | 'skipped_lock' | 'running' | 'requested' | 'unknown'
export type SlotStatus = 'ran' | 'ran_failed' | 'ran_dry_run' | 'missed' | 'pending' | 'not_measured'
export type Tone = 'success' | 'danger' | 'warning' | 'info' | 'neutral'

export interface HistoryRun {
  run_id: string | null; source: string; mode: 'live' | 'dry_run'; result: RunResult
  requested_at: string | null; started_at: string | null; finished_at: string | null
  exit_code: number | null; duration_s: number | null; attempt: number | null; retry_of: string | null
  requested_by: string | null; inline_attempts: string[] | null; reason: string | null
}
export interface HistorySlot { slot_at: string; status: SlotStatus; run_id: string | null; started_at: string | null }
export interface FixEvent { at: string; kind: string; by: string; outcome: string | null; detail: string | null; ref: string | null }
export interface Cadence {
  expressions: string[]; timezone: string; every_hours: number | null; market_days_only: boolean; schedule_gap?: string | null
}
export interface HistoryListRow {
  lane_id: string; job: string; scheduler: string; state: string; status: HistoryStatus; status_reason: string | null
  cadence: Cadence; last_run: HistoryRun | null; last_success_at: string | null
  missed_count: number | null; missed_gap: string | null; fix_count: number; last_fix: FixEvent | null
  history_sources: string[]; history_gap: string | null; output_written_at?: string | null
}
export interface HistoryDetailRow extends Omit<HistoryListRow, 'output_written_at'> {
  runs: HistoryRun[]; slots: HistorySlot[]; fixes: FixEvent[]
  output: { path_kind: string | null; written_at: string | null; note: string } | null
}
export interface SourceClock { name: string; newest_record_at: string | null; covers_from: string | null; note: string | null }
export interface HistorySummary {
  jobs: number; active: number; with_missed: number; missed_not_measured: number; fixed_14d: number; no_run_history: number
  [status: string]: number
}
interface HistoryBase { schema: string; computed_at: string; summary: HistorySummary; sources: SourceClock[]; gaps: string[]; note: string }
export interface HistoryListWire extends HistoryBase {
  rows: HistoryListRow[]; total: number; offset: number; limit: number; has_more: boolean; filter: string
}
export interface HistoryDetailWire extends HistoryBase { row: HistoryDetailRow | null }

export const HISTORY_FILTERS = [
  ['attention', 'Needs attention'], ['fixed', 'Fixed (14 days)'], ['all', 'All jobs'],
  ['n8n', 'n8n'], ['cron', 'Host cron'], ['systemd', 'systemd'], ['other', 'Event / none'],
] as const
export type HistoryFilter = typeof HISTORY_FILTERS[number][0]

export const STATUS_LABEL: Record<HistoryStatus, string> = {
  ok: 'Running on schedule', ok_unverified: 'Output on time, success unproven', failed: 'Last run failed',
  missed: 'Missed a run', late: 'Late', running: 'Running now', not_measured: 'Not measured',
  paused: 'Paused', retired: 'Retired', never_scheduled: 'Never scheduled',
}
export const statusTone = (s: HistoryStatus): Tone =>
  s === 'ok' ? 'success' : s === 'failed' ? 'danger' : s === 'missed' || s === 'late' || s === 'not_measured' ? 'warning'
    : s === 'running' || s === 'ok_unverified' ? 'info' : 'neutral'

export const RESULT_LABEL: Record<RunResult, string> = {
  succeeded: 'Succeeded', failed: 'Failed', timed_out: 'Timed out', refused: 'Refused', skipped_lock: 'Skipped (still running)',
  running: 'Running', requested: 'Queued', unknown: 'Result not stated',
}
export const resultTone = (r: RunResult): Tone =>
  r === 'succeeded' ? 'success' : r === 'failed' || r === 'timed_out' || r === 'refused' ? 'danger'
    : r === 'skipped_lock' || r === 'unknown' ? 'warning' : 'info'

export const SLOT_LABEL: Record<SlotStatus, string> = {
  ran: 'Ran', ran_failed: 'Ran, failed', ran_dry_run: 'Dry run only', missed: 'No run', pending: 'Due now', not_measured: 'Not measured',
}
export const slotTone = (s: SlotStatus): Tone =>
  s === 'ran' ? 'success' : s === 'ran_failed' ? 'danger' : s === 'missed' || s === 'ran_dry_run' ? 'warning' : 'neutral'

export const FIX_LABEL: Record<string, string> = {
  retry: 'Retried', dead_letter: 'Gave up (dead letter)', dead_letter_released: 'Dead letter released',
  breaker_opened: 'Paused by breaker', breaker_released: 'Breaker released', incident_opened: 'Incident opened',
  heal_attempt: 'Heal attempted', incident_closed: 'Incident closed', self_heal_fixer: 'Code fix requested',
  diagnosis_opened: 'Failure diagnosed', self_healed: 'Self-healed', self_heal_action: 'Self-heal action',
  cron_self_heal: 'Cron self-heal',
}
export const fixLabel = (kind: string) => FIX_LABEL[kind] ?? kind.replace(/_/g, ' ')
export const fixTone = (f: FixEvent): Tone =>
  f.kind === 'self_healed' || f.kind === 'incident_closed' || f.kind.endsWith('_released') || f.outcome === 'succeeded' || f.outcome === 'ok'
    ? 'success' : f.kind === 'dead_letter' || f.kind === 'breaker_opened' || f.outcome === 'failed' ? 'danger' : 'info'

export const SCHEDULER_LABEL: Record<string, string> = { n8n: 'n8n', cron: 'Host cron', systemd: 'systemd timer', event: 'Event', none: 'No scheduler' }
export const schedulerLabel = (s: string) => SCHEDULER_LABEL[s] ?? s

/** "Nov 6, 7:05 PM ET" in the operator's zone, or the caller's fallback when the writer left no time. */
export function etTime(value: string | null | undefined, fallback = 'Not recorded'): string {
  if (!value) return fallback
  const ms = Date.parse(value)
  if (!Number.isFinite(ms)) return fallback
  return new Date(ms).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET'
}

/** "3 h ago" relative to the projection's computed_at (never the browser clock, so a cached page does not drift). */
export function ago(value: string | null | undefined, reference: string | null | undefined): string | null {
  const a = value ? Date.parse(value) : NaN, b = reference ? Date.parse(reference) : NaN
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  const minutes = Math.round((b - a) / 60_000)
  if (minutes < 0) return 'after this check'
  if (minutes < 1) return 'just now'
  if (minutes < 90) return `${minutes} min ago`
  const hours = minutes / 60
  if (hours < 36) return `${Math.round(hours)} h ago`
  return `${Math.round(hours / 24)} d ago`
}

export function duration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds < 60) return `${Math.round(seconds)} s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}

// Plain cadence: the cron fields with their zone, "about every 4 h", or the schedule gap.
export function cadenceText(c: Cadence): string {
  if (c.expressions.length) {
    const zone = c.timezone === 'America/New_York' ? 'ET' : c.timezone
    return `${c.expressions.join(' · ')} (${zone})${c.market_days_only ? ', market days only' : ''}`
  }
  if (c.every_hours) return `about every ${c.every_hours < 1 ? `${Math.round(c.every_hours * 60)} min` : `${+c.every_hours.toFixed(2)} h`} (no wall-clock schedule)`
  return c.schedule_gap || 'No schedule declared'
}

/** Missed count with its honesty: a number only where history covers the slots, else why not. */
export function missedText(row: Pick<HistoryListRow, 'missed_count' | 'missed_gap'>): string {
  if (row.missed_count == null) return `Not measured${row.missed_gap ? `: ${row.missed_gap}` : ''}`
  if (row.missed_count === 0) return 'None in the last 10 expected runs'
  return `${row.missed_count} of the last 10 expected runs`
}

export function historyQuery(filter: string, offset: number, q: string, limit = 50): string {
  const p = new URLSearchParams({ filter, offset: String(offset), limit: String(limit) })
  if (q.trim()) p.set('q', q.trim())
  return `/api/v2/jobs-history?${p.toString()}`
}
export const detailQuery = (laneId: string) => `/api/v2/jobs-history?job=${encodeURIComponent(laneId)}`
