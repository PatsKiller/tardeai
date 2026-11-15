// Allocation — the two-denominator pin (RELEASE-ACCEPTANCE-LEDGER row D).
//
// Runs the REAL approved selector (portfolio-analytics.mjs, the reviewed v0.5 port) over synthetic rows and
// asserts what the page prints: book weight and selected-view weight are different numbers over different
// denominators, each named at its column; a sleeve with rows and no published value is Unknown, never $0.00
// or 0%; a sleeve absent from a non-empty selection is a measured absence; an empty selection has no
// denominator at all; and a book the selector refuses is a refusal, not a page of zeros.
//
// Synthetic identities only (public repo). No fixture, no network, no clock.

import test from 'node:test'
import assert from 'node:assert/strict'
import { buildAllocationModel } from './allocationView.ts'

const SNAP = {
  id: 'snap-synthetic-20261115',
  currency: 'USD',
  session: 'REGULAR',
  observedAt: '2026-11-15T14:30:00Z',
  status: 'fresh',
}

let seq = 0
function row(o = {}) {
  seq += 1
  const accountId = o.accountId ?? 'ira'
  const symbol = o.symbol ?? `SYN${seq}`
  return {
    rowId: `${accountId}:${symbol}:${seq}`,
    accountId,
    accountName: accountId === 'ira' ? 'Retirement IRA' : 'Taxable',
    securityId: symbol,
    symbol,
    name: symbol,
    snapshotId: SNAP.id,
    currency: 'USD',
    isCash: o.isCash ?? false,
    sector: o.sector === undefined ? 'Technology' : o.sector,
    marketValue: o.marketValue === undefined ? 100 : o.marketValue,
    unrealizedPnl: o.unrealizedPnl === undefined ? 5 : o.unrealizedPnl,
  }
}

/** book: 5 valued rows over 2 accounts = 5700; 7 rows total. One Energy row and one Real Estate row are
 *  present but unpublish a value. Cash is one row, classified by the selector as 'Cash & sweep'. */
function book() {
  return [
    row({ symbol: 'AAA', accountId: 'ira', sector: 'Technology', marketValue: 1000, unrealizedPnl: 120 }),
    row({ symbol: 'BBB', accountId: 'ira', sector: 'Energy', marketValue: 500, unrealizedPnl: -30 }),
    row({ symbol: 'CSH', accountId: 'ira', sector: null, isCash: true, marketValue: 200, unrealizedPnl: null }),
    row({ symbol: 'CCC', accountId: 'tax', sector: 'Technology', marketValue: 3000, unrealizedPnl: 400 }),
    row({ symbol: 'DDD', accountId: 'tax', sector: 'Healthcare', marketValue: 1000, unrealizedPnl: 40 }),
    row({ symbol: 'EEE', accountId: 'tax', sector: 'Energy', marketValue: null, unrealizedPnl: null }),
    row({ symbol: 'FFF', accountId: 'tax', sector: 'Real Estate', marketValue: null, unrealizedPnl: null }),
  ]
}

const near = (a, b) => Math.abs(a - b) < 1e-9
const sleeve = (m, key) => m.sleeves.find(s => s.key === key)

test('T1 the two weights are different numbers over different, stated denominators', () => {
  const m = buildAllocationModel(book(), SNAP, { scope: 'ira', sector: '', query: '' })
  assert.equal(m.bookView.total, 5700)
  assert.equal(m.view.total, 1700)
  assert.equal(m.bookView.coverage.valued, 5)
  assert.equal(m.bookView.coverage.total, 7)
  assert.equal(m.view.coverage.valued, 3)

  const tech = sleeve(m, 'Technology')
  assert.equal(tech.book.amount, 4000)
  assert.equal(tech.selected.amount, 1000)
  assert.ok(near(tech.book.weight, 4000 / 5700), `book weight ${tech.book.weight}`)
  assert.ok(near(tech.selected.weight, 1000 / 1700), `selected weight ${tech.selected.weight}`)
  assert.ok(Math.abs(tech.book.weight - tech.selected.weight) > 0.1, 'the two denominators must not coincide')

  // Each column sums to its own 100%: the selector's weights, not a sum this page computed.
  const bookSum = m.sleeves.filter(s => s.inBook).reduce((n, s) => n + (s.book.weight ?? 0), 0)
  const selSum = m.sleeves.filter(s => s.inSelection).reduce((n, s) => n + (s.selected.weight ?? 0), 0)
  assert.ok(near(bookSum, 1), `book weights sum ${bookSum}`)
  assert.ok(near(selSum, 1), `selected weights sum ${selSum}`)
})

test('T2 a sleeve in the book but not in the selection is a measured absence, not an unknown', () => {
  const m = buildAllocationModel(book(), SNAP, { scope: 'ira', sector: '', query: '' })
  const health = sleeve(m, 'Healthcare')
  assert.equal(health.inBook, true)
  assert.equal(health.inSelection, false)
  assert.equal(health.book.amount, 1000)
  assert.ok(near(health.book.weight, 1000 / 5700))
  assert.equal(health.selected.amount, 0)
  assert.equal(health.selected.weight, 0)
  assert.equal(health.selected.count, 0)
})

test('T3 rows present, no value published: Unknown amount and no weight — never $0.00 or 0.0%', () => {
  const m = buildAllocationModel(book(), SNAP, { scope: 'ALL', sector: '', query: '' })
  const re = sleeve(m, 'Real Estate')
  assert.equal(re.inBook, true)
  assert.equal(re.book.count, 1)
  assert.equal(re.book.valued, 0)
  assert.equal(re.book.amount, null, 'an unpriced sleeve must not print an amount')
  assert.equal(re.book.weight, null, 'the selector\'s 0 value must not become a 0% weight')

  // Partial coverage keeps the published amount and its weight, with the count available to the cell title.
  const energy = sleeve(m, 'Energy')
  assert.equal(energy.book.count, 2)
  assert.equal(energy.book.valued, 1)
  assert.equal(energy.book.amount, 500)
  assert.ok(energy.book.weight !== null)
})

