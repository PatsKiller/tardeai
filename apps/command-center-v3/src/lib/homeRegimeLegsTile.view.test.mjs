// LQ-20261113-3048 (Combined Home A06) — the header REGIME tile never keeps the confident dot on missing legs.
//
// Measured 2026-11-13 14:06 ET: risk_on_trend at 0.17 on the VIX bucket alone (trend and breadth `not_measured`),
// 8.2 h old on a fresh envelope, painted with the quiet OK dot. The tile's tone read only the clock.
//
// The projection below mirrors the REGIME tile's tone/stale/badge/meta/colour bindings in MetricStrip.tsx; the
// wiring check pins those expressions to the component so the projection cannot drift away from it.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { regimeState, regimeLegsNote, MIN_REGIME_LEGS, REGIME_LEGS } from './homeRegime.ts'
import { regimeAgeNote, NOT_CURRENT_COLOR } from './headerMarketClock.ts'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

const row = {
  regime_label: 'risk_on_trend', confidence: 0.17, stale_data: false,
  volatility_state: 'neutral', trend_state: 'not_measured', breadth_state: 'not_measured',
}
const env = r => ({ ok: true, data: r, as_of: '2026-11-13T05:51:43-05:00', age_hours: 8.2, stale: false, stale_after_hours: 26 })

const tile = info => {
  const legsText = regimeLegsNote(info)
  const thin = info.legsMeasured != null && info.legsMeasured < MIN_REGIME_LEGS
  return {
    tone: info.stale || info.incomplete ? 'warn' : 'ok',
    stale: info.stale
      ? (thin ? `${info.legsMeasured} of ${REGIME_LEGS.length} legs measured`
        : info.ageHours != null ? `${info.ageHours.toFixed(1)} h old` : 'clock not reported')
      : null,
    staleLabel: thin ? `NOT CURRENT · ${info.legsMeasured}/${REGIME_LEGS.length} LEGS`
      : info.ageHours != null ? `STALE · ${info.ageHours.toFixed(1)} h` : 'STALE',
    meta: regimeAgeNote(info, legsText || null),
    grey: info.stale,
  }
}

const cases = []
const check = (name, fn) => cases.push({ name, fn })

check('the 11-13 one-leg tile is warn, grey, and says it rests on one leg', () => {
  const v = tile(regimeState(row, env(row)))
  assert.equal(v.tone, 'warn')
  assert.equal(v.grey, true, `a one-leg label must take ${NOT_CURRENT_COLOR}`)
  assert.equal(v.stale, '1 of 3 legs measured')
  assert.equal(v.staleLabel, 'NOT CURRENT · 1/3 LEGS')
  assert.equal(v.meta, 'stale · 8.2 h old · 1 of 3 legs measured (trend, breadth not measured)')
})

check('two legs: warn tone, market colour kept, the missing leg named', () => {
  const r = { ...row, trend_state: 'bearish' }
  const v = tile(regimeState(r, env(r)))
  assert.equal(v.tone, 'warn')
  assert.equal(v.grey, false)
  assert.equal(v.stale, null)
  assert.equal(v.meta, '8.2 h old · 2 of 3 legs measured (breadth not measured)')
})

check('three legs on a fresh clock keep the quiet dot', () => {
  const r = { ...row, trend_state: 'bullish', breadth_state: 'broad' }
  const v = tile(regimeState(r, env(r)))
  assert.equal(v.tone, 'ok')
  assert.equal(v.stale, null)
  assert.equal(v.meta, '8.2 h old')
})

check('a clock-stale tile with every leg keeps the clock badge', () => {
  const r = { ...row, trend_state: 'bullish', breadth_state: 'broad' }
  const v = tile(regimeState(r, { ...env(r), stale: true, age_hours: 30.4 }))
  assert.equal(v.staleLabel, 'STALE · 30.4 h')
  assert.equal(v.stale, '30.4 h old')
})

check('MetricStrip binds the leg-aware tone, badge, note and tip', () => {
  const src = readFileSync(join(app, 'src/components/MetricStrip.tsx'), 'utf8')
  assert.match(src, /const regimeLegsText = regimeLegsNote\(regimeInfo\)/)
  assert.match(src, /const regimeThin = regimeInfo\.legsMeasured != null && regimeInfo\.legsMeasured < MIN_REGIME_LEGS/)
  assert.match(src, /tone: worseTone\(regimeInfo\.stale \|\| regimeInfo\.incomplete \? 'warn' : 'ok', regimeStale \? 'warn' : 'ok'\)/)
  assert.match(src, /regimeThin \? `\$\{regimeInfo\.legsMeasured\} of \$\{REGIME_LEGS\.length\} legs measured`/)
  assert.match(src, /staleLabel: regimeThin \? `NOT CURRENT · \$\{regimeInfo\.legsMeasured\}\/\$\{REGIME_LEGS\.length\} LEGS`/)
  assert.match(src, /regimeAgeNote\(regimeInfo, regimeLegsText \|\|/)
  assert.match(src, /color: regimeInfo\.stale \? NOT_CURRENT_COLOR/)
  assert.match(src, /LEGS: \$\{regimeLegsText\}/)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
