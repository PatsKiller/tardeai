// node --experimental-strip-types src/lib/draftOrderView.test.ts
// A saved draft reads with the side/type/price it actually carries (page audit 2026-10-25: protective SELL
// stops showed as "BUY … STOP" with "NO STOP"). Synthetic drafts only.
import { draftOrderView, protectiveStopLine, PROTECTIVE_STOP_MARKER } from './draftOrderView.ts'
declare const process: { exit(code?: number): never }

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}

// Stage 2c protective stop, shaped like protective_stop_pilot.build_intent: direction stays LONG.
const protective = {
  direction: 'LONG', entry: { method: 'STOP', stop_price: 101.25 }, tif: 'GTC',
  meta: { strategy_id: PROTECTIVE_STOP_MARKER, signal_evidence: { instruction: 'SELL', order_type: 'STOP', stop_price: 101.25 } },
}
const v = draftOrderView(protective)
eq('protective side is SELL, never BUY', v.side, 'SELL')
eq('protective type from the draft', v.orderType, 'STOP')
eq('protective price is the stop trigger', v.price, 101.25)
eq('protective flagged', v.protective, true)
eq('line', protectiveStopLine({ side: v.side, qty: 7, symbol: 'FIXA', orderType: v.orderType, price: v.price, tif: 'GTC' }),
  'SELL 7 FIXA STOP 101.25 GTC — protective stop')

// Marker alone (older rows without signal_evidence.instruction) still reads SELL.
eq('marker only → SELL', draftOrderView({ direction: 'LONG', entry: { method: 'STOP', stop_price: 5 }, meta: { strategy_id: PROTECTIVE_STOP_MARKER } }).side, 'SELL')

// Stop-limit and trailing.
const sl = draftOrderView({ direction: 'LONG', entry: { method: 'STOP_LIMIT', stop_price: 50, limit_price: 49.5 },
  meta: { strategy_id: PROTECTIVE_STOP_MARKER, signal_evidence: { instruction: 'SELL', order_type: 'STOP_LIMIT' } } })
eq('stop-limit type', sl.orderType, 'STOP_LIMIT')
eq('stop-limit price is the trigger', sl.price, 50)
const tr = draftOrderView({ direction: 'LONG', entry: { method: 'STOP', stop_price: 80 },
  meta: { strategy_id: PROTECTIVE_STOP_MARKER, signal_evidence: { instruction: 'SELL', order_type: 'TRAILING_STOP', trail_pct: 6 } } })
eq('trailing type from evidence, not entry.method', tr.orderType, 'TRAILING_STOP')
eq('trailing pct', tr.trailPct, 6)
eq('trailing line shows the trail, not the reference price',
  protectiveStopLine({ side: tr.side, qty: 3, symbol: 'FIXB', orderType: tr.orderType, price: tr.price, tif: 'GTC', trailPct: tr.trailPct }),
  'SELL 3 FIXB TRAILING STOP trail 6% GTC — protective stop')

// Ordinary entry drafts are unchanged.
const buy = draftOrderView({ direction: 'LONG', entry: { method: 'LIMIT', limit_price: 20 } })
eq('buy entry stays BUY', [buy.side, buy.orderType, buy.price, buy.protective], ['BUY', 'LIMIT', 20, false])
const short = draftOrderView({ direction: 'SHORT', entry: { method: 'LIMIT', limit_price: 20 } })
eq('short entry stays SELL SHORT', [short.side, short.protective], ['SELL SHORT', false])
const buyStop = draftOrderView({ direction: 'LONG', entry: { method: 'STOP', stop_price: 30 } })
eq('a BUY stop entry without a SELL instruction stays BUY (no inversion either way)', [buyStop.side, buyStop.protective], ['BUY', false])
eq('empty draft', draftOrderView(null), { side: 'BUY', orderType: 'LIMIT', price: null, protective: false, trailPct: null })

if (failed) { console.error(`${failed} failed`); process.exit(1) }
console.log('draftOrderView: all passed')
