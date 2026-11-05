// SurfaceState@v1 contract tests (BOARD row 36). Pure: no React, no fetch, no fixtures with real values.
// The "must never say" half is what makes this a contract: every state's OWN wording is checked against every
// vocabulary it is forbidden to use, so a future edit that re-introduces "unavailable" into a loading state fails here.
import { readFileSync } from 'node:fs'
import { deriveSurfaceState, surfaceGap, refreshMarker, rendersData, nextSurfaceReport, MUST_NEVER_SAY, type SurfaceShape, type SurfaceStateName } from './surfaceState.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, condition: boolean) {
  if (condition) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
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

// Cloud review 2026-11-05 (P1): the shell's surface publisher must keep ONE identity across report updates. Every mounted
// surface publishes from an effect whose dependencies include `publish`; when publish was recreated per render, publishing
// caused a render that produced a new publish, which re-ran every effect, which published again — a loop that never settled.
// This repo has no effect-capable renderer (no jsdom, no react-test-renderer), so the guard is structural and pins the exact
// wiring that removes the loop rather than claiming to exercise it.
const surfaceGapSrc = readFileSync(new URL('../components/SurfaceGap.tsx', import.meta.url), 'utf8')
const appSrc = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8')
const hookBlock = surfaceGapSrc.slice(surfaceGapSrc.indexOf('const publish = useCallback('), surfaceGapSrc.indexOf('return useMemo('))
check('the channel builds publish with useCallback and an empty dependency list',
  hookBlock.includes('useCallback(') && /\[\s*\]\s*,?\s*\)/.test(hookBlock))
check('the channel value is memoised on the report and the stable publish',
  surfaceGapSrc.includes('return useMemo(() => ({ report, publish }), [report, publish])'))
check('the shell takes the channel from the hook, never an inline publish',
  appSrc.includes('const surfaceChannel = useSurfaceChannel()') && !appSrc.includes('publish: (next'))

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
