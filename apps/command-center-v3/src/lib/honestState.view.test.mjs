// Honest-state delivery test (BOARD row 36). Renders the REAL pages with a stubbed fetch hook and asserts the
// "must never say" columns of SurfaceState@v1 against what the page actually prints.
//
// BEFORE the contract this file fails twice — /agents prints "Agents unavailable" beside "Loading the desk
// projection.", and /approvals prints "Loading the latest queue." beside "Queue unavailable". AFTER it, every case
// below passes. That before/after is the point: a passing test that never failed is not evidence.
//
// No live server, no network, no portfolio values: synthetic rows only.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
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
      if (list.includes('useApi')) stubs.push('const useApi = (...a: any[]): any => { const f = (globalThis as any).__deskFixture; return typeof f === "function" ? f(String(a[0] ?? "")) : f }')
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
// Generate the REAL agents_payload ABI using synthetic private files and an injected DB callback. No live data,
// connection or provider. In particular, failed reads go in sources[].gap while top-level errors stays empty.
const realAgentPayloads = JSON.parse(execFileSync('python3', ['-c', String.raw`
import importlib.util, json, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
spec = importlib.util.spec_from_file_location('agents_view_fixture', Path(sys.argv[1]) / 'scripts/lib/desks_a.py')
producer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = producer
spec.loader.exec_module(producer)
root = Path(tempfile.mkdtemp(prefix='agents-view-'))
healthy = root / 'healthy'
stamp = '2030-01-01T00:00:00Z'
files = {
 'runtime/advisory_kb_lessons.jsonl': json.dumps({'ts': stamp, 'title': 'Synthetic lesson'}) + '\n',
 'cio/aif_memory.jsonl': json.dumps({'memory_id': 'synthetic', 'status': 'ACTIVE', 'created_at': stamp}) + '\n',
 'cio/aif_memory_admissions.jsonl': '', 'cio/cio_production_cases.jsonl': '', 'cio/maturity_promotions.json': '{}',
}
def write_tree(tree, omit=None):
 for name, content in files.items():
  if name == omit: continue
  path = tree / 'data' / name
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(content.encode())
 (tree / 'data/runtime/agent_runtime_journals').mkdir(parents=True)
write_tree(healthy)
panel_missing = root / 'panel-missing'
write_tree(panel_missing, 'cio/cio_production_cases.jsonl')
model_note = root / 'model-note'
write_tree(model_note)
journal = model_note / 'data/runtime/agent_runtime_journals/synthetic/run.jsonl'
journal.parent.mkdir(parents=True)
journal.write_bytes((json.dumps({'ts': stamp, 'agent_id': 'synthetic', 'run_id': 'fixture', 'job_type': 'synthetic',
                                'model_error': 'Synthetic recorded model error'}) + '\n').encode())
states = {lane: 'ACTIVE' for lanes in producer.AGENTS_LANES.values() for lane in lanes}
def query(sql, *args, **kwargs):
 if 'agent_calibration_windows' in sql: return []
 return [{'completed': 0, 'failed': 0, 'queued': 0, 'processing': 0, 'total': 0, 'n': 0, 'newest': stamp}]
def refused(*args, **kwargs):
 raise RuntimeError('synthetic DB read refused')
def payload(tree, db, lane_states):
 return producer.agents_payload(root=tree, data_root=tree, db_query=db, states=lane_states,
                               now=datetime(2030, 1, 1, tzinfo=timezone.utc))
def low_sample(sql, *args, **kwargs):
 if 'agent_calibration_windows' in sql:
  return [{'agent_name': 'synthetic', 'brier_score': 0.1, 'low_sample_size': True, 'created_at': stamp}]
 return query(sql, *args, **kwargs)
print(json.dumps({'partial': payload(healthy, refused, states), 'healthy': payload(healthy, query, states),
                  'missing': payload(root / 'missing', refused, states), 'registry': payload(healthy, query, {}),
                  'panelMissing': payload(panel_missing, query, states), 'calibrationNote': payload(healthy, low_sample, states),
                  'modelNote': payload(model_note, query, states)}))
`, resolve(app, '../..')], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } }))
assert.deepEqual(realAgentPayloads.partial.errors, [])
assert.ok(realAgentPayloads.partial.sources.some(s => s.id === 'pipeline' && s.gap === 'Agent jobs could not be read.'))
assert.equal(realAgentPayloads.healthy.sources.filter(s => s.gap).length, 1)
const projectionPartial = realAgentPayloads.partial

