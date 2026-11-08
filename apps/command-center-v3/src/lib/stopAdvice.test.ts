import assert from 'node:assert/strict'
import { kindOf, stopList } from './stopAdvice.ts'
import { badgeText, stampModel, type StampWire } from './sinceCloseStamp.ts'


const describe = (_n: string, f: () => void) => f()
const it = (n: string, f: () => void) => { try { f() } catch (e) { console.error('FAIL', n); throw e } }
const expect = (a: any) => ({
  toBe: (b: any) => assert.equal(a, b),
  toEqual: (b: any) => assert.deepEqual(a, b),
  toBeNull: () => assert.equal(a, null),
  toContain: (b: string) => assert.ok(String(a).includes(b), `${a} !~ ${b}`),
  toBeCloseTo: (b: number, d = 2) => assert.ok(Math.abs(a - b) < 10 ** -d / 2),
  toMatchObject: (b: any) => { for (const k of Object.keys(b)) assert.equal(a[k], b[k]) },
})
// synthetic symbols and numbers only (the repo is public)
const Q = { AAA: { price: 134.0 }, BBB: { price: 165.5 }, CCC: { price: 50 } }

describe('kindOf', () => {
  it('maps the CIO answer spellings', () => {
    expect(kindOf('ADD STOP')).toBe('ADD_STOP')
    expect(kindOf('add_a_stop')).toBe('ADD_STOP')
    expect(kindOf('Raise')).toBe('RAISE')
    expect(kindOf('FIX QTY')).toBe('FIX_QTY')
    expect(kindOf('NO_ACTION')).toBe('NO_ACTION')
    expect(kindOf('hold')).toBe('HOLD')
    expect(kindOf('???')).toBeNull()
  })
})

describe('stopList', () => {
  const raw = [
    { symbol: 'CCC', answer: 'HOLD', why: 'structure intact' },
    { symbol: 'BBB', answer: 'RAISE', stop_now: 160.78, stop_suggested: 164, qty: 200, account: 'Roth', why: 'higher low' },
    { symbol: 'AAA', answer: 'ADD STOP', stop_suggested: 120.46, qty: 200, account: 'Brokerage', why: 'no stop on file' },
    { symbol: 'DDD', answer: 'FIX QTY', stop_now: 10, stop_suggested: 10, qty: 50, held_qty: 50 },
    { symbol: 'EEE', answer: 'NO ACTION' },
  ]
  const L = stopList(raw, Q)
  it('sorts urgent first, numbers rows, splits the quiet names', () => {
    expect(L.actions.map(r => [r.n, r.symbol, r.kind])).toEqual([[1, 'AAA', 'ADD_STOP'], [2, 'DDD', 'FIX_QTY'], [3, 'BBB', 'RAISE']])
    expect(L.quiet.map(r => r.symbol)).toEqual(['CCC', 'EEE'])
    expect(L.header).toBe('Your actions · 3 stop changes at Schwab')
    expect(L.actions[0].urgent).toBe(true)
    expect(L.actions[2].urgent).toBe(false)
  })
  it('computes the dollar consequences from qty and quotes', () => {
    expect(L.actions[0].consequence).toMatchObject({ text: '$26,800 has no stop', tone: 'danger' }) // 200 x 134.00
    expect(L.actions[2].consequence).toMatchObject({ text: "Locks in $644 of Friday's gain", tone: 'success' }) // (164-160.78) x 200
    expect(L.actions[1].consequence?.tone).toBe('warning')
  })
  it('worst case is (close - stop) x qty', () => {
    expect(L.actions[0].worstCase).toBeCloseTo((134 - 120.46) * 200, 2)
  })
  it('one stop change reads singular; empty or junk input is an empty list', () => {
    expect(stopList([raw[2]], Q).header).toBe('Your actions · 1 stop change at Schwab')
    expect(stopList(undefined, Q).actions).toEqual([])
    expect(stopList([null, 5, { symbol: 'X' }], Q).actions).toEqual([])
  })
})

