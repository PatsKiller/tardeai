// FQ-085 (HQ-01) — the Home REGIME line reads the clock that sits BESIDE the row in the broker envelope.
//
// The wire is { ok, data: { regime_label: 'risk_off', … }, as_of, age_hours, stale, stale_after_hours }.
// `useApi` unwraps `data`, so the page receives the ROW and nothing else unless it asks for the envelope too.
//
// This file previously extracted the derivation block out of HomeDoNow.tsx and evaluated it with the WHOLE wire body
// as its `regime` argument — which is why it stayed green while the page itself could never see `stale` (cc-deepseek-5's
// BLOCK on #2642, verified by driving the real unwrap). So it now does two things: it drives the REAL module with the
// shapes the hook actually delivers, and it checks the page asks for the envelope at all.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { regimeState, regimeClockTitle } from './homeRegime.ts'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const wire = {
  ok: true,
  data: { regime_label: 'risk_off', confidence: 0.67, stale_data: false },
  as_of: '2026-11-04T10:52:08.078825+00:00', age_hours: 5.53, stale: false, stale_after_hours: 12,
}
// What useApi hands a component: `data` unwrapped, plus the envelope it now also exposes.
const row = wire.data

const cases = []
const check = (name, fn) => cases.push({ name, fn })

check('the label is read from the row the hook delivers', () => {
  assert.equal(regimeState(row, wire).text, 'risk off')
})

check('the envelope clock is carried, not discarded', () => {
  const got = regimeState(row, wire)
  assert.equal(got.ageHours, 5.53)
  assert.equal(got.asOf, wire.as_of)
  assert.equal(got.stale, false)
})

check('a stale envelope is never presented as current', () => {
  const got = regimeState(row, { ...wire, stale: true, age_hours: 9.4 })
  assert.equal(got.text, 'risk off (stale, 9.4 h old)')
  assert.equal(got.stale, true)
})

check('a stale envelope with no age still says stale', () => {
  const got = regimeState(row, { ...wire, stale: true, age_hours: undefined })
  assert.equal(got.text, 'risk off (stale)')
})

check("the row's own stale_data flag still counts", () => {
  assert.equal(regimeState({ ...row, stale_data: true }, wire).stale, true)
})

check('the envelope outranks a row that says nothing', () => {
  assert.equal(regimeState({ ...row, stale: false }, { ...wire, stale: true }).stale, true)
})

check('no regime at all reads unknown, not fresh', () => {
  assert.equal(regimeState(null, null).text, 'unknown')
})

check('a row with no label is reported, not guessed', () => {
  assert.equal(regimeState({ confidence: 0.4 }, wire).text, 'not reported')
})

check('a missing clock is stated as missing, never as current', () => {
  const got = regimeState(row, { ok: true, data: row })
  assert.equal(got.asOf, null)
  assert.equal(regimeClockTitle(got), 'regime clock not reported')
})

check('the clock title carries the stamp and the age when they exist', () => {
  assert.match(regimeClockTitle(regimeState(row, wire)), /regime as_of .* \(5\.5 h old\)/)
})

// The wiring half: the page must ASK for the envelope. Without this the helper is correct and unused.
check('HomeDoNow destructures the envelope from useApi and passes it', () => {
  const page = readFileSync(join(app, 'src/pages/HomeDoNow.tsx'), 'utf8')
  // Comments may NAME the old shape (they explain why it was wrong); only executable lines count.
  const code = page.split('\n').filter(l => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
  assert.match(page, /envelope: regimeEnv/, 'the page does not ask useApi for the envelope')
  assert.match(page, /regimeState\(regime, regimeEnv\)/, 'the page does not pass the envelope to regimeState')
  assert.ok(!/regime\s*\??\.\s*stale/.test(code), 'the page still reads the clock off the unwrapped row')
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
