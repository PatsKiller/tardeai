/** CONTROL_PLANE_API_V1_BASELINE HTTP envelope (084674c5).
 *  Live R24 pages consume this shape. Envelope key is `data`, not `payload`.
 *  ControlPlane@v1.0.0 remains field vocabulary; it is not the HTTP response.
 *  HTTP 200 / API existence is not a LIVE claim. live_claim=false always.
 *  MEMORY_BEHAVIOR_INFLUENCE=0. Do not infer maturity, promotions, or RuntimeStatus.
 */

export const CONTROL_PLANE_API_V1_BASELINE = 'CONTROL_PLANE_API_V1_BASELINE' as const
export const CONTROL_PLANE_API_V1_BASELINE_COMMIT =
  '084674c560abd7bb910726f62e41508703c07e40' as const

export const CONTROL_PLANE_SUMMARY_GET = {
  learning: '/api/v3/control-plane/learning',
  maturity: '/api/v3/control-plane/maturity',
  audit: '/api/v3/control-plane/audit',
} as const

export interface ControlPlaneApiV1Envelope<T = unknown> {
  ok: boolean
  as_of: string
  source_sha: string | null
  freshness: string
  data_quality: string
  evidence_class: string
  data: T
}

export interface ControlPlaneApiV1Pagination {
  limit: number
  offset: number
  total: number
}

export interface ControlPlaneApiV1Collection<T = Record<string, unknown>> {
  items: T[]
  pagination: ControlPlaneApiV1Pagination
}

const ENVELOPE_KEYS = [
  'ok',
  'as_of',
  'source_sha',
  'freshness',
  'data_quality',
  'evidence_class',
  'data',
] as const

export function isControlPlaneApiV1Envelope(
  value: unknown,
): value is ControlPlaneApiV1Envelope {
  if (value === null || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  if (!ENVELOPE_KEYS.every(key => Object.prototype.hasOwnProperty.call(row, key))) return false
  if (typeof row.ok !== 'boolean') return false
  if (typeof row.as_of !== 'string') return false
  if (row.source_sha !== null && typeof row.source_sha !== 'string') return false
  if (typeof row.freshness !== 'string') return false
  if (typeof row.data_quality !== 'string') return false
  if (typeof row.evidence_class !== 'string') return false
  return true
}

export function isControlPlaneApiV1Collection(
  value: unknown,
): value is ControlPlaneApiV1Collection {
  if (value === null || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  const pagination = row.pagination
  if (!Array.isArray(row.items)) return false
  if (pagination === null || typeof pagination !== 'object') return false
  const page = pagination as Record<string, unknown>
  return (
    typeof page.limit === 'number' &&
    typeof page.offset === 'number' &&
    typeof page.total === 'number'
  )
}

/** AVAILABLE + empty items is EMPTY_VALID, not UNAVAILABLE. */
export function collectionViewState(envelope: ControlPlaneApiV1Envelope): string {
  const quality = envelope.data_quality
  if (quality !== 'AVAILABLE') return quality
  if (!isControlPlaneApiV1Collection(envelope.data)) return 'INVALID_SCHEMA'
  if (envelope.data.pagination.total === 0) return 'EMPTY_VALID'
  return 'AVAILABLE'
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function recordsFromItems(items: unknown[]): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  for (const item of items) {
    if (isRecord(item)) out.push(item)
  }
  return out
}

export function extrasFromData(data: unknown, skip: readonly string[]): Record<string, unknown> {
  if (!isRecord(data)) return {}
  const extras: Record<string, unknown> = {}
  for (const key of Object.keys(data)) {
    if (skip.indexOf(key) >= 0) continue
    extras[key] = data[key]
  }
  return extras
}
