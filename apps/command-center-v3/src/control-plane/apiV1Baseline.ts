/** CONTROL_PLANE_API_V1_BASELINE — frozen HTTP envelope from 084674c5.
 * Integrator-owned. Do not rename keys while R22–R24 consume this freeze.
 * ControlPlane@v1.0.0 remains field vocabulary; this file is the HTTP shape.
 * HTTP 200 + API existence is not a LIVE claim.
 */

export const CONTROL_PLANE_API_V1_BASELINE = 'CONTROL_PLANE_API_V1_BASELINE' as const
export const CONTROL_PLANE_API_V1_BASELINE_COMMIT =
  '084674c560abd7bb910726f62e41508703c07e40' as const

export const CONTROL_PLANE_SUMMARY_ROUTES = {
  system: '/api/v3/control-plane/system',
  agents: '/api/v3/control-plane/agents',
  workflows: '/api/v3/control-plane/workflows',
  research: '/api/v3/control-plane/research',
  stores: '/api/v3/control-plane/stores',
  identity: '/api/v3/control-plane/identity',
  notifications: '/api/v3/control-plane/notifications',
  learning: '/api/v3/control-plane/learning',
  maturity: '/api/v3/control-plane/maturity',
  audit: '/api/v3/control-plane/audit',
} as const

export type ControlPlaneSummaryPage = keyof typeof CONTROL_PLANE_SUMMARY_ROUTES

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
  return ENVELOPE_KEYS.every(key => Object.prototype.hasOwnProperty.call(row, key))
}

export function isControlPlaneApiV1Collection(
  value: unknown,
): value is ControlPlaneApiV1Collection {
  if (value === null || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  const pagination = row.pagination
  return (
    Array.isArray(row.items) &&
    pagination !== null &&
    typeof pagination === 'object' &&
    typeof (pagination as ControlPlaneApiV1Pagination).limit === 'number' &&
    typeof (pagination as ControlPlaneApiV1Pagination).offset === 'number' &&
    typeof (pagination as ControlPlaneApiV1Pagination).total === 'number'
  )
}

/** AVAILABLE + empty items is EMPTY_VALID, not UNAVAILABLE. */
export function collectionViewState(envelope: ControlPlaneApiV1Envelope): string {
  const quality = envelope.data_quality
  if (quality !== 'AVAILABLE') return quality
  if (isControlPlaneApiV1Collection(envelope.data) && envelope.data.pagination.total === 0) {
    return 'EMPTY_VALID'
  }
  return 'AVAILABLE'
}
