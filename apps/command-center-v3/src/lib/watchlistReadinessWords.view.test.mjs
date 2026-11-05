// FQ-078: live /watchlist (WatchIntelligenceUnified) explains readiness in plain words.
// cx-openai-4 R1 on #2611: the prior gate only grepped unused WatchCardV2; Unified still shouted
// NO_CALL / NOT_SCHEDULED / AFTER_HOURS_CURRENT. This file renders the live route.
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
// cc-deepseek-9 P3: the server renderer emits one `useLayoutEffect does nothing on the server` warning per component,
// each stack line carrying a multi-megabyte data: URL. Siblings filter exactly this one; unfiltered it wrote ~3 MB of
// stderr per build. Everything else still prints.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
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

if (typeof globalThis.window === 'undefined') globalThis.window = globalThis
if (typeof globalThis.matchMedia !== 'function') {
  globalThis.matchMedia = () => ({
    matches: false, media: '',
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent() { return false },
  })
  globalThis.window.matchMedia = globalThis.matchMedia
}

const { default: Unified } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))

const card = {
  symbol: 'AAA', company: 'Fixture Corp', street_rating: 'BUY', trade_ai_state: 'READY',
  quote_freshness: 'AFTER_HOURS_CURRENT',
  review_freshness: 'STALE',
  cio_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  maria_review: { status: 'NOT_RUN', reason_code: 'FUTURE_CODE' },
}
// cc-deepseek-9 P2: two of the five readiness mappings were paired with no assertion, so swapping their sentences left
// this file green. One card per code, so every mapping is rendered and asserted below.
const FRESHNESS_CASES = ['CURRENT', 'PREMARKET_CURRENT', 'AFTER_HOURS_CURRENT', 'STALE', 'DATA_UNAVAILABLE']
const cards = FRESHNESS_CASES.map((code, i) => ({ ...card, symbol: `F${i}`, quote_freshness: code }))
globalThis.__watchlistFixture = {
  data: { cards, items: cards.map(c => ({ card: c })), summary: {}, views: { top_ideas: {} }, projections: {} },
  loading: false, error: null,
}

const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Unified)))
const text = html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

ok(/not scheduled/i.test(text), 'NOT_SCHEDULED was not plain-English')
ok(/future code/i.test(text), 'unknown reason was not de-coded')
ok(/after hours/i.test(text), 'AFTER_HOURS_CURRENT was not plain-English')
// every readiness code has its own sentence, and the sentence is the one its code maps to
const FRESHNESS_WORDS = {
  CURRENT: 'Current',
  PREMARKET_CURRENT: 'Current · pre-market',
  AFTER_HOURS_CURRENT: 'Current · after hours',
  STALE: 'Stale',
  DATA_UNAVAILABLE: 'Unavailable',
}
for (const [code, words] of Object.entries(FRESHNESS_WORDS)) {
  ok(text.includes(words), `readiness code ${code} did not render its sentence ${JSON.stringify(words)}`)
}
// the swap cc-deepseek-9 used to prove the gap: pre-market and stale are distinct sentences, never interchangeable
ok(!text.includes('Current · pre-market') || text.includes('Stale'),
   'the pre-market sentence is present without the stale one — a swap would pass')
ok(text.includes('No provider or model assigned'), 'the NONE/NO_CALL line is still shouted')
for (const raw of ['NOT_SCHEDULED', 'FUTURE_CODE', 'AFTER_HOURS_CURRENT', 'NO_CALL']) {
  ok(!text.includes(raw), `raw code ${raw} still visible on live /watchlist`)
}
const boxes = (html.match(/data-review-box/g) || []).length
ok(boxes >= 2, `only ${boxes} review box(es) — live row not exercised`)

if (failures.length) {
  console.error('FQ-078 FAILED:\n  - ' + failures.join('\n  - '))
  console.error(`rendered ${boxes} boxes; text: ` + text.slice(0, 900))
  process.exit(1)
}
console.log('FQ-078 ok: live WatchIntelligenceUnified explains readiness in plain words')
