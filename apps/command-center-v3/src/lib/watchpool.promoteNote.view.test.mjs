// node src/lib/watchpool.promoteNote.view.test.mjs
// FQ-079 — the Promote-unavailable sentence is RENDERED with producer-shaped input, not grepped from the source.
//
// cc-deepseek-3's review of #2660 at a098e91b: the previous test asserted strings in WatchpoolHub.tsx, so it passed while
// the producer's lowercase "unavailable" never matched the uppercase literal and the audited row explained nothing. This
// renders the component with `divergence` exactly as build_pro_analyst_read_model.py writes it.
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
  let js = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map((s) => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { PromoteUnavailableNote } = await import(compile(join(app, 'src/lib/watchpoolPromoteNote.tsx')))
const text = (m) => m.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"')
  .replace(/\s+/g, ' ').trim()
const render = (props) => text(renderToStaticMarkup(React.createElement(PromoteUnavailableNote, props)))

const results = []
const check = (name, fn) => {
  try { fn(); results.push({ name, passed: true }) } catch (e) { results.push({ name, passed: false, error: e.message.split('\n')[0] }) }
}

// The audited row: a directive IS attached, the Street comparison is unavailable — producer case, lowercase.
check('the producer lowercase value renders the Street explanation', () => {
  const t = render({ directiveId: 42, divergence: 'unavailable' })
  assert.match(t, /Street comparison unavailable/)
  assert.match(t, /Promote still attaches it to your watchlist/)
  assert.doesNotMatch(t, /against your book/)
})

check('an uppercase value renders the same sentence (case cannot drift)', () => {
  assert.equal(render({ directiveId: 42, divergence: 'UNAVAILABLE' }), render({ directiveId: 42, divergence: 'unavailable' }))
})

check('a present, healthy comparison renders nothing', () => {
  for (const d of ['aligned', 'mixed', 'divergent', null, undefined]) {
    assert.equal(render({ directiveId: 42, divergence: d }), '', `divergence ${String(d)} must not explain anything`)
  }
})

check('no directive renders the missing-directive sentence, not the comparison one', () => {
  const t = render({ directiveId: null, divergence: 'unavailable' })
  assert.match(t, /no directive is attached to this suggestion/)
  assert.doesNotMatch(t, /Street comparison unavailable/)
})

check('both branches carry the same test id, so the page has one selector', () => {
  const a = renderToStaticMarkup(React.createElement(PromoteUnavailableNote, { directiveId: null }))
  const b = renderToStaticMarkup(React.createElement(PromoteUnavailableNote, { directiveId: 7, divergence: 'unavailable' }))
  assert.match(a, /data-testid="wp-promote-unavailable"/)
  assert.match(b, /data-testid="wp-promote-unavailable"/)
})

const out = { results, passed: results.filter((r) => r.passed).length, failed: results.filter((r) => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
