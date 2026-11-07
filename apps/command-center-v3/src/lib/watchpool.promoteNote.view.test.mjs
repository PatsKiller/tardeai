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

const { PromoteUnavailableNote, divergenceReason, liveDivergence } = await import(compile(join(app, 'src/lib/watchpoolPromoteNote.tsx')))
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

// ── LQ-20261107-250: 'unavailable' was two facts; the sentence must name the missing side ────────────
check('a Street view with no internal direction says THAT, not that no view is attached', () => {
  const t = render({ directiveId: 42, divergence: 'unavailable', reason: 'no_internal_direction' })
  assert.match(t, /the Street view exists/)
  assert.match(t, /system's own directional read is missing/)
  assert.doesNotMatch(t, /no professional-analyst view is attached/)
  assert.match(t, /Promote still attaches it to your watchlist/)
})

check('no professional coverage keeps the coverage sentence', () => {
  const t = render({ directiveId: 42, divergence: 'unavailable', reason: 'no_professional_coverage' })
  assert.match(t, /no professional-analyst view is attached/)
  assert.doesNotMatch(t, /the Street view exists/)
})

check('coverage without a usable Street direction says so', () => {
  const t = render({ directiveId: 42, divergence: 'unavailable', reason: 'no_street_direction' })
  assert.match(t, /coverage exists for this name but no Street direction is attached/)
  assert.doesNotMatch(t, /no professional-analyst view is attached/)
})

check('an unreadable read model is named a data error, not an absence of coverage', () => {
  const t = render({ directiveId: 42, divergence: 'unavailable', reason: 'read_model_unreadable' })
  assert.match(t, /could not be read just now/)
  assert.match(t, /data error, not an absence of coverage/)
})

check('the reason is a rendered attribute, so the page can be asserted by cause', () => {
  const m = renderToStaticMarkup(React.createElement(PromoteUnavailableNote,
    { directiveId: 7, divergence: 'unavailable', reason: 'no_internal_direction' }))
  assert.match(m, /data-divergence-reason="no_internal_direction"/)
})

check('before the live map arrives nothing is asserted', () => {
  assert.equal(render({ directiveId: 42, divergence: 'unavailable', pending: true }), '')
})

check('the reason is derived from the live pill sides the API map carries', () => {
  const has = { has: true, street: 'bullish', internal: null }
  const noCoverage = { has: false, street: null, internal: null }
  const coveredNoStreet = { has: true, street: null, internal: 'bullish' }
  const aligned = { has: true, street: 'bullish', internal: 'bullish' }
  assert.equal(divergenceReason('unavailable', has), 'no_internal_direction')
  assert.equal(divergenceReason('unavailable', noCoverage), 'no_professional_coverage')
  assert.equal(divergenceReason('unavailable', coveredNoStreet), 'no_street_direction',
    'coverage without a usable consensus key is its own reason, as in the read model')
  assert.equal(divergenceReason('unavailable', aligned), null, 'only an unavailable comparison explains anything')
  assert.equal(divergenceReason('unavailable', undefined), null, 'a name with no pill invents no cause')
  assert.equal(divergenceReason('divergent', has), null)
  assert.equal(divergenceReason('unavailable', has, true), 'read_model_unreadable')
})

check('the row prefers the live pill verdict over the stored-at-insert hit value', () => {
  assert.equal(liveDivergence('unavailable', { divergence: 'aligned' }), 'aligned')
  assert.equal(liveDivergence('unavailable', undefined), 'unavailable')
  assert.equal(liveDivergence('unavailable', {}), 'unavailable')
})

const out = { results, passed: results.filter((r) => r.passed).length, failed: results.filter((r) => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