test('T4 an empty selection has no denominator: every selected side is withheld', () => {
  const m = buildAllocationModel(book(), SNAP, { scope: 'ALL', sector: '', query: 'no-such-holding' })
  assert.equal(m.view.rows.length, 0)
  assert.ok(m.sleeves.length > 0)
  for (const s of m.sleeves) {
    assert.equal(s.selected.amount, null, `${s.key} amount`)
    assert.equal(s.selected.weight, null, `${s.key} weight`)
  }
  // The book side is untouched by a filter it does not share.
  assert.equal(m.bookView.total, 5700)
  assert.ok(near(sleeve(m, 'Technology').book.weight, 4000 / 5700))
})

test('T5 a sleeve filter rebases the selected view and leaves the book basis alone', () => {
  const m = buildAllocationModel(book(), SNAP, { scope: 'ALL', sector: 'Technology', query: '' })
  assert.equal(m.view.total, 4000)
  assert.deepEqual(m.view.sectors.map(s => s.key), ['Technology'])
  assert.equal(sleeve(m, 'Technology').selected.weight, 1)
  assert.equal(sleeve(m, 'Technology').selected.amount, 4000)
  // Every other sleeve is absent from this selection: 0 amount, 0% share of the Technology slice.
  for (const key of ['Healthcare', 'Energy', 'Cash & sweep', 'Real Estate']) {
    const s = sleeve(m, key)
    assert.equal(s.selected.amount, 0, `${key} selected amount`)
    assert.equal(s.selected.weight, 0, `${key} selected weight`)
    assert.ok(s.book.weight > 0 || s.book.weight === null, `${key} book weight still measured`)
  }
  // The book basis never narrows with the filters: 5 sleeves, 5700 total.
  assert.equal(m.bookView.sectors.length, 5)
  assert.equal(m.bookView.total, 5700)
})

test('T6 the cash bucket keeps the selector key the page maps for the reader', () => {
  const m = buildAllocationModel(book(), SNAP, { scope: 'ALL', sector: '', query: '' })
  const cash = sleeve(m, 'Cash & sweep')
  assert.ok(cash, 'cash rows bucket on the selector key')
  assert.equal(cash.inBook, true)
  assert.equal(cash.book.amount, 200)
  assert.equal(m.sleeves.some(s => s.key === 'Funds & Cash'), false, 'the display label is not a selector key')
})

test('T7 a book whose allocation is invalid withholds every weight and keeps the amounts', () => {
  const negative = buildAllocationModel(
    [row({ symbol: 'SHT', sector: 'Energy', marketValue: -50, unrealizedPnl: 0 })],
    SNAP,
    { scope: 'ALL', sector: '', query: '' },
  )
  assert.equal(negative.bookView.allocationValid, false)
  assert.equal(negative.bookView.negative, true)
  assert.equal(sleeve(negative, 'Energy').book.weight, null)
  assert.equal(sleeve(negative, 'Energy').book.amount, -50)

  const zero = buildAllocationModel([row({ symbol: 'ZED', marketValue: 0, unrealizedPnl: 0 })], SNAP, {
    scope: 'ALL',
    sector: '',
    query: '',
  })
  assert.equal(zero.bookView.allocationValid, false)
  assert.equal(sleeve(zero, 'Technology').book.weight, null)
  assert.equal(sleeve(zero, 'Technology').book.amount, 0, 'a published zero value is still a published value')
})

test('T8 a book the selector refuses is a refusal, not a page of zeros', () => {
  const r = row({ symbol: 'DUP', marketValue: 10 })
  const rows = [r, { ...r }]
  assert.throws(() => buildAllocationModel(rows, SNAP, { scope: 'ALL', sector: '', query: '' }), /Duplicate/)
  const mixed = [row({ symbol: 'MIX' })].map(x => ({ ...x, snapshotId: 'another-snapshot' }))
  assert.throws(() => buildAllocationModel(mixed, SNAP, { scope: 'ALL', sector: '', query: '' }), /Mixed snapshot/)
})

test('T9 an absent sleeve takes the SELECTION\'s validity, not the book\'s — 0% is a measured absence only there', () => {
  // The book is valid (5700 over positive rows), but a sector filter keeping only the unpriced Real Estate
  // row leaves the selection with no valued total, so its allocation is invalid. A sleeve absent from that
  // non-empty selection must print "—" (weight null), never 0% — 0% would divide by a denominator the
  // selector refused. Pins the M5 mutant (absence keyed on bookView.allocationValid) that survived -8's
  // mutation pass on this suite at 8eb2645ad.
  const m = buildAllocationModel(book(), SNAP, { scope: 'ALL', sector: 'Real Estate', query: '' })
  assert.equal(m.bookView.allocationValid, true, 'the book side must stay valid for this case to bite')
  assert.equal(m.view.rows.length, 1, 'the selection is non-empty, so this is not the empty-selection path')
  assert.equal(m.view.allocationValid, false, 'no valued total: the selection carries no denominator')

  const tech = sleeve(m, 'Technology')
  assert.equal(tech.inBook, true)
  assert.equal(tech.inSelection, false)
  assert.equal(tech.selected.amount, 0, 'the absence is still measured — an amount of 0, not null')
  assert.equal(tech.selected.weight, null, 'the weight must be withheld, not 0%')
  // The book side keeps its own valid denominator untouched.
  assert.ok(near(tech.book.weight, 4000 / 5700))
})
