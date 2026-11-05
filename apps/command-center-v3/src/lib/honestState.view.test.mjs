// Honest-state delivery test (BOARD row 36). Renders the REAL pages with a stubbed fetch hook and asserts the
// "must never say" columns of SurfaceState@v1 against what the page actually prints.
//
// BEFORE the contract this file fails twice — /agents prints "Agents unavailable" beside "Loading the desk
// projection.", and /approvals prints "Loading the latest queue." beside "Queue unavailable". AFTER it, every case
// below passes. That before/after is the point: a passing test that never failed is not evidence.
//
// No live server, no network, no portfolio values: synthetic rows only.
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
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
    // Stylesheets are a build-time concern for an SSR harness.
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
    // The two fetch hooks become the fixture; every other export of the same module is kept.
    .replace(/import \{([^}]*)\} from (['"][^'"]+['"])/g, (whole, names, spec) => {
      const list = names.split(',').map(s => s.trim()).filter(Boolean)
      const kept = list.filter(n => n !== 'useApi' && n !== 'useGovernance')
      const stubs = []
      if (list.includes('useApi')) stubs.push('const useApi = (..._a: any[]): any => (globalThis as any).__deskFixture')
      if (list.includes('useGovernance')) stubs.push('const useGovernance = (...a: any[]): any => (globalThis as any).__govFixture(...a)')
      const imp = kept.length ? `import { ${kept.join(', ')} } from ${spec}` : ''
      return [imp, ...stubs].filter(Boolean).join('\n')
    })
  // `.ts` is transpiled WITHOUT JSX: `jsx: ReactJSX` makes a generic arrow (`<R>(x: R) => ...`) parse as a JSX tag.
  const jsx = path.endsWith('.tsx') ? ts.JsxEmit.ReactJSX : ts.JsxEmit.None
  let js = ts.transpileModule(source, { compilerOptions: { jsx, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, removeComments: true } }).outputText
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

const render = el => renderToStaticMarkup(React.createElement(MemoryRouter, null, el))
  .replace(/<[^>]+>/g, ' ')
  .replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<')
  .replace(/\s+/g, ' ').trim()

const { default: DeskBoard } = await import(compile(join(app, 'src/components/DeskBoard.tsx')))
const { default: ApprovalsHub } = await import(compile(join(app, 'src/pages/ApprovalsHub.tsx')))

// ── fixtures: synthetic only ─────────────────────────────────────────────────────────────────────
const projection = {
  ok: true, desk: 'agents', as_of: '2030-01-01T00:00:00Z',
  sources: [{ id: 'projection', label: 'Agents projection', as_of: '2030-01-01T00:00:00Z', lane_ids: ['fixture-lane'], max_age_hours: 26 }],
  decisions: [], decision_gap: null,
  tabs: { runtime: { panels: [{ id: 'p', title: 'Panel', rows: [{ id: 'r', label: 'Fixture row', value: 'OK' }] }] } },
}
const deskConfig = { desk: 'agents', title: 'Agents', purpose: 'Fixture purpose.', tabs: [{ id: 'runtime', label: 'Runtime' }],
  classicHref: '/agents/classic', testId: 'agents' }
const queue = {
  items: [{ id: 'fixture-1', kind: 'POLICY', title: 'Fixture item', version: null, proposed_by: 'fixture', created_at: '2030-01-01T00:00:00Z' }],
  pending_count: 1, known_pending_count: 1, complete: true, gaps: [], as_of: '2030-01-01T00:00:00Z', recent: [], filtered_count: 1, offset: 0,
}
const queuePartial = { ...queue, pending_count: null, known_pending_count: 1, complete: false, gaps: [{ source: 'releases', reason: 'did not answer' }] }
// A desk projection whose envelope says one source did not answer, with no decisions and an empty tab: this is the
// shape where a renderer that defaults to "No open decisions on file" / "No rows on file" claims completeness it
// does not have (reviewer F1, 2026-11-04).
const projectionPartial = {
  ...projection,
  errors: ['releases did not answer'],
  decisions: [], decision_gap: null,
  tabs: { runtime: { panels: [{ id: 'p', title: 'Panel', rows: [], empty: null }] } },
}

// Vocabulary that must never appear together.
const LOADING = /\bLoading\b|has not answered/i
const FAILED = /\bunavailable\b|could not be read/i

const cases = []
function caseOf(surface, state, text, assertions) {
  const failures = []
  for (const [name, ok] of assertions) if (!ok) failures.push(name)
  cases.push({ surface, state, passed: failures.length === 0, failed_assertions: failures, text: text.slice(0, 320) })
}