// Vocabulary that must never appear together.
// DeskPage fetches /api/v2/desk-sources separately from the page's own payload. The harness used to serve ONE fixture to
// every useApi call, so that fetch received the page's data and printed "Writer clocks unavailable" beside a loading
// banner — cc3's N2. The stub now routes by URL when the fixture is a function, and this supplies the source payload:
// a writer for every lane the page asks about, or a PENDING read while the page itself is still loading (so a loading
// page's sources are loading too, which is the truth at that moment).
function deskSources(url, pending) {
  if (pending) return { data: null, error: null, loading: true, stale: false, refetch() {} }
  const lanes = decodeURIComponent(String(url).split('lanes=')[1] ?? '').split(',').filter(Boolean)
  return { data: { ok: true, writers: lanes.map(lane_id => ({ lane_id, last_success_at: '2030-01-01T00:00:00Z', evidence_as_of: '2030-01-01T00:00:00Z' })) },
    error: null, loading: false, stale: false, refetch() {} }
}
const route = (fixture, state) => (url) => /desk-sources/.test(url) ? deskSources(url, state === 'loading') : fixture
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
  globalThis.__deskFixture = route(fixture, state)
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
  // N1 (cc-deepseek-3): this fixture omitted `loading: true`, so the case derived UNREADABLE and the assertions
  // passed without ever exercising the loading wording. It now loads.
  loading: { data: null, error: null, loading: true, refresh() {} },
  error: { data: null, error: 'The latest evidence is unavailable. Please try again.', refresh() {} },
  partial: { data: { ...queuePartial }, error: null, refresh() {} },
  ready: { data: queue, error: null, refresh() {} },
  malformed: { data: { items: 'not-a-list', gaps: 'nope' }, error: null, loading: false, refresh() {} },
})) {
  globalThis.__govFixture = () => fixture
  globalThis.__deskFixture = route(fixture, state)
  let text = ''
  try { text = render(React.createElement(ApprovalsHub)) } catch (e) {
    cases.push({ surface: '/approvals', state, passed: false, failed_assertions: [`rendering threw: ${e.name}: ${e.message}`], text: '' })
    continue
  }
  caseOf('/approvals', state, text, [
    // The strict rule, restored: with per-URL routing (cc3 N2 closed) the page's own fetch no longer receives the
    // approval queue, so loading and failure words must never co-render on the real page in ANY state.
    ['loading and failure words never co-render', !(LOADING.test(text) && FAILED.test(text))],
    state === 'loading' ? ['a loading approvals page says loading', /Loading/i.test(text)] : ['no loading claim', true],
    state === 'error' ? ['a failed page says unavailable', /unavailable/i.test(text)] : ['no failure claim', !/Queue unavailable/i.test(text)],
    state === 'partial' ? ['a partial page shows its known rows', /Fixture item/.test(text)] : ['no partial rows', true],
    state === 'partial' ? ['a partial page never shows a complete-looking total', !/\b1 waiting for review\b/.test(text)] : ['no complete total', true],
    state === 'partial' ? ['a partial page says the total is unknown', /not yet known|unavailable/i.test(text)] : ['no total claim', true],
    // F3: a malformed payload renders as unreadable; it must not throw (the render call above would have thrown).
    state === 'malformed' ? ['a malformed payload says it could not be read', /could not be read/i.test(text)] : ['no unreadable claim', true],
    state === 'malformed' ? ['a malformed payload never claims a complete total', !/\b1 waiting for review\b/.test(text)] : ['no total from nothing', true],
  ])
}

