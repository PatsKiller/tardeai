// ── Schwab Trader API ticket DRAFTS from the exit ladder — preview/copy only ──
// Generates operator hand-off artifacts in Schwab's exact order-payload shape (the same JSON the
// Trader API expects at POST /trader/v1/accounts/{hash}/orders). NOTHING here sends them: there is
// no write route in this app (validate_schwab_no_writes.py guards that). The operator enters them
// in Thinkorswim, or they wait for a future fenced write path behind the canary protocol.
//
// Ladder mapping (mirrors lib/exitLadder.ts):
//   entry  → BUY LIMIT DAY
//   stop   → SELL STOP (full qty) GTC — protective; shrink/replace as tranches fill
//   T1/T2  → SELL LIMIT GTC tranches (⅓ each)
//   runner → SELL TRAILING_STOP GTC (offset = 1R) — arm after T2 fills
// Broker reality: shares back only ONE open sell order at a time. In ToS use 1st-trigger-OCO /
// blast-all with manual management; the per-ticket notes say what to adjust when.

import type { Ladder } from './exitLadder'

export type SchwabTicket = { label: string; note?: string; payload: any }

const leg = (instruction: 'BUY' | 'SELL', quantity: number, symbol: string) => ({
  instruction,
  quantity,
  instrument: { symbol, assetType: 'EQUITY' },
})

const base = (orderType: string, duration: 'DAY' | 'GOOD_TILL_CANCEL') => ({
  orderType,
  session: 'NORMAL',
  duration,
  orderStrategyType: 'SINGLE',
})

export function schwabTicketsFromLadder(o: { symbol: string; qty: number; entry: number | null; stop: number | null; ladder: Ladder | null }): SchwabTicket[] {
  const { symbol, qty, entry, stop, ladder } = o
  const t: SchwabTicket[] = []
  if (!symbol || qty <= 0) return t

  if (entry) t.push({
    label: `BUY ${qty} ${symbol} LIMIT ${entry.toFixed(2)} DAY`,
    payload: { ...base('LIMIT', 'DAY'), price: entry.toFixed(2), orderLegCollection: [leg('BUY', qty, symbol)] },
  })

  if (!stop || !ladder) return t

  t.push({
    label: `SELL ${qty} ${symbol} STOP ${stop.toFixed(2)} GTC — protective stop`,
    note: 'full-position protection; shrink qty (or cancel/replace) as T1/T2 tranches fill; after T1 move trigger to breakeven',
    payload: { ...base('STOP', 'GOOD_TILL_CANCEL'), stopPrice: stop.toFixed(2), orderLegCollection: [leg('SELL', qty, symbol)] },
  })

  // tranche split mirrors the advisory ladder: ⅓ / ⅓ / runner (remainder rides the runner)
  const q1 = Math.floor(qty / 3)
  const q2 = Math.floor(qty / 3)
  const q3 = qty - q1 - q2
  const [s1, s2] = ladder.steps

  if (q1 > 0 && s1) t.push({
    label: `SELL ${q1} ${symbol} LIMIT ${s1.px.toFixed(2)} GTC — ${s1.label}`,
    note: 'on fill: move the protective stop to breakeven',
    payload: { ...base('LIMIT', 'GOOD_TILL_CANCEL'), price: s1.px.toFixed(2), orderLegCollection: [leg('SELL', q1, symbol)] },
  })

  if (q2 > 0 && s2) t.push({
    label: `SELL ${q2} ${symbol} LIMIT ${s2.px.toFixed(2)} GTC — ${s2.label}`,
    note: 'on fill: trail the runner stop to T1; arm the trailing-stop ticket below',
    payload: { ...base('LIMIT', 'GOOD_TILL_CANCEL'), price: s2.px.toFixed(2), orderLegCollection: [leg('SELL', q2, symbol)] },
  })

  if (q3 > 0) t.push({
    label: `SELL ${q3} ${symbol} TRAILING STOP offset $${ladder.R.toFixed(2)} GTC — runner`,
    note: 'arm AFTER T2 fills (shares must be free); trails last price by 1R',
    payload: {
      ...base('TRAILING_STOP', 'GOOD_TILL_CANCEL'),
      stopPriceLinkBasis: 'LAST',
      stopPriceLinkType: 'VALUE',
      stopPriceOffset: Number(ladder.R.toFixed(2)),
      orderLegCollection: [leg('SELL', q3, symbol)],
    },
  })

  return t
}

export function ticketsText(tickets: SchwabTicket[]): string {
  return tickets.map(t => `# ${t.label}${t.note ? `\n# note: ${t.note}` : ''}\n${JSON.stringify(t.payload, null, 2)}`).join('\n\n') + '\n'
}
