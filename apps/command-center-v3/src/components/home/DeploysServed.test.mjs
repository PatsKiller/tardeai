// LQ-20261113-3084 (review 3080 R1/R2): the Deploys rows are rendered, not source-grepped, and the Home card's tone follows
// the SERVED release, not the poller. node src/components/home/DeploysServed.test.mjs (synthetic fixtures only)
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}
const React = (await import(pathToFileURL(require.resolve('react')).href)).default
const { renderToStaticMarkup } = await import(pathToFileURL(require.resolve('react-dom/server')).href)
const { DeploysSummaryRows } = await import(compile(join(app, 'src/components/home/DeploysSummaryRows.tsx')))
const { deploysSummary, freshness } = await import(compile(join(app, 'src/lib/deploys.ts')))

const NOW = Date.parse('2031-03-10T15:00:00Z')
const f = freshness('2031-03-10T14:59:00Z', true, { nowMs: NOW })
const SERVED = { sha: '7b0cc18d05cb892e8da50f8acadcfa3e340ebdd9', activated_at: '2031-03-10T14:50:00Z', is_current: true, error: null }
const wire = (served, outcome = 'deploy_failed', main = '9c21372aa5ef', latch = 'ABSENT') => ({
  schema: 'DeploysStatus@v1', generated_at: '2031-03-10T14:59:00Z', served,
  latest: outcome ? { as_of: '2031-03-09T22:30:00Z', path: 'poller', outcome, main_sha: main } : null,
  stop: { latch: { status: latch } },
})
const html = w => renderToStaticMarkup(React.createElement(DeploysSummaryRows, { s: deploysSummary(w, f) }))
let n = 0
function test(name, fn) { fn(); n += 1; console.log(`ok - ${name}`) }

test('served ok + poller failed: Serving row first, poller row labelled and flagged, tone is not the poller\'s red', () => {
  const h = html(wire(SERVED))
  assert.match(h, /data-testid="deploys-served"[^>]*>Serving: .*7b0cc18d0/)
  assert.match(h, /Poller, last decision: .*deploy_failed · main 9c21372aa/)
  assert.match(h, /not the served release/)
  assert.match(h, /before it was activated/)
  assert.ok(h.indexOf('deploys-served') < h.indexOf('deploys-last'))
  const s = deploysSummary(wire(SERVED), f)
  assert.equal(s.cardTone, 'warning')
  assert.notEqual(s.cardTone, 'danger')
  assert.match(s.cardTip, /served release 7b0cc18d05cb/)
  assert.match(s.cardTip, /does not change what is served/)
})
test('served UNKNOWN renders UNKNOWN and the card is warning', () => {
  const w = wire({ sha: null, error: 'no BUILD_SHA in x' }, 'verified', 'a'.repeat(40))
  const h = html(w)
  assert.match(h, /Serving: .*UNKNOWN \(no BUILD_SHA in x\)/)
  assert.doesNotMatch(h, /serving[^<]*aaaaaaaaa/i)
  assert.equal(deploysSummary(w, f).cardTone, 'warning')
  assert.equal(deploysSummary(wire(undefined, 'verified'), f).cardTone, 'warning')
})
test('not the CURRENT release is said and warns', () => {
  const w = wire({ ...SERVED, is_current: false }, 'verified', '7b0cc18d0')
  assert.match(html(w), /not the CURRENT release/)
  assert.equal(deploysSummary(w, f).cardTone, 'warning')
})
test('served ok + poller same: neutral, no "differs" wording', () => {
  const w = wire(SERVED, 'verified', '7b0cc18d0')
  const h = html(w)
  assert.doesNotMatch(h, /not the served release/)
  assert.equal(deploysSummary(w, f).cardTone, 'neutral')
})
test('a STOP latch is still danger; unavailable read is warning', () => {
  assert.equal(deploysSummary(wire(SERVED, 'verified', '7b0cc18d0', 'SET'), f).cardTone, 'danger')
  assert.equal(deploysSummary(null, freshness(null, false, { nowMs: NOW, error: 'HTTP 503' })).cardTone, 'danger')
  assert.equal(deploysSummary(wire(SERVED, 'verified', '7b0cc18d0'), freshness('2031-03-10T10:00:00Z', true, { nowMs: NOW })).cardTone, 'warning')
})
test('HomeDoNow draws the Deploys card from cardTone/cardTip, not the poller outcome', () => {
  const src = readFileSync(join(app, 'src/pages/HomeDoNow.tsx'), 'utf8')
  assert.match(src, /k: 'Deploys', v: dp\.line, to: '\/system\/releases', tone: dp\.cardTone, tip: dp\.cardTip/)
  assert.doesNotMatch(src, /dp\.lastTone === 'danger'/)
})
console.log(`${n} passed`)
