export type CalibrationBucket = { bucket: string; n: number; hit_rate: number | null }
export type AgentCalibrationRow = {
  agent: string
  scored_outcomes: number
  status: 'MEASURED' | 'INSUFFICIENT_SAMPLE' | string
  hit_rate: number | null
  brier: number | null
  by_confidence?: CalibrationBucket[]
  by_basis?: Record<string, number>
  by_surface?: Record<string, number>
}
export type AgentCalibrationResponse = {
  ok?: boolean
  schema?: string
  min_sample?: number
  agents?: AgentCalibrationRow[]
  unscored_observations?: number
  note?: string
}

/** Hit rate as text; below the sample floor it is never shown as a number. */
export function hitRateText(row: AgentCalibrationRow, minSample: number): string {
  if (row.status !== 'MEASURED' || row.hit_rate === null || row.hit_rate === undefined) {
    return `insufficient sample (${row.scored_outcomes} of ${minSample} scored)`
  }
  return `${Math.round(row.hit_rate * 100)}% hit · ${row.scored_outcomes} scored`
}

/** "DIRECTIONAL 20 · EXPECTATION 4" — readable, never raw JSON. */
export function countsText(counts: Record<string, number> | undefined): string {
  const parts = Object.entries(counts || {}).filter(([, n]) => n > 0).map(([k, n]) => `${k.toLowerCase().replace(/_/g, ' ')} ${n}`)
  return parts.length ? parts.join(' · ') : 'none'
}

export function bucketText(b: CalibrationBucket): string {
  const label = b.bucket === 'not_stated' ? 'confidence not stated' : `stated ${b.bucket}`
  return b.hit_rate === null ? `${label}: ${b.n} scored (sample too small)` : `${label}: ${Math.round(b.hit_rate * 100)}% hit of ${b.n}`
}
