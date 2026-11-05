// node --experimental-strip-types src/lib/incidentRow.test.mjs
//
// FQ-045 / FQ-046. The titles below are COPIED FROM THE AUDIT'S OWN PHONE CAPTURE
// (audit/page-audit-20261104T0011Z/pass3-inspection/ops_incidents-phone390-y1300.png), so the test fails if the page
// stops handling the strings that were actually reported, not a tidy version of them.
import { nextActionOf, plainTitle, plainWords, priorityOf, rowModel } from './incidentRow.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const CAPTURED = [
  'lane coverage-stall unhealthy: research_up_thesis_flat:deepseek_ok, 24h=58,thesis_sustained=11,canary_coverage=20',
  'lane drive-sync unhealthy: DEGRADED_STALE_SOURCE',
  'test_run_discovery_shadow: first fails locally: reads live_industry_novelty_coming instead of an isolated default',
  'main red: test_agents_25_10_exclusions_still_name_these_classes_and_blocks_after_AGENTS_md_25_0_0 (#2236) renamed the 25.10 heading',
  'expected service off: DISABLED:tradeai-iris-taxonomy-timer',
  'expected service off: MISSING:tradeai-phone-status-service',
  'health tick step pipeline-watchdog broken (rc=1)',
  'Anthropic credit cap hit: CREDIT_PROCESS_CAP x7 in 60 min',
  'Disk at99.7percent used; approved cleanup remains unapplied',
]

const tokens = (s) => new Set(String(s).toLowerCase().match(/[a-z0-9]+/g) ?? [])

// ---- 1. NO WORD IS DROPPED: every token of the ledger title survives in the headline or in the lifted detail -------
for (const t of CAPTURED) {
  const { headline, rawDetail } = plainTitle(t)
  const have = tokens(`${headline} ${rawDetail ?? ''}`)
  const missing = [...tokens(t)].filter(w => !have.has(w))
  check(`nothing invented, nothing dropped: ${t.slice(0, 46)}…`, missing.length === 0, missing.join(','))
}

// ---- 1b. A DECIMAL KEEPS ITS POINT (cc-deepseek-5 F2 on #2628) -------------------------------------------
// "Disk at99.7percent used" rendered as "at99 7percent" — the dotted-identifier rule ate the decimal separator on the
// operator's row. The rule must split market.regime.indicators and leave 99.7 alone.
for (const [text, wanted] of [
  ['Disk at99.7percent used; approved cleanup remains unapplied', '99.7'],
  ['Margin buffer is 12.5 percent of the book', '12.5'],
]) {
  const { headline } = plainTitle(text)
  check(`a decimal keeps its point: ${wanted}`, headline.includes(wanted), headline)
}
for (const dotted of ['market.regime.indicators', 'risk.snapshot.v2']) {
  const { headline } = plainTitle(dotted)
  check(`a dotted identifier still separates: ${dotted}`, !headline.includes(dotted), headline)
}

// ---- 2. THE IDENTIFIER NOISE IS GONE FROM THE ROW --------------------------------------------------------------
check('an underscore lane name is spelled out', !plainTitle(CAPTURED[0]).headline.includes('_'))
check('it reads as a sentence', /^Lane coverage-stall unhealthy: research up thesis flat/.test(plainTitle(CAPTURED[0]).headline), plainTitle(CAPTURED[0]).headline)
// the lifted detail stays VERBATIM: it is what the operator would paste into a terminal
check('the measurement tail is lifted, not deleted', plainTitle(CAPTURED[0]).rawDetail === '24h=58, thesis_sustained=11, canary_coverage=20', plainTitle(CAPTURED[0]).rawDetail)
check('an ALL_CAPS code is spelled out', plainTitle(CAPTURED[1]).headline === 'Lane drive-sync unhealthy: degraded stale source', plainTitle(CAPTURED[1]).headline)
check('a test path is spelled out', !/_/.test(plainTitle(CAPTURED[2]).headline), plainTitle(CAPTURED[2]).headline)
check('a raw parenthetical leaves the sentence', plainTitle(CAPTURED[6]).headline === 'Health tick step pipeline-watchdog broken', plainTitle(CAPTURED[6]).headline)
check('but is kept for the detail', plainTitle(CAPTURED[6]).rawDetail === 'rc=1', plainTitle(CAPTURED[6]).rawDetail)
check('a service marker becomes a word', /disabled — tradeai-iris-taxonomy-timer/.test(plainTitle(CAPTURED[4]).headline), plainTitle(CAPTURED[4]).headline)

