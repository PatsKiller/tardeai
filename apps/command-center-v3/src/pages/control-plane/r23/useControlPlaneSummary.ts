/**
 * GET-only hook for CONTROL_PLANE_API_V1_BASELINE summary routes.
 * Injected envelope is for tests/layout only — not a live fallback.
 * Preview JSON must not be passed off as the API result.
 */

import { useEffect, useMemo, useState } from 'react'
import {
  collectionItems,
  collectionPagination,
  fetchControlPlaneSummary,
  viewStateFromEnvelope,
  type ControlPlaneApiV1Collection,
  type ControlPlaneApiV1Envelope,
  type ControlPlaneApiV1Pagination,
} from './fetchControlPlaneSummary'

export interface ControlPlaneSummaryState {
  loading: boolean
  envelope: ControlPlaneApiV1Envelope | null
  viewState: string
  error: string | null
  items: Record<string, unknown>[]
  pagination: ControlPlaneApiV1Pagination | null
}

export function useControlPlaneSummary(
  path: string,
  injected?: ControlPlaneApiV1Envelope<ControlPlaneApiV1Collection> | ControlPlaneApiV1Envelope | null,
): ControlPlaneSummaryState {
  const [loading, setLoading] = useState(!injected)
  const [envelope, setEnvelope] = useState<ControlPlaneApiV1Envelope | null>(injected ?? null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (injected) {
      setEnvelope(injected)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    const ac = new AbortController()
    setLoading(true)
    setError(null)
    fetchControlPlaneSummary(path, { signal: ac.signal }).then((result) => {
      if (cancelled) return
      if (result.error === 'aborted') return
      setEnvelope(result.envelope)
      setError(result.error)
      setLoading(false)
    })
    return () => {
      cancelled = true
      ac.abort()
    }
  }, [path, injected])

  return useMemo(() => {
    if (loading) {
      return {
        loading: true,
        envelope,
        viewState: 'LOADING',
        error,
        items: [],
        pagination: envelope ? collectionPagination(envelope.data) : null,
      }
    }
    const viewState = envelope
      ? viewStateFromEnvelope(envelope)
      : error === 'GET body is not JSON' || (error && error.includes('INVALID_SCHEMA'))
        ? 'INVALID_SCHEMA'
        : 'UNAVAILABLE'
    return {
      loading: false,
      envelope,
      viewState,
      error,
      items: envelope ? collectionItems(envelope.data) : [],
      pagination: envelope ? collectionPagination(envelope.data) : null,
    }
  }, [loading, envelope, error])
}
