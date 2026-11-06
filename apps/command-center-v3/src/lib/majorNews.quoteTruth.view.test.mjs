// FQ-090: actual Major News rendering, using newly constructed invented rows only.
// Missing percentages, retained reads, modal text and dollar tooltips are exercised independently.
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
    { symbol: 'ZZPOS', account: 'fixture_alpha', value: 3, day_change: 1, day_change_pct: 1.5, stop: 1 },
    { symbol: 'ZZMISS', account: 'fixture_alpha', value: 1, day_change: 0, day_change_pct: null, stop: 1 },
    { symbol: 'ZZNEG', account: 'fixture_alpha', value: 6, day_change: -1, day_change_pct: -0.75, stop: 1 },
  ],
}

function render(b = book, extra = {}) {
  globalThis.__bookFixture = (url) => {
    // extra.book lets a case say what the read's transport state was (fresh vs retained-after-failure).
    if (String(url).includes('book-map')) return { data: b, loading: false, error: null, ...(extra.book || {}) }
    if (String(url).includes('headline-counts')) return { data: { counts: {} }, loading: false, error: null }
    return { data: extra.news ?? null, loading: false, error: null }
  }
  return renderToStaticMarkup(React.createElement(Grid))
}

const { default: Grid, MajorNewsModalBody } = await import(compile(join(app, 'src/components/home/MajorNewsGrid.tsx')))

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('a missing day percent is not rendered as a number', () => {
  const t = readingText(render())
  assert.doesNotMatch(t, /ZZMISS\s*\+0\.00%/, 'a null day percent still prints +0.00%')
  const cell = (render().match(/data-day-pct="[^"]*"[^>]*>[^<]*</g) || []).join(' ')
  assert.match(cell, /data-day-pct="not-reported"/, cell)
})

check('a reported day percent is unchanged', () => {
  const t = readingText(render())
  assert.match(t, /ZZPOS\s*\+1\.50%/)
  assert.match(t, /ZZNEG\s*-0\.75%/)
})

check('unknown movers sort after the known ones', () => {
  const t = readingText(render())
  assert.ok(t.indexOf('ZZPOS') < t.indexOf('ZZMISS'), 'a null-percent row sorted among real movers')
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
  // The modal renders only when `sym` is set, which SSR cannot click. Render its own body
  // directly so the dash and the sentence are exercised, not the grid cell again.
  const row = book.rows.find(r => r.symbol === 'ZZMISS')
  const markup = renderToStaticMarkup(React.createElement(MajorNewsModalBody, {
    symbol: 'ZZMISS', row, news: null, ingest: null, onClose: () => {},
  }))
  const t = readingText(markup)
  assert.match(markup, /data-day-pct="not-reported"/, 'the modal did not mark the percent as not reported')
  assert.match(t, /ZZMISS\s+—/, `the modal printed a number for a missing percent: ${t}`)
  assert.match(t, /day change not reported/, 'the modal did not say the day change was not reported')
  assert.doesNotMatch(t, /\+0\.00%/, 'the modal invented +0.00%')
})

check('a retained read after a failed refresh cannot render as fresh', () => {
  const fresh = readingText(render())
  const retained = readingText(render(book, { book: { stale: true, transport: 'RETAINED', receivedAt: '2026-11-04T15:30:00Z' } }))
  assert.doesNotMatch(fresh, /quote read failed/, 'a healthy read claims its quote read failed')
  assert.match(retained, /quote read failed, showing the last good read/, 'a retained read rendered as fresh')
  assert.match(retained, /15:30:00Z/, 'the retained read did not say when the last good read arrived')
})

check('the tooltip never invents a dollar move, and never contradicts the percent', () => {
  const b = {
    ok: true, as_of: '2026-11-04',
    rows: [
      { symbol: 'ZPOS', account: 'fixture_alpha', value: 1, day_change: null, day_change_pct: 3.25, stop: 1 },
      { symbol: 'ZNEG', account: 'fixture_alpha', value: 1, day_change: null, day_change_pct: -2.5, stop: 1 },
      { symbol: 'ZOK', account: 'fixture_alpha', value: 1, day_change: 42, day_change_pct: 1.1, stop: 1 },
    ],
  }
  const titles = [...render(b).matchAll(/title="([^"]*)"/g)].map(m => m[1])
  const bySym = (s) => titles.find(t => t.startsWith(s))
  const pos = bySym('ZPOS'); const neg = bySym('ZNEG'); const ok = bySym('ZOK')
  assert.ok(pos && neg && ok, `missing tooltip(s): ${titles.join(' | ')}`)
  assert.match(pos, /\+3\.25%/, pos)
  assert.doesNotMatch(pos, /\+\$0/, `a missing dollar move became +$0: ${pos}`)
  assert.match(neg, /-2\.50%/, neg)
  assert.doesNotMatch(neg, /\+\$0/, `a stock down 2.5% got a +$0 tooltip: ${neg}`)
  assert.match(neg, /dollar move not reported/, neg)
  assert.match(ok, /\+\$42/, ok)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
