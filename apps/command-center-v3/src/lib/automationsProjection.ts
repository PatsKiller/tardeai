// Automations projection → operator view (design automations/v001, APPROVED 2026-11-04).
// Pure: the page renders what the broker computed and never re-derives a number. A missing or
// unreadable source is UNAVAILABLE/STALE with a reason — never a zero that reads as "all quiet".
export type WorkflowRow = {
  workflow_id?: string | number | null; name?: string | null; state?: string | null
  runs?: number | null; ok?: number | null; fail?: number | null; fail_pct?: number | null
  last_error?: string | null; last_error_kind?: string | null; last_error_at?: string | null
  folder?: string | null; steps?: number | null; active?: boolean | null
  updated_at?: string | null; created_at?: string | null; last_run_at?: string | null
}
export type AutomationsPayload = {
  schema?: string; as_of?: string; window_days?: number
  kpi?: {
    runs?: number | null; ok?: number | null; failed?: number | null; running?: number | null
    fail_rate_pct?: number | null; fail_rate_unavailable_reason?: string | null
    avg_run_s?: number | null; cron_left?: number | null
    cron_left_has_draft?: number | null
    deltas?: Record<string, number | null> | null; deltas_unavailable_reason?: string | null
  }
  workflows?: WorkflowRow[]
  counts?: { workflows?: number | null; live?: number | null; shadow?: number | null; off?: number | null; failing?: number | null }
}
export type AutomationsFilter = 'all' | 'failing' | 'live' | 'off'

// cc-deepseek-5's BLOCK at d4bc7430, F1: this constant did not match what the producer emits
// (scripts/lib/data_broker/n8n_automations.py: SCHEMA = "N8nAutomations@v1"), so every real payload
// fell through to UNAVAILABLE and the page rendered nothing. The seam test below reads the Python
// constant directly so the two cannot drift again.
export const SCHEMA = 'N8nAutomations@v1'
/** The broker caches 60 s and the page polls at 60 s; three missed refreshes is the stale line. */
export const STALE_AFTER_MS = 180_000
/** SPEC: the alert banner appears when the 7-day failure rate is over 10%. */
export const FAIL_RATE_BANNER_PCT = 10

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export function fmtEt(iso: unknown): string | null {
  const t = Date.parse(String(iso ?? ''))
  if (!Number.isFinite(t)) return null
  return new Date(t).toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }) + ' ET'
}

export function displayCount(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? String(v) : '—'
}

/** The one-line reason a row fails, or null when it does not fail. Never invents a cause. */
export function rowFailure(row: WorkflowRow): { failing: boolean; reason: string | null } {
  const fail = num(row.fail) ?? 0
  if (fail <= 0) return { failing: false, reason: null }
  return { failing: true, reason: row.last_error || 'no error text recorded for the last failure' }
}

export function matchesFilter(row: WorkflowRow, filter: AutomationsFilter): boolean {
  const state = String(row.state ?? '').toLowerCase()
  if (filter === 'all') return true
  if (filter === 'failing') return (num(row.fail) ?? 0) > 0
  if (filter === 'live') return state === 'live'
  if (filter === 'off') return state === 'off'
  return true
}

export function searchRows(rows: WorkflowRow[], query: string): WorkflowRow[] {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(r => String(r.name ?? '').toLowerCase().includes(q)
    || String(r.folder ?? '').toLowerCase().includes(q)
    || String(r.last_error ?? '').toLowerCase().includes(q))
}

/** Top cause for the banner: the failing workflow with the most failures; ties keep broker order. */
export function topCause(rows: WorkflowRow[]): { name: string; reason: string; fail: number } | null {
  let best: { name: string; reason: string; fail: number } | null = null
  for (const row of rows) {
    const { failing, reason } = rowFailure(row)
    if (!failing) continue
    const fail = num(row.fail) ?? 0
    if (!best || fail > best.fail) best = { name: String(row.name ?? 'unnamed workflow'), reason: reason ?? '', fail }
  }
  return best
}

export function projectAutomations(
  data: AutomationsPayload | null | undefined,
  opts: { error?: boolean; nowMs?: number } = {},
) {
  const now = opts.nowMs ?? Date.now()
  const known = !!data && data.schema === SCHEMA
  const asOf = data?.as_of && Number.isFinite(Date.parse(data.as_of)) ? data.as_of : null
  const ageMs = asOf ? now - Date.parse(asOf) : null
  const stale = known && !opts.error && (ageMs === null || ageMs < 0 || ageMs > STALE_AFTER_MS)
  const status: 'OK' | 'STALE' | 'UNAVAILABLE' = !known || opts.error ? 'UNAVAILABLE' : stale ? 'STALE' : 'OK'
  const rows = known ? (data?.workflows ?? []) : []
  const rate = num(data?.kpi?.fail_rate_pct)
  const cause = topCause(rows)
  return {
    data: known ? data : null,
    status, asOf, stale,
    rows,
    counts: {
      workflows: num(data?.counts?.workflows), live: num(data?.counts?.live), shadow: num(data?.counts?.shadow),
      off: num(data?.counts?.off), failing: num(data?.counts?.failing),
    },
    kpi: {
      runs: num(data?.kpi?.runs), failed: num(data?.kpi?.failed), running: num(data?.kpi?.running),
      failRate: rate, avgRunS: num(data?.kpi?.avg_run_s),
      failRateUnavailable: data?.kpi?.fail_rate_unavailable_reason || null,
      cronLeft: num(data?.kpi?.cron_left), cronLeftHasDraft: num(data?.kpi?.cron_left_has_draft),
      deltas: data?.kpi?.deltas ?? null,
      deltasUnavailable: data?.kpi?.deltas_unavailable_reason || (data?.kpi?.deltas ? null : 'no prior 7-day snapshot'),
    },
    // Only a measured rate can raise the banner; an unreadable rate must not read as "fine".
    banner: rate !== null && rate > FAIL_RATE_BANNER_PCT && cause
      ? { show: true, rate, cause }
      : status === 'OK' ? { show: false, rate, cause: null } : { show: false, rate, cause: null },
  }
}
