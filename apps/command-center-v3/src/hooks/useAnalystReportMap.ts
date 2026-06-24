/** Registry map: symbol → verified prospectus DOCX/PDF (disk-checked server-side). */
import { useMemo } from 'react'
import { useApi } from './useApi'

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
  const { data } = useApi<any>('/api/v2/reports/analyst/links?limit=500', 120_000)
  return useMemo(() => {
    const payload = data?.data ?? data
    const links = payload?.links ?? {}
    return links as Record<string, AnalystReportEntry>
  }, [data])
}