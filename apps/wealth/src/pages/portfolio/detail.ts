// Row detail — the drawer's content for ONE row, and nothing else.
//
// The axis this file must not cross: the drawer shows the SAME row identity the table shows. Every field here is
// a served cell of that row (shares, price, value, basis, day change, weight, cap, yield, protection), carrying
// the clock the wire published for it. It does not fetch, does not join a second row, does not aggregate the book,
// and does not recompute a number: no shares × price, no P/L, no weight, no score. `belowFloor` is the one
// adapter-DERIVED flag the contract defines, and it is labelled as derived here.
//
// Pure: no React, no DOM — the invariants can pin it.

import type { HoldingsRow } from './contract'
import { marketCapText, money, pct, price, shares, signedMoney, signedPct, unavailable } from './format'

export interface DetailField {
  label: string
  value: string
  /** Where the value came from, in words the reader can check: a served field, a clock, or a named rule. */
  source: string
}

export function detailHeading(row: HoldingsRow): { title: string; eyebrow: string } {
  return {
    title: row.symbol,
    eyebrow: `${row.name} · ${row.accountLabel} · ${row.accountKey}`,
  }
}

export function detailFields(row: HoldingsRow): DetailField[] {
  const f: DetailField[] = [
    { label: 'Account', value: row.accountLabel, source: `account key ${row.accountKey}` },
    { label: 'Kind', value: row.kind === 'CASH' ? 'Cash' : 'Security', source: 'served asset type' },
    { label: 'Shares', value: shares(row.shares), source: 'served shares' },
    {
      label: 'Price',
      value: row.worthless ? unavailable('no price served for a worthless identifier') : price(row.price),
      source: row.priceAsOf === null ? 'served price; no quoted clock on this row' : `served price, quoted ${row.priceAsOf}`,
    },
    {
      label: 'Average cost',
      value: row.avgCost === null ? unavailable('no basis served') : money(row.avgCost),
      source: 'remaining basis ÷ remaining shares, as served (never recomputed here)',
    },
    {
      label: 'Market value',
      value: row.marketValue === null ? unavailable('unpriced — no price served') : money(row.marketValue),
      source: 'served market value',
    },
    {
      label: 'Day change',
      value: row.dayChange === null ? unavailable('no day change served') : `${signedMoney(row.dayChange)} · ${signedPct(row.dayChangePct)}`,
      source: 'served; the wire declares no day-change clock (day_pnl UNKNOWN), so this is not a current-day figure',
    },
    { label: 'Weight of book', value: pct(row.portfolioPct), source: 'served percent of the cash-inclusive book' },
    {
      label: 'Gain / loss',
      value:
        row.gainLoss === null
          ? unavailable('not served for this row')
          : `${signedMoney(row.gainLoss)} · ${signedPct(row.gainLossPct)}`,
      source: 'served gain/loss fields (not recomputed)',
    },
    { label: 'Market cap', value: marketCapText(row.marketCapB), source: 'served in millions' },
    {
      label: 'Yield',
      value: row.yieldPct === null ? unavailable('not published for this instrument') : pct(row.yieldPct),
      source: 'served yield percent',
    },
    {
      label: 'Below the notional floor',
      value:
        row.marketValue === null
          ? unavailable('unpriced — unknown is not below the floor')
          : row.belowFloor
            ? 'yes — listed and outside the counted scope'
            : 'no',
      source: 'ADAPTER-DERIVED (C2): the served market value compared once with the served floor; the wire marks no row',
    },
  ]

  const p = row.protection
  f.push({
    label: 'Protection',
    value: p === null ? 'not applicable — a cash row is not protected' : `${p.state} · ${p.reason}`,
    source:
      p === null
        ? 'cash rows carry no protection block'
        : `${p.basis === null ? 'no basis served' : `basis ${p.basis}`}; ${
            p.asOf === null ? 'read clock absent' : `read ${p.asOf}${p.stale ? ' (stale)' : ''}`
          }; ${p.stop === null ? 'the route publishes no per-row resting stop price' : `stop ${price(p.stop)}`}`,
  })
  f.push({
    label: 'Fib ladder',
    value: unavailable('not shown: the route serves a ladder with no clock for it'),
    source: 'reported absent rather than labelled with the quote clock',
  })
  f.push({
    label: 'Valuation',
    value: unavailable('UNASSESSED: valuation-assessment@1 is not wired on this route'),
    source: 'a bare served P/E is not an assessment',
  })
  return f
}
