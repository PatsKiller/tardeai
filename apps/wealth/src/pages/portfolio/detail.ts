// Row detail — the drawer's content for ONE row, and nothing else.
//
// The axis this file must not cross: the drawer shows the SAME row identity the table shows. Every field here is
// a served cell of that row (shares, price, value, basis, day change, weight, cap, yield, protection), carrying
// the clock the wire published for it. It does not fetch, does not join a second row, does not aggregate the book,
// and does not recompute a number: no shares × price, no P/L, no weight, no score. `belowFloor` is the one
// adapter-DERIVED flag the contract defines, and it is labelled as derived here.
//
// The fields are grouped the way v04's asset detail groups them (Position · Fundamentals · Levels · Protection), so
// the drawer can show the approved tabs (r2, verdict 2026-11-15T0342Z B3). A group with no producer on this route
// still states the gap field by field instead of disappearing; Thesis and History are not groups at all, because
// nothing on this route is a thesis or a history — `detailSections` says so in `unserved`.
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

/** Position: what the account holds, at the served marks. */
export function positionFields(row: HoldingsRow): DetailField[] {
  return [
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
}

/**
 * Fundamentals: v04's pane, field by field. This route serves the market cap and the yield; the multiples and the
 * enrichment are not on the read, and the assessment is not wired — each is stated, not omitted.
 */
export function fundamentalsFields(row: HoldingsRow): DetailField[] {
  if (row.kind === 'CASH') {
    return [{ label: 'Fundamentals', value: 'not applicable — a cash row has no issuer', source: 'cash rows carry no fundamentals' }]
  }
  return [
    { label: 'Market cap', value: marketCapText(row.marketCapB), source: 'served in millions' },
    {
      label: 'Yield',
      value: row.yieldPct === null ? unavailable('not published for this instrument') : pct(row.yieldPct),
      source: 'served yield percent',
    },
    {
      label: 'Trailing / forward P/E',
      value: unavailable('no multiple and no assessment are served on this route'),
      source: 'the wire serves no per-row multiple here, and valuation-assessment@1 is not wired',
    },
    {
      label: 'EPS · PEG · Beta',
      value: unavailable('no enrichment is served on this route'),
      source: 'the read carries no EPS, PEG or beta field for the row',
    },
    {
      label: 'Sector / industry',
      value: unavailable('no classification is served on this route'),
      source: 'the read carries no sector or industry field for the row',
    },
    {
      label: 'Valuation',
      value: unavailable('UNASSESSED: valuation-assessment@1 is not wired on this route'),
      source: 'a bare served P/E would not be an assessment, and none is served here either',
    },
  ]
}

/** Levels: v04's pane. The wire's Fibonacci block has no clock, so nothing here is dated. */
export function levelsFields(row: HoldingsRow): DetailField[] {
  if (row.kind === 'CASH') {
    return [{ label: 'Levels', value: 'not applicable — a cash row has none', source: 'cash rows carry no price levels' }]
  }
  return [
    {
      label: 'Price',
      value: row.worthless ? unavailable('no price served for a worthless identifier') : price(row.price),
      source: 'served price for this row',
    },
    {
      label: 'Support / resistance',
      value: unavailable('no levels reader serves this route'),
      source: 'the wire carries no support, resistance, pivot or timeframe field',
    },
    {
      label: 'RSI · moving averages',
      value: unavailable('no technicals are served on this route'),
      source: 'the read carries no RSI or moving-average field for the row',
    },
    {
      label: 'Next review',
      value: unavailable('no next-review field is served on this route'),
      source: 'nothing on the read states when the row is next reviewed',
    },
    {
      label: 'Fib ladder',
      value: unavailable('a ladder is served without a clock, so it is not dated here'),
      source: 'reported absent rather than labelled with the quote clock',
    },
  ]
}

/** Protection: the stops read, in its own words, with the clock it published. */
export function protectionFields(row: HoldingsRow): DetailField[] {
  const p = row.protection
  if (p === null) {
    return [{ label: 'Protection', value: 'not applicable — a cash row is not protected', source: 'cash rows carry no protection block' }]
  }
  return [
    { label: 'State', value: `${p.state} · ${p.reason}`, source: 'the protection producer’s verdict for this account' },
    {
      label: 'Resting stop',
      value: p.stop === null ? unavailable('the route publishes no per-row resting stop price') : price(p.stop),
      source: 'served stop price for this row',
    },
    { label: 'Stop basis', value: p.basis ?? unavailable('no basis served'), source: 'as recorded by the stops read' },
    {
      label: 'Read clock',
      value: p.asOf === null ? unavailable('read clock absent') : `${p.asOf}${p.stale ? ' (stale)' : ''}`,
      source: 'the clock of the broker stop read, as served',
    },
    { label: 'Next step', value: p.nextStep, source: 'the producer’s own next step, quoted' },
  ]
}

export interface DetailSection {
  title: string
  fields: DetailField[]
}

/**
 * The drawer's tabs, in v04's order. `Thesis` and `History` are returned in `unserved` rather than as empty tabs:
 * a tab that opens onto nothing is not evidence, and the drawer says which reader would fill it.
 */
export function detailSections(row: HoldingsRow): { sections: DetailSection[]; unserved: string[] } {
  return {
    sections: [
      { title: 'Position', fields: positionFields(row) },
      { title: 'Fundamentals', fields: fundamentalsFields(row) },
      { title: 'Levels', fields: levelsFields(row) },
      { title: 'Protection', fields: protectionFields(row) },
    ],
    unserved: [
      'Thesis — no thesis producer serves the holdings route; the row carries no thesis text.',
      'History — the route serves no per-row event history; the drawer does not reconstruct one.',
    ],
  }
}

/** The flat list, for callers that read the whole row at once (and for the invariants). */
export function detailFields(row: HoldingsRow): DetailField[] {
  return detailSections(row).sections.flatMap(s => s.fields)
}
