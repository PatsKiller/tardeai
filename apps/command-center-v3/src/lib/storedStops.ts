// Stored broker stops for page views: the persisted observations the CIO truth document already merges into
// each /api/v2/portfolio/holdings row (stop_last_known → stop_source 'broker_resting', stop_state, stop_price,
// stop_captured_at, stop_qty, stop_order_id). Reading these never triggers a broker call.
//
// Page audit 2026-10-25: Portfolio polled /api/v2/holdings/live-stops every 60 s, and that handler reads Schwab
// on a cache miss. Page views now read the stored model only; an operator-triggered refresh stays where it was.

/** The stored resting stop on one holdings row, in the shape the stop panels read; undefined when none. */
export function storedStopFor(h: any): any | undefined {
  if (!h || String(h.stop_source || '') !== 'broker_resting') return undefined
  // Only an ACTIVE resting order is protection; pending / filled / unknown stay unprotected (never overclaimed).
  if (String(h.stop_state || '') !== 'active') return undefined
  const price = Number(h.stop_price)
  if (!Number.isFinite(price) || price <= 0) return undefined
  return {
    symbol: String(h.symbol || '').toUpperCase(),
    account: h.account,
    stop_price: price,
    qty: h.stop_qty ?? null,
    order_id: h.stop_order_id ?? null,
    status: h.stop_state,
    source: 'stop_last_known',
    broker_verified: false,
    fetched_at: h.stop_captured_at ?? null,
    note: 'Last known broker stop (stored observation; no live broker read on page view)',
  }
}

/** Oldest capture time among the stored resting stops shown (the honest age of the stop section), or null. */
export function storedStopsAsOf(rows: any[]): string | null {
  let oldest: string | null = null
  for (const h of rows || []) {
    const s = storedStopFor(h)
    const at = s?.fetched_at
    if (typeof at === 'string' && at && (oldest == null || at < oldest)) oldest = at
  }
  return oldest
}
