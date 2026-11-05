// Stored broker stops for page views: the persisted observations the CIO truth document already merges into
// each /api/v2/portfolio/holdings row (stop_last_known → stop_source 'broker_resting', stop_state, stop_price,
// stop_captured_at, stop_qty, stop_order_id). Reading these never triggers a broker call.
//
// Page audit 2026-10-25: Portfolio polled /api/v2/holdings/live-stops every 60 s, and that handler reads Schwab
// on a cache miss. Page views now read the stored model only; an operator-triggered refresh stays where it was.

/** The stored resting stop on one holdings row, in the shape the stop panels read; undefined when none.

    An ACTIVE broker order is reported even when its trigger price was not recorded — a trailing stop has no fixed
    trigger price in the stored observation. Dropping that row made the stored page model state that a position has
    no broker stop while the broker still holds one. The unknown price stays null and is flagged, never filled in
    from a planned or advisory level. */
export function storedStopFor(h: any): any | undefined {
  if (!h || String(h.stop_source || '') !== 'broker_resting') return undefined
  // Only an ACTIVE resting order is protection; pending / filled / unknown stay unprotected (never overclaimed).
  if (String(h.stop_state || '') !== 'active') return undefined
  const rawPrice = Number(h.stop_price)
  const price = Number.isFinite(rawPrice) && rawPrice > 0 ? rawPrice : null
  const orderType = String(h.stop_order_type || h.order_type || '').trim().toUpperCase() || null
  return {
    symbol: String(h.symbol || '').toUpperCase(),
    account: h.account,
    stop_price: price,
    // The trigger price is UNKNOWN, not zero and not an advisory level: a screen must say "not recorded".
    price_unknown: price == null,
    order_type: orderType,
    trail_offset: h.trail_offset ?? null,
    trail_pct: h.trail_pct ?? null,
    qty: h.stop_qty ?? null,
    order_id: h.stop_order_id ?? null,
    status: h.stop_state,
    source: 'stop_last_known',
    broker_verified: false,
    fetched_at: h.stop_captured_at ?? null,
    // The wording never says "trailing": isTrailingBrokerStop() reads this note as a last resort, so naming a kind
    // here would classify every unpriced order as trailing whatever its order_type says. The kind comes only from
    // the broker's own order metadata (order_type / trail offsets).
    note: price == null
      ? 'Last known broker stop (stored observation; trigger price not recorded; no live broker read on page view)'
      : 'Last known broker stop (stored observation; no live broker read on page view)',
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
