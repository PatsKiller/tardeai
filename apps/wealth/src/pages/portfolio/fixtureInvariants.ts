// Invariants the synthetic fixture must hold. This module imports no React and no DOM, so it can be
// compiled and run in node: the fixture is checked, not assumed.
//
// What is checked is only what the WIRE would guarantee: a value equals its own components, a weight is a
// percent of the cash-inclusive book, a ladder lies inside its stated window, a state is consistent with the
// fields it implies, a count has a population behind it. If one of these fails, the fixture is lying about
// the contract.
//
// The F1 pin at the bottom is deliberately not vacuous: it asserts that the last-known-good book contains a
// row whose UNASSESSED P/E carries a value, and that the cell text for it keeps the value. Reverting
// `peCellText` to the bare word "Unassessed" turns this module red.

import type { HoldingsBook, HoldingsRow } from './contract'
import { cellCarriesValue, peCellText } from './cells'
import { FIXTURE_BOOK, FIXTURE_BOOK_EMPTY, FIXTURE_BOOK_LAST_KNOWN_GOOD, FIXTURE_BOOK_LEGACY_PUBLISHED, FIXTURE_BOOK_STALE, FIXTURE_BOOK_VALUATION_CLOCK } from './fixtures'

const TOL = 0.02

function close(a: number, b: number): boolean {
  return Math.abs(a - b) <= TOL
}

function checkRow(book: HoldingsBook, r: HoldingsRow): string[] {
  const out: string[] = []
  const id = `${r.accountKey}:${r.symbol}`
  const floor = book.population.floorUsd

  if (r.price !== null && r.marketValue !== null && !close(r.marketValue, r.shares * r.price)) {
    out.push(`${id}: marketValue ${r.marketValue} != shares x price ${r.shares * r.price}`)
  }
  if (r.kind === 'SECURITY' && r.price !== null && r.avgCost !== null) {
    if (r.gainLoss !== null && !close(r.gainLoss, r.shares * (r.price - r.avgCost))) {
      out.push(`${id}: gainLoss ${r.gainLoss} != shares x (price - avgCost)`)
    }
    if (r.gainLoss !== null && r.gainLossPct !== null) {
      const pct = (r.gainLoss / (r.shares * r.avgCost)) * 100
      if (!close(r.gainLossPct, pct)) out.push(`${id}: gainLossPct ${r.gainLossPct} != ${pct.toFixed(2)}`)
    }
  }
  if (r.dayChange !== null && r.dayChangePct !== null && r.dayChangePct !== 0 && r.marketValue !== null) {
    const implied = r.marketValue - r.marketValue / (1 + r.dayChangePct / 100)
    if (!close(r.dayChange, implied)) out.push(`${id}: dayChange ${r.dayChange} != prior-value implied ${implied.toFixed(2)}`)
  }
  if (r.kind === 'CASH') {
    if (r.protection !== null) out.push(`${id}: cash row carries protection`)
    if (r.gainLoss !== null) out.push(`${id}: cash row carries a gain/loss`)
    if (r.fib !== null) out.push(`${id}: cash row carries a ladder`)
    if (r.valuation?.status !== 'N_A') out.push(`${id}: cash valuation status is ${r.valuation?.status}, expected N_A`)
  }
  if (r.kind === 'SECURITY' && r.protection === null) out.push(`${id}: security row has no protection object`)
  if (r.protection) {
    if (r.protection.state === 'GAP' && r.protection.stop !== null) out.push(`${id}: GAP row carries a stop`)
    if (r.protection.state === 'PROTECTED' && r.protection.stop === null) out.push(`${id}: PROTECTED row has no stop`)
    if (r.protection.state === 'UNKNOWN' && r.protection.asOf !== null) out.push(`${id}: UNKNOWN row carries a read clock`)
    if (r.protection.stop !== null && r.price !== null && r.protection.stop >= r.price) {
      out.push(`${id}: stop ${r.protection.stop} is not below price ${r.price}`)
    }
    if (!r.protection.nextStep.trim()) out.push(`${id}: no next step`)
    if (!r.protection.reason.trim()) out.push(`${id}: no reason`)
  }
  if (r.fib) {
    const { high, low } = r.fib.window
    if (!(low < high)) out.push(`${id}: ladder window low >= high`)
    if (r.fib.levels.length > 0) {
      if (r.fib.levels.length !== 7) out.push(`${id}: ladder has ${r.fib.levels.length} levels, expected 7`)
      for (const l of r.fib.levels) {
        const expected = high - l.ratio * (high - low)
        if (!close(l.price, expected)) out.push(`${id}: level ${l.ratio} price ${l.price} != ${expected.toFixed(2)}`)
      }
    }
    if (r.fib.nearestLevel !== null && (r.fib.nearestLevel < low || r.fib.nearestLevel > high)) {
      out.push(`${id}: nearestLevel ${r.fib.nearestLevel} outside its window`)
    }
    if (r.price !== null && r.fib.retracementFromHighPct !== null) {
      const pct = ((high - r.price) / (high - low)) * 100
      if (!close(r.fib.retracementFromHighPct, pct)) {
        out.push(`${id}: retracement ${r.fib.retracementFromHighPct} != ${pct.toFixed(2)}`)
      }
      if (r.fib.nearestLevel !== null && r.fib.levels.length > 0) {
        const nearest = r.fib.levels.reduce((a, b) => (Math.abs(b.price - r.price!) < Math.abs(a.price - r.price!) ? b : a))
        if (!close(r.fib.nearestLevel, nearest.price)) out.push(`${id}: nearestLevel ${r.fib.nearestLevel} != nearest ${nearest.price}`)
      }
    }
  }
  if (r.valuation && r.valuation.account_security_key !== id) {
    out.push(`${id}: valuation key ${r.valuation.account_security_key} != ${id}`)
  }

  // F3: an unpriced row is not a zero row. No price, no value, no derived change — and never a fake 0.
  if (r.marketValue === null) {
    if (r.kind !== 'SECURITY') out.push(`${id}: non-security row with a null market value`)
    if (r.price !== null) out.push(`${id}: unpriced row carries a price`)
    if (r.gainLoss !== null || r.dayChange !== null) out.push(`${id}: unpriced row carries a derived change`)
  }
  // A worthless zero is a fact: the producer keeps the identifier at exactly zero value.
  if (r.worthless) {
    if (r.marketValue !== 0) out.push(`${id}: worthless row market value ${r.marketValue}, expected 0`)
    if (r.kind !== 'SECURITY') out.push(`${id}: worthless row is not a security`)
  }
  // F8/C2: the floor mark is ADAPTER-DERIVED (the wire marks no row, only the two counts), so this comparison
  // IS the definition of `belowFloor`. It never fires on an unpriced row: unknown is not "below".
  if (r.kind === 'SECURITY' && floor !== null) {
    const expectedBelow = r.marketValue !== null && r.marketValue < floor
    if (r.belowFloor !== expectedBelow) {
      out.push(`${id}: belowFloor ${r.belowFloor} disagrees with market value ${r.marketValue} against floor ${floor}`)
    }
  }
  return out
}

