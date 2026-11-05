// FQ-077: at phone width the WHOLE filter toolbar is inside the disclosure, and nothing renders twice — proved by
// rendering the page at both widths, not by finding strings in its source.
//
// cc-deepseek-5's whole-head BLOCK on #2609 (2026-11-05T13:08Z) found the first version of this file asserting the
// arrangement that CAUSED the defect: the `<details>` was a sibling of the toolbar, so a phone got one extra collapsed
// line and then the same wall of controls under it (R1); the chips rendered twice once it opened (R2); and the tests
// could not see containment at all because they grepped the source (R3). It also read `matchMedia(...).matches` once
// during render and never updated (R4). This file renders the real page at both widths.
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

// Server rendering emits one `useLayoutEffect does nothing on the server` warning per component, and each stack line
// embeds a multi-megabyte `data:` module URL; the FQ-075 render test documents the same flood.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
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

// A controllable viewport: `matches` is read through the same matchMedia the page subscribes to.
let viewportNarrow = false
const mediaState = {
  matches: false, media: '', onchange: null,
  addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
  dispatchEvent() { return false },
}
function setViewport(narrow) {
  viewportNarrow = narrow
  mediaState.matches = narrow
  globalThis.matchMedia = () => mediaState
  globalThis.window = globalThis
  globalThis.window.matchMedia = globalThis.matchMedia
}
setViewport(false)

const { default: Unified } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))

const card = {
  symbol: 'CCC', company: 'Fixture Row Corp', street_rating: 'BUY', trade_ai_state: 'READY',
  quote_freshness: 'CURRENT', review_freshness: 'CURRENT',
  cio_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  maria_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  last: 9.5, day_change_pct: -0.2,
}
globalThis.__watchlistFixture = {
  data: { cards: [card], items: [{ card }], summary: {}, views: { top_ideas: {} }, projections: {} },
  loading: false,
  error: null,
}

function render(narrow, url = '/?view=starred') {
  setViewport(narrow)
  return renderToStaticMarkup(
    React.createElement(MemoryRouter, { initialEntries: [url] }, React.createElement(Unified)),
  )
}
const textOf = html => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')
// The element's own HTML, from its opening `<details …>` to the matching `</details>` (the page has no nested details).
function detailsHtml(html) {
  const open = html.indexOf('<details')
  if (open < 0) return null
  const close = html.indexOf('</details>', open)
  return close < 0 ? null : html.slice(open, close + '</details>'.length)
}
function countIn(haystack, needle) {
  return haystack.split(needle).length - 1
}

const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

// ── phone width ─────────────────────────────────────────────────────────────────────────────────────────────────
const phone = render(true)
const phoneText = textOf(phone)
const box = detailsHtml(phone)
ok(box !== null, 'at phone width the page renders no <details> disclosure at all')
ok(phone.includes('data-testid="filters-compact"'), 'the disclosure does not carry the filters-compact testid')
ok((box ?? '').includes('<summary'), 'the disclosure has no summary line to open it')

// R1: the CONTROLS are inside the disclosure, not merely a summary next to them.
const filterControls = [...phone.matchAll(/<select\b[^>]*\bdata-filter="([a-z_]+)"/g)].map(m => m[1])
ok(filterControls.length === 8, `rendered ${filterControls.length} data-filter controls (expected 8)`)
for (const name of filterControls) {
  ok((box ?? '').includes(`data-filter="${name}"`), `the ${name} filter renders OUTSIDE the phone disclosure`)
}
for (const label of ['Decision filters', 'Sort: watch rank', '★ Starred only', 'Held only', 'Grid', 'Table',
                     'Search symbol, company, sector']) {
  ok((box ?? '').includes(label), `"${label}" is outside the phone disclosure — the toolbar was not moved`)
}

// R2: each active chip renders exactly once.
ok(countIn(phoneText, 'view:starred') === 1,
  `the active chip "view:starred" rendered ${countIn(phoneText, 'view:starred')} times at phone width (expected once)`)

// The summary states the state of the filters.
ok(/Filters · 1 active/.test(phoneText), 'the summary does not name how many filters are active')

// ── desktop width ───────────────────────────────────────────────────────────────────────────────────────────────
const desktop = render(false)
const desktopText = textOf(desktop)
ok(!desktop.includes('data-testid="filters-compact"'),
  'desktop rendered the phone filter disclosure instead of inline filters')
ok(desktop.includes('data-filter-toolbar'), 'desktop lost the filter toolbar')
ok([...desktop.matchAll(/<select\b[^>]*\bdata-filter="/g)].length === 8, 'desktop lost filter controls')
ok(countIn(desktopText, 'view:starred') === 1, 'the active chip did not render exactly once on desktop')

if (failures.length) {
  console.error('FQ-077 FAILED:\n  - ' + failures.join('\n  - '))
  console.error('phone text: ' + phoneText.slice(0, 700))
  process.exit(1)
}
console.log('FQ-077 ok: phone puts the whole toolbar inside the disclosure, desktop keeps it inline, chips render once')
