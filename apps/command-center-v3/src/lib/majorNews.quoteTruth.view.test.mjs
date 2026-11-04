// FQ-090 (HQ-06) — Major News: a missing day percent is not +0.00%, and the grid says what its clock is.
//
// Live at release 105df180e, /api/v2/portfolio/book-map returned 4 of 27 rows with `day_change_pct: null` (NVDA among
// them) and a top-level `as_of` of "2026-11-04" — a date, not an intraday quote time. The grid printed every null as a
// green "+0.00%", sorted it among the movers, and showed no clock at all.
//
// Red-first: the null-percent and as-of controls fail against the parent component; the reported-value control is
// green on both sides by design.
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
  let source = readFileSync(path, 'utf8').replace(
    /import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__bookFixture(String(_args[0] ?? \'\'))',
  )
  let js = ts.transpileModule(source, {
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

function readingText(markup) {
  return markup.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/\s+/g, ' ').trim()
}

const book = {
  ok: true, as_of: '2026-11-04',
  rows: [
    { symbol: 'SPCX', account: 'a', value: 27578, day_change: 500, day_change_pct: 1.85, stop: 10 },
    { symbol: 'NVDA', account: 'a', value: 9000, day_change: 0, day_change_pct: null, stop: 100 },
    { symbol: 'SCHD', account: 'a', value: 60000, day_change: -120, day_change_pct: -0.2, stop: 20 },
  ],
}

function render(b = book, extra = {}) {
  globalThis.__bookFixture = (url) => {
    if (String(url).includes('book-map')) return { data: b, loading: false, error: null }
    if (String(url).includes('headline-counts')) return { data: { counts: {} }, loading: false, error: null }
    return { data: extra.news ?? null, loading: false, error: null }
  }
  return renderToStaticMarkup(React.createElement(Grid))
}

const { default: Grid } = await import(compile(join(app, 'src/components/home/MajorNewsGrid.tsx')))

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('a missing day percent is not rendered as a number', () => {
  const t = readingText(render())
  assert.doesNotMatch(t, /NVDA\s*\+0\.00%/, 'a null day percent still prints +0.00%')
  const cell = (render().match(/data-day-pct="[^"]*"[^>]*>[^<]*</g) || []).join(' ')
  assert.match(cell, /data-day-pct="not-reported"/, cell)
})

check('a reported day percent is unchanged', () => {
  const t = readingText(render())
  assert.match(t, /SPCX\s*\+1\.85%/)
  assert.match(t, /SCHD\s*-0\.20%/)
})

check('unknown movers sort after the known ones', () => {
  const t = readingText(render())
  assert.ok(t.indexOf('SPCX') < t.indexOf('NVDA'), 'a null-percent row sorted among real movers')
})

check('the grid states its clock, and a date-only as_of is called what it is', () => {
  const t = readingText(render())
  assert.match(t, /as of 2026-11-04/)
  assert.match(t, /no intraday quote time/)
})

check('a payload with no as_of says so instead of showing nothing', () => {
  const t = readingText(render({ ...book, as_of: undefined }))
  assert.match(t, /quote time not reported/)
})

check('the modal refuses to invent a percent too', () => {
  const markup = render()
  const modal = (markup.match(/data-day-pct="not-reported"[^>]*>[^<]*</) || [''])[0]
  assert.ok(modal.length > 0)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