/** F1: every UNASSESSED assessment that carries a value must keep that value in the cell, marked as last known. */
function checkValuationCell(r: HoldingsRow): string[] {
  const out: string[] = []
  const id = `${r.accountKey}:${r.symbol}`
  const v = r.valuation
  if (!v) return out
  for (const measure of ['trailing', 'forward'] as const) {
    const pe = v[measure]
    if (!pe || pe.value === null) continue
    const text = peCellText(v, measure)
    if (pe.status === 'UNASSESSED') {
      if (!cellCarriesValue(text)) out.push(`${id}: UNASSESSED ${measure} with a served value renders "${text}" without the value`)
      if (!/last known/i.test(text)) out.push(`${id}: UNASSESSED ${measure} with a served value is not marked last known: "${text}"`)
    } else if (!cellCarriesValue(text)) {
      out.push(`${id}: ${pe.status} ${measure} with a served value renders "${text}" without the value`)
    }
  }
  const fm = v.fund_metric
  if (v.status === 'FUND_METRIC' && fm?.value != null && !cellCarriesValue(peCellText(v, 'trailing'))) {
    out.push(`${id}: fund metric value ${fm.value} is not rendered in the P/E cell`)
  }
  return out
}

export function checkBook(book: HoldingsBook): string[] {
  const out: string[] = []
  if (book.contract !== 'portfolio-holdings@2') out.push(`contract ${book.contract}`)
  if (book.source !== 'FIXTURE') out.push(`source ${book.source}`)
  if (book.rows.length !== book.counts.allRows) out.push(`allRows ${book.counts.allRows} != rows ${book.rows.length}`)
  const nonCash = book.rows.filter(r => r.kind === 'SECURITY').length
  const cash = book.rows.filter(r => r.kind === 'CASH').length
  if (nonCash !== book.counts.nonCash) out.push(`nonCash ${book.counts.nonCash} != ${nonCash}`)
  if (cash !== book.counts.cash) out.push(`cash ${book.counts.cash} != ${cash}`)
  if (book.counts.nonCashOverFloor > nonCash) out.push('nonCashOverFloor exceeds nonCash')
  if (!book.counts.primaryScopeLabel.trim()) out.push('count has no scope label')
  // A fixture book always serves its age and its stale limit; either one unserved is an adapter case (R1/R1b).
  const ageSec = book.freshness.ageSeconds
  const limitSec = book.freshness.staleAfterSeconds
  if (ageSec === null) out.push('freshness.ageSeconds is not served (a fixture must serve one)')
  else if (limitSec === null) out.push('freshness.staleAfterSeconds is not served (a fixture must serve one)')
  else if (book.freshness.stale !== ageSec > limitSec) {
    out.push('stale flag disagrees with age vs stale_after')
  }
  if (book.rows.length > 0) {
    const sum = book.rows.reduce((a, r) => a + r.portfolioPct, 0)
    if (!close(sum, 100)) out.push(`weights sum to ${sum.toFixed(2)}, not 100`)
    if (book.rows.some(r => r.dayChange !== null) && book.dayPnl.status !== 'UNKNOWN') {
      out.push('day changes served without a declared clock, but dayPnl.status is not UNKNOWN')
    }
  }
  for (const r of book.rows) {
    out.push(...checkRow(book, r))
    out.push(...checkValuationCell(r))
  }

  // F2 / C2 / C3: the population is stated, and its TWO populations stay distinct — `excluded` is removals
  // (an omission the reader cannot see), `listedNotCounted` is rows in the table outside the counted scope
  // (the opposite of an omission). Merging them would print "omitted: 14" about 14 visible rows.
  const pop = book.population
  if (pop.renderedRows !== book.rows.length) out.push(`population.renderedRows ${pop.renderedRows} != rows ${book.rows.length}`)
  if (pop.readRows < pop.renderedRows) out.push('population.readRows is below renderedRows')
  const excluded = pop.excluded.reduce((a, e) => a + e.count, 0)
  if (pop.readRows - pop.renderedRows !== excluded) {
    out.push(`population gap ${pop.readRows - pop.renderedRows} != excluded ${excluded}`)
  }
  // Audit A: a cross-population measure count must never feed the omission arithmetic.
  if (pop.measurePopulation && pop.measurePopulation.differenceFromRead !== pop.measurePopulation.rowCount - pop.readRows) {
    out.push('measurePopulation.differenceFromRead is not rowCount − readRows')
  }
  if (pop.completeness !== 'BROKER_COMPLETENESS_UNVERIFIED') out.push('fixture claims broker completeness')
  for (const e of pop.excluded) {
    if (e.count <= 0) out.push(`excluded ${e.kind} has count ${e.count}`)
    if (!e.label.trim() || !e.rule.trim()) out.push(`excluded ${e.kind} does not state its label and rule`)
  }
  const listed = pop.listedNotCounted.reduce((a, l) => a + l.count, 0)
  for (const l of pop.listedNotCounted) {
    if (l.count <= 0) out.push(`listedNotCounted ${l.scope} has count ${l.count}`)
    if (!l.reason.trim() || !l.scope.trim()) out.push(`listedNotCounted ${l.scope} does not state its reason and scope`)
  }
  if (listed > pop.renderedRows) {
    out.push(`listedNotCounted ${listed} exceeds renderedRows ${pop.renderedRows} (a listed row is a rendered row)`)
  }
  if (pop.floorUsd !== null) {
    const overFloor = book.rows.filter(
      r => r.kind === 'SECURITY' && r.marketValue !== null && r.marketValue >= pop.floorUsd! && !r.belowFloor,
    ).length
    if (overFloor !== book.counts.nonCashOverFloor) {
      out.push(`nonCashOverFloor ${book.counts.nonCashOverFloor} != ${overFloor} rows over floor ${pop.floorUsd}`)
    }
    // C2: the producer publishes BOTH counts; the under-floor one must tie to the rows and to the listed block.
    const underFloor = book.rows.filter(
      r => r.kind === 'SECURITY' && r.marketValue !== null && r.marketValue < pop.floorUsd!,
    ).length
    if (underFloor !== book.counts.heldUnderFloor) {
      out.push(`heldUnderFloor ${book.counts.heldUnderFloor} != ${underFloor} rows priced under floor ${pop.floorUsd}`)
    }
    for (const l of pop.listedNotCounted.filter(l => l.scope === 'holdings.held_under_100')) {
      if (l.count !== underFloor) {
        out.push(`listedNotCounted ${l.scope} says ${l.count}, the book has ${underFloor} rows under floor ${pop.floorUsd}`)
      }
    }
  }

  // F4: the as-of clock is a declared clock, and the build clock is present, identified and distinct.
  const asOfClock = book.clocks.find(c => c.role === book.asOfClock)
  if (!asOfClock) out.push(`asOfClock ${book.asOfClock} is not among the declared clocks`)
  else if (asOfClock.at !== book.asOf) out.push(`asOf ${book.asOf} != the ${book.asOfClock} clock ${asOfClock.at}`)
  const buildClocks = book.clocks.filter(c => c.isBuildClock)
  if (book.rows.length > 0) {
    if (buildClocks.length !== 1) out.push(`${buildClocks.length} build clocks declared, expected 1`)
    else if (buildClocks[0].role !== 'BUILD') out.push(`build clock role is ${buildClocks[0].role}`)
    else if (buildClocks[0].at !== null && buildClocks[0].at >= book.asOf) {
      out.push('build clock is not older than the as-of clock (the fixture would hide the trap)')
    }
  }
  for (const c of book.clocks) {
    if (!c.source.trim()) out.push(`clock ${c.role} has no source`)
  }

  // F5: per-account totals are the producer's, and they tie to the served rows (fixture coherence, not a wire
  // rule: the wire's accounts block may include value the row list omits, which the adapter must then carry).
  if (book.accounts !== null) {
    const keys = new Set(book.rows.map(r => r.accountKey))
    for (const a of book.accounts) {
      if (!keys.has(a.accountKey)) out.push(`account ${a.accountKey} has no row`)
      const rows = book.rows.filter(r => r.accountKey === a.accountKey)
      const derived = rows.reduce((s, r) => s + (r.marketValue ?? 0), 0)
      if (a.totalUsd !== null && !close(a.totalUsd, derived)) {
        out.push(`account ${a.accountKey} total ${a.totalUsd} != served rows ${derived.toFixed(2)}`)
      }
      const cashDerived = rows.filter(r => r.kind === 'CASH').reduce((s, r) => s + (r.marketValue ?? 0), 0)
      if (a.cashUsd !== null && !close(a.cashUsd, cashDerived)) {
        out.push(`account ${a.accountKey} cash ${a.cashUsd} != cash rows ${cashDerived.toFixed(2)}`)
      }
      if (!a.source.trim()) out.push(`account ${a.accountKey} has no source`)
    }
    const total = book.accounts.reduce((s, a) => s + (a.totalUsd ?? 0), 0)
    const allRows = book.rows.reduce((s, r) => s + (r.marketValue ?? 0), 0)
    if (!close(total, allRows)) out.push(`accounts total ${total} != served rows ${allRows.toFixed(2)}`)
    const value = book.measures.find(m => m.id === 'account_value')
    if (value && value.valueUsd !== null && !close(value.valueUsd, total)) {
      out.push(`account_value ${value.valueUsd} != accounts total ${total.toFixed(2)}`)
    }
  }

  // F6 / C1.1: the rule the ledger actually holds is MEASURED ⇒ value + clock; VERIFIED ⇒ receipt. "Measured"
  // is not "verified": a MEASURED measure with `verified: false` is the normal case on this read, and today all
  // four are `verified: false, receipt: null`. A receipt is required only where the ledger says verified, and
  // the fixture may never invent one (an invented `fixture:rcpt-*` string hid exactly this defect in r2).
  if (book.measures.length === 0) out.push('no book measures carried')
  for (const m of book.measures) {
    if (!m.label.trim() || !m.definition.trim() || !m.reason.trim()) out.push(`measure ${m.id} is not stated`)
    if (m.status === 'MEASURED') {
      if (m.valueUsd === null) out.push(`measure ${m.id} is MEASURED without a value`)
      if (m.asOf === null) out.push(`measure ${m.id} is MEASURED without a clock`)
    } else if (m.valueUsd !== null) {
      out.push(`measure ${m.id} is UNKNOWN but carries value ${m.valueUsd}`)
    }
    if (m.verified && m.receiptId === null) out.push(`measure ${m.id} is VERIFIED without a receipt`)
    if (!m.verified && m.receiptId !== null) out.push(`measure ${m.id} carries receipt ${m.receiptId} but is not verified`)
    if (m.receiptId !== null && m.receiptId.trim().length === 0) out.push(`measure ${m.id} has an empty receipt id`)
    if (m.receiptId !== null && /^fixture:/.test(m.receiptId)) {
      out.push(`measure ${m.id} carries an invented receipt ${m.receiptId}; the ledger publishes none today`)
    }
  }
  const verified = book.measures.find(m => m.id === 'verified_daily_pnl')
  if (!verified) out.push('verified_daily_pnl is not carried')
  else if (verified.status !== 'UNKNOWN') out.push(`verified_daily_pnl is ${verified.status}; it must stay UNKNOWN`)

  // The session label names its source when it claims to be known (the rows carry none).
  if (book.session.status === 'KNOWN' && !book.session.source) out.push('known session has no source')
  if (book.session.status !== 'KNOWN' && !book.session.reason.trim()) out.push('unknown session has no reason')

  return out
}

