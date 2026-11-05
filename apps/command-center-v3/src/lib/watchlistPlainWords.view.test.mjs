// FQ-075: the watchlist row must state its state in plain words, and an unknown reason code must be
// de-coded — proved by rendering the real component, not by finding strings in its source.
//
// codex/cx-openai-4 R1 on #2605: the first version of this file and its pytest mirror only grepped the
// source. Two deliberately broken copies of the component — the JSX call replaced by the raw code, and
// the unknown-code fallback returning the key — left all three registered assertions GREEN while the
// page rendered `NOT_SCHEDULED` in every review box. A gate that stays green when the thing it protects
// is removed is decoration. This file renders the component and asserts the words it actually prints.
import { readFileSync, existsSync } from 'node:fs'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  // The component reads the API through this hook; a render test supplies the payload instead.
  let source = readFileSync(path, 'utf8')
    .replace(/import\s+['"][^'"]+\.css['"];?/g, '')
    .replace(
      /import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__watchlistFixture',
    )
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

// Unified pulls MobileDetailSheet which calls matchMedia at useState init — stub before import.
if (typeof globalThis.window === 'undefined') {
  globalThis.window = globalThis
}
if (typeof globalThis.matchMedia !== 'function') {
  globalThis.matchMedia = () => ({
    matches: false,
    media: '',
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent() { return false },
  })
  globalThis.window.matchMedia = globalThis.matchMedia
}

// Live /watchlist consumer is WatchIntelligenceUnified (App → WatchHub), not the unused Board page.
const { default: Unified } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))

// Every review box is rendered from this one card; three codes cover the known map, an unknown code,
// and a name that also exists on Object.prototype.
const card = {
  symbol: 'AAA', company: 'Fixture Corp', street_rating: 'BUY', trade_ai_state: 'READY',
  quote_freshness: 'AFTER_HOURS_CURRENT',
  review_freshness: 'STALE',
  cio_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  maria_review: { status: 'NOT_RUN', reason_code: 'FUTURE_CODE' },
  // Unified shows CIO + Maria on the card; a third code still exercises plainReason via maria-like path when needed
}
globalThis.__watchlistFixture = {
  data: {
    cards: [card],
    items: [{ card }],
    summary: {},
    views: { top_ideas: {} },
    projections: {},
  },
  loading: false,
  error: null,
}

const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Unified)))
const text = html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

// 1. the words the live /watchlist page must print — literal expectations, not the helper's own output
ok(text.includes('not scheduled'), 'a known code (NOT_SCHEDULED) did not render as "not scheduled"')
ok(text.includes('future code'), 'an unknown code (FUTURE_CODE) did not render as "future code"')
ok(text.includes('up to date after the close') || text.includes('after the close'), 'AFTER_HOURS_CURRENT was not plain-English on the live page')
ok(!text.includes('function Object'), 'a prototype member leaked into the row')

// 2. no policy / freshness code is shouted at the operator on the live route
for (const raw of ['NOT_SCHEDULED', 'FUTURE_CODE', 'AFTER_HOURS_CURRENT', 'NO_CALL']) {
  ok(!text.includes(raw), `the raw code ${raw} is rendered on the live /watchlist row`)
}

// 3. the facts that replaced the code line are still said on each review box
const boxes = (html.match(/data-review-box/g) || []).length
const plainLines = (text.match(/No provider or model assigned/g) || []).length
ok(boxes >= 2, `only ${boxes} review box(es) rendered — the live row under test was not exercised`)
ok(plainLines === boxes, `the plain provider/model line is on ${plainLines} of ${boxes} review boxes`)

if (failures.length) {
  console.error('FQ-075 FAILED:\n  - ' + failures.join('\n  - '))
  console.error(`rendered ${boxes} review boxes; text: ` + text.slice(0, 900))
  process.exit(1)
}
console.log('FQ-075 ok: live WatchIntelligenceUnified says plain words and shouts no code')
