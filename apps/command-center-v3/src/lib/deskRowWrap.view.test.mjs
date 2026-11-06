// node src/lib/deskRowWrap.view.test.mjs
//
// FQ-064 / FQ-132 (lead ruling 2026-11-05): the leaderboard a phone actually shows is the SERVER projection
// rendered by DeskPanels on /strategy — not the classic StrategyHub table at /strategy/classic. This test
// renders DeskPanels itself and asserts two things on the rendered HTML: a row the projection marks as
// carrying measured figures cannot break inside a number, and a prose row keeps its old wrapping.
//
// Mutation proof: delete the `row.nowrap` branch in DeskBoard.tsx RowBody and this file goes red.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  // A stylesheet has no runtime value; the render tree below this module never needs it.
  const source = readFileSync(path, 'utf8').replace(/^import\s+['"][^'"]+\.css['"]\s*;?$/gm, '')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
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

const { DeskPanels } = await import(compile(join(app, 'src/components/DeskBoard.tsx')))

const measured = {
  id: 'lb-core_growth_compounder', label: 'core growth compounder · win 49.4% · 158 trades', value: '+$93', tone: 'good', nowrap: true,
}
const prose = { id: 'lb-sort', label: 'Ranked by', value: 'live expectancy (avg R), then P/L, then win rate', tone: null }
const panel = { id: 'leaderboard', title: 'Leaderboard', rows: [measured, prose] }

const html = renderToStaticMarkup(React.createElement(DeskPanels, { panels: [panel], onOpen() {} }))

let pass = 0, fail = 0
const check = (name, fn) => {
  try { fn(); pass++; console.log(`  [PASS] ${name}`) } catch (e) { fail++; console.log(`  [FAIL] ${name}: ${e.message}`) }
}

/** The rendered cells, matched by attribute order-agnostic tag capture and by their visible text. */
function cellStyles() {
  const spans = [...html.matchAll(/<span([^>]*)>([\s\S]*?)<\/span>/g)].map(m => ({
    style: (/\bstyle="([^"]*)"/.exec(m[1]) || [null, ''])[1], text: m[2],
  }))
  const byText = (t) => spans.filter(s => s.text.includes(t))
  return { measuredLabel: byText('core growth compounder')[0], measuredValue: byText('+$93')[0], proseValue: byText('live expectancy')[0] }
}

check('the projection row renders with its exact text intact', () => {
  assert.match(html, /core growth compounder · win 49\.4% · 158 trades/)
  assert.match(html, /\+&#x24;93|\+\$93/)
})

check('a row carrying measured figures cannot wrap inside a number', () => {
  const { measuredLabel, measuredValue } = cellStyles()
  assert.ok(measuredLabel, 'measured label cell not rendered')
  assert.ok(measuredValue, 'measured value cell not rendered')
  for (const [name, cell] of [['label', measuredLabel], ['value', measuredValue]]) {
    assert.match(cell.style, /overflow-wrap:\s*normal/, `${name} cell still breaks anywhere: ${cell.style}`)
  }
  assert.match(measuredValue.style, /white-space:\s*nowrap/, `value cell still wraps: ${measuredValue.style}`)
})

check('a prose row keeps the wrapping it had (nothing is globally disabled)', () => {
  const { proseValue } = cellStyles()
  assert.ok(proseValue, 'prose value cell not rendered')
  assert.match(proseValue.style, /overflow-wrap:\s*anywhere/, `prose cell lost its wrapping: ${proseValue.style}`)
})

console.log(`deskRowWrap.view: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
