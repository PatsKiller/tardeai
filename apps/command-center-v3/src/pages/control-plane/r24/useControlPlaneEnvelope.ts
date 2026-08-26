/** Live CONTROL_PLANE_API_V1_BASELINE loader for R24 summary pages.
 *  GET /api/v3/control-plane/{learning,maturity,audit}. Envelope key is `data`.
 *  Accepts { ok, as_of, source_sha, freshness, data_quality, evidence_class, data }.
 *  Collection data is { items, pagination: {limit, offset, total} }.
 *  UNAVAILABLE / INVALID_SCHEMA / GET failure is the page truth — never keep FIXTURE.
 *  EMPTY_VALID = AVAILABLE + pagination.total 0.
 *  Frozen ControlPlane@v1.0.0 JSON is labeled FIXTURE for tests / injected props only.
 *  HTTP 200 is not a live claim. liveClaim=false. MEMORY_BEHAVIOR_INFLUENCE=0.
 *  Does not compute maturity. Does not auto-promote lessons to policy. */

import { useEffect, useState } from 'react'
import {
  CONTROL_PLANE_API_V1_BASELINE,
  collectionViewState,
  extrasFromData,
  isControlPlaneApiV1Collection,
  isControlPlaneApiV1Envelope,
  isRecord,
  recordsFromItems,
  type ControlPlaneApiV1Envelope,
  type ControlPlaneApiV1Pagination,
} from './httpEnvelope'
import {
  CONTROL_PLANE_GET,
  isControlPlaneEnvelope,
  type ControlPlanePageName,
} from './frozenEnvelope'

export type EnvelopeDataSource = 'FIXTURE' | 'PROP' | 'PENDING' | 'FETCH_FAILED' | `GET ${string}`

const AUTHORITY = 'READ_ONLY_ADVISORY' as const

export interface ControlPlaneView {
  page: ControlPlanePageName
  liveClaim: false
  memoryBehaviorInfluence: 0
  authority: typeof AUTHORITY
  financialAction: false
  computesMaturity: false
  computesCioDecisions: false
  computesAgentState: false
  computesNotificationEligibility: false
  contract: typeof CONTROL_PLANE_API_V1_BASELINE | 'ControlPlane@v1.0.0'
  dataSource: EnvelopeDataSource
  viewState: string
  dataQuality: string | null
  freshness: string | null
  evidenceClass: string | null
  asOf: string | null
  sourceSha: string | null
  ok: boolean | null
  items: Record<string, unknown>[]
  pagination: ControlPlaneApiV1Pagination | null
  data: unknown
  envelope: unknown
  extras: Record<string, unknown>
  error: string | null
  fixtureLabel: boolean
}

const CONSTANTS = {
  liveClaim: false as const,
  memoryBehaviorInfluence: 0 as const,
  authority: AUTHORITY,
  financialAction: false as const,
  computesMaturity: false as const,
  computesCioDecisions: false as const,
  computesAgentState: false as const,
  computesNotificationEligibility: false as const,
}

function fixtureItems(page: ControlPlanePageName, payload: unknown): Record<string, unknown>[] {
  if (!isRecord(payload)) return []
  const key = page === 'maturity' ? 'dimensions' : page === 'audit' ? 'claims' : 'items'
  const raw = payload[key]
  return Array.isArray(raw) ? recordsFromItems(raw) : []
}

function pendingView(page: ControlPlanePageName): ControlPlaneView {
  return {
    ...CONSTANTS,
    page,
    contract: CONTROL_PLANE_API_V1_BASELINE,
    dataSource: 'PENDING',
    viewState: 'PENDING',
    dataQuality: null,
    freshness: null,
    evidenceClass: null,
    asOf: null,
    sourceSha: null,
    ok: null,
    items: [],
    pagination: null,
    data: null,
    envelope: null,
    extras: {},
    error: null,
    fixtureLabel: false,
  }
}

function unavailableView(page: ControlPlanePageName, reason: string, dataSource: EnvelopeDataSource): ControlPlaneView {
  return {
    ...CONSTANTS,
    page,
    contract: CONTROL_PLANE_API_V1_BASELINE,
    dataSource,
    viewState: 'UNAVAILABLE',
    dataQuality: 'UNAVAILABLE',
    freshness: null,
    evidenceClass: null,
    asOf: null,
    sourceSha: null,
    ok: null,
    items: [],
    pagination: null,
    data: null,
    envelope: null,
    extras: {},
    error: reason,
    fixtureLabel: false,
  }
}

