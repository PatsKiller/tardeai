// Presentation rules for the Fundamentals nav page — pure text, no React, no fetch, no formula.
//
// This page is a REUSE of the reviewed Holdings `fundamentals` preset (portfolio/presets.ts, commit ca4e75d07):
// the same eight columns, the same adapter output (`HoldingsBook.rows`), the same format helpers. It owns no
// reader, computes no value and applies no threshold. Everything below decides only what a cell SAYS.
//
// The two cells the route fixes (LEAD-ROUTE-FUNDAMENTALS-NAV-WIRING-20261115T1613Z), retyped for G2:
//   * Peer TTM median — no reader serves one on any route; the cell prints `Not available`.
//   * Evidence (the valuation assessment) — valuation-assessment@1 is not wired on this read; the cell prints
//     `Not available` and derives NO status. `assessmentText` takes no row on purpose: a served assessment
//     (a synthetic fixture one, today) cannot leak a status word into the page through this function.
// The contract id (NOT_WIRED) is the disclosure's text and each cell's title — reachable, not repeated per row.
//
// Market cap is the served field (`marketCapB`, MILLIONS — format.marketCapText divides once). The row carries no
// market-cap-specific clock; the only provenance it carries is the profile record's `profileSource` /
// `profileUpdatedAt`, so the cell names that record and calls its instant a record clock, never a price clock.

import { peCellText } from '../portfolio/cells'
import type { AnalyticsSnapshot } from '../portfolio/analytics/portfolio-analytics.mjs'
import type { HoldingsRow } from '../portfolio/contract'
import { marketCapText as servedMarketCapText, multiple, pct, price, unavailable } from '../portfolio/format'

/**
 * The contract id and the reason, character for character. It is the page DISCLOSURE's text and the cells'
 * title/accessible name (G2) — no longer printed in the cells themselves, where it cost two technical lines on
 * every row. Tests pin it here and pin that the cells do NOT carry it.
 */
export const NOT_WIRED = 'not wired — valuation-assessment@1'

/**
 * What a route-fixed cell prints instead (G2): short and truthful. The contract that would serve the value is
 * named in the disclosure and on the cell's title, so the reader can still reach it in one place.
 */
export const NOT_AVAILABLE = 'Not available'

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
  return 'valuation-assessment@1 is not wired on this route; this cell prints no assessment status and derives none'
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

// ---- One compact evidence line and the disclosure behind it (G2) ---------------------------------------
//
// The page prints ONE short warning above the table; the producer's whole notice, the reason and the session/read
// clock go behind the disclosure. This mirrors the Allocation page's `readStatus` contract (same rules, same
// fallback) but lives here because this branch builds on 399aa8298, where that function does not exist yet; it
// takes the adapter's sentence (`freshnessCopy(snapshot).line`) as its single source rather than deriving one.

export interface EvidenceCopy {
  /** The one warning line, or null when the read is current and nothing is being withheld. */
  line: string | null
  /** The full producer notice, the reason and the clock, for the disclosure. Null when there is nothing to add. */
  detail: string | null
}

/** The notice's lead clause — the part before its first parenthetical or first sentence — and the remainder. */
function leadClause(text: string): { lead: string; rest: string | null } {
  const paren = text.indexOf(' (')
  if (paren > 0) return { lead: text.slice(0, paren).trim(), rest: text.slice(paren).trim() }
  const sentence = text.indexOf('. ')
  if (sentence > 0) return { lead: text.slice(0, sentence + 1).trim(), rest: text.slice(sentence + 1).trim() }
  return { lead: text.trim(), rest: null }
}

const trimOrNull = (v: string | null | undefined): string | null =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : null

/**
 * `line` is the adapter's ONE freshness sentence: when it is non-empty it IS the top line, verbatim. It is
 * empty on a read the producer's verdict calls current — but `holdingsProps` still sets `notice` then when the
 * payload carries no health flag and no producer clock (`healthUnproven`), so the notice's own lead clause is
 * the fallback line: a calm strip over an unmeasured read is the one thing this page must not print.
 */
export function evidenceCopy(
  notice: string | null | undefined,
  snapshot: Pick<AnalyticsSnapshot, 'reason' | 'session' | 'observedAt'>,
  line: string | null | undefined,
): EvidenceCopy {
  const lineText = trimOrNull(line)
  const noticeText = trimOrNull(notice)
  const reason = trimOrNull(snapshot.reason)
  const rawSession = trimOrNull(snapshot.session) ?? 'Session unknown'
  const sessionText = /^Session\b/.test(rawSession) ? rawSession : `Session ${rawSession}`
  const clock = `${sessionText} · read ${snapshot.observedAt ?? 'time unknown'}.`

  const noticeClause = noticeText === null ? null : leadClause(noticeText)
  const warning = lineText ?? noticeClause?.lead ?? null

  const detailParts: string[] = []
  // The whole notice goes behind the disclosure only when the top line truncated it.
  if (noticeClause !== null && noticeClause.rest !== null) detailParts.push(`Full notice: ${noticeText}`)
  if (reason !== null && !(noticeText ?? '').includes(reason) && !(lineText ?? '').includes(reason)) {
    detailParts.push(reason)
  }
  if (warning !== null || detailParts.length > 0) detailParts.push(clock)
  return { line: warning, detail: detailParts.length > 0 ? detailParts.join(' ') : null }
}
