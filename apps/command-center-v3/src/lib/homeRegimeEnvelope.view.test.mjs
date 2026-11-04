// FQ-085 (HQ-01) — the Home REGIME line reads the broker envelope that carries it, and never presents a stale or
// absent regime as current.
//
// Live at release 105df180e, `/api/v2/risk-regime/latest` returns a BrokerReadEnvelope:
//   { ok, data: { regime_label: 'risk_off', … }, as_of, age_hours: 5.53, stale: false, stale_after_hours }
// `HomeDoNow.tsx` read `regime?.regime_label`, which is inside `data`, so the line fell back to "unknown" and the
// clock beside `data` was never read. This pins the repaired read: label from `data`, the envelope's clock surfaced,
// and a stale or missing clock never rendered as a current verdict.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const page = readFileSync(join(app, 'src/pages/HomeDoNow.tsx'), 'utf8')

// The derivation lives inline in the component (it needs no new module); these checks read that exact expression
// block out of the source and evaluate it against the live shapes, so the test cannot drift from the page.
function regimeBlock() {
  const start = page.indexOf('const regimeData: any =')
  assert.ok(start > 0, 'the regime derivation is gone from HomeDoNow.tsx')
  const end = page.indexOf('const regimeText', start)
  const stop = page.indexOf('\n', page.indexOf(": regimeLabel", end))
  assert.ok(end > start && stop > end, 'the regime derivation block is malformed')
  return page.slice(start, stop)
}

// The block is TypeScript; transpile it exactly as the build would, then evaluate it.
const ts = (await import('node:module')).createRequire(join(app, 'package.json'))('typescript')
const compiled = ts.transpileModule(regimeBlock(), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
// eslint-disable-next-line no-new-func
const derive = new Function('regime', `${compiled}\nreturn { regimeLabel, regimeStale, regimeAgeH, regimeAsOf, regimeText }`)

const live = {
  ok: true,
  data: { regime_label: 'risk_off', confidence: 0.67, stale_data: false },
  as_of: '2026-11-04T10:52:08.078825+00:00', age_hours: 5.53, stale: false, stale_after_hours: 12,
}

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('the label is read from inside the envelope', () => {
  assert.equal(derive(live).regimeText, 'risk off')
})

check('the envelope clock is carried, not discarded', () => {
  const got = derive(live)
  assert.equal(got.regimeAgeH, 5.53)
  assert.equal(got.regimeAsOf, live.as_of)
  assert.equal(got.regimeStale, false)
})

check('a stale envelope is never presented as current', () => {
  const got = derive({ ...live, stale: true, age_hours: 9.4 })
  assert.equal(got.regimeText, 'risk off (stale, 9.4 h old)')
  assert.equal(got.regimeStale, true)
})

check("the snapshot's own stale flag counts too", () => {
  assert.equal(derive({ ...live, data: { ...live.data, stale_data: true } }).regimeText, 'risk off (stale, 5.5 h old)')
})

check('a missing label says so instead of "unknown"', () => {
  assert.equal(derive({ ...live, data: {} }).regimeText, 'not reported')
})

check('no payload at all still reads "unknown"', () => {
  assert.equal(derive(undefined).regimeText, 'unknown')
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
