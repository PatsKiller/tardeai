import assert from 'node:assert/strict'
import { accountText, actionVerb, calDay, cardVisible, daysUntil, etTime, fv, meterParts, panelVisible, pct, tierToneOf, triggerFill, usd, usdShort, type CioCardWire } from './cioCard.ts'

const P = { source_id: 'market_risk:2031-03-03T02:00:00+00:00', as_of: '2031-03-03T02:00:00+00:00' }

// a fact without provenance is not a value
assert.equal(fv({ value: 5, ...P }), 5)
assert.equal(fv({ value: 5, source_id: '', as_of: P.as_of }), undefined)
assert.equal(fv(undefined), undefined)

// visibility: only an evaluated HomeCioCard@v1 draws the card; the panel only at YELLOW/ORANGE/RED
const red: CioCardWire = { schema: 'HomeCioCard@v1', card: { tier: { value: 'RED', ...P } }, panel: { header: { tier: { value: 'RED', ...P } } } }
assert.equal(cardVisible(red), true)
assert.equal(panelVisible(red), true)
assert.equal(cardVisible({ schema: 'HomeCioCard@v1', card: {} }), false)
assert.equal(cardVisible({ schema: 'Other@v1', card: { tier: { value: 'RED', ...P } } }), false)
assert.equal(panelVisible({ schema: 'HomeCioCard@v1', panel: { header: { tier: { value: 'GREEN', ...P } } } }), false)
assert.equal(cardVisible(null), false)

assert.equal(tierToneOf('RED'), 'danger'); assert.equal(tierToneOf('YELLOW'), 'warning'); assert.equal(tierToneOf(undefined), 'neutral')

// Eastern times, calendar days, countdown
assert.equal(etTime('2031-03-03T02:00:00+00:00'), 'Sun 9:00 PM ET')
assert.equal(etTime('nope'), '')
assert.equal(calDay('2031-03-04'), 'Tue 03-04')
assert.equal(daysUntil('2031-03-04', Date.parse('2031-03-03T02:00:00Z')), 2) // Sun evening ET → Tue
assert.equal(daysUntil('bad', Date.now()), null)

// money and percent, missing is a dash
assert.equal(usd(49945.4), '$49,945'); assert.equal(usd(null), '—')
assert.equal(usdShort(1248614), '$1.25M'); assert.equal(usdShort(87633), '$88K'); assert.equal(usdShort(1500), '$1.5K')
assert.equal(pct(7.04), '7.0%'); assert.equal(pct(2.34, 1, true), '+2.3%'); assert.equal(pct(-3.04), '−3.0%'); assert.equal(pct(undefined), '—')

// driver meter widths are the points' share of 100
assert.deepEqual(meterParts([{ name: 'A', points: 33.6, ...P }, { name: 'B', points: 0, ...P }, { name: 'C', points: 26, ...P }]).map(x => x.width), [33.6, 26])

// trigger fill: server's fill first, else value/act, clamped
assert.equal(triggerFill({ key: 'k', label: 'l', value: 7, act: 10, fill: 0.7, ...P }), 0.7)
assert.equal(triggerFill({ key: 'k', label: 'l', value: 12, act: 10, ...P }), 1)
assert.equal(triggerFill({ key: 'k', label: 'l', value: 1, ...P }), null)

assert.equal(actionVerb({ answer: 'RAISE' }), 'Raise stop'); assert.equal(actionVerb({ answer: 'ADD_STOP' }), 'Add stop')
assert.equal(accountText('example_rollover_ira'), 'Example Rollover IRA')

console.log('cioCard.test.ts: ok')
