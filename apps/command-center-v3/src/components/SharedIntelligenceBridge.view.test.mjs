// FQ-138: the Re-Entry stop count must name what it measures. The number is an event saved or INFERRED as stopped out
// (`normalizedEvent` prefers a saved event and otherwise matches a regex over action/description/event_status/
// completion_status/operator_status) — it is not a broker confirmation. #2514 replaced the previous tooltip, which carried
// that qualifier, with a count-comparison sentence that dropped it. This renders the real component and asserts the
// qualifier is back, so the wording cannot be quietly removed again.
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
  const source = readFileSync(path, 'utf8')
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

const mod = await import(compile(join(app, 'src/components/SharedIntelligenceBridge.tsx')))
const markup = renderToStaticMarkup(React.createElement(mod.ReentryContextCounts, {
  classified: 3, stopped: 7, resistanceMissing: 1, cacheLine: '2026-11-05 02:30',
}))
const tooltip = (markup.match(/title="([^"]*saved or inferred[^"]*)"/) || [])[1] || ''
const results = []
const check = (name, fn) => { try { fn(); results.push({ name, passed: true }) } catch (e) { results.push({ name, passed: false, assertion: String(e.message).split('\n')[0] }) } }

check('the stop count renders its number and label', () => {
  assert.match(markup, />7 latest exit a stop-out</)
})
check('the tooltip says the event was saved or inferred', () => {
  assert.match(tooltip, /saved or inferred as stopped out/)
})
check('the tooltip says it is not a broker confirmation', () => {
  assert.match(tooltip, /Not a broker confirmation/)
})
check('the tooltip keeps the count-comparison sentence #2514 added', () => {
  assert.match(tooltip, /market-risk re-entry watch/)
  assert.match(tooltip, /losing round trips/)
})
check('no tooltip on this strip claims broker or confirmed authority', () => {
  assert.doesNotMatch(markup, /title="[^"]*(broker-confirmed|confirmed by the broker)[^"]*"/i)
})

const out = { file: 'SharedIntelligenceBridge.view.test.mjs', results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 2))
process.exitCode = out.failed ? 1 : 0
