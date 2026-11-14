/**
 * RR-009 (sprint 8H-2): the Rotation summary counters were `<div onClick title=…>` with
 * cursor:pointer — no role, no keyboard path, no accessible name, no selected state, no visible
 * focus. A counter that filters the review queue is a button.
 *
 * Acceptance asserted here: a clickable tile is a real <button type="button"> carrying
 * aria-pressed (not colour-only selection), an accessible name that includes the count, its
 * visible text/label, a declared keyboard-focus outline, and no click handler anywhere without a
 * button. A tile with no queue behind it never renders a dead button.
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

const componentPath = join(app, 'src/components/rotation/SummaryFilterCard.tsx')
const { SummaryFilterCard } = await import(compile(componentPath))

const noop = () => {}
const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}

const clickable = renderToStaticMarkup(React.createElement(SummaryFilterCard, {
  label: 'Trim Review', value: 3, color: '#ef4444', onClick: noop, active: false, hint: 'Held names the engine scores for a trim review',
}))
const selected = renderToStaticMarkup(React.createElement(SummaryFilterCard, {
  label: 'Add Review', value: 0, color: '#22c55e', onClick: noop, active: true,
}))
const staticTile = renderToStaticMarkup(React.createElement(SummaryFilterCard, { label: 'Rotation Ideas', value: '—' }))

check('a filtering counter is a real button, not a clickable div', () => {
  assert.match(clickable, /<button[^>]*type="button"/)
  assert.doesNotMatch(clickable, /<div[^>]*onclick/i)
})
check('selected state is aria-pressed, so it is not conveyed by colour alone', () => {
  assert.match(clickable, /aria-pressed="false"/)
  assert.match(selected, /aria-pressed="true"/)
})
check('the accessible name carries the label and the count', () => {
  assert.match(clickable, /aria-label="Trim Review: 3/)
  assert.match(selected, /aria-label="Add Review: 0, filter on"/)
})
check('the visible layout is unchanged: count, uppercase label, caret for a filter', () => {
  assert.match(clickable, />3</)
  assert.match(clickable, /Trim Review/)
  assert.match(clickable, /▾/)
})
check('a zero count is shown, never blanked by a truthy render', () => {
  assert.match(selected, />0</)
  assert.match(selected, /Add Review/)
})
check('the hint is an explanation, not the only affordance', () => {
  assert.match(clickable, /title="Held names the engine scores for a trim review"/)
  assert.match(clickable, /Held names the engine scores for a trim review/)
})
check('a keyboard focus outline is declared for the button', () => {
  const src = readFileSync(componentPath, 'utf8')
  assert.match(src, /onFocus=\{\(\) => setFocused\(true\)\}/)
  assert.match(src, /onBlur=\{\(\) => setFocused\(false\)\}/)
  assert.match(src, /outline: focused && clickable \? `2px solid \$\{accent\}` : 'none'/)
})
check('a counter with no queue behind it is static, not a dead button', () => {
  assert.doesNotMatch(staticTile, /<button/)
  assert.match(staticTile, /data-testid="rotation-summary-card"/)
  assert.match(staticTile, /Rotation Ideas/)
  assert.doesNotMatch(staticTile, /cursor:pointer/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)
