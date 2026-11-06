/**
 * Retired Intel routes (intel/v001, 2026-11-06) redirect to their new home. The map lives in
 * lib/intelConsolidation.ts so it is unit-tested; these components only read the query string.
 */
import { Navigate, useLocation } from 'react-router-dom'
import { intelligenceRedirect, keepQueryRedirect, recIntelRedirect } from '../../lib/intelConsolidation'

export function IntelligenceRedirect() {
  const { search } = useLocation()
  return <Navigate to={intelligenceRedirect(search)} replace />
}

export function RecIntelRedirect() {
  const { search } = useLocation()
  return <Navigate to={recIntelRedirect(search)} replace />
}

export function KeepQueryRedirect({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={keepQueryRedirect(to, search)} replace />
}
