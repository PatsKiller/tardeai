/** Unwrap the metric-guide response (hotfix 2026-09-28).
 *
 * api_v2 wraps every payload as `{ ok, data }`; the PR3 loader read `entries` off the raw
 * body and so never saw the served YAML (it fell back to the local registry). Pure, no
 * imports, so the build's plain-node test can cover it.
 */
export type GuideBody = { version?: unknown; entries?: unknown; guide?: unknown; metrics?: unknown }

export function unwrapGuideResponse(j: unknown): { entries: Record<string, unknown>; version: string } | null {
  if (!j || typeof j !== 'object') return null
  const raw = j as { data?: unknown } & GuideBody
  const body: GuideBody = raw.data && typeof raw.data === 'object' ? (raw.data as GuideBody) : raw
  const entries = body.entries || body.guide || body.metrics
  if (!entries || typeof entries !== 'object' || Array.isArray(entries)) return null
  return { entries: entries as Record<string, unknown>, version: String(body.version || 'server') }
}