const wire = (over: Partial<StampWire> = {}): StampWire => ({
  updated_at: '2031-03-10T13:46:00Z', updated_text: '', next_refresh_at: '', next_refresh_text: 'Tue 03-10 · 10:30 AM ET', sources: [], any_warn: false,
  schedule: {
    trading_day: true, grace_min: 30, market_open: '2031-03-10T13:30:00Z', market_close: '2031-03-10T20:00:00Z', cio: ['2031-03-10T10:00:00Z'],
    fixed: [['6:00 AM', '10:00'], ['9:15 AM', '13:15'], ['9:45 AM', '13:45'], ['10:30 AM', '14:30'], ['12:00 PM', '16:00']].map(([text, hm]) => ({ text, at: `2031-03-10T${hm}:00Z` })),
  },
  ...over,
})

describe('stampModel', () => {
  it('badge is the ET clock and weekday of the instant', () => {
    expect(badgeText('2031-03-10T13:46:00Z')).toBe('UPDATED 9:46 AM ET · MON 03-10')
  })
  it('marks done, next and later against the client clock', () => {
    const m = stampModel(wire(), Date.parse('2031-03-10T14:00:00Z'))!
    expect(m.slots.map(s => s.state)).toEqual(['done', 'done', 'done', 'next', 'later'])
    expect(m.ago).toBe('14 min ago')
    expect(m.missed).toBe(false)
    expect(m.slots[0].cio).toBe(true)
  })
  it('turns amber/missed when a market-hours fixed slot is 30+ min past with no build since', () => {
    const m = stampModel(wire({ updated_at: '2031-03-10T13:00:00Z' }), Date.parse('2031-03-10T14:20:00Z'))!
    expect(m.missed).toBe(true)
    expect(m.slots.find(s => s.state === 'missed')?.text).toBe('9:45 AM')
    expect(m.missedText).toContain('9:45 AM update did not run')
  })
  it('a slot inside the grace window, or before the open, is not a failure', () => {
    expect(stampModel(wire({ updated_at: '2031-03-10T13:00:00Z' }), Date.parse('2031-03-10T13:40:00Z'))!.missed).toBe(false)
    expect(stampModel(wire({ updated_at: '2031-03-09T22:00:00Z' }), Date.parse('2031-03-10T11:00:00Z'))!.missed).toBe(false)
  })
  it('no schedule, no model', () => {
    expect(stampModel(null)).toBeNull()
  })
})

console.log('stopAdvice tests passed')

import { synopsisModel } from './synopsis.ts'
{
  const now = Date.parse('2031-03-10T14:00:00Z')
  const syn = { posture: 'Defensive', risk: 'ORANGE', verdict: 'Raise two stops, add one.', book: 'Down 1.2% Friday', market: null, reentry: 'None ready', this_week: 'CPI Tuesday', do_now: '3 stop changes', generated_at: '2031-03-10T11:00:00Z' }
  const ok = synopsisModel(syn, null, now)
  assert.equal(ok.state, 'ok'); assert.equal(ok.posture, 'Defensive'); assert.equal(ok.verdict, 'Raise two stops, add one.')
  assert.deepEqual(ok.rows.map(r => r.key), ['book', 'reentry', 'this_week', 'do_now'])  // the null market row is not drawn
  const old = synopsisModel({ ...syn, generated_at: '2031-03-08T11:00:00Z' }, null, now)
  assert.equal(old.state, 'stale'); assert.ok(old.notice?.startsWith('CIO synopsis not built since'))
  const none = synopsisModel(undefined, '2031-03-09T11:00:00Z', now)
  assert.equal(none.state, 'missing'); assert.ok(none.notice?.includes('not built since')); assert.equal(none.rows.length, 0)
  assert.equal(synopsisModel(null, null, now).notice, 'CIO synopsis not built yet')
  console.log('synopsis tests passed')
}
