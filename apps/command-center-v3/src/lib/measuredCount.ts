// A count that cannot be measured is a gap, never 0 (operator design rule 2026-10-25: "a gap shown as a gap").
// Live audit 2026-10-25: Jobs showed "Missed 0" while most due jobs were "Not measured", and Ops → Data approvals
// showed Approved 0 · Ready 0 · Not ready 0 · Findings 0 while the live scan was still checking every domain.
// Pure module: no React, no DOM, no fetch. CountTile renders what this returns.

/** value null = not measurable (render "—" + reason). atLeast = a measured floor; more may be hidden in the gap. */
export type MeasuredCount = { value: number | null; reason: string | null; atLeast?: boolean }

export const GAP_MARK = '—'

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0

export function measured(value: unknown, reason: string | null = null): MeasuredCount {
  return isCount(value) ? { value, reason: null } : { value: null, reason: reason || 'Not measured' }
}

export function countText(c: MeasuredCount): string {
  if (c.value === null) return GAP_MARK
  return c.atLeast ? `${c.value}+` : String(c.value)
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

// ── Jobs & health ─────────────────────────────────────────────────────────────────────────────────────────────
export type JobsSummary = Record<string, unknown> & {
  not_measured?: unknown; unknown?: unknown; missed?: unknown; missed_measured?: unknown
  gap_reasons?: Record<string, string | null> | null
}

/** Jobs whose execution could not be measured (server `not_measured`, older servers `unknown`). */
export function jobsNotMeasured(summary: JobsSummary | null | undefined): MeasuredCount {
  if (!summary) return { value: null, reason: 'Jobs observation unavailable' }
  const raw = summary.not_measured ?? summary.unknown
  if (!isCount(raw)) return { value: null, reason: 'The server did not report how many jobs are unmeasured' }
  return { value: raw, reason: raw ? (summary.gap_reasons?.not_measured || 'No run receipt or no measurable schedule') : null }
}

/**
 * Missed runs are only countable for jobs whose schedule and receipts are measured. With unmeasured jobs, 0 missed
 * is not a fact — show the gap; a positive count is a floor ("2+").
 */
export function jobsMissed(summary: JobsSummary | null | undefined): MeasuredCount {
  if (!summary) return { value: null, reason: 'Jobs observation unavailable' }
  const missed = summary.missed
  if (!isCount(missed)) return { value: null, reason: summary.gap_reasons?.missed || 'Missed runs are not measured' }
  const unmeasured = jobsNotMeasured(summary)
  const complete = summary.missed_measured === true || (summary.missed_measured === undefined && unmeasured.value === 0)
  if (complete) return { value: missed, reason: null }
  const why = summary.gap_reasons?.missed
    || (unmeasured.value ? `${plural(unmeasured.value, 'job')} not measured, so missed runs among them cannot be counted`
      : 'Missed-run detection is not measured')
  return missed > 0 ? { value: missed, reason: why, atLeast: true } : { value: null, reason: why }
}

/** Plain count tiles (due/succeeded/failed): missing → gap, never 0. */
export function jobsCount(summary: JobsSummary | null | undefined, key: string): MeasuredCount {
  if (!summary) return { value: null, reason: 'Jobs observation unavailable' }
  return measured(summary[key], 'Not reported by the server')
}

// ── Ops → Data approvals ──────────────────────────────────────────────────────────────────────────────────────
export type DataTileKey = 'approved' | 'ready' | 'notReady' | 'findings'
type VerdictRow = { verdict?: string | null; live?: { findings?: unknown[] | null } | null }
type Scan = { state?: string | null } | null | undefined

/**
 * Tiles count verdicts from the rows. While any row is unchecked (scan running, or the row has no verdict yet) the
 * totals are not known: each tile is a gap with "scan running · N of M checked", not 0.
 */
export function dataApprovalTiles(
  rows: readonly VerdictRow[] | null | undefined,
  counts: Record<DataTileKey, number>,
  scan: Scan,
): Record<DataTileKey, MeasuredCount> {
  const rs = rows || []
  const keys: DataTileKey[] = ['approved', 'ready', 'notReady', 'findings']
  const all = (reason: string) => Object.fromEntries(keys.map(k => [k, { value: null, reason }])) as Record<DataTileKey, MeasuredCount>
  if (!rs.length) return all(scan?.state === 'RUNNING' ? 'Scan running · no domain checked yet' : 'No domains were read')
  const checked = rs.filter(r => !!r.verdict).length
  if (checked < rs.length) {
    const lead = scan?.state === 'RUNNING' ? 'Scan running' : scan?.state === 'FAILED' ? 'Scan failed' : 'Not checked yet'
    return all(`${lead} · ${checked} of ${rs.length} checked`)
  }
  return Object.fromEntries(keys.map(k => [k, { value: counts[k], reason: null }])) as Record<DataTileKey, MeasuredCount>
}
