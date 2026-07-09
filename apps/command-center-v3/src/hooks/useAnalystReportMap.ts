/** Registry map: symbol → verified prospectus DOCX/PDF (disk-checked server-side). */
import { useEffect, useMemo } from 'react'
import { useApi } from './useApi'

export const ANALYST_LINKS_REFETCH = 'cc:analyst-links-refetch'

export function requestAnalystReportMapRefetch() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(ANALYST_LINKS_REFETCH))
}

export type AnalystReportEntry = {
  docx?: string
  pdf?: string
  generated_at?: string
  grok_edited?: boolean
  recommendation?: string
  report_type?: 'symbol_holding' | 'symbol_watchlist'
  generation?: number
  oversight_verdict?: string
}

export function useAnalystReportMap(): Record<string, AnalystReportEntry> {
  const { data, refetch } = useApi<any>('/api/v2/reports/analyst/links?limit=500', 120_000)
  useEffect(() => {
    const onRefetch = () => refetch()
    window.addEventListener(ANALYST_LINKS_REFETCH, onRefetch)
    return () => window.removeEventListener(ANALYST_LINKS_REFETCH, onRefetch)
  }, [refetch])
  return useMemo(() => {
    const payload = data?.data ?? data
    const links = payload?.links ?? {}
    return links as Record<string, AnalystReportEntry>
  }, [data])
}