// F1: actual producer failures override its generic no-decision sentence. A healthy producer's registry-clock
// note remains visible without making every healthy read permanently partial.
for (const [name, payload] of Object.entries(realAgentPayloads)) {
  globalThis.__deskFixture = route({data:payload,error:null,loading:false,refetch(){}}, 'ready')
  try {
    const text = render(React.createElement(DeskBoard, deskConfig))
    const partial = ['partial', 'missing', 'registry', 'panelMissing'].includes(name)
    caseOf('/agents', `producer-${name}`, text, [
      ['source failures make coverage unknown', partial ? /not complete|total is not yet known/i.test(text) : !/not complete|total is not yet known/i.test(text)],
      ['unknown coverage cannot claim no open decisions', !partial || !/No writer or data decisions are open/i.test(text)],
      ['known rows survive failed reads', /Jobs completed/.test(text)],
      ['informational clock note retained', name === 'registry' || /carries no update time/.test(text)],
    ])
  } catch(e) {cases.push({surface:'/agents',state:`producer-${name}`,passed:false,failed_assertions:[e.message],text:''})}
}

globalThis.__govFixture = () => ({data:{...queue,pending_count:null,complete:false,gaps:[]},error:null,loading:false,refresh(){}})
globalThis.__deskFixture = route({data:null,error:null,loading:false}, 'ready')
const unexplainedPartial = render(React.createElement(ApprovalsHub))
caseOf('/approvals', 'incomplete-without-gap-reason', unexplainedPartial, [
  ['explicit incomplete coverage is never empty/complete', /total is not yet known/i.test(unexplainedPartial) && !/waiting for review/.test(unexplainedPartial)],
])

globalThis.__deskFixture = route({data:projection,error:null,loading:false,refreshing:true,refetch(){}}, 'ready')
const refreshingText = render(React.createElement(DeskBoard, deskConfig))
caseOf('/agents', 'refreshing-retains-rows', refreshingText, [
  ['ready refresh has a visible updating marker', /Updating the Agents page data/.test(refreshingText)],
  ['refresh retains known rows without initial-loading wording', /Fixture row/.test(refreshingText) && !/Loading the/.test(refreshingText)],
])

// F2: mutate one structural field at a time, leaving the other fields valid. Exercise downstream rendering,
// React text children and numeric totals, rather than only a protected gaps extractor.
const malformedDesk = [
 ['sources missing', d => {delete d.sources}], ['sources object', d => {d.sources={}}],
 ['source null', d => {d.sources=[null]}], ['source lanes object', d => {d.sources[0].lane_ids={}}],
 ['source label object', d => {d.sources[0].label={}}], ['source gap object', d => {d.sources[0].gap={}}],
 ['decisions missing', d => {delete d.decisions}], ['decisions null', d => {d.decisions=null}],
 ['decision null', d => {d.decisions=[null]}], ['decision title object', d => {d.decisions=[{id:'x',title:{}}]}],
 ['tabs null', d => {d.tabs=null}], ['tab null', d => {d.tabs.runtime=null}],
 ['panels missing', d => {d.tabs.runtime={}}], ['panel null', d => {d.tabs.runtime.panels=[null]}],
 ['rows object', d => {d.tabs.runtime.panels[0].rows={}}], ['row null', d => {d.tabs.runtime.panels[0].rows=[null]}],
 ['row value object', d => {d.tabs.runtime.panels[0].rows[0].value={}}],
 ['detail fields object', d => {d.tabs.runtime.panels[0].rows[0].detail={title:'Detail',fields:{}}}],
 ['errors object', d => {d.errors={}}],
]
const malformedQueue = [
 ['items missing', d => {delete d.items}], ['items object', d => {d.items={}}],
 ['item null', d => {d.items=[null]}], ['item title object', d => {d.items[0].title={}}],
 ['item href object', d => {d.items[0].governed_href={}}],
 ['recent missing', d => {delete d.recent}], ['recent null', d => {d.recent=null}],
 ['history decision missing', d => {d.recent=[{actor:'synthetic',at:'2030-01-01T00:00:00Z'}]}],
 ['gaps missing', d => {delete d.gaps}], ['gap null', d => {d.gaps=[null]}],
 ['gap source object', d => {d.gaps=[{source:{},reason:'synthetic'}]}],
 ['pending missing', d => {delete d.pending_count}], ['pending string', d => {d.pending_count='1'}],
 ['pending NaN', d => {d.pending_count=NaN}], ['pending Infinity', d => {d.pending_count=Infinity}],
 ['pending negative', d => {d.pending_count=-1}], ['known total missing', d => {delete d.known_pending_count}],
 ['filtered total object', d => {d.filtered_count={}}], ['complete missing', d => {delete d.complete}],
 ['resolved object', d => {d.resolved={}}], ['resolved malformed', d => {d.resolved=[{title:{}}]}],
]
for (const [surface, base, mutations, Component, props] of [
  ['/agents', projection, malformedDesk, DeskBoard, deskConfig],
  ['/approvals', queue, malformedQueue, ApprovalsHub, {}],
]) for (const [name, mutate] of mutations) {
  const payload = structuredClone(base); mutate(payload)
  const fixture = {data:payload,error:null,loading:false,refetch(){},refresh(){}}
  globalThis.__deskFixture = route(fixture, 'ready'); globalThis.__govFixture = () => fixture
  try {
    const text = render(React.createElement(Component, props))
    caseOf(surface, `malformed-${name}`, text, [
      ['malformed boundary is unreadable', /not in a usable shape/.test(text)],
      ['malformed boundary has no empty-result or count claim', !/waiting for review|No open decisions on file|No items in this view/.test(text)],
      ['malformed boundary offers recovery', /Try again/.test(text)],
    ])
  } catch(e) {cases.push({surface,state:`malformed-${name}`,passed:false,failed_assertions:[`render threw: ${e.message}`],text:''})}
}

