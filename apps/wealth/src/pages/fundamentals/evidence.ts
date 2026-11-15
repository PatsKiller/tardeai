// Presentation rules for the Fundamentals nav page — pure text, no React, no fetch, no formula.
//
// This page is a REUSE of the reviewed Holdings `fundamentals` preset (portfolio/presets.ts, commit ca4e75d07):
// the same eight columns, the same adapter output (`HoldingsBook.rows`), the same format helpers. It owns no
// reader, computes no value and applies no threshold. Everything below decides only what a cell SAYS.
//
// The two cells the route fixes (LEAD-ROUTE-FUNDAMENTALS-NAV-WIRING-20261115T1613Z):
//   * Peer TTM median — no reader serves one on any route; the cell prints the route's literal.
//   * Evidence (the valuation assessment) — valuation-assessment@1 is not wired on this read; the cell prints
//     the same literal and derives NO status. `assessmentText` takes no row on purpose: a served assessment
//     (a synthetic fixture one, today) cannot leak a status word into the page through this function.
//
// Market cap is the served field (`marketCapB`, MILLIONS — format.marketCapText divides once). The row carries no
// market-cap-specific clock; the only provenance it carries is the profile record's `profileSource` /
// `profileUpdatedAt`, so the cell names that record and calls its instant a record clock, never a price clock.

import { peCellText } from '../portfolio/cells'
import type { HoldingsRow } from '../portfolio/contract'
import { marketCapText as servedMarketCapText, multiple, pct, price, unavailable } from '../portfolio/format'

/** The route's literal, character for character. Two cells print it; tests pin it. */
export const NOT_WIRED = 'not wired — valuation-assessment@1'

/** The Holdings preset's own cash rule: these columns do not apply to a cash row (HoldingsTable.cell). */
export const CASH_COLUMN = 'this column does not apply to a cash row'

/** Under the table: what the market-cap provenance line is, and what it is not. */
export const MARKET_CAP_PROVENANCE_NOTE =
  'Market cap is the served field (the wire is in millions and is divided by 1,000 once for display). Its ' +
  'provenance line is the row’s profile record — source and clock — because this read serves no ' +
  'market-cap-specific clock; the record clock is not a price clock.'

export function peerMedianText(): string {
  return NOT_WIRED
}

export function peerMedianNote(): string {
  return 'no reader serves a peer median on any served route; valuation-assessment@1, which owns the benchmark, is not wired here'
}

export function assessmentText(): string {
  return NOT_WIRED
}

export function assessmentNote(): string {
  return 'valuation-assessment@1 is not wired on this route; this page prints no assessment status and derives none'
}

/** The served price, unchanged; a worthless identifier has no price by definition (the preset's own rule). */
export function priceText(row: HoldingsRow): string {
  return row.worthless ? unavailable('no price served for a worthless identifier') : price(row.price)
}

function wireName(which: 'peTrailing' | 'peForward'): string {
  return which === 'peTrailing' ? 'pe' : 'forward_pe'
}

/**
 * One P/E cell. A served provider multiple prints as served; with none served, the valuation-assessment@1
 * status word is the fallback — the same two-step HoldingsTable.peServed applies, so the two routes cannot
 * disagree about a P/E cell.
 */
export function peText(row: HoldingsRow, which: 'peTrailing' | 'peForward'): string {
  const served = row.fundamentals?.[which] ?? null
  if (served !== null) return multiple(served)
  if (row.valuation === null) return unavailable(`no served ${wireName(which)} multiple and no assessment for this row`)
  return peCellText(row.valuation, which === 'peTrailing' ? 'trailing' : 'forward')
}

/** What the P/E cell's hover names: a served multiple and an assessment are different instruments of evidence. */
export function peNote(row: HoldingsRow, which: 'peTrailing' | 'peForward'): string {
  const served = row.fundamentals?.[which] ?? null
  if (served !== null) return `served provider multiple · wire ${wireName(which)} · not a valuation-assessment@1 assessment`
  if (row.valuation === null) return `no served ${wireName(which)} multiple and no assessment for this row`
  return 'valuation-assessment@1 status word, not a provider multiple'
}

/** "N/A — <reason>" or the served cap in its own unit. Never a zero for an absent cap. */
export function marketCapText(row: HoldingsRow): string {
  if (row.marketCapB === null) {
    return unavailable(row.kind === 'CASH' ? 'cash has no market cap' : 'not published for this instrument')
  }
  return servedMarketCapText(row.marketCapB)
}

export function marketCapSource(row: HoldingsRow): string {
  return row.profileSource ?? 'not served'
}

export function marketCapClock(row: HoldingsRow): string {
  return row.profileUpdatedAt ?? 'clock not served'
}

/** The visible second line of a served cap: the profile record's source AND clock together. */
export function marketCapProvenance(row: HoldingsRow): string {
  return `source ${marketCapSource(row)} · record ${marketCapClock(row)}`
}

/** A percent as served (the preset's `pct` default: two decimals); an absent yield is a reason, not 0. */
export function yieldText(row: HoldingsRow): string {
  return row.yieldPct === null ? unavailable('not published for this instrument') : pct(row.yieldPct)
}