// ---- 3. A TITLE THAT ALREADY SPEAKS ENGLISH IS NOT "TRANSLATED" --------------------------------------------------
const PLAIN = 'Native PR approval callback lacks synchronous head verification'
const p = plainTitle(PLAIN)
check('a plain title is returned untouched', p.headline === PLAIN, p.headline)
check('and is not duplicated into a raw copy', p.raw === null && p.rawDetail === null)

// ---- 4. THE RAW TITLE IS KEPT WHENEVER SOMETHING CHANGED ---------------------------------------------------------
const changedTitle = plainTitle(CAPTURED[1])
check('the ledger title is preserved verbatim for the detail', changedTitle.raw === CAPTURED[1], changedTitle.raw)

// ---- 5. PRIORITY IS THE LEDGER'S OWN CODE, NOT A GLOSS ------------------------------------------------------------
check('P1 is the highest tone', priorityOf({ severity: 'P1' }).tone === 'danger')
check('P2 is the warning tone', priorityOf({ severity: 'P2' }).code === 'P2' && priorityOf({ severity: 'P2' }).tone === 'warning')
check('an unrecorded priority says so', priorityOf({}).code === 'Not recorded' && priorityOf({}).tone === 'neutral')

// ---- 6. NEXT ACTION IS DERIVED FROM FIELDS ------------------------------------------------------------------------
const base = { schema: 'IncidentRecord@v1', id: 'X', opened_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z',
  source: { kind: 'watcher', watcher: 'lane_health' }, title: 't', evidence: [], attempts: [], fix_refs: [] }
check('a blocked incident quotes its own handoff',
  nextActionOf({ ...base, status: 'blocked', handoff: 'restart the lane' }) === 'Needs a person. Next: restart the lane')
check('a blocked incident with no handoff says there is none',
  nextActionOf({ ...base, status: 'blocked' }) === 'Needs a person, and no next step is recorded.')
check('an open incident names an owner when it has one',
  nextActionOf({ ...base, status: 'open', owner: 'cc-deepseek-4' }) === 'Nobody is working on it yet. Owner: cc-deepseek-4.')
check('a fixing incident says who is on it', nextActionOf({ ...base, status: 'fixing', owner: 'a3f' }) === 'Being fixed. Owner: a3f.')
check('a closed incident says why', nextActionOf({ ...base, status: 'closed', resolution: 'not_reproducible' }) === "Closed as won't fix — not reproducible.")
const unknown = nextActionOf({ ...base, status: 'quarantined' })
check('an unknown status is reported as unknown, not as someone else\'s meaning', /does not know \(quarantined\)/.test(unknown), unknown)

// ---- 7. THE ROW MODEL ---------------------------------------------------------------------------------------------
const row = rowModel({ ...base, status: 'blocked', severity: 'P1', title: CAPTURED[1], handoff: 're-auth the drive lane' },
  { age: '5 d 4 h', source: 'watcher · lane_health' })
check('the row carries a plain headline', row.headline === 'Lane drive-sync unhealthy: degraded stale source', row.headline)
check('the row carries the priority', row.priority.code === 'P1')
check('the row carries the next action', row.nextAction === 'Needs a person. Next: re-auth the drive lane', row.nextAction)
check('the row meta has no identifier underscores', !row.meta.includes('_'), row.meta)


// ---- cx-openai-4's two findings at 52e815c12 (R1 qualification, R2 phone age) -------------------------------------
const QUAL = plainTitle('Data service healthy (NOT VERIFIED)')
check('R1: a qualification stays in the sentence', /NOT VERIFIED/.test(QUAL.headline), QUAL.headline)
check('R1: and is not treated as machine detail', !/NOT VERIFIED/.test(QUAL.rawDetail ?? ''), String(QUAL.rawDetail))
const UNV = plainTitle('Feed reachable (UNVERIFIED)')
check('R1: UNVERIFIED is a qualification too', /UNVERIFIED/.test(UNV.headline), UNV.headline)
check('R1: an assignment in brackets still moves to the detail', (plainTitle('Disk check ran (rc=1)').rawDetail ?? '') === 'rc=1')
const compactRow = rowModel({ ...base, status: 'open', title: 't' }, { age: '1 h 30 min', source: 'watcher · lane_health' })
check('R2: the row model carries the age on its own', compactRow.age === '1 h 30 min', compactRow.age)

// the phone branch of the page must render the age, not drop the whole meta line
// cc-deepseek-5 F1 on #2628: the server renderer emits one `useLayoutEffect does nothing on the server` warning per
// component, each stack line carrying a multi-megabyte data: URL of the compiled page. Unfiltered this file wrote ~19.5 MB
// of stderr per build. Five sibling view tests filter exactly this one warning; everything else still prints.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

import { readFileSync } from 'node:fs'

