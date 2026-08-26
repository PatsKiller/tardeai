/** CONTROL_PLANE_API_V1_BASELINE summary GET helper (R22 page-local).
 *
 * HTTP freeze envelope (do not invent a different shape):
 *   { ok, as_of, source_sha, freshness, data_quality, evidence_class, data }
 * Collection data:
 *   { items: object[], pagination: { limit, offset, total } }
 *
 * First paint is LOADING, then the API envelope.
 * Fetch failure → data_quality=UNAVAILABLE (honest). Never substitute a populated
 * ControlPlane@v1.0.0 fixture as live list data.
 *
 * ok=true with UNAVAILABLE is real — do not treat ok as live.
 * API existence is not a LIVE claim. Never infer LIVE_EVENT_DRIVEN from process/pid/queue.
 *
 * Do NOT call GET /api/v3/control-plane/agents/{id} or /workflows/{id} (R21.1 pending).
 */

import { useEffect, useState } from 'react'

export const CONTROL_PLANE_HTTP_FREEZE = 'CONTROL_PLANE_API_V1_BASELINE'

export const CONTROL_PLANE_AGENTS_URL = '/api/v3/control-plane/agents'
export const CONTROL_PLANE_WORKFLOWS_URL = '/api/v3/control-plane/workflows'

export function agentDetailUrl(agentId: string): string {
  return `/api/v3/control-plane/agents/${encodeURIComponent(agentId)}`
}

export function workflowDetailUrl(workflowId: string): string {
  return `/api/v3/control-plane/workflows/${encodeURIComponent(workflowId)}`
}

/** data_quality values that pages MUST render explicitly (no empty-state ambiguity). */
export const DATA_QUALITY_VALUES = [
  'AVAILABLE',
  'UNAVAILABLE',
  'INVALID_SCHEMA',
  'STALE',
  'DEGRADED',
  'EMPTY_VALID',
] as const

export type DataQualityValue = (typeof DATA_QUALITY_VALUES)[number]

/** EMPTY_VALID = data_quality AVAILABLE AND pagination.total === 0 */
export const EMPTY_VALID_RULE =
  'EMPTY_VALID = data_quality AVAILABLE AND pagination.total === 0'

export const ENVELOPE_KEYS = [
  'ok',
  'as_of',
  'source_sha',
  'freshness',
  'data_quality',
  'evidence_class',
  'data',
] as const

export type ControlPlaneHttpEnvelope = {
  ok: boolean
  as_of: string | null
  source_sha: string | null
  freshness: string | null
  data_quality: string
  evidence_class: string
  data: unknown
}

export type CollectionPagination = {
  limit: number
  offset: number
  total: number
}

export type CollectionData = {
  items: Record<string, unknown>[]
  pagination: CollectionPagination
}

export type FetchPhase = 'LOADING' | 'READY'

const DEFAULT_PAGINATION: CollectionPagination = { limit: 50, offset: 0, total: 0 }

function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key)
}

export function isHttpEnvelope(body: unknown): body is ControlPlaneHttpEnvelope {
  if (!body || typeof body !== 'object') return false
  const rec = body as Record<string, unknown>
  for (const key of ENVELOPE_KEYS) {
    if (!hasOwn(rec, key)) return false
  }
  return typeof rec.ok === 'boolean'
    && typeof rec.data_quality === 'string'
    && typeof rec.evidence_class === 'string'
}

export function asCollection(data: unknown): CollectionData | null {
  if (!data || typeof data !== 'object') return null
  const rec = data as Record<string, unknown>
  if (!Array.isArray(rec.items)) return null
  const pag = rec.pagination
  if (!pag || typeof pag !== 'object') return null
  const p = pag as Record<string, unknown>
  if (typeof p.limit !== 'number' || typeof p.offset !== 'number' || typeof p.total !== 'number') {
    return null
  }
  const items: Record<string, unknown>[] = []
  for (const row of rec.items) {
    if (row && typeof row === 'object' && !Array.isArray(row)) {
      items.push(row as Record<string, unknown>)
    }
  }
  return {
    items,
    pagination: { limit: p.limit, offset: p.offset, total: p.total },
  }
}

export function displayedDataQuality(
  envelope: ControlPlaneHttpEnvelope,
  collection: CollectionData | null,
): string {
  if (
    envelope.data_quality === 'AVAILABLE'
    && collection
    && collection.pagination.total === 0
  ) {
    return 'EMPTY_VALID'
  }
  return envelope.data_quality
}

export function unavailableEnvelope(reason: string): ControlPlaneHttpEnvelope {
  return {
    ok: true,
    as_of: null,
    source_sha: null,
    freshness: null,
    data_quality: 'UNAVAILABLE',
    evidence_class: 'SOURCE_ONLY',
    data: {
      items: [],
      pagination: { ...DEFAULT_PAGINATION },
      error: reason,
    },
  }
}

export function invalidSchemaEnvelope(reason: string): ControlPlaneHttpEnvelope {
  return {
    ok: false,
    as_of: null,
    source_sha: null,
    freshness: null,
    data_quality: 'INVALID_SCHEMA',
    evidence_class: 'SOURCE_ONLY',
    data: {
      items: [],
      pagination: { ...DEFAULT_PAGINATION },
      error: reason,
    },
  }
}

export async function fetchControlPlaneSummary(
  url: string,
  signal?: AbortSignal,
): Promise<ControlPlaneHttpEnvelope> {
  try {
    const response = await fetch(url, {
      method: 'GET',
      cache: 'no-store',
      headers: { accept: 'application/json' },
      signal,
    })
    const text = await response.text()
    let body: unknown
    try {
      body = JSON.parse(text)
    } catch {
      return invalidSchemaEnvelope('response is not JSON')
    }
    if (!isHttpEnvelope(body)) {
      return invalidSchemaEnvelope('response is not a CONTROL_PLANE_API_V1_BASELINE envelope')
    }
    return body
  } catch (err) {
    if (signal?.aborted) {
      return unavailableEnvelope('aborted')
    }
    const message = err instanceof Error ? err.message : 'fetch failed'
    return unavailableEnvelope(message)
  }
}

export function useControlPlaneSummary(url: string): {
  phase: FetchPhase
  envelope: ControlPlaneHttpEnvelope | null
} {
  const [phase, setPhase] = useState<FetchPhase>('LOADING')
  const [envelope, setEnvelope] = useState<ControlPlaneHttpEnvelope | null>(null)

  useEffect(() => {
    if (!url) {
      setPhase('READY')
      setEnvelope(null)
      return
    }
    const controller = new AbortController()
    setPhase('LOADING')
    setEnvelope(null)
    fetchControlPlaneSummary(url, controller.signal).then(next => {
      if (controller.signal.aborted) return
      setEnvelope(next)
      setPhase('READY')
    })
    return () => {
      controller.abort()
    }
  }, [url])

  return { phase, envelope }
}