export function checkAllFixtures(): string[] {
  const out = [...checkBook(FIXTURE_BOOK)]
  for (const bad of checkBook(FIXTURE_BOOK_EMPTY)) out.push(`empty: ${bad}`)
  for (const bad of checkBook(FIXTURE_BOOK_STALE)) out.push(`stale: ${bad}`)
  for (const bad of checkBook(FIXTURE_BOOK_LAST_KNOWN_GOOD)) out.push(`last-known-good: ${bad}`)
  // R1 / R3(b) fixtures (review 2026-11-15T1704Z): both are the same book with one served fact changed, so the
  // same invariants must hold — and each must actually carry the fact its test name claims, or the test is vacuous.
  for (const bad of checkBook(FIXTURE_BOOK_VALUATION_CLOCK)) out.push(`valuation-clock: ${bad}`)
  for (const bad of checkBook(FIXTURE_BOOK_LEGACY_PUBLISHED)) out.push(`legacy-published: ${bad}`)
  if (!FIXTURE_BOOK_VALUATION_CLOCK.clocks.some(c => c.role === 'VALUATION'))
    out.push('the R1 fixture serves no VALUATION clock — the basis-UNKNOWN test would be vacuous')
  if (!FIXTURE_BOOK_LEGACY_PUBLISHED.rows.some(r => r.marketValue === 0 && r.gainLoss !== null))
    out.push('the R3(b) fixture carries no zero-value row with a published gain/loss — the legacy test would be vacuous')
  if (FIXTURE_BOOK_EMPTY.rows.length !== 0) out.push('empty fixture has rows')
  if (!FIXTURE_BOOK_STALE.freshness.stale) out.push('stale fixture is not stale')

  // The F1 pin must be exercised, not vacuous: the book exists for one reason, a served value behind an
  // UNASSESSED status, and the text for it must carry both the value and the "last known" marker.
  const pin = FIXTURE_BOOK_LAST_KNOWN_GOOD.rows.filter(
    r => r.valuation?.trailing?.status === 'UNASSESSED' && r.valuation?.trailing?.value !== null,
  )
  if (pin.length === 0) out.push('last-known-good fixture carries no UNASSESSED-with-value row')
  for (const r of pin) {
    const text = peCellText(r.valuation, 'trailing')
    if (!cellCarriesValue(text) || !/last known/i.test(text)) {
      out.push(`F1 pin: ${r.accountKey}:${r.symbol} renders "${text}", expected the served value marked last known`)
    }
  }

  // And the unpriced / worthless pair must both be represented, or the two renderings are untested.
  const rows = FIXTURE_BOOK.rows
  if (!rows.some(r => r.marketValue === null)) out.push('fixture has no unpriced row')
  if (!rows.some(r => r.worthless)) out.push('fixture has no worthless row')
  if (!rows.some(r => r.belowFloor)) out.push('fixture has no below-floor row')
  return out
}
