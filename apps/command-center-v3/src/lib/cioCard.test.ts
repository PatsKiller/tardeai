import assert from 'node:assert/strict'
import { accountText, actionVerb, calDay, cardVisible, daysUntil, driverTone, etTime, fv, meterParts, panelVisible, pct, TIER_CUTOFFS, tierToneOf, trancheShares, triggerFill, usd, usdCents, usdShort, type CioCardWire } from './cioCard.ts'

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

// driver meter widths are the points' share of 100; a driver with no number is absent, never a 0-point segment
assert.deepEqual(meterParts([{ name: 'A', points: 33.6, ...P }, { name: 'B', points: 0, ...P }, { name: 'C', points: 26, ...P }]).map(x => x.width), [33.6, 26])
assert.deepEqual(meterParts([{ name: 'A', ...P }, { name: 'B', points: Number.NaN, ...P }, { name: 'C', points: 7, ...P }]).map(x => x.name), ['C'])

// LQ-20261107-1642: a segment's tone is its DRIVER STATE, not its position — the order below reverses the
// old nth-child rule (first is red, second amber) and each part must still take its own state's tone.
const segs = meterParts([{ name: 'Breadth', state: 'WARN', points: 12, ...P }, { name: 'Volatility', state: 'STRESS', points: 19, ...P }])
assert.deepEqual(segs.map(s => s.tone), ['warning', 'danger'])
assert.deepEqual(segs.map(s => s.state), ['WARN', 'STRESS'])
// every word of the engine's state vocabulary maps to a real tone, and an absent/unknown state is never a stress colour
assert.equal(driverTone('STRESS'), 'danger'); assert.equal(driverTone('WARN'), 'warning')
assert.equal(driverTone('IMPROVING'), 'info'); assert.equal(driverTone('CALM'), 'success')
assert.equal(driverTone('UNKNOWN'), 'neutral'); assert.equal(driverTone(undefined), 'neutral'); assert.equal(driverTone('not-a-state'), 'neutral')
assert.deepEqual(meterParts([{ name: 'A', points: 5, ...P }])[0].state, 'UNKNOWN') // absent state is named, not invented
// the tier cutoffs are the policy's own numbers (config/market_risk_policy.yaml `tiers`), on the same 0-100 scale
assert.deepEqual(TIER_CUTOFFS.map(t => [t.tier, t.score]), [['BLUE', 25], ['YELLOW', 40], ['ORANGE', 60], ['RED', 75]])

// trigger fill: server's fill first, else value/act, clamped
assert.equal(triggerFill({ key: 'k', label: 'l', value: 7, act: 10, fill: 0.7, ...P }), 0.7)
assert.equal(triggerFill({ key: 'k', label: 'l', value: 12, act: 10, ...P }), 1)
assert.equal(triggerFill({ key: 'k', label: 'l', value: 1, ...P }), null)

assert.equal(actionVerb({ answer: 'RAISE' }), 'Raise stop'); assert.equal(actionVerb({ answer: 'ADD_STOP' }), 'Add stop')
assert.equal(accountText('example_rollover_ira'), 'Example Rollover IRA')

// LQ-20261107-1654: a tranche row is whole shares at the LIVE price plus the cash left over; without a price it says so
assert.equal(trancheShares({ tranche: 1, usd: 15065, shares: 81, leftover_usd: 96.2 }), '81 sh + $96.20 cash')
assert.equal(trancheShares({ tranche: 2, usd: 15064, shares: 81, leftover_usd: 95.2 }), '81 sh + $95.20 cash')
assert.equal(trancheShares({ tranche: 1, usd: 1200, shares: null, leftover_usd: null }), 'needs a live price')
assert.equal(trancheShares({ tranche: 1, usd: 1200, shares: 4 }), '4 sh')
assert.equal(usdCents(0), '$0.00'); assert.equal(usdCents(-3.5), '−$3.50'); assert.equal(usdCents(null), '—')

console.log('cioCard.test.ts: ok')
