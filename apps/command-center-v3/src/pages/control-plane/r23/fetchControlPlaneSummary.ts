/**
 * CONTROL_PLANE_API_V1_BASELINE (084674c5) consumer.
 * GET-only summary helper for R23 pages. Does not implement HTTP APIs.
 * Envelope key is `data`, not ControlPlane@v1.0.0 `payload`.
 * HTTP 200 / API existence is not a LIVE claim. live_claim=false.
 *
 * Canonical files (missing => UNAVAILABLE, legitimate):
 *   data/runtime/research_attention.json
 *   data/runtime/canonical_store_registry.json or store_registry.json
 *   data/runtime/identity_registry.json
 *   data/runtime/notification_receipts.json
 *
 * Do not fall back to populated ControlPlane@v1.0.0 preview JSON.
 * Do not mint identities, decide notification class, or recompute store freshness.
 */

export const CONTROL_PLANE_API_V1_BASELINE = 'CONTROL_PLANE_API_V1_BASELINE' as const
export const CONTROL_PLANE_API_V1_BASELINE_COMMIT =
  '084674c560abd7bb910726f62e41508703c07e40' as const

export const CONTROL_PLANE_SUMMARY_GET = {
  research: '/api/v3/control-plane/research',
  stores: '/api/v3/control-plane/stores',
  identity: '/api/v3/control-plane/identity',
  notifications: '/api/v3/control-plane/notifications',
} as const

export const CANONICAL_RUNTIME_FILES = {
  research: 'data/runtime/research_attention.json',
  stores: 'data/runtime/canonical_store_registry.json or store_registry.json',
  identity: 'data/runtime/identity_registry.json',
  notifications: 'data/runtime/notification_receipts.json',
} as const

export type ControlPlaneSummaryGetPath =
  (typeof CONTROL_PLANE_SUMMARY_GET)[keyof typeof CONTROL_PLANE_SUMMARY_GET]

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

export type DataQualityViewState =
  | 'UNAVAILABLE'
  | 'INVALID_SCHEMA'
  | 'STALE'
  | 'DEGRADED'
  | 'EMPTY_VALID'
  | 'AVAILABLE'
  | 'LOADING'

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
  return ENVELOPE_KEYS.every((key) => Object.prototype.hasOwnProperty.call(row, key))
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

/**
 * Banner state from data_quality.
 * EMPTY_VALID = AVAILABLE and pagination.total===0
 * UNAVAILABLE with items=[] is NOT EMPTY_VALID.
 * Pages must read data_quality, not ok (UNAVAILABLE still has ok:true).
 */
export function viewStateFromEnvelope(envelope: ControlPlaneApiV1Envelope): string {
  const quality = envelope.data_quality
  if (quality === 'UNAVAILABLE') return 'UNAVAILABLE'
  if (quality === 'INVALID_SCHEMA') return 'INVALID_SCHEMA'
  if (quality === 'STALE') return 'STALE'
  if (quality === 'DEGRADED') return 'DEGRADED'
  if (quality === 'AVAILABLE') {
    if (isControlPlaneApiV1Collection(envelope.data) && envelope.data.pagination.total === 0) {
      return 'EMPTY_VALID'
    }
    return 'AVAILABLE'
  }
  if (quality === undefined || quality === null || quality === '') return 'UNAVAILABLE'
  return String(quality)
}

export function collectionItems(data: unknown): Record<string, unknown>[] {
  if (!isControlPlaneApiV1Collection(data)) return []
  const items: Record<string, unknown>[] = []
  for (const row of data.items) {
    if (row !== null && typeof row === 'object' && !Array.isArray(row)) {
      items.push(row as Record<string, unknown>)
    }
  }
  return items
}

export function collectionPagination(data: unknown): ControlPlaneApiV1Pagination | null {
  if (!isControlPlaneApiV1Collection(data)) return null
  return data.pagination
}

export interface ControlPlaneFetchResult {
  envelope: ControlPlaneApiV1Envelope | null
  viewState: string
  error: string | null
}

export async function fetchControlPlaneSummary(
  path: ControlPlaneSummaryGetPath | string,
  init?: { signal?: AbortSignal },
): Promise<ControlPlaneFetchResult> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
      signal: init?.signal,
    })
  } catch (err) {
    if (isAbortError(err)) {
      return { envelope: null, viewState: 'LOADING', error: 'aborted' }
    }
    return {
      envelope: null,
      viewState: 'UNAVAILABLE',
      error: 'GET failed — canonical projection unreachable',
    }
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    return {
      envelope: null,
      viewState: 'INVALID_SCHEMA',
      error: 'GET body is not JSON',
    }
  }

  return parseControlPlaneResponse(response.status, body)
}

export function parseControlPlaneResponse(
  httpStatus: number,
  body: unknown,
): ControlPlaneFetchResult {
  if (!isControlPlaneApiV1Envelope(body)) {
    return {
      envelope: null,
      viewState: 'INVALID_SCHEMA',
      error: `HTTP ${httpStatus} body is not CONTROL_PLANE_API_V1_BASELINE envelope`,
    }
  }
  return {
    envelope: body,
    viewState: viewStateFromEnvelope(body),
    error: null,
  }
}

function isAbortError(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'name' in err &&
    (err as { name: string }).name === 'AbortError'
  )
}