function invalidSchemaView(page: ControlPlanePageName, reason: string, envelope: unknown, dataSource: EnvelopeDataSource): ControlPlaneView {
  return {
    ...CONSTANTS,
    page,
    contract: CONTROL_PLANE_API_V1_BASELINE,
    dataSource,
    viewState: 'INVALID_SCHEMA',
    dataQuality: 'INVALID_SCHEMA',
    freshness: null,
    evidenceClass: null,
    asOf: null,
    sourceSha: null,
    ok: null,
    items: [],
    pagination: null,
    data: null,
    envelope,
    extras: {},
    error: reason,
    fixtureLabel: false,
  }
}

function viewFromHttp(
  page: ControlPlanePageName,
  envelope: ControlPlaneApiV1Envelope,
  dataSource: EnvelopeDataSource,
): ControlPlaneView {
  const viewState = collectionViewState(envelope)
  const collection = isControlPlaneApiV1Collection(envelope.data) ? envelope.data : null
  const items = collection ? recordsFromItems(collection.items) : []
  return {
    ...CONSTANTS,
    page,
    contract: CONTROL_PLANE_API_V1_BASELINE,
    dataSource,
    viewState,
    dataQuality: envelope.data_quality,
    freshness: envelope.freshness,
    evidenceClass: envelope.evidence_class,
    asOf: envelope.as_of,
    sourceSha: envelope.source_sha,
    ok: envelope.ok,
    items,
    pagination: collection ? collection.pagination : null,
    data: envelope.data,
    envelope,
    extras: extrasFromData(envelope.data, ['items', 'pagination']),
    error: viewState === 'AVAILABLE' || viewState === 'EMPTY_VALID' ? null : viewState,
    fixtureLabel: false,
  }
}

function viewFromFixture(
  page: ControlPlanePageName,
  envelope: { payload?: unknown; as_of?: unknown; evidence_class?: unknown; source_sha?: unknown; data_quality?: unknown },
  dataSource: EnvelopeDataSource,
): ControlPlaneView {
  const payload = envelope.payload
  return {
    ...CONSTANTS,
    page,
    contract: 'ControlPlane@v1.0.0',
    dataSource,
    viewState: 'FIXTURE',
    dataQuality: typeof envelope.data_quality === 'string' ? envelope.data_quality : null,
    freshness: null,
    evidenceClass: typeof envelope.evidence_class === 'string' ? envelope.evidence_class : null,
    asOf: typeof envelope.as_of === 'string' ? envelope.as_of : null,
    sourceSha: typeof envelope.source_sha === 'string' ? envelope.source_sha : null,
    ok: null,
    items: fixtureItems(page, payload),
    pagination: null,
    data: payload,
    envelope,
    extras: extrasFromData(payload, ['items', 'dimensions', 'claims']),
    error: null,
    fixtureLabel: true,
  }
}

function interpretInjected(page: ControlPlanePageName, injected: unknown): ControlPlaneView {
  if (isControlPlaneApiV1Envelope(injected)) {
    return viewFromHttp(page, injected, 'PROP')
  }
  if (isControlPlaneEnvelope(injected, page)) {
    return viewFromFixture(page, injected, 'FIXTURE')
  }
  return invalidSchemaView(page, 'injected body is not CONTROL_PLANE_API_V1_BASELINE', injected, 'PROP')
}

export function extraPresent(view: ControlPlaneView, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(view.extras, key)
}

export function useControlPlaneEnvelope(
  page: ControlPlanePageName,
  injected?: unknown,
): ControlPlaneView {
  const [view, setView] = useState<ControlPlaneView>(() => {
    if (injected !== undefined) return interpretInjected(page, injected)
    return pendingView(page)
  })

  useEffect(() => {
    if (injected !== undefined) {
      setView(interpretInjected(page, injected))
      return
    }
    const url = CONTROL_PLANE_GET[page]
    let cancelled = false
    setView(pendingView(page))
    fetch(url, {
      method: 'GET',
      cache: 'no-store',
      headers: { accept: 'application/json' },
    })
      .then(async response => {
        if (!response.ok) {
          throw new Error(`GET ${url} status ${response.status}`)
        }
        return response.json()
      })
      .then(body => {
        if (cancelled) return
        if (!isControlPlaneApiV1Envelope(body)) {
          setView(invalidSchemaView(
            page,
            'response is not CONTROL_PLANE_API_V1_BASELINE (data, not payload)',
            body,
            `GET ${url}`,
          ))
          return
        }
        setView(viewFromHttp(page, body, `GET ${url}`))
      })
      .catch(err => {
        if (cancelled) return
        const reason = err instanceof Error ? err.message : 'GET unavailable'
        setView(unavailableView(page, reason, 'FETCH_FAILED'))
      })
    return () => {
      cancelled = true
    }
  }, [page, injected])

  return view
}
