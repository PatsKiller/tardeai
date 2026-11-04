// FQ-098: a CIO stance carries the date its evidence was read. Rendered without that date it looks like current advice —
// the operator saw "TRIM" for SPCX resting on 2026-08-29 evidence. A stance older than STANCE_STALE_DAYS is NAMED stale,
// with its evidence date, and is never presented as a live call.
export const STANCE_STALE_DAYS = 14

export interface StanceLine { text: string; stale: boolean; evidenceDate: string | null }

/** `CIO TRIM · conviction 62 · evidence 2026-08-29 (stale — 67 days old)` — or the fresh form with its date. */
export function cioStanceLine(stance: string, asOf?: string | null, conviction?: number | string | null,
                              now: Date = new Date()): StanceLine {
  const evidenceDate = asOf ? String(asOf).slice(0, 10) : null
  const parsed = evidenceDate ? Date.parse(`${evidenceDate}T00:00:00Z`) : NaN
  const ageDays = Number.isFinite(parsed) ? Math.floor((now.getTime() - parsed) / 86_400_000) : null
  const stale = ageDays != null && ageDays > STANCE_STALE_DAYS
  const parts = [`CIO ${stance}`]
  if (conviction != null && conviction !== '') parts.push(`conviction ${conviction}`)
  if (!evidenceDate) {
    parts.push('no evidence date — treat as unverified')
    return { text: parts.join(' · '), stale: true, evidenceDate: null }
  }
  parts.push(stale ? `evidence ${evidenceDate} (stale — ${ageDays} days old; not current advice)`
                   : `evidence ${evidenceDate} (${ageDays} days old)`)
  return { text: parts.join(' · '), stale, evidenceDate }
}
