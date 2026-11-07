// node src/lib/n8nCatalog.render.test.mjs
// Ops › Jobs & n8n › n8n catalog (LQ-20261107-150). RENDERS the real components and asserts: every chip and top stat
// carries tooltip text (data-tip + title), never a bare "dry", "not audited" for lanes with no verdict, lane taps open
// the existing ?lane= sheet, a missing count reads "—", and no write button. Synthetic fixtures only.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { pathname: '/', search: '', href: 'http://synthetic.invalid/' } }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.split('\n').map(line => {
    if (!/^\s*(import|export)\b/.test(line)) return line
    return line.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
      if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
      let target = resolve(dirname(path), spec)
      const isFile = (p) => existsSync(p) && statSync(p).isFile()
      if (!isFile(target)) target = ['.ts', '.tsx', '.js', '/index.ts', '/index.tsx'].map(s => target + s).find(isFile)
      if (!target) throw new Error(`Missing fixture dependency ${spec}`)
      return `from ${JSON.stringify(compile(target))}`
    })
  }).join('\n')
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}



const { MemoryRouter } = require('react-router-dom')
// SSR warns once per component that uses a layout effect; expected on the server and noisy in CI logs.
const __origConsoleError = console.error
console.error = (...args) => { if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return; __origConsoleError(...args) }
const { N8nCatalogView, LaneRow } = await import(compile(join(app, 'src/components/N8nCatalogViews.tsx')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const h = (el, url = '/ops/jobs-n8n?tab=catalog') => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [url] }, el))
const buttons = html => html.match(/<button[^>]*>/g) || []
const attr = (tag, name) => (tag.match(new RegExp(`${name}="([^"]*)"`)) || [])[1]

const lane = (id, extra) => ({ lane_id: id, title: `Synthetic ${id}`, does: 'does a synthetic thing', category_key: 'research', mode: 'live',
  in_relay: true, schedule: ['0 7 * * 1-5'], ...extra })
const lanes = {
  'syn-pass': lane('syn-pass', { verdict: 'PASS', verdict_class: 'pass' }),
  'syn-fail': lane('syn-fail', { mode: 'both', verdict: 'FAIL_DATA', verdict_class: 'fail', defect: 'synthetic stale values', work_item: 'LQ-20261107-999' }),
  'syn-dry': lane('syn-dry', { mode: 'dry', in_relay: false, verdict: null, verdict_class: 'not_audited', does: null }),
  'syn-unlisted': lane('syn-unlisted', { in_relay: false, verdict: 'UNVERIFIABLE', verdict_class: 'not_provable', defect: 'no live run yet' }),
}
const data = {
  schema: 'N8nCatalog@v1', computed_at: '2026-01-07T15:00:00Z',
  stats: { modes: { live: 2, both: 1, dry: 1, none: 5 }, audit: { pass: 1, fail: 1, not_provable: 1, audited: 3 } },
  categories: [
    { key: 'research', label: 'Research & intel', blurb: 'Synthetic news.', modes: { live: 2, both: 1, dry: 1, none: 0 }, lanes: Object.keys(lanes) },
    { key: 'broker', label: 'Broker', blurb: 'Synthetic broker.', modes: { live: 0, both: 0, dry: 0, none: 5 }, lanes: [] },
  ],
  lanes, relay: { source: 'test', lanes: 3, paused: [] }, audit: { state: 'ok', written_at: '2026-01-07T14:00:00Z', by: 'synthetic', rows: 3 }, notes: [],
}
const html = h(React.createElement(N8nCatalogView, { data, loading: false, error: null }))

// 1. Every chip and stat has tooltip text, on data-tip and on title (the desktop fallback).
const tips = buttons(html).filter(b => b.includes('data-tip='))
check(tips.length === 7 + 2 * 4 + 4 * 2, `7 stats + 4 mode counts per category (2) + 2 chips per lane (4) carry a tip (got ${tips.length})`)
check(tips.every(b => (attr(b, 'data-tip') || '').trim().length > 10 && attr(b, 'title') === attr(b, 'data-tip')), 'every tip is non-empty and mirrored on title')
check(buttons(html).every(b => b.includes('data-tip=') || b.includes('aria-expanded')), 'every button is a tip chip or the Show/Hide toggle')
check((html.match(/data-testid="n8n-catalog-stat"/g) || []).length === 7, 'seven top stats')

// 2. Words: Dry run spelled out; no verdict says "Not audited"; verdict tip carries defect + work item.
check(!/>\s*dry\s*</i.test(html) && html.includes('Dry run on n8n'), 'never a bare "dry"')
check(/data-lane="syn-dry"[\s\S]*?Not audited/.test(html), 'a lane with no verdict reads Not audited')
check(html.includes('Defect: synthetic stale values') && html.includes('Work item: LQ-20261107-999'), 'verdict tip carries the defect and work item')
check(!/data-lane="syn-pass"[\s\S]*?n8n-catalog-defect/.test(html.split('data-lane="syn-fail"')[0]), 'a PASS lane shows no defect line')
check(html.includes('synthetic stale values') && html.includes('No description yet'), 'failing defect shown; missing description stated')
check(/data-lane="syn-unlisted"[\s\S]*?not in the relay live list/.test(html) && !/data-lane="syn-dry"[^]*?not in the relay live list[^]*?data-lane="syn-unlisted"/.test(html), 'only the unlisted live lane is flagged off the relay list')

// 3. Lane tap opens the existing full-screen sheet; nothing writes.
check(html.includes('href="/ops/jobs-n8n?tab=n8n&amp;lane=syn-fail"'), 'lane link opens ?lane= sheet')
check(!/>(Run|Retry|Pause|Resume|Rerun)</.test(html), 'no write button')
check(html.includes('Nothing in this category is on n8n') && html.includes('All 5 jobs run on cron or systemd.'), 'empty category says so')

// 4. Missing data: every stat reads "—", never 0; a note renders.
const empty = h(React.createElement(N8nCatalogView, { data: { notes: ['No audit file yet: every lane is not audited.'] }, loading: false, error: null }))
check((empty.match(/<strong[^>]*>—<\/strong>/g) || []).length === 7, 'missing counts read —')
check(empty.includes('every lane is not audited') && empty.includes('No categories are reported.'), 'note and empty state')

// 5. A lone row renders both chips with tips.
const row = h(React.createElement(LaneRow, { lane: lanes['syn-dry'] }))
check(buttons(row).length === 2 && buttons(row).every(b => (attr(b, 'data-tip') || '').length > 10), 'lane row: two chips, both with tips')

if (failed) { console.error(`n8nCatalog.render: ${failed} failed`); process.exit(1) }
console.log('n8nCatalog.render: all checks passed')
