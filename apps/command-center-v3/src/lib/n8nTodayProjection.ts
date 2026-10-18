// Daily receipt availability → operator view. Pure; never invents zero or recovery.
export type Row = Record<string, unknown>
export type Source = 'runs' | 'relay' | 'diagnoses' | 'cutovers'
export type N8nTodayPayload = {
  schema?: string; status?: string; day?: string; as_of?: string; last_good_at?: string | null
  runs?: { by_mode_state?: Record<string, Record<string, number>> | null; totals?: Record<string, number | null>; lanes_active?: number | null }
  failures?: Row[]; failures_total?: number | null; failures_returned?: number; failures_truncated?: boolean
  lock_skips?: Array<{ lane: string; mode: string; count: number }>
  relay?: { workflow_errors?: Row[]; truncated?: boolean }
  diagnoses?: { by_lane?: Record<string, number>; total?: number | null; truncated?: boolean }
  heals?: Row[]; heals_total?: number | null; cutovers_today?: Row[]; cutovers_total?: number | null
  coverage?: { window?: { since?: string; through?: string; timezone?: string }; sources?: Partial<Record<Source, { status?: string; complete?: boolean }>>; run_namespaces?: { included?: string[]; excluded?: string }; qualification?: string }
  note?: string
}
const finiteCount = (v: unknown): number | null => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : null
export function projectN8nToday(data: N8nTodayPayload | null | undefined, opts: { error?: boolean; stale?: boolean; nowMs?: number } = {}) {
  const now = opts.nowMs ?? Date.now()
  const known = !!data && ['N8nToday@v1', 'N8nToday@v2'].includes(data.schema ?? '')
  const current = data?.schema === 'N8nToday@v2'
  const asOf = data?.as_of && Number.isFinite(Date.parse(data.as_of)) ? data.as_of : null
  const age = asOf ? now - Date.parse(asOf) : null
  const stale = !!opts.stale || (known && (age == null || age < 0 || age > 180_000))
  const unavailable = !known || !!opts.error
  const status = !known ? 'UNAVAILABLE' : stale || opts.error ? 'STALE' : !current ? 'PARTIAL' : data?.status ?? 'UNAVAILABLE'
  const available = (source: Source) => !unavailable && !stale && current && ['OK', 'PARTIAL'].includes(data?.status ?? '') && data?.coverage?.sources?.[source]?.complete === true
  const empty = (source: Source) => available(source) ? 'No matching records in observed coverage' : status === 'STALE' ? 'STALE · current records unavailable' : 'UNAVAILABLE · coverage incomplete'
  const last = data?.last_good_at ?? asOf
  const lastGoodAgeSeconds = last && Number.isFinite(Date.parse(last)) && Date.parse(last) <= now ? Math.round((now - Date.parse(last)) / 1000) : null
  return {
    data: known ? data : null, status, asOf, lastGoodAgeSeconds,
    counts: {
      live: available('runs') ? finiteCount(data?.runs?.totals?.live) : null,
      dry: available('runs') ? finiteCount(data?.runs?.totals?.dry_run) : null,
      failures: available('runs') ? finiteCount(data?.failures_total) : null,
      lockSkippedLanes: available('runs') && Array.isArray(data?.lock_skips) ? data.lock_skips.length : null,
      recoveryActions: available('diagnoses') ? finiteCount(data?.heals_total) : null,
      diagnoses: available('diagnoses') ? finiteCount(data?.diagnoses?.total) : null,
      cutovers: available('cutovers') ? finiteCount(data?.cutovers_total) : null,
    },
    available, empty,
    coverageLabel: current ? `Observed ${data?.coverage?.window?.since ?? 'unknown'} → ${data?.coverage?.window?.through ?? 'unknown'} (${data?.coverage?.window?.timezone ?? 'unknown'}); namespaces ${(data?.coverage?.run_namespaces?.included ?? []).join(', ') || 'unknown'}. ${data?.coverage?.run_namespaces?.excluded ?? ''}` : 'Legacy receipt response: coverage and totals are unverified; details only.',
  }
}
export function displayCount(value: number | null): string { return value == null ? 'UNAVAILABLE' : String(value) }
