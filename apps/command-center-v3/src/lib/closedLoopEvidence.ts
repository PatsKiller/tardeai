/** Plain evidence wording shared by the rendered proposal caller and the dependency-light CI gate. */
export function closedLoopEvidenceText(evidence: Record<string, unknown> | null | undefined, metrics: Record<string, unknown> | null | undefined): string {
  const delta = evidence?.score_delta
  const numericDelta = typeof delta === 'number' || (typeof delta === 'string' && delta.trim() !== '')
    ? Number(delta)
    : NaN
  const absent = !Number.isFinite(numericDelta)
  const sample = evidence?.sample_days != null
    ? `Based on ${evidence.sample_days} days of signals`
    : 'Based on the available signals'
  const confidence = evidence?.confidence ? ` · confidence ${String(evidence.confidence).toLowerCase()}` : ''
  const change = absent
    ? ' · score change not recorded'
    : numericDelta !== 0
      ? ` · score ${numericDelta > 0 ? 'up' : 'down'} ${Math.abs(numericDelta).toFixed(3)}`
      : ' · score unchanged'
  const trigger = metrics?.trigger_rate != null
    ? ` · candidate trigger rate ${(Number(metrics.trigger_rate) * 100).toFixed(0)}% (scoring-window length not recorded)`
    : ''
  return sample + confidence + change + trigger
}
