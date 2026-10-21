// Recent pipeline failures (audit 2026-10-21): GET /api/v2/system/pipeline-failures groups pipeline_runs failures
// over the window. UNAVAILABLE (null counts) is never rendered as "no failures".

export interface PipelineFailureRow {
  pipeline: string; failed: number; lastFailedAt: string | null; lastError: string | null
  zombieCleared: number | null   // runs that never finished, settled failed by remediate_pipeline_failures
}
export interface PipelineFailuresModel {
  state: 'OK' | 'UNAVAILABLE' | 'LOADING'
  windowHours: number
  rows: PipelineFailureRow[]
  failedRuns: number | null
  note: string | null
}

export function pipelineFailuresFrom(payload: any, opts: { loading?: boolean; error?: unknown } = {}): PipelineFailuresModel {
  const windowHours = typeof payload?.window_hours === 'number' ? payload.window_hours : 24
  if (!payload) {
    if (opts.loading && !opts.error) return { state: 'LOADING', windowHours, rows: [], failedRuns: null, note: null }
    return { state: 'UNAVAILABLE', windowHours, rows: [], failedRuns: null, note: opts.error ? String(opts.error) : 'no payload' }
  }
  if (payload.status !== 'OK' || !Array.isArray(payload.pipelines)) {
    return { state: 'UNAVAILABLE', windowHours, rows: [], failedRuns: null, note: String(payload.note ?? payload.status ?? 'malformed') }
  }
  const rows = payload.pipelines.map((r: any) => ({
    pipeline: String(r?.pipeline ?? '(unknown)'), failed: Number(r?.failed) || 0,
    lastFailedAt: typeof r?.last_failed_at === 'string' ? r.last_failed_at : null,
    lastError: typeof r?.last_error === 'string' && r.last_error ? r.last_error : null,
    zombieCleared: typeof r?.zombie_cleared === 'number' ? r.zombie_cleared : null,
  }))
  rows.sort((a: PipelineFailureRow, b: PipelineFailureRow) => b.failed - a.failed || String(b.lastFailedAt).localeCompare(String(a.lastFailedAt)))
  return { state: 'OK', windowHours, rows, failedRuns: rows.reduce((n: number, r: PipelineFailureRow) => n + r.failed, 0), note: null }
}
