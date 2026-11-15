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
import { sectorDisplayLabel, sectorSource } from './analyticsAdapter'
import { displayOf, identitySecondLine } from './displayIdentity'
import { decimal, marketCapText, money, multiple, pct, price, shares, signedMoney, signedPct, unavailable } from './format'

export interface DetailField {
  label: string
  value: string
  /** Where the value came from, in words the reader can check: a served field, a clock, or a named rule. */
  source: string
}

export function detailHeading(row: HoldingsRow): { title: string; eyebrow: string } {
  // The eyebrow is the table cell's own second line plus the account key (spec T6 parity): the resolved identity,
  // never the per-row `name`, so the drawer cannot name an instrument differently from the row that opened it.
  const identity = displayOf(row)
  return {
    title: row.symbol,
    eyebrow: `${identitySecondLine(identity, row.symbol, row.accountLabel)} · ${row.accountKey}`,
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

// ---- Fundamentals: every field the wire serves on the row, as served ------------------------------------------
//
// The drawer is where the complete set lives (the approved preset carries eight columns; these are the rest of
// what the read actually serves). Nothing is derived: no EPS from price/PE, no growth from two EPS values, no
// score from PEG or beta. `peTrailing` / `peForward` are named as provider multiples because they are not
// valuation-assessment@1 assessments, and the Assessment entry says so in the contract's own words.
const missing = (what: string) => unavailable(`no ${what} served for this instrument`)

/** Fundamentals: every field the wire serves on the row, as served. */
export function fundamentalsFields(row: HoldingsRow): DetailField[] {
  if (row.kind === 'CASH') {
    return [{ label: 'Fundamentals', value: 'not applicable — a cash row has none', source: 'cash rows carry no enrichment block' }]
  }
  const f = row.fundamentals
  if (f === null) {
    return [
      {
        label: 'Fundamentals',
        value: unavailable('the enrichment never reached this row'),
        source: 'every wire fundamental field is null or absent; they are reported absent, never as zero',
      },
    ]
  }
  return [
    { label: 'Trailing P/E', value: f.peTrailing === null ? missing('trailing P/E') : multiple(f.peTrailing), source: 'wire pe · served provider multiple, not a valuation assessment' },
    { label: 'Forward P/E', value: f.peForward === null ? missing('forward P/E') : multiple(f.peForward), source: 'wire forward_pe · served provider multiple, not a valuation assessment' },
    { label: 'EPS (TTM)', value: f.epsTtm === null ? missing('TTM EPS') : money(f.epsTtm), source: 'wire eps_ttm · dollars per share as published' },
    { label: 'EPS, next year (estimate)', value: f.epsNextY === null ? missing('next-year EPS') : money(f.epsNextY), source: 'wire eps_next_y · the provider’s estimate, not a measurement' },
    { label: 'PEG', value: f.peg === null ? missing('PEG') : decimal(f.peg), source: 'wire peg · served ratio, no threshold applied' },
    { label: 'Beta', value: f.beta === null ? missing('beta') : decimal(f.beta), source: 'wire beta · served ratio, no interpretation added' },
    { label: 'Sector', value: sectorDisplayLabel(row), source: sectorSource(row) },
    { label: 'Industry', value: f.industry ?? missing('industry'), source: 'wire industry' },
    { label: 'Performance, year to date', value: f.perfYtdPct === null ? missing('YTD performance') : pct(f.perfYtdPct), source: 'wire perf_ytd_pct · percent as published' },
    { label: 'Short interest (float)', value: f.shortFloatPct === null ? missing('short float') : pct(f.shortFloatPct), source: 'wire short_float_pct · percent of float as published' },
    { label: 'Insider ownership', value: f.insiderOwnPct === null ? missing('insider ownership') : pct(f.insiderOwnPct), source: 'wire insider_own_pct · percent as published' },
    { label: 'Institutional ownership', value: f.instOwnPct === null ? missing('institutional ownership') : pct(f.instOwnPct), source: 'wire inst_own_pct · percent as published' },
    { label: 'Analyst rating', value: f.analystRating ?? missing('analyst rating'), source: 'wire analyst_rating · the provider’s own label, shown as text with no colour verdict' },
    {
      label: 'Assessment',
      value: row.valuation === null ? unavailable('UNASSESSED: valuation-assessment@1 is not wired on this route') : `${row.valuation.status} · ${row.valuation.reason}`,
      source: 'a bare served P/E is not a valuation-assessment@1 assessment; the two are shown apart',
    },
    {
      label: 'Industry / own-history TTM median',
      value: unavailable('no reader serves a peer or history median'),
      source: 'the approved drawer shows both; neither is on any served route, so neither is guessed',
    },
  ]
}

// ---- Levels: the served technicals plus the stored fib ladder ------------------------------------------------
export function levelsFields(row: HoldingsRow): DetailField[] {
  if (row.kind === 'CASH') {
    return [{ label: 'Levels', value: 'not applicable — a cash row has none', source: 'cash rows carry no price levels' }]
  }
  const f = row.fundamentals
  const out: DetailField[] = [
    { label: 'RSI (14)', value: f?.rsi == null ? missing('RSI') : f.rsi.toFixed(1), source: 'wire rsi · served value, no overbought/oversold threshold applied' },
    { label: 'SMA20', value: f?.sma20Pct == null ? missing('SMA20') : `${pct(f.sma20Pct)} vs SMA20`, source: 'wire sma20_pct · percent distance from the 20-day average, as served' },
    { label: 'SMA50', value: f?.sma50Pct == null ? missing('SMA50') : `${pct(f.sma50Pct)} vs SMA50`, source: 'wire sma50_pct · percent distance from the 50-day average, as served' },
    { label: 'SMA200', value: f?.sma200Pct == null ? missing('SMA200') : `${pct(f.sma200Pct)} vs SMA200`, source: 'wire sma200_pct · percent distance from the 200-day average, as served' },
    { label: 'From the 52-week high', value: f?.week52HighPct == null ? missing('52-week high distance') : pct(f.week52HighPct), source: 'wire week52_high_pct · percent below the provider’s 52-week high, as served' },
  ]
  const fib = row.fib
  out.push({
    label: 'Fib ladder',
    value: fib === null ? unavailable('a ladder is served without a clock, so it is not dated here') : fib.levels.map(l => `${Math.round(l.ratio * 1000) / 10}% ${price(l.price)}`).join(' · '),
    source: fib === null ? 'the wire serves a fib block but no clock for it; the row reports it absent rather than date it with the quote clock' : `retracement of the stored 52-week range, ${price(fib.window.low)} – ${price(fib.window.high)}, as of ${fib.window.asOf}`,
  })
  out.push(
    {
      label: 'Support / resistance',
      value: unavailable('no levels reader serves this route'),
      source: 'the wire carries no support, resistance, pivot or timeframe field',
    },
    {
      label: 'Next review',
      value: unavailable('no next-review field is served on this route'),
      source: 'nothing on the read states when the row is next reviewed',
    },
  )
  return out
}

/** Protection: the stops read, in its own words, with the clock it published. */
export function protectionFields(row: HoldingsRow): DetailField[] {
  const p = row.protection
  if (p === null) {
    return row.kind === 'CASH'
      ? [{ label: 'Protection', value: 'not applicable — a cash row is not protected', source: 'cash rows carry no protection block' }]
      : [{ label: 'Protection', value: 'UNKNOWN — no protection record served', source: 'this security has no protection block; absence is not an active stop or a reported gap' }]
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
      value: p.asOf === null ? unavailable('read clock absent') : `${p.asOf}${p.stale === true ? ' (stale)' : ''}`,
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
