/**
 * FQ-033 (cc-deepseek-8 R1 at 75251580): the panel said "PR census could not refresh — the last good copy is shown"
 * whenever `census.warning` was truthy. `warning` is not a failure flag. `scripts/lib/work_pipeline.py` initialises it
 * to "PR census: first refresh pending" before any refresh has run, and replaces it with the joined PARTIAL warnings
 * after a SUCCESSFUL refresh. So a freshly started server told the operator a refresh had failed and that a good copy
 * was on screen when no copy existed, and a partly degraded census was described as a failure — the same class of
 * defect this row exists to remove: text asserting something the code did not do.
 *
 * The sentence is now chosen from the fact that makes it true, and says no more than the payload shows. Import-free so
 * the gate can test it directly.
 */
export type CensusSituation = {
  /** no refresh has been recorded yet — whatever else is true, there is no copy to show */
  pending: boolean
  /** the sentence for the panel, or '' when the payload calls for none */
  text: string
}

export function censusSituation(a: { refreshedAt?: string | null; warning?: string | null }): CensusSituation {
  const pending = !a.refreshedAt
  const warned = typeof a.warning === 'string' && a.warning.trim() !== ''
  if (pending) {
    return { pending: true, text: warned ? 'PR census is still loading — there is no census copy yet.' : '' }
  }
  // A refresh HAS happened. A warning may be a partial one from a successful refresh, so the panel never claims the
  // whole refresh failed; the producer's own words stay under Technical.
  return { pending: false, text: warned ? 'PR census reported a problem — its own words are under Technical.' : '' }
}
