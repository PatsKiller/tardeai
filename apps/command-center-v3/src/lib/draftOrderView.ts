// How a saved broker draft READS on the Manual Entry Desk: side, order type and price taken from the
// draft's own fields, never assumed. Display/read-model only: nothing here builds, stages or sends an order.
//
// Page audit 2026-10-25: Stage 2c protective stops (sell-to-close a held long, stamped
// meta.strategy_id = PROTECTIVE_STOP_2C, meta.signal_evidence.instruction = SELL) were shown as
// "BUY 201 V STOP 350.35 GTC" with "NO STOP — risk undefined", because the desk derived the side from
// `direction` (LONG, which the protective intent keeps because the SELL closes the long).

export const PROTECTIVE_STOP_MARKER = 'PROTECTIVE_STOP_2C'

export type DraftOrderView = {
  /** BUY · SELL · SELL SHORT … exactly as the draft says. */
  side: string
  /** STOP · STOP_LIMIT · TRAILING_STOP · MARKET · LIMIT … from the draft. */
  orderType: string
  /** The draft's working price (stop trigger for a stop, limit for a limit); null when it has none. */
  price: number | null
  /** True when the draft is itself a protective sell stop on a held position. */
  protective: boolean
  /** Trailing stops: the trail percent from the draft (the price is then only the live reference). */
  trailPct: number | null
}

function num(v: unknown): number | null {
  const n = typeof v === 'string' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : null
}
function word(v: unknown): string {
  return typeof v === 'string' ? v.trim().toUpperCase() : ''
}

/** `intent` is the draft's intent_json (or the draft itself when the row is already the intent). */
export function draftOrderView(intent: any): DraftOrderView {
  const it = intent ?? {}
  const entry = it.entry ?? {}
  const meta = it.meta ?? {}
  const ev = meta.signal_evidence ?? {}
  const instruction = word(ev.instruction ?? it.instruction ?? it.side)
  const protective = word(meta.strategy_id) === PROTECTIVE_STOP_MARKER
  const direction = word(it.direction)
  let side: string
  if (instruction === 'SELL' || instruction === 'BUY' || instruction === 'SELL_SHORT' || instruction === 'BUY_TO_COVER') {
    side = instruction.replace(/_/g, ' ')
  } else if (protective) {
    side = 'SELL'  // a protective stop closes a held long; the marker alone says so
  } else {
    side = direction === 'SHORT' ? 'SELL SHORT' : 'BUY'
  }
  const orderType = word(ev.order_type) || word(entry.method) || 'LIMIT'
  const price = orderType.includes('STOP')
    ? num(entry.stop_price) ?? num(ev.stop_price) ?? num(entry.limit_price)
    : num(entry.limit_price) ?? num(entry.stop_price)
  return {
    side, orderType, price,
    protective: protective || (side === 'SELL' && orderType.includes('STOP') && direction !== 'SHORT'),
    trailPct: orderType === 'TRAILING_STOP' ? num(ev.trail_pct) : null,
  }
}

/** The one-line read of a protective stop draft, for copy text: "SELL 201 V STOP 350.35 GTC — protective stop". */
export function protectiveStopLine(o: { side: string; qty: number; symbol: string; orderType: string; price: number | null; tif: string; trailPct?: number | null }): string {
  const px = o.trailPct != null ? ` trail ${o.trailPct}%` : o.price != null ? ` ${o.price.toFixed(2)}` : ''
  return `${o.side} ${o.qty} ${o.symbol} ${o.orderType.replace(/_/g, ' ')}${px} ${o.tif} — protective stop`
}