// cx-openai cloud P1 on 75796da8c: the R2 age check used to be a regex over the page SOURCE, which fails if `m.age`
// drifts more than 120 characters from `sheet.mobile` and passes on matching text inside a comment - a layout
// assertion wearing a behaviour's name (AGENTS 8A). The rendered page already proves it: `the phone keeps the age and
// drops the SOURCE identifier` asserts the real "21 h 07 min" on the server-rendered phone view below. Removing this
// one loses no coverage; mutating the age out of the phone branch reds the rendered check.


// ---- cx-openai-4's second review (43cd0cbae): ORDER-INDEPENDENT mixed cases, no word list ------------------------
const MIXED = [
  'Data service healthy (rc=1; UNAVAILABLE)',
  'Data service healthy (UNAVAILABLE; rc=1)',
  'Data service healthy (rc=1; NOT READY)',
  'Data service healthy (NOT READY; rc=1)',
  'Data service healthy (rc=1; NO VALID READ)',
  'Data service healthy (rc=1; SOMETHING NEW ENTIRELY)',
]
for (const t of MIXED) {
  const m = plainTitle(t)
  const qual = t.slice(t.indexOf('(')).replace(/[()]/g, '').split(';').map(x => x.trim()).filter(x => !/=/.test(x)).join(' ')
  check(`a mixed bracket keeps its qualification: ${t}`, m.headline.includes(qual), m.headline)
  check(`and does not lift prose into the detail: ${t}`, !(m.rawDetail ?? '').includes(qual), String(m.rawDetail))
}
const pureMachine = plainTitle('Disk check ran (rc=1)')
check('a bracket that is nothing but machine detail is still lifted', pureMachine.headline === 'Disk check ran' && (pureMachine.rawDetail ?? '') === 'rc=1', `${pureMachine.headline} | ${pureMachine.rawDetail}`)
const pureRef = plainTitle('Merged in (#2236)')
check('a bare reference is still machine detail', !/2236/.test(pureRef.headline), pureRef.headline)

// A lifted measurement tail can carry the ')' that closed a bracket it does not own, so a qualified headline must never
// render a hanging bracket. Found while re-checking cx-openai-4's order-independent cases at this head.
const balanced = (s) => { let d = 0; for (const c of s) { if (c === '(') d++; else if (c === ')') { d--; if (d < 0) return false } } return d === 0 }
for (const t of MIXED.concat(['Data service healthy (NO VALID READ; rc=1)'])) {
  const m = plainTitle(t)
  check(`a qualified headline keeps its bracket closed: ${t}`, balanced(m.headline), m.headline)
}

// ---- THE PAGE ITSELF (cc-deepseek-5's BLOCK at 43cd0cbae) ----------------------------------------------------------
// Everything above tests a model. The page could render `r.title` or lose the next-action line and every check above
// would stay green, so this mounts the real OpsIncidents and asserts what the operator's phone shows. Same pattern as
// the other view tests: compile the TSX with the repo's own TypeScript, stub the data hook, render to static markup.
import { existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve as resolvePath } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const APP = resolvePath(dirname(fileURLToPath(import.meta.url)), '../..')
const nodeRequire = createRequire(join(APP, 'package.json'))
const ts = nodeRequire('typescript')
const React = nodeRequire('react')
const { renderToStaticMarkup } = nodeRequire('react-dom/server')
const { MemoryRouter } = nodeRequire('react-router-dom')

const compiledTsx = new Map()
function compileTsx(path) {
  if (compiledTsx.has(path)) return compiledTsx.get(path)
  const source = readFileSync(path, 'utf8').replace(
    /import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._a: any[]): any => (globalThis as any).__incidentFixture',
  )
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  // a stylesheet has nothing to contribute to markup, and node cannot resolve its import
  js = js.replace(/^[ \t]*import\s+['"][^'"]+\.css['"];?[ \t]*$/gm, '')
    .replace(/^[ \t]*import\s+(\w+)\s+from\s+['"][^'"]+\.css['"];?[ \t]*$/gm, 'const $1 = {}')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(nodeRequire.resolve(spec)).href)}`
    const wanted = resolvePath(dirname(path), spec)
    const target = [wanted, wanted + '.ts', wanted + '.tsx', wanted + '.js',
      join(wanted, 'index.ts'), join(wanted, 'index.tsx'), join(wanted, 'index.js')]
      .find(p => existsSync(p) && !statSync(p).isDirectory())
    if (!target) throw new Error(`missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compileTsx(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  compiledTsx.set(path, url)
  return url
}

