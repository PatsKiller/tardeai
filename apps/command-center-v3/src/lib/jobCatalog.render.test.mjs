// node src/lib/jobCatalog.render.test.mjs
// Ops › Jobs & n8n tappable status tiles + described job cards + Job catalog cards (operator 2026-11-06). RENDERS the
// real components and asserts: 44 px toggle tiles that filter and show the active one, readable titles, "what it does"
// / "if it fails" lines or "No description yet", a status mix per category, no write button. Synthetic fixtures only.
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

const { TileGrid, N8nLanesTab } = await import(compile(join(app, 'src/components/JobsN8nViews.tsx')))
const { JobCard, CategoryCard, JobDescription } = await import(compile(join(app, 'src/components/JobCatalogViews.tsx')))
const { historyTiles, n8nTiles } = await import(compile(join(app, 'src/lib/jobsN8n.ts')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const h = (el, url = '/ops/jobs-n8n') => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [url] }, el))
const flat = s => s.replace(/\s/g, '')

// 1. Status tiles are tappable 44 px toggles; the active one is pressed and ticked.
const summary = { jobs: 9, active: 9, failed: 2, with_missed: 1, late: 0, ok: 4, ok_unverified: 1, fixed_14d: 3, missed_not_measured: 0, no_run_history: 0 }
const tiles = h(React.createElement(TileGrid, { tiles: historyTiles(summary, 'needs'), label: 'x', active: 'failed', onPick: () => {} }))
check((tiles.match(/<button/g) || []).length === 6, 'six tile buttons')
check((tiles.match(/aria-pressed="true"/g) || []).length === 1 && /data-status="failed" aria-pressed="true"/.test(tiles), 'only Failed is pressed')
check((flat(tiles).match(/min-height:44px/g) || []).length === 6, 'every tile is a 44 px target')
check(tiles.includes('✓ <!-- -->Failed') || tiles.includes('✓ Failed'), 'active tile is ticked')
check(tiles.includes('tap to clear') && tiles.includes('tap to filter the list'), 'tiles say what a tap does')
const still = h(React.createElement(TileGrid, { tiles: n8nTiles(null, []), label: 'x' }))
check(!/<button/.test(still), 'without onPick the tiles stay plain (other pages unchanged)')

// 2. n8n lanes tab: ?status= filters the cards to that tile and shows a clear bar.
const lane = (id, extra) => ({ lane_id: id, on_live_list: true, stage: 'canary', mode: 'live', workflow: 'wf-synthetic', ...extra })
const rows = [
  lane('synthetic-ok', { outcome: { effective_mode: 'live', health: 'OK', failures_24h: 0, failures_7d: 0 } }),
  lane('synthetic-failing', { outcome: { effective_mode: 'live', health: 'FAILING', health_reason: 'last run failed (exit 1)', failures_24h: 1, failures_7d: 1 } }),
  lane('synthetic-shadow', { stage: 'shadow', outcome: { effective_mode: 'dry_run', health: 'OK', failures_24h: 0, failures_7d: 0 } }),
]
const state = { as_of: '2026-01-07T15:00:00Z', n8n: { state: 'OK', rows, outcomes_as_of: '2026-01-07T15:00:00Z' } }
const all = h(React.createElement(N8nLanesTab, { state, loading: false, error: null }), '/ops/jobs-n8n?tab=n8n')
check((all.match(/data-testid="jobs-n8n-lane"/g) || []).length === 3 && !all.includes('jobs-n8n-status-filter'), 'no status: every lane')
const failing = h(React.createElement(N8nLanesTab, { state, loading: false, error: null }), '/ops/jobs-n8n?tab=n8n&status=live_failing')
check((failing.match(/data-testid="jobs-n8n-lane"/g) || []).length === 1 && failing.includes('synthetic-failing'), '?status=live_failing shows only the failing lane')
check(failing.includes('data-testid="jobs-n8n-status-filter"') && failing.includes('Clear filter'), 'clear bar shown')
check(/data-status="live_failing" aria-pressed="true"/.test(failing), 'Live, failing tile is pressed')
const bogus = h(React.createElement(N8nLanesTab, { state, loading: false, error: null }), '/ops/jobs-n8n?tab=n8n&status=nope')
check((bogus.match(/data-testid="jobs-n8n-lane"/g) || []).length === 3, 'unknown ?status= is ignored, not an empty list')
check(!/>(Run|Retry|Pause|Add to live list|Remove from live list)</.test(failing), 'still no write button')

