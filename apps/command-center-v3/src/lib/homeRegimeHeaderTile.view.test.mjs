// LQ-20261107-1392 (1 of 4) — the HEADER REGIME tile reads the clock that sits beside the row.
//
// Measured on the live host 2026-11-08: /api/v2/risk-regime/latest answered
//   { ok: true, data: { regime_label: 'high_volatility', … }, as_of: '2026-11-06T21:05:…', age_hours: 55.23,
//     stale: true, stale_after_hours: 26 }
// while the header painted a quiet "●" beside it. The tile destructured useApi's TRANSPORT `stale` — which only ever
// means "the last refetch failed" — and never asked for `envelope`, so a 55-hour-old snapshot on a healthy connection
// read as current. HomeDoNow already had the right rule (lib/homeRegime.ts); the header simply did not use it.
//
// These checks drive the REAL module with the shapes the hook delivers and mirror the tile's own bindings, then pin
// those bindings to MetricStrip.tsx so the projection cannot drift away from the component.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { TOKENS } from './designTokens.ts'
import { regimeState, regimeClockTitle } from './homeRegime.ts'
import { regimeAgeNote, NOT_CURRENT_COLOR } from './headerMarketClock.ts'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

// The live body, verbatim in shape and values (times US Eastern: last snapshot 2026-11-06 16:05 ET).
const wire = {
  ok: true,
  data: { regime_label: 'high_volatility', confidence: 0.58, trend_state: 'bearish', breadth_state: 'weak', volatility_state: 'high' },
  as_of: '2026-11-06T21:05:01-05:00',
  age_hours: 55.23,
  stale: true,
  stale_after_hours: 26,
}
// What useApi hands a component: `data` unwrapped, plus the whole body as `envelope`.
const row = wire.data

// The REGIME tile's clock-bearing fields, mirrored from MetricStrip.tsx. `tone` is what paints the dot
// ('ok' → dim ●, 'warn' → ▲) and what turns the rail amber; `meta` is the one line under the value.
const tile = info => ({
  tone: info.stale ? 'warn' : 'ok',
  staleBadge: info.stale ? (info.ageHours != null ? `STALE · ${info.ageHours.toFixed(1)} h` : 'STALE') : null,
  // LQ-20261107-1610: the age line is shown in every state, and a stale label is the not-current grey.
  meta: regimeAgeNote(info),
  title: regimeClockTitle(info),
  color: info.stale ? NOT_CURRENT_COLOR : TOKENS.text[0],
})

const cases = []
const check = (name, fn) => cases.push({ name, fn })

check('the envelope clock is carried into the tile, not discarded', () => {
  const got = regimeState(row, wire)
  assert.equal(got.ageHours, 55.23)
  assert.equal(got.asOf, wire.as_of)
  assert.equal(got.stale, true)
})

check('the 55-hour snapshot never paints a current dot', () => {
  const v = tile(regimeState(row, wire))
  assert.equal(v.tone, 'warn')
  assert.equal(v.meta, 'stale · 2.3 d old')
  assert.equal(v.title, 'regime as_of 2026-11-06T21:05:01-05:00 (55.2 h old)')
  assert.equal(v.color, 'var(--text3)')
})

check('the stale badge names the age the envelope measured', () => {
  assert.equal(tile(regimeState(row, wire)).staleBadge, 'STALE · 55.2 h')
})

check('a fresh envelope keeps the quiet dot', () => {
  const v = tile(regimeState(row, { ...wire, stale: false, age_hours: 2.1 }))
  assert.equal(v.tone, 'ok')
  assert.equal(v.meta, '2.1 h old', 'a fresh regime must still say how old it is (LQ-1610)')
  assert.equal(v.staleBadge, null)
})

check('a body that carries the row and no clock is not current', () => {
  const v = tile(regimeState(row, { ok: true, data: row }))
  assert.equal(v.tone, 'warn', 'a clockless body still renders as current')
  assert.equal(v.meta, 'regime clock not reported')
})

check('no row at all stays unknown, never fresh', () => {
  assert.equal(regimeState(null, null).text, 'unknown')
})

// ── the wiring half: the component must ASK for the envelope ────────────────────────────────────────────────
check('MetricStrip destructures the envelope and uses the shared rule', () => {
  const src = readFileSync(join(app, 'src/components/MetricStrip.tsx'), 'utf8')
  // Comments may NAME the old shape (they explain why it was wrong); only executable lines count.
  const code = src.split('\n').filter(l => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
  assert.match(src, /envelope: regimeEnv/, 'the tile does not ask useApi for the envelope')
  assert.match(src, /regimeState\(regime, regimeEnv\)/, 'the tile does not pass the envelope to regimeState')
  assert.match(src, /tone: worseTone\(regimeInfo\.stale \? 'warn' : 'ok'/, 'the dot does not follow the regime clock')
  assert.match(src, /regimeClockTitle\(regimeInfo\)/, 'the meta line does not name the regime clock')
  assert.ok(!/tone: regimeStale \?/.test(code), 'the dot still follows the transport stale flag')
  // LQ-20261107-1610: age on the face in every state; stale is grey, not amber.
  assert.match(code, /asOfNote: regime\s*\n?\s*\? regimeAgeNote\(regimeInfo/, 'the age line is not shown in every state')
  assert.match(code, /color: regimeInfo\.stale \? NOT_CURRENT_COLOR/, 'a stale regime is not the not-current grey')
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
