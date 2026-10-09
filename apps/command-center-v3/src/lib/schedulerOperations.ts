export type SchedulerRun = {
  run_id?: string | null; mode?: string | null; state?: string | null
  requested_at?: string | null; started_at?: string | null; finished_at?: string | null
  exit_code?: number | null; duration_s?: number | null
  receipt?: { lock_skipped?: boolean; output_signal?: string | null; code_sha?: string | null } | null
}
export type SchedulerRow = {
  lane_id: string; domain: string | null; owner: string | null; scheduler_type: string
  declared_state: string; runtime_state: string; schedule: string | null; next_due: string | null
  last_requested: string | null; last_started: string | null; last_completed: string | null
  last_exit: number | null; duration: number | null; receipt: string | null
  output_signal: { kind?: string; path?: string; table?: string; reason?: string } | null
  output_age: number | null; freshness: string; lock_skips_24h: number | null; failures_24h: number | null
  duplicate_scheduler: boolean | null; scheduler_drift: boolean | null; code_sha: string | null
  code_root: string | null; consumer: string | null; evidence_class: string; health_reason?: string | null
  slo_verdict?: string; p50_runtime_s?: number | null; p95_runtime_s?: number | null
  completion_ratio?: number | null; timeline: SchedulerRun[]
}
export type SchedulerPayload = {
  schema: 'SchedulerOperations@v1'; status: string; as_of: string | null; source_sha?: string | null
  rows: SchedulerRow[]; sources?: Record<string, { measured?: boolean; as_of?: string | null; reason?: string | null }>
}
export const SCHEDULER_FILTERS = ['All', 'Problems', 'cron', 'systemd', 'n8n', 'OpenClaw', 'event', 'CIO', 'Hermes', 'Broker/Safety', 'Maintenance'] as const
export type SchedulerFilter = typeof SCHEDULER_FILTERS[number]
export function schedulerProblems(row: SchedulerRow): boolean {
  return !['LIVE', 'EXPECTED_SILENT'].includes(row.runtime_state)
    || row.duplicate_scheduler === true || row.scheduler_drift === true
    || (row.slo_verdict != null && row.slo_verdict !== 'NOT_MEASURED' && row.slo_verdict !== 'OK')
}
export function filterSchedulerRows(rows: SchedulerRow[], filter: SchedulerFilter): SchedulerRow[] {
  if (filter === 'All') return rows
  if (filter === 'Problems') return rows.filter(schedulerProblems)
  if (['cron', 'systemd', 'n8n', 'OpenClaw', 'event'].includes(filter)) return rows.filter(r => r.scheduler_type.toLowerCase() === filter.toLowerCase())
  const patterns: Record<string, RegExp> = {
    CIO: /cio/i, Hermes: /hermes/i, 'Broker/Safety': /broker|order|stop|risk|safety|watchdog|reaper|protection/i,
    Maintenance: /maintenance|backup|retention|hygiene|cleanup|restore/i,
  }
  return rows.filter(r => patterns[filter]?.test([r.lane_id, r.domain, r.owner].filter(Boolean).join(' ')))
}
export function measuredNumber(value: number | null | undefined, suffix = ''): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value}${suffix}` : 'NOT_MEASURED'
}
export function operatorTime(value: string | null | undefined): string {
  if (!value) return 'NOT_MEASURED'
  const at = new Date(value)
  if (!Number.isFinite(at.getTime()) || !/Z$|[+-]\d\d:\d\d$/.test(value)) return 'NOT_MEASURED'
  return `${at.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ET`
}