// 3. Described job card: readable title, two lines; undescribed says so.
const base = { lane_id: 'synthetic-ask-lifecycle', job: 'Synthetic ask lifecycle', scheduler: 'n8n', state: 'ACTIVE', status: 'failed',
  status_reason: 'Exit code 1', cadence: { expressions: ['*/30 * * * *'], timezone: 'America/New_York', every_hours: null, market_days_only: false },
  last_run: null, last_success_at: null, missed_count: 0, missed_gap: null, fix_count: 0, last_fix: null, history_sources: ['n8n run ledger'], history_gap: null }
const described = { ...base, title: 'Synthetic question tracker', category: 'cio', category_key: 'cio', does: 'Moves synthetic questions to answered.', breaks: 'Synthetic answers stop appearing.' }
const cats = [{ key: 'cio', label: 'CIO & advice', blurb: '' }, { key: 'ops', label: 'Ops, health & self-heal', blurb: '' }]
const card = h(React.createElement(JobCard, { row: described, computedAt: '2026-01-07T15:00:00Z', categories: cats, href: '/ops/jobs-n8n?tab=all&history=synthetic-ask-lifecycle' }))
check(card.includes('data-testid="job-title">Synthetic question tracker<'), 'title replaces the generated name')
check(card.includes('synthetic-ask-lifecycle'), 'lane id kept as a small reference')
check(card.includes('Moves synthetic questions to answered.') && card.includes('What it does') && card.includes('Synthetic answers stop appearing.') && card.includes('If it fails'), 'two description lines')
check(/href="\/ops\/jobs-n8n\?tab=all&amp;history=synthetic-ask-lifecycle"/.test(card), 'links into Jobs & n8n run history')
const bare = h(React.createElement(JobCard, { row: { ...base, category_fallback: 'ops', category_key: 'ops' }, computedAt: '2026-01-07T15:00:00Z', categories: cats, onOpen: () => {} }))
check(bare.includes('data-testid="job-title">Synthetic ask lifecycle<') && bare.includes('No description yet') && bare.includes('Ops, health &amp; self-heal'), 'undescribed: generated name, "No description yet", owner category')
check(!/>(Run|Retry|Pause)</.test(card + bare), 'no write button on a job card')
const desc = h(React.createElement(JobDescription, { row: { does: null, breaks: null, category: null } }))
check(desc.includes('No description yet'), 'missing description stated')

// 4. Category card: tappable, count, blurb, status mix.
const cat = { key: 'cio', label: 'CIO & advice', blurb: 'Synthetic verdicts.', jobs: 55, described: 50, with_missed: 0, fixed_14d: 1,
  status_mix: { failed: 3, missed: 0, late: 0, running: 0, ok: 40, ok_unverified: 0, not_measured: 12, inactive: 0 } }
const cc = h(React.createElement(CategoryCard, { cat, onOpen: () => {} }))
check(/^<button/.test(cc) && /min-height:44px/.test(flat(cc)), 'category card is a 44 px button')
check(cc.includes('CIO &amp; advice') && cc.includes('Synthetic verdicts.') && cc.includes('>55<'), 'name, blurb, count')
check(cc.includes('3 failed · 40 ok · 12 not measured') && cc.includes('50 of 55 described'), 'status mix and described count')

if (failed) { console.error(`jobCatalog.render: ${failed} failed`); process.exit(1) }
console.log('jobCatalog.render: all checks passed')
