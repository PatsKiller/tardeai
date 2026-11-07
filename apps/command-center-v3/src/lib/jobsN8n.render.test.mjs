// node src/lib/jobsN8n.render.test.mjs
// Ops › Jobs & n8n (design pages/jobs v002, operator-approved 2026-11-06). RENDERS the real lane card, lane detail, n8n
// tab and incident card and asserts what the operator sees: plain-words why, no invented zeros, 44 px targets, a
// full-screen sheet, no write button, a link to the switches in Ops Controls. Synthetic fixtures only.
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
const { TileGrid, LaneCardView, LaneDetail, IncidentCardView, N8nLanesTab } = await import(compile(join(app, 'src/components/JobsN8nViews.tsx')))
const { laneCard, n8nTiles } = await import(compile(join(app, 'src/lib/jobsN8n.ts')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const h = (el, url = '/ops/jobs-n8n?tab=n8n') => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [url] }, el))
const noop = () => {}
const NOW = Date.parse('2026-01-07T15:00:00Z')

// Synthetic lanes only.
const failing = { lane_id: 'synthetic-failing', on_live_list: true, stage: 'canary', mode: 'live', workflow: 'wf-synthetic',
  outcome: { effective_mode: 'live', health: 'FAILING', health_reason: 'last run failed (exit 1)', failures_24h: 2, failures_7d: 3,
    last_run: { outcome: 'FAILED', mode: 'live', at: '2026-01-07T14:40:00Z' }, runs_7d: { live: 10, dry_run: 0 } } }
const excluded = { lane_id: 'synthetic-excluded', on_live_list: false, stage: 'canary', live_exclusion: 'NO_WRAPPER',
  live_exclusion_text: 'needs the effect-claim wrapper', outcome: { effective_mode: 'dry_run', health: 'OK' } }
const cut = { lane_id: 'synthetic-cutover', on_live_list: true, stage: 'cutover', outcome: { effective_mode: 'live', health: 'OK' } }

// Tiles: a null value renders a dash, never 0.
const tiles = h(React.createElement(TileGrid, { tiles: n8nTiles(null, []), label: 'x' }))
check((tiles.match(/data-testid="jobs-n8n-tile"/g) || []).length === 6, 'six n8n tiles')
check(!/>0</.test(tiles) && tiles.includes('—'), 'unknown tile shows a dash, not 0')

// Lane card: the why in words, a 44 px button, no write control.
const card = h(React.createElement(LaneCardView, { card: laneCard(excluded, NOW), onOpen: noop }))
check(card.includes('Not on the live list: needs the effect-claim wrapper'), 'exclusion why in words')
check(card.includes('Not live'), 'live-list chip')
check(/min-height:44px/.test(card), '44 px tap target on the card button')
const fcard = h(React.createElement(LaneCardView, { card: laneCard(failing, NOW), onOpen: noop }))
check(fcard.includes('last run failed (exit 1)') && fcard.includes('Failing'), 'failing lane quotes the health reason')
check(fcard.includes('20 min ago'), 'last run relative time')

// Detail.
const detail = h(React.createElement(LaneDetail, { row: failing, card: laneCard(failing, NOW) }))
check(detail.includes('10 live · 0 dry run'), 'runs over 7 days')
check(detail.includes('2 in 24 h · 3 in 7 d'), 'failures')
check(detail.includes('workflow wf-synthetic'), 'registry facts')
check(detail.includes('This server does not report promotion readiness'), 'absent readiness said, not invented')

// Whole tab from a synthetic controls state: tiles, move sentence, cards, link to the switches, no action buttons.
const state = { as_of: '2026-01-07T15:00:00Z', n8n: { state: 'OK', rows: [failing, excluded, cut], outcomes_as_of: '2026-01-07T15:00:00Z',
  summary: { live_healthy: 1, live_failing: 1, rehearsing: 1, ready_to_promote: 0, never_ran: 0 } } }
const tab = h(React.createElement(N8nLanesTab, { state, loading: false, error: null }))
check((tab.match(/data-testid="jobs-n8n-lane"/g) || []).length === 3, 'three lane cards')
check(tab.indexOf('synthetic-failing') < tab.indexOf('synthetic-cutover'), 'failing lane listed first')
check(tab.includes('Move to n8n: 2 of 3 lanes run for real through n8n; 1 rehearse (dry run)'), 'move-to-n8n sentence')
check(/href="\/system\/ops-controls\?tab=n8n"/.test(tab), 'switches link to Ops Controls')
check(!/>(Run|Retry|Pause|Add to live list|Remove from live list)</.test(tab), 'no write button on the page')
check(!/<table/.test(tab), 'no table (phone-first cards)')
check(!tab.includes('jobs-n8n-lane-sheet'), 'no sheet until a lane is opened')
const opened = h(React.createElement(N8nLanesTab, { state, loading: false, error: null }), '/ops/jobs-n8n?tab=n8n&lane=synthetic-excluded')
check(opened.includes('data-testid="jobs-n8n-lane-sheet"') && opened.includes('role="dialog"') && opened.includes('aria-modal="true"'), 'lane opens a full-screen dialog sheet')
check(/position:fixed;inset:0/.test(opened.replace(/\s/g, '')), 'sheet is full screen')
const empty = h(React.createElement(N8nLanesTab, { state: null, loading: false, error: 'HTTP 503' }))
check(empty.includes('n8n lanes could not be read: HTTP 503') && empty.includes('No n8n lane is reported.'), 'read failure stated')

// Incident card links to the Incidents page detail, where Acknowledge / Close live.
const inc = { schema: 'Incident@v1', id: 'INC-synthetic-1', opened_at: '2026-01-07T13:00:00Z', updated_at: '2026-01-07T14:00:00Z', status: 'fixing',
  source: { kind: 'watcher', watcher: 'synthetic-watcher' }, title: 'Synthetic lane missed two runs', severity: 'P2', evidence: [], attempts: [], fix_refs: [] }
const icard = h(React.createElement(IncidentCardView, { inc, nowMs: NOW }))
check(icard.includes('Synthetic lane missed two runs'), 'incident headline')
check(/href="\/ops\/incidents\?detail=INC-synthetic-1"/.test(icard), 'opens in Incidents')
check(!/<button/.test(icard), 'no action button on the incident card')

if (failed) { console.error(`jobsN8n.render: ${failed} failed`); process.exit(1) }
console.log('jobsN8n.render: all checks passed')
