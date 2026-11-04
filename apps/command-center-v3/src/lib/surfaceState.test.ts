// SurfaceState@v1 contract tests (BOARD row 36). Pure: no React, no fetch, no fixtures with real values.
// The "must never say" half is what makes this a contract: every state's OWN wording is checked against every
// vocabulary it is forbidden to use, so a future edit that re-introduces "unavailable" into a loading state fails here.
import { deriveSurfaceState, surfaceGap, refreshMarker, rendersData, nextSurfaceReport, footerQualifier, sameSurfaceReport, surfaceReportReducer, MUST_NEVER_SAY, type SurfaceShape, type SurfaceStateName } from './surfaceState.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, condition: boolean, detail?: string) {
  if (condition) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}${detail ? ` — ${detail}` : ''}`) }
}

type Row = { id: string }
type Fixture = { rows: Row[]; gaps?: string[] }
const shape: SurfaceShape<Fixture> = {
  what: 'desk projection',
  isEmpty: d => d.rows.length === 0,
  gaps: d => d.gaps ?? [],
}
const present = { rows: [{ id: 'fixture' }] as Row[], gaps: [] as string[] }

// ── the derivation ──────────────────────────────────────────────────────────────────────────────────
const at = (r: Parameters<typeof deriveSurfaceState<Fixture>>[0]) => deriveSurfaceState<Fixture>(r, shape).state
check('first read in flight is loading', at({ data: null, loading: true }) === 'loading')
check('failed read with nothing retained is unavailable', at({ data: null, error: 'boom', loading: false }) === 'unavailable')
check('a read that finished with no data and no error is unreadable, not loading forever',
  at({ data: null, loading: false, error: null }) === 'unreadable')
check('payload with gaps is partial', at({ data: { ...present, gaps: ['approvals'] } }) === 'partial')
check('successful read with no rows is empty', at({ data: { rows: [], gaps: [] } }) === 'empty')
check('last-good after a failed re-read is stale', at({ data: present, stale: true }) === 'stale')
check('complete payload is ready', at({ data: present }) === 'ready')
check('wrong-shaped payload is unreadable', deriveSurfaceState<Fixture>({ data: { nope: 1 } as unknown as Fixture },
  { ...shape, usable: d => Array.isArray((d as { rows?: unknown }).rows) }).state === 'unreadable')

// ── the exclusivity the two captured defects violated ──────────────────────────────────────────────
const loadingText = surfaceGap(deriveSurfaceState({ data: null, loading: true }, shape), shape)!
const unavailableText = surfaceGap(deriveSurfaceState({ data: null, error: 'boom' }, shape), shape)!
const say = (t: { title: string; reason: string }) => `${t.title} ${t.reason}`
const violates = (state: SurfaceStateName, text: string) => MUST_NEVER_SAY[state].some(rx => rx.test(text))

check('a loading surface never co-renders the failure vocabulary (the /agents defect)', !violates('loading', say(loadingText)))
check('an unavailable surface never co-renders loading (the /approvals defect)', !violates('unavailable', say(unavailableText)))
check('an empty surface never says unavailable or could-not-be-read', !violates('empty', say(surfaceGap(deriveSurfaceState({ data: { rows: [], gaps: [] } }, shape), shape)!)))
check('an unreadable surface never says unavailable', !violates('unreadable', say(surfaceGap(deriveSurfaceState({ data: null, loading: false }, shape), shape)!)))
check('a ready surface renders no banner at all', surfaceGap(deriveSurfaceState({ data: present }, shape), shape) === null)

// ── partial: data present, total MUST read as unknown ──────────────────────────────────────────────
const partial = deriveSurfaceState({ data: { rows: [{ id: 'fixture' }], gaps: ['approvals', 'releases'] } }, shape)
const partialText = surfaceGap(partial, shape, {})!
check('partial keeps the rows', partial.state === 'partial' && partial.data !== null)
check('partial marks the total as unknown', partial.totalKnown === false)
check('partial names the sources that did not answer', /approvals/.test(partialText.reason) && /releases/.test(partialText.reason))
check('partial says the total is not yet known', /total is not yet known/i.test(partialText.reason))
check('partial never presents a complete-looking total', !violates('partial', say(partialText)))
check('ready marks the total as known', deriveSurfaceState({ data: present }, shape).totalKnown === true)

// ── refreshing is a marker, never a full-page state ────────────────────────────────────────────────
const refreshing = deriveSurfaceState({ data: present, refreshing: true, loading: true }, shape)
check('refreshing keeps the data and its ready state', refreshing.state === 'ready' && refreshing.refreshing === true)
check('refreshing is never rendered as loading', !violates('refreshing', say(refreshMarker(refreshing, { what: 'queue' })!)))

// ── every state's own wording is inside its own allowed vocabulary ─────────────────────────────────
const all: { name: SurfaceStateName; s: ReturnType<typeof deriveSurfaceState<Fixture>> }[] = [
  { name: 'loading', s: deriveSurfaceState({ data: null, loading: true }, shape) },
  { name: 'unavailable', s: deriveSurfaceState({ data: null, error: 'boom' }, shape) },
  { name: 'unreadable', s: deriveSurfaceState({ data: null }, shape) },
  { name: 'empty', s: deriveSurfaceState({ data: { rows: [], gaps: [] } }, shape) },
  { name: 'stale', s: deriveSurfaceState({ data: present, stale: true }, shape) },
  { name: 'partial', s: partial },
]
for (const { name, s } of all) {
  const t = surfaceGap(s, shape, { lastGoodAt: '10 minutes ago' })
  check(`${name}: its own wording obeys its own "must never say" list`, t !== null && !violates(name, say(t)))
}

// ── F3: a malformed payload is unreadable, never an exception out of render ────────────────────────
const throwingShape: SurfaceShape<Fixture> = {
  what: 'desk projection',
  gaps: d => (d as unknown as { gaps: string[] }).gaps.map(String),   // throws when `gaps` is not an array
  isEmpty: d => (d as unknown as { rows: unknown[] }).rows.length === 0,
}
const malformed = deriveSurfaceState({ data: { gaps: 'nope' } as unknown as Fixture, loading: false }, throwingShape)
check('a malformed payload is unreadable, not a thrown error', malformed.state === 'unreadable')
check('and it exposes no data to render', malformed.data === null)

// ── F2: one owner for the footer slot, and one predicate for "rendered data" ───────────────────────
check('rendersData: ready renders', rendersData(deriveSurfaceState({ data: present }, shape)))
check('rendersData: empty still rendered (the read succeeded)', rendersData(deriveSurfaceState({ data: { rows: [], gaps: [] } }, shape)))
check('rendersData: unavailable is not rendered', !rendersData(deriveSurfaceState({ data: null, error: 'boom' }, shape)))
check('rendersData: loading is not rendered', !rendersData(deriveSurfaceState({ data: null, loading: true }, shape)))
check('footer: a publish takes the slot', nextSurfaceReport(null, { name: 'Agents', dataLoaded: true })?.name === 'Agents')
check('footer: an OUTGOING page cannot erase the INCOMING page', nextSurfaceReport({ name: 'Approvals', dataLoaded: false }, null, 'Agents')?.name === 'Approvals')
check('footer: the owner can clear its own slot', nextSurfaceReport({ name: 'Agents', dataLoaded: true }, null, 'Agents') === null)

// ── Rule 7: the build line is a fact about the BUNDLE, and must say when the page's data did not load ─────
// Without the qualifier, "matches served artifact" sits as an all-clear above a page that failed — the same
// false-healthy class as the two contradictions. Pure, so it is tested without rendering the shell.
check('qualifier: no report yet adds nothing', footerQualifier(null) === '')
check('qualifier: a page that rendered its data adds nothing', footerQualifier({ name: 'Agents', dataLoaded: true }) === '')
const q = footerQualifier({ name: 'Approvals', dataLoaded: false })
check('qualifier: a page that did not render its data is named', q.includes('Approvals') && q.includes('data did not load'))
check('qualifier: it never claims the page is fine', !/unavailable|loading|\bok\b/i.test(q))

// ── B1 (cc-deepseek-3): the footer channel must SETTLE, not re-render for ever ────────────────────────────
// Measured on the branch: 255,468 renders in 2.5 s on /agents and /approvals. Cause: the provider's value object
// changed identity on every publish, so `publish` did too, so both effects in the hook re-ran on every render —
// publish -> state change -> new publish -> effects -> publish. This is the mechanism as a pure state machine: a
// render derives `publish` (old wiring: fresh per state, the useMemo([state]) bug; new wiring: one stable function),
// runs both effects, and re-renders only if the state object actually changed.
type Report = { name: string; dataLoaded: boolean }
function simulate(wiring: 'old' | 'new', maxRenders = 200): { renders: number; publishes: number } {
  let state: Report | null = null
  let publishes = 0
  let renders = 0
  let lastPublish: ((r: Report | null, clearingFrom?: string) => void) | null = null
  while (renders < maxRenders) {
    renders++
    // A render's publisher. Old wiring: memoised on the state, so a new function per state. New wiring: stable.
    const publish = wiring === 'old'
      ? (next: Report | null, clearingFrom?: string) => { publishes++; state = nextSurfaceReport(state, next, clearingFrom) }
      : (next: Report | null, clearingFrom?: string) => { publishes++; state = surfaceReportReducer(state, next, clearingFrom) }
    const depsChanged = wiring === 'new' ? lastPublish === null : publish !== lastPublish
    lastPublish = publish
    if (!depsChanged) break                       // React does not re-run effects whose deps did not change
    const before: Report | null = state
    publish(null, 'Agents')                        // effect 2's cleanup fires first on a dependency change
    publish({ name: 'Agents', dataLoaded: true })  // effect 1 re-publishes (a fresh object literal, as the hook does)
    if (state === before) break                    // no state change: React has nothing to re-render
  }
  return { renders, publishes }
}
const looped = simulate('old')
const settled = simulate('new')
check('B1: the old wiring loops instead of settling', looped.renders >= 200, `${looped.renders} renders`)
check('B1: the stable publisher settles within two renders', settled.renders === 2, `${settled.renders} renders`)
check('B1: and a settled channel publishes only twice', settled.publishes === 2, `${settled.publishes} publishes`)
// The reducer half: a repeat publish of the same report must not create a new state object.
const first = surfaceReportReducer(null, { name: 'Agents', dataLoaded: true })
const again = surfaceReportReducer(first, { name: 'Agents', dataLoaded: true })
check('B1: an unchanged report keeps the same state object', again === first)
const changed = surfaceReportReducer(first, { name: 'Agents', dataLoaded: false })
check('B1: a changed report replaces the state object', changed !== first && changed?.dataLoaded === false)
check('sameSurfaceReport: null and a report differ', !sameSurfaceReport(null, { name: 'Agents', dataLoaded: true }))
check('sameSurfaceReport: equal content is equal, even across objects', sameSurfaceReport({ name: 'A', dataLoaded: true }, { name: 'A', dataLoaded: true }))
