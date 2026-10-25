/** Presentation of recorded evidence only. No execution or broker calls. */
export function pageTab<T extends string>(raw: string | null, tabs: readonly T[], fallback: T): T {
  return tabs.find(tab => tab.toLowerCase() === raw?.toLowerCase()) ?? fallback
}

export function observedTime(raw: unknown): string {
  if (typeof raw !== 'string' || !raw.trim()) return 'Time unavailable'
  // A trading date is not a midnight UTC sync timestamp.
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return `${raw} · time not recorded`
  const date = new Date(raw)
  if (!Number.isFinite(date.getTime())) return 'Time unavailable'
  return date.toLocaleString('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }) + ' ET'
}

export function verifiedEventLabel(event: {
  mode?: string; dry_run?: boolean; success?: boolean; verified?: boolean; exit_code?: number | null
}): string {
  if (event.dry_run || /dry.?run|preview|shadow/i.test(event.mode || '')) return 'Preview'
  if (event.success === false || (event.exit_code != null && event.exit_code !== 0)) return 'Failed'
  if (event.verified === true) return 'Verified'
  if (event.success === true) return 'Completed'
  return 'Unverified'
}

export function recordedPercent(raw: unknown): string {
  if (raw == null || raw === '') return 'Not recorded'
  const n = Number(String(raw).replace(/%$/, ''))
  return Number.isFinite(n) && n >= 0 && n <= 100 ? `${n}%` : 'Not recorded'
}

export function syncEvidenceState(
  state: string, step: { rc?: number | null } | null | undefined,
  lastSuccess: string | null | undefined, operatorRun: string | null | undefined,
): string {
  if (state !== 'OK' || step?.rc == null || step.rc === 0) return state
  // Ignore an old failure only when a recorded successful run demonstrably supersedes it.
  const successAt = lastSuccess?.includes('T') ? Date.parse(lastSuccess) : NaN
  const failedAt = operatorRun?.includes('T') ? Date.parse(operatorRun) : NaN
  return Number.isFinite(successAt) && Number.isFinite(failedAt) && successAt > failedAt ? state : 'DEGRADED'
}
