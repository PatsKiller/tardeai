// OPS-C1 (operator OP-020, 2026-11-14) — the /ops Queue card names ONE failed-unit list, with its scope and
// observation time, and never prints an all-clear it cannot prove.
//
// Part A renders the component directly (green on this branch). Part B renders the real System page and asserts the
// card carries it — **deliberately red until the SystemHub.tsx hunk is applied**: that page is claimed by another
// session (cc-deepseek-5, wt/s2-rotation-redeploy), so this branch delivers the wiring as a patch instead of an edit.
// The failing-before half is the point, not an accident.
//
// The incident: the Queue card listed `hermes-deep-research-local` and missed `tradeai-deploy-on-main` while the
// Platform card listed the tradeai units. After the change both read one snapshot.
import assert from 'node:assert/strict'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

// The server renderer emits one `useLayoutEffect does nothing on the server` warning per component. Same filter as
// retirement.metric.view.test.mjs and riskDeskSourceNote.view.test.mjs — unfiltered it stalls CI job logs.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

if (typeof globalThis.window === 'undefined') {
  globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) }
}

function isFile(path) {
  try {
    return statSync(path).isFile()
  } catch {
    return false
  }
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
    .replace(
      /import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__qctFixture',
    )
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!isFile(target)) target = ['.ts', '.tsx', '.js'].map((s) => target + s).find(isFile)
    if (!target) target = ['.ts', '.tsx', '.js'].map((s) => resolve(dirname(path), spec, 'index' + s)).find(isFile)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { QueueFailedUnitsNote } = await import(compile(join(app, 'src/components/QueueFailedUnitsNote.tsx')))
const { default: SystemHub } = await import(compile(join(app, 'src/pages/SystemHub.tsx')))

const AS_OF = '2026-11-14T20:05:58.424203Z'
const SCOPE = 'systemctl --user list-units --state=failed --all — every user unit, no pattern'
const SOURCE = 'systemctl --user list-units --all --state=failed --no-legend --plain --no-pager'
const ANSWERED = { units: [{ unit: 'tradeai-deploy-on-main.service' }], count: 1, outside_count: 0, scope: SCOPE, source: SOURCE, as_of: AS_OF, answered: true, reason: null }
const UNKNOWN = { units: [], count: 0, outside_count: 0, scope: null, source: SOURCE, as_of: AS_OF, answered: false, reason: 'systemctl timed out after 2 s' }

const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

function renderPage(sections) {
  globalThis.__qctFixture = { data: { sections, timers_total: 0, cron_count: 0, services_running: 0, llm_jobs: 0 }, error: null, loading: false, stale: false, transport: 'OK' }
  return text(renderToStaticMarkup(
    React.createElement(MemoryRouter, { initialEntries: ['/system?tab=Queue'] }, React.createElement(SystemHub, { onDrill() {} })),
  ))
}

const fails = []
const check = (ok, message) => { if (!ok) fails.push(message) }

// ── Part A — the component (green here) ──────────────────────────────────────────────────────────────────────

const answered = text(renderToStaticMarkup(React.createElement(QueueFailedUnitsNote, { section: ANSWERED })))
check(/1 failed user unit in scope/.test(answered), `the note does not state the count: ${JSON.stringify(answered)}`)
check(/as of 2026-11-14 20:05:58Z/.test(answered), 'the note does not carry the snapshot observation time')
check(/every user unit, no pattern/.test(answered), 'the note does not state the source scope')

const unknown = text(renderToStaticMarkup(React.createElement(QueueFailedUnitsNote, { section: UNKNOWN })))
check(/Failed-unit state unknown: systemctl timed out after 2 s/.test(unknown), `an unanswerable probe must say so: ${JSON.stringify(unknown)}`)
check(/Nothing here is known to be OK/.test(unknown), 'an unanswerable probe must not read as OK')

check(renderToStaticMarkup(React.createElement(QueueFailedUnitsNote, { section: null })) === '', 'an absent section renders nothing')

// ── Part B — the page wiring (RED until the SystemHub hunk is applied) ──────────────────────────────────────

const page = renderPage({
  needs_attention: [{ job_id: 'tradeai-deploy-on-main', reason: 'service failed', unit: 'tradeai-deploy-on-main.service', source: SOURCE, as_of: AS_OF }],
  failed_units: ANSWERED,
})
check(/1 failed user unit in scope/.test(page), 'the /ops Queue page does not render the failed-unit count/scope/as_of — SystemHub.tsx hunk not applied')
check(/as of 2026-11-14 20:05:58Z/.test(page), 'the /ops Queue page does not carry the failed-unit observation time — SystemHub.tsx hunk not applied')
check(!/All systems nominal/.test(page), 'the /ops Queue page claimed an all-clear while a failed unit was listed')

const pageUnknown = renderPage({ needs_attention: [], failed_units: UNKNOWN })
check(/Failed-unit state unknown/.test(pageUnknown), 'an unanswerable probe must render as unknown on the page — SystemHub.tsx hunk not applied')
check(!/All systems nominal/.test(pageUnknown), 'the page claimed an all-clear it could not prove')
check(/Nothing here is known to be OK/.test(pageUnknown), 'the page must say nothing is known to be OK when the probe failed')

const pageAbsent = renderPage({ needs_attention: [] })
check(/All systems nominal/.test(pageAbsent), 'without the section the page keeps its previous, self-describing state')
check(!/Failed-unit state unknown/.test(pageAbsent), 'an absent section must not be rendered as an unknown probe')

if (fails.length) {
  console.error(`QueueFailedUnitsNote.view: ${fails.length} failure(s)\n  - ${fails.join('\n  - ')}`)
  process.exit(1)
}
console.log('QueueFailedUnitsNote.view: ok — the /ops Queue card carries count, scope and as_of, and UNKNOWN is never an all-clear')