// /agents
for (const [state, fixture] of Object.entries({
  loading: { data: null, error: null, loading: true, refetch() {} },
  error: { data: null, error: 'HTTP 503 from the desk projection', loading: false, refetch() {} },
  ready: { data: projection, error: null, loading: false, refetch() {} },
  partial: { data: projectionPartial, error: null, loading: false, refetch() {} },
  stale: { data: projection, error: 'refetch failed', loading: false, stale: true, refetch() {} },
})) {
  globalThis.__deskFixture = fixture
  let text = ''
  try { text = render(React.createElement(DeskBoard, deskConfig)) } catch (e) {
    cases.push({ surface: '/agents', state, passed: false, failed_assertions: [`rendering threw: ${e.name}: ${e.message}`], text: '' })
    continue
  }
  caseOf('/agents', state, text, [
    ['loading and failure words never co-render', !(LOADING.test(text) && FAILED.test(text))],
    state === 'loading' ? ['a loading page says loading', /Loading/i.test(text)] : ['no loading claim', true],
    state === 'error' ? ['a failed page says unavailable exactly as a failure', /unavailable/i.test(text)] : ['no failure claim', !/Agents unavailable/i.test(text)],
    (state === 'ready' || state === 'stale') ? ['a page with data renders its rows', /Fixture row/.test(text)] : ['no rows before data', !/Fixture row/.test(text)],
    // F1: while the envelope says sources are missing, the renderer may not print a complete-looking line.
    state === 'partial' ? ['partial never claims "No open decisions on file"', !/No open decisions on file/i.test(text)] : ['no false empty claim', true],
    state === 'partial' ? ['partial never claims "No rows on file"', !/No rows on file/i.test(text)] : ['no false panel empty', true],
    state === 'partial' ? ['partial says a source did not answer', /did not answer/i.test(text)] : ['no gap claim', true],
    state === 'partial' ? ['partial says the list is not complete', /not complete/i.test(text)] : ['no completeness claim', true],
    // F2 retained-data path: last-good data must be labelled, never shown as current.
    state === 'stale' ? ['a stale page labels the retained data', /last good/i.test(text)] : ['no stale label when not stale', true],
    state === 'stale' ? ['a stale page still renders its rows', /Fixture row/.test(text)] : ['rows only when expected', true],
  ])
}

// /approvals
for (const [state, fixture] of Object.entries({
  loading: { data: null, error: null, refresh() {} },
  error: { data: null, error: 'The latest evidence is unavailable. Please try again.', refresh() {} },
  partial: { data: { ...queuePartial }, error: null, refresh() {} },
  ready: { data: queue, error: null, refresh() {} },
  malformed: { data: { items: 'not-a-list', gaps: 'nope' }, error: null, loading: false, refresh() {} },
})) {
  globalThis.__govFixture = () => fixture
  let text = ''
  try { text = render(React.createElement(ApprovalsHub)) } catch (e) {
    cases.push({ surface: '/approvals', state, passed: false, failed_assertions: [`rendering threw: ${e.name}: ${e.message}`], text: '' })
    continue
  }
  caseOf('/approvals', state, text, [
    ['loading and failure words never co-render', !(LOADING.test(text) && FAILED.test(text))],
    state === 'error' ? ['a failed page says unavailable', /unavailable/i.test(text)] : ['no failure claim', !/Queue unavailable/i.test(text)],
    state === 'partial' ? ['a partial page shows its known rows', /Fixture item/.test(text)] : ['no partial rows', true],
    state === 'partial' ? ['a partial page never shows a complete-looking total', !/\b1 waiting for review\b/.test(text)] : ['no complete total', true],
    state === 'partial' ? ['a partial page says the total is unknown', /not yet known|unavailable/i.test(text)] : ['no total claim', true],
    // F3: a malformed payload renders as unreadable; it must not throw (the render call above would have thrown).
    state === 'malformed' ? ['a malformed payload says it could not be read', /could not be read/i.test(text)] : ['no unreadable claim', true],
    state === 'malformed' ? ['a malformed payload never claims a complete total', !/\b1 waiting for review\b/.test(text)] : ['no total from nothing', true],
  ])
}

// Cloud review 2026-11-05 (P1): the shell's surface publisher must keep ONE identity across report updates. Every mounted
// surface publishes from an effect whose dependencies include `publish`; when publish was recreated per render, publishing
// caused a render that produced a new publish, which re-ran every effect, which published again — a loop that never settled.
// This repo has no effect-capable renderer (no jsdom, no react-test-renderer), so the guard is structural and names the exact
// wiring that removes the loop rather than pretending to exercise it. It lives here, in the .mjs harness, because a
// `node:fs` import inside a typechecked .ts test fails the build (caught by tsc during the 2026-11-05 merge-up).
const surfaceGapSrc = readFileSync(new URL('../components/SurfaceGap.tsx', import.meta.url), 'utf8')
const appSrc = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8')
const hookBlock = surfaceGapSrc.slice(surfaceGapSrc.indexOf('const publish = useCallback('), surfaceGapSrc.indexOf('return useMemo('))
const channelChecks = [
  ['channel publishes with useCallback and an empty dependency list', hookBlock.includes('useCallback(') && /\[\s*\]\s*,?\s*\)/.test(hookBlock)],
  ['channel value is memoised on the report and the stable publish', surfaceGapSrc.includes('return useMemo(() => ({ report, publish }), [report, publish])')],
  ['shell takes the channel from the hook, never an inline publish', appSrc.includes('const surfaceChannel = useSurfaceChannel()') && !appSrc.includes('publish: (next')],
]
for (const [name, ok] of channelChecks) if (!ok) cases.push({ surface: 'shell', state: 'channel', passed: false, failed_assertions: [name], text: '' })
const out = { schema: 'HonestStateView@v1', channel_checks: channelChecks.map(([n]) => n), cases,  passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) {
  for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.surface}/${c.state}: ${c.failed_assertions.join('; ')} :: ${c.text}`)
}
process.exitCode = out.failed ? 1 : 0
