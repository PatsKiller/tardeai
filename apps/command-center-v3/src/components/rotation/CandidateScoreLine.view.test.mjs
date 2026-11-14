/**
 * RR-004 rendered contract (sprint 8H-2): a genuine 0 renders as 0 and is not blanked by a truthy
 * render; a missing score renders as unavailable with its reason; the stop-driven note sits beside
 * the zero. Proven on the component the page actually mounts.
 */
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
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

const { CandidateScoreLine } = await import(compile(join(app, 'src/components/rotation/CandidateScoreLine.tsx')))
const render = candidate => renderToStaticMarkup(React.createElement(CandidateScoreLine, { candidate }))

const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}

const zero = render({ trim_score: 0, add_score: 0, confidence: 0.5, degradation: { thesis_status: 'triggered' } })
const missing = render({ add_score: 42, confidence: 0.7 })
const real = render({ trim_score: 12.34, add_score: 87.5, confidence: 0.623 })

check('a real trim score of 0 is rendered, not dropped', () => {
  assert.match(zero, />Trim score 0</)
  assert.match(zero, /data-score="trim" data-score-state="zero"/)
})
check('a real add score of 0 is rendered, not dropped', () => {
  assert.match(zero, />Add score 0</)
  assert.match(zero, /data-score="add" data-score-state="zero"/)
})
check('the stop-driven note accompanies the zero instead of replacing it', () => {
  assert.match(zero, /data-score-note="stop-driven"/)
  assert.match(zero, />stop-driven</)
  assert.match(zero, />Trim score 0</)
})
check('a missing score says unavailable and carries its reason', () => {
  assert.match(missing, />Trim score unavailable</)
  assert.match(missing, /data-score-state="unavailable"/)
  assert.match(missing, /Trim score unavailable — trim_score was not returned as a number by the engine/)
  assert.doesNotMatch(missing, /data-score-note="stop-driven"/)
})
check('an unknown trim is never painted as a zero', () => {
  assert.doesNotMatch(missing, />Trim score 0</)
  assert.doesNotMatch(missing, /data-score="trim" data-score-state="zero"/)
})
check('labels say "score", values pass through, and confidence states its 0–1 scale', () => {
  assert.match(real, />Trim score 12.34</)
  assert.match(real, />Add score 87.5</)
  assert.match(real, />Confidence 0.623</)
  assert.match(real, /0–1 engine confidence/)
  assert.match(real, /0–100 engine score/)
  assert.doesNotMatch(real, />trim 12\.34<|>add 87\.5<|>conf 0\.623</)
})
check('a score never claims a share or sizing meaning', () => {
  assert.match(real, /not a share quantity, weight or order/)
  assert.doesNotMatch(real, /shares/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)
