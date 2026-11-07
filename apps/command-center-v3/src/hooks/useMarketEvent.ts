import { useMemo } from 'react'
import { useApi } from './useApi'
import { MARKET_EVENT_ACTIVE_API, bannerModel, normalizeMarketEvent } from '../lib/marketEvent'

/** GET /api/v2/market-event/active (MarketEvent@v1), polled once a minute. `event` is null until a valid body arrives. */
export function useMarketEvent(options?: { enabled?: boolean }) {
  const api = useApi<any>(MARKET_EVENT_ACTIVE_API, 60_000, options)
  const event = useMemo(() => normalizeMarketEvent(api.data), [api.data])
  const banner = useMemo(() => bannerModel({ data: api.data, loading: api.loading, error: api.error }), [api.data, api.loading, api.error])
  return { ...api, event, banner }
}