const at21h07m = new Date(Date.now() - (21 * 60 + 7) * 60_000).toISOString()
const LEDGER = {
  ledger_present: true,
  watchers_as_of: at21h07m,
  supervisor_as_of: at21h07m,
  summary: { counts: { open: 1, fixing: 0, blocked: 1, fixed: 0 } },
  incidents: [
    { schema: 'IncidentRecord@v1', id: 'inc-blocked', status: 'blocked', severity: 'P1',
      title: 'lane drive-sync unhealthy: DEGRADED_STALE_SOURCE', handoff: 're-auth the drive lane',
      opened_at: at21h07m, updated_at: at21h07m, source: { kind: 'watcher', watcher: 'lane_health' },
      evidence: [], attempts: [], fix_refs: [] },
    { schema: 'IncidentRecord@v1', id: 'inc-open', status: 'open',
      title: 'health tick step pipeline-watchdog broken (rc=1)',
      opened_at: at21h07m, updated_at: at21h07m, source: { kind: 'watcher', watcher: 'lane_health' },
      evidence: [], attempts: [], fix_refs: [] },
  ],
}

let Page = null
const renderPage = (mobile) => {
  globalThis.window = { matchMedia: () => ({ matches: mobile, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {} }) }
  globalThis.__incidentFixture = { data: LEDGER, loading: false, error: null, refetch() {} }
  return renderToStaticMarkup(React.createElement(MemoryRouter, { basename: '/v3', initialEntries: ['/v3/ops/incidents'] },
    React.createElement(Page)))
}

let phone = '', desk = ''
try {
  Page = (await import(compileTsx(join(APP, 'src/pages/OpsIncidents.tsx')))).default
  phone = renderPage(true)
  desk = renderPage(false)
} catch (e) {
  check('the incidents page renders at all', false, `${e.name}: ${String(e.message).split('\n')[0]}`)
}

if (phone) {
  check('the phone shows the plain headline, not the ledger title',
    phone.includes('Lane drive-sync unhealthy: degraded stale source') && !phone.includes('DEGRADED_STALE_SOURCE'), phone.slice(0, 300))
  check('the phone shows the priority the ledger recorded', />P1</.test(phone), phone.slice(0, 300))
  check('an unrecorded priority says so on the phone', phone.includes('Not recorded'))
  check('the phone shows the next action, in words', phone.includes('Needs a person. Next: re-auth the drive lane'))
  check('the phone says nobody is on an open incident', phone.includes('Nobody is working on it yet'))
  check('the phone keeps the age and drops the SOURCE identifier', /21 h 07 min/.test(phone) && !phone.includes('watcher · lane_health'),
    phone.match(/.{0,40}21 h.{0,40}/)?.[0] ?? 'no age on the phone')
  check('the desktop row keeps the source the phone drops', desk.includes('watcher · lane health') && !desk.includes('lane_health'),
    desk.match(/.{0,40}watcher.{0,40}/)?.[0] ?? 'no source on the desktop row')
}

// ---- cx-openai-4 F1 (third review): an ASSIGNMENT tail is lifted only when it is made of numbers ---------------
// The same qualification-loss class as the bracket rule, reached through a different syntax. A value that is a word,
// a verdict or a phrase is prose, and prose that qualifies the sentence must stay in the sentence.
const QUALIFYING_TAILS = [
  'Data service healthy, status=NOT VERIFIED',
  'Data service healthy, detail=unavailable',
  'Service recovered, evidence=not checked',
]
for (const t of QUALIFYING_TAILS) {
  const p = plainTitle(t)
  const qualifier = t.slice(t.indexOf(',') + 1).trim()
  check(`an assignment qualifier stays in the sentence: ${qualifier}`, p.headline.includes(qualifier), `${p.headline} | ${p.rawDetail}`)
  check(`and is not lifted into the detail: ${qualifier}`, !(p.rawDetail ?? '').includes(qualifier), String(p.rawDetail))
}
// The positive control: a genuinely numeric measurement tail is still machine detail and is still lifted verbatim.
const MEASURED = plainTitle('lane coverage-stall unhealthy: research_up_thesis_flat:deepseek_ok, 24h=58,thesis_sustained=11')
check('a numeric measurement tail is still lifted', MEASURED.rawDetail === '24h=58, thesis_sustained=11', String(MEASURED.rawDetail))
check('and does not stay in the sentence', !MEASURED.headline.includes('24h=58'), MEASURED.headline)
const MIXED_TAIL = plainTitle('Disk pressure high, pct=99.7,note=check the volume')
check('one prose value keeps the whole tail in the sentence', MIXED_TAIL.headline.includes('note=check the volume'), `${MIXED_TAIL.headline} | ${MIXED_TAIL.rawDetail}`)

console.log(`incidentRow: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
