import { useMemo } from 'react'
import { useApi } from './useApi'
import type { IntelligenceItemStatus, IntelligenceItemType } from '../lib/intelligenceItemId'

export function useIntelligenceItemState(ids: string[], itemType?: IntelligenceItemType) {
  const unique = useMemo(() => [...new Set(ids.filter(Boolean))], [ids])
  const qs = unique.length
    ? `ids=${encodeURIComponent(unique.join(','))}${itemType ? `&type=${encodeURIComponent(itemType)}` : ''}`
    : ''
  const { data, loading, error, refetch } = useApi<Record<string, { status: IntelligenceItemStatus; note?: string; updated_at?: string }>>(
    `/api/v2/intelligence/item-state?${qs || 'ids='}`,
    60_000,
    { enabled: unique.length > 0 },
  )
  const byId = useMemo(() => {
    const m = new Map<string, IntelligenceItemStatus>()
    const raw = data ?? {}
    for (const [id, row] of Object.entries(raw)) {
      if (row?.status) m.set(id, row.status)
    }
    return m
  }, [data])
  return { byId, loading, error, refresh: refetch }
}
