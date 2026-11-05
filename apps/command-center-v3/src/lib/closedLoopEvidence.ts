/** Plain evidence wording shared by the rendered proposal caller and the dependency-light CI gate. */
export function closedLoopEvidenceText(evidence: Record<string, unknown> | null | undefined, metrics: Record<string, unknown> | null | undefined): string {
  const delta = evidence?.score_delta
  const absent = delta == null || String(delta).trim() === ''
  const sample = evidence?.sample_days != null
    ? `Based on ${evidence.sample_days} days of signals`
    : 'Based on the available signals'
  const confidence = evidence?.confidence ? ` · confidence ${String(evidence.confidence).toLowerCase()}` : ''
  const change = absent
    ? ' · score change not recorded'
    : Number(delta) !== 0
      ? ` · score ${Number(delta) > 0 ? 'up' : 'down'} ${Math.abs(Number(delta)).toFixed(3)}`
      : ' · score unchanged'
  const trigger = metrics?.trigger_rate != null
    ? ` · fired on ${(Number(metrics.trigger_rate) * 100).toFixed(0)}% of those days`
    : ''
  return sample + confidence + change + trigger
}