// B1 wiring pins (cc-deepseek-3): the shell's publisher must be memoised with NO dependencies and the report and the
// publisher must be separate providers — a single value object rebuilt from the report is what made `publish` change
// identity on every publish and looped /agents (255,468 renders in 2.5 s). Read from the source, because the pure model
// test can only prove the mechanism, not that the shell uses it.
const appSource = readFileSync(join(app, 'src/App.tsx'), 'utf8')
cases.push({
  surface: '/shell', state: 'wiring', passed:
    /const publishSurfaceState = useCallback\([\s\S]*?\}, \[\]\)/.test(appSource) &&
    !/useMemo\(\(\) => \(\{\s*report/.test(appSource) &&
    /SurfacePublishContext\.Provider/.test(appSource) && /SurfaceReportContext\.Provider/.test(appSource),
  failed_assertions: [], text: '',
})

// FQ-018: plain-language decision first, exact scheduling/source evidence retained behind details.
const agentDiagnostic = { ...projection, sources: [{ id: 'summary', label: 'Agent runtime lanes', as_of: null, lane_ids: [],
  gap: 'Lane counts come from config/lane_registry.json; it carries no update time.' }], decisions: [{ id: 'runs-gate-b-shadow',
  title: 'tradeai-agent-runtime@{fixture} timers: 3 runs, no model by design',
  detail: '3 runs carry the Gate-B placeholder; 3 recorded retrieval_count 0.', href: '/agents?tab=runtime&detail=timeline:run-gate-b' }] }
globalThis.__deskFixture = route({data:agentDiagnostic,error:null,loading:false,refetch(){}},'ready')
const diagnosticHtml = renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(DeskBoard,deskConfig)))
const visibleDiagnostic = diagnosticHtml.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g,'')
cases.push({surface:'/agents',state:'plain-language',passed:
  /Choose how these agents should use AI/.test(visibleDiagnostic) && /no AI findings/.test(visibleDiagnostic) &&
  !/Gate-B|retrieval_count|config\/lane_registry|tradeai-agent-runtime@/.test(visibleDiagnostic) &&
  /Gate-B/.test(diagnosticHtml) && /config\/lane_registry/.test(diagnosticHtml) && /Technical details/.test(diagnosticHtml),
  failed_assertions:['operator explanation and collapsed diagnostic preservation'],text:visibleDiagnostic.slice(0,300)})

const out = { schema: 'HonestStateView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) {
  for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.surface}/${c.state}: ${c.failed_assertions.join('; ')} :: ${c.text}`)
}
process.exitCode = out.failed ? 1 : 0
