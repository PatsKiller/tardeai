// LQ-20261113-3048 (Combined Home A06) — an unmeasured regime leg is missing evidence, and one leg is never current.
//
// Measured 2026-11-13 14:06 ET: the latest snapshot (05:51 ET) read risk_on_trend at confidence 0.17 with
// trend_state and breadth_state `not_measured` and stale_data false, 8.2 h old on a fresh envelope, and the Home
// REGIME tile painted the quiet OK dot. The label rested on the VIX bucket alone. Rows written before the classifier
// counted legs still say stale_data=false, so lib/homeRegime.ts derives the leg count from the row itself.
//
// These checks drive the REAL module with that shape (synthetic values) and with two and three measured legs.
// HomeDoNow binds `regimeInfo.stale` and `regimeInfo.text` (pinned in homeRegimeEnvelope.view.test.mjs), so the
// classic line inherits the result without a page change.
import assert from 'node:assert/strict'
import { regimeState, regimeLegs, regimeLegsNote, MIN_REGIME_LEGS } from './homeRegime.ts'

// The 11-13 shape: fresh envelope, row says not stale, two of three legs not measured.
const oneLegRow = {
  regime_label: 'risk_on_trend', confidence: 0.17, stale_data: false,
  volatility_state: 'neutral', trend_state: 'not_measured', breadth_state: 'not_measured',
}
const env = (row, extra = {}) => ({
  ok: true, data: row, as_of: '2026-11-13T05:51:43-05:00', age_hours: 8.2, stale: false, stale_after_hours: 26,
  ...extra,
})

const cases = []
const check = (name, fn) => cases.push({ name, fn })

check('the 11-13 one-leg row is not current even though the row and the envelope say fresh', () => {
  const s = regimeState(oneLegRow, env(oneLegRow))
  assert.equal(s.legsMeasured, 1)
  assert.deepEqual(s.legsMissing, ['trend', 'breadth'])
  assert.equal(s.stale, true, 'a one-leg label must never render as current')
  assert.equal(s.incomplete, true)
  assert.equal(s.confident, false)
  assert.equal(s.text, 'risk on trend (1 of 3 legs measured)')
})

check('the legs note names the unmeasured legs', () => {
  assert.equal(regimeLegsNote(regimeState(oneLegRow, env(oneLegRow))), '1 of 3 legs measured (trend, breadth not measured)')
})

check('two measured legs are incomplete: no confident tone, but not called stale', () => {
  const row = { ...oneLegRow, trend_state: 'bearish' }
  const s = regimeState(row, env(row))
  assert.equal(s.legsMeasured, 2)
  assert.deepEqual(s.legsMissing, ['breadth'])
  assert.equal(s.stale, false)
  assert.equal(s.incomplete, true)
  assert.equal(s.confident, false)
  assert.equal(s.text, 'risk on trend (2 of 3 legs measured)')
})

check('three measured legs on a fresh clock are confident and print the plain label', () => {
  const row = { ...oneLegRow, trend_state: 'bullish', breadth_state: 'broad' }
  const s = regimeState(row, env(row))
  assert.equal(s.legsMeasured, 3)
  assert.deepEqual(s.legsMissing, [])
  assert.equal(s.stale, false)
  assert.equal(s.incomplete, false)
  assert.equal(s.confident, true)
  assert.equal(s.text, 'risk on trend')
  assert.equal(regimeLegsNote(s), '')
})

check('no measured leg at all is not current', () => {
  const row = { ...oneLegRow, volatility_state: 'unknown' }
  const s = regimeState(row, env(row))
  assert.equal(s.legsMeasured, 0)
  assert.equal(s.stale, true)
  assert.equal(s.confident, false)
})

check('null, empty and spaced variants all count as unmeasured', () => {
  for (const v of [null, undefined, '', '  ', 'UNKNOWN', 'Not_Measured', 'not measured']) {
    const row = { ...oneLegRow, trend_state: 'bearish', breadth_state: v }
    assert.deepEqual(regimeLegs(row).missing, ['breadth'], `breadth_state=${JSON.stringify(v)}`)
  }
})

check('a row that reports none of the leg fields is unknown on legs, not "all measured" and not degraded', () => {
  const row = { regime_label: 'risk_off', confidence: 0.67, stale_data: false }
  const s = regimeState(row, env(row))
  assert.equal(s.legsMeasured, null)
  assert.deepEqual(s.legsMissing, [])
  assert.equal(s.incomplete, false)
  assert.equal(s.stale, false)
  assert.equal(s.text, 'risk off')
})

// LQ-20261113-3061 (review 3048 C3): a partial row (some leg fields absent) counts the absent legs as unmeasured and
// NAMES them - before, a volatility-only row was stale with legsMissing [] and no reason in the text.
check('a partial row names its absent legs as unmeasured and is not current on one leg', () => {
  const row = { regime_label: 'risk_off', confidence: 0.5, stale_data: false, volatility_state: 'neutral' }
  const s = regimeState(row, env(row))
  assert.equal(s.legsMeasured, 1)
  assert.deepEqual(s.legsMissing, ['trend', 'breadth'])
  assert.equal(s.stale, true)
  assert.equal(s.incomplete, true)
  assert.equal(s.text, 'risk off (1 of 3 legs measured)')
})

check('a partial row with two measured legs is incomplete, names the absent one, and is not called stale', () => {
  const row = { regime_label: 'risk_off', confidence: 0.5, stale_data: false, volatility_state: 'neutral', trend_state: 'bearish' }
  const s = regimeState(row, env(row))
  assert.equal(s.legsMeasured, 2)
  assert.deepEqual(s.legsMissing, ['breadth'])
  assert.equal(s.stale, false)
  assert.equal(s.confident, false)
  assert.equal(regimeLegsNote(s), '2 of 3 legs measured (breadth not measured)')
})

check('n/a and none count as unmeasured (the list the classifier shares)', () => {
  for (const v of ['n/a', 'N/A', 'none', 'None']) {
    const row = { ...oneLegRow, trend_state: 'bearish', breadth_state: v }
    assert.deepEqual(regimeLegs(row).missing, ['breadth'], `breadth_state=${JSON.stringify(v)}`)
  }
})

check('a stale clock and missing legs are both said', () => {
  const s = regimeState(oneLegRow, env(oneLegRow, { stale: true, age_hours: 30.4 }))
  assert.equal(s.text, 'risk on trend (stale, 30.4 h old, 1 of 3 legs measured)')
  assert.equal(s.confident, false)
})

check('a clockless body with missing legs says both', () => {
  const s = regimeState(oneLegRow, { ok: true, data: oneLegRow })
  assert.equal(s.text, 'risk on trend (clock not reported, 1 of 3 legs measured)')
})

check('the stale_data flag a counting classifier writes is still honoured', () => {
  const row = { ...oneLegRow, stale_data: true }
  const s = regimeState(row, env(row))
  assert.equal(s.stale, true)
  assert.equal(s.text, 'risk on trend (stale, 8.2 h old, 1 of 3 legs measured)')
})

check('the threshold mirrors the classifier', () => {
  assert.equal(MIN_REGIME_LEGS, 2)
})

check('no row stays unknown and never confident', () => {
  const s = regimeState(null, null)
  assert.equal(s.text, 'unknown')
  assert.equal(s.confident, false)
  assert.equal(s.legsMeasured, null)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
