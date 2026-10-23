// node --experimental-strip-types src/lib/optionsLifecycleDesk.test.ts
// Options lifecycle desk (Gate 3, 2026-10-22): Step 7 open legs from the monitor, act-first ordering,
// and freshness on every number. Uses the captured proposals fixture plus a synthetic open-positions
// fixture shaped exactly like scripts/options_engine.py:_monitor_position output.
import {
  actBucket, actFirstSort, buildIdeas, buildPlans, freshnessChips, laneCounts, MODEL_GLOSSARY_KEYS, openPositionRows, openUrgency,
  planIdeas, quoteFreshness,
} from './optionsDeskModel.ts'
import { hasGlossary } from './optionsGlossary.ts'
import { FIXTURE } from './optionsDesk.fixture.ts'
import { OPEN_POSITIONS_FIXTURE as OPEN } from './optionsOpenPositions.fixture.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const NOW = new Date('2026-10-22T15:00:00Z')
const raw: any[] = FIXTURE.proposals.data.proposals

// ── Step 7: open legs ───────────────────────────────────────────────────────────────────────────
const open = openPositionRows(OPEN, NOW)
eq('one row per open leg', open.length, 4)
ok('every open row sits in step 7', open.every(r => r.lane === 'open'))
const xyz = open.find(r => r.symbol === 'XYZ')!
eq('urgency from the monitor: defend → protect', xyz.urgency, 'protect')
eq('harvest → act', open.find(r => r.symbol === 'ABC')!.urgency, 'act')
eq('monitor → calm', open.find(r => r.symbol === 'QRS')!.urgency, 'calm')
eq('still_working false alone is protect', openUrgency({ lifecycle_phase: 'monitor', still_working: false }), 'protect')
eq('XYZ contract text', xyz.contract, 'Oct 27 $50C × 2')
eq('XYZ strategy label', xyz.strategyLabel, 'Short call')
ok('XYZ stuck quotes the served rule, not a paraphrase', xyz.stuck === 'Monitor says Roll to Next Expiration (Short call ITM and DTE ≤ 7)')
eq('short leg cost is the credit received at open', xyz.cost, '+$220 credit')
eq('long leg cost is the debit paid', open.find(r => r.symbol === 'QRS')!.cost, '$450')
ok('cost freshness names the monitor run', /^at open · monitored 10:45 ET · 15 min old$/.test(xyz.costAge))
eq('next step opens the existing Lifecycle view (no order route)', xyz.next, { kind: 'view', label: 'Manage in Lifecycle', view: 'Lifecycle' })
ok('every econ tile on an open row carries a note', xyz.econ.every(e => typeof e.note === 'string' && e.note.length > 0))
ok('mark tile says the provider quote time is not served', /provider quote time not served/.test(xyz.econ.find(e => e.label === 'Mark')!.note!))
eq('unrealized P/L served value', xyz.econ.find(e => e.label === 'Unrealized P/L')!.value, '−$300')
const lmn = open.find(r => r.symbol === 'LMN')!
eq('missing basis: P/L —', lmn.econ.find(e => e.label === 'Unrealized P/L')!.value, '—')
eq('missing basis: reason shown', lmn.econ.find(e => e.label === 'Unrealized P/L')!.note, 'missing avg_entry / fill basis')
ok('missing basis fails the P/L check', lmn.checks.some(c => c.mark === '✗' && /P\/L unknown/.test(c.text)))
eq('missing basis: cost —', lmn.cost, '—')
ok('the last check is always yours, with 2FA', open.every(r => r.checks[r.checks.length - 1].mark === '○' && /per-order 2FA/.test(r.checks[r.checks.length - 1].text)))
eq('alerts attach by leg id', xyz.monitor?.alerts, ['Short call ITM with ≤7 DTE — assignment risk elevated'])
eq('no positions → no rows', openPositionRows({ ok: true, data: { positions: [] } }, NOW).length, 0)
eq('absent payload → no rows', openPositionRows(null, NOW).length, 0)

// ── Act-first ordering ──────────────────────────────────────────────────────────────────────────
const ideas = buildIdeas(raw, NOW)
const plans = buildPlans(FIXTURE.intents, ideas, NOW)
const all = actFirstSort([...ideas, ...planIdeas(plans), ...open])
const order = all.map(r => `${r.lane}${r.urgency ? `:${r.urgency}` : ''}`)
const firstIdx = (k: string) => order.indexOf(k)
ok('protect-first open leg is the first row', order[0] === 'open:protect')
ok('your decision comes next', order[1] === 'you')
ok('then the open leg to harvest', order[2] === 'open:act')
ok('data before research before plan (the mockup order)', firstIdx('data') < firstIdx('research') && firstIdx('research') < firstIdx('plan'))
ok('calm open legs after plan matches', firstIdx('open:calm') > order.lastIndexOf('plan'))
eq('buckets are monotonic', all.map(actBucket).every((b, i, a) => i === 0 || a[i - 1] <= b), true)
const dataRows = all.filter(r => r.lane === 'data')
eq('inside a bucket, the larger dollar amount first', dataRows.map(r => r.symbol), ['SCHG', 'XLB'])
const tie = actFirstSort([
  { lane: 'you', strategy: 'cash_secured_put', costValue: 9000, symbol: 'AAA' },
  { lane: 'you', strategy: 'protective_put', costValue: 100, symbol: 'ZZZ' },
] as any[])
eq('inside a bucket, protection (insuring held shares) before income', tie.map(r => r.symbol), ['ZZZ', 'AAA'])
eq('buildIdeas already returns act-first order', buildIdeas(raw, NOW).map(i => i.lane), ['you', 'data', 'data', 'research'])

// ── Freshness on every number ───────────────────────────────────────────────────────────────────
for (const r of all) ok(`row ${r.id} has a cost freshness line`, typeof r.costAge === 'string' && r.costAge.length > 0)
const spcx = ideas.find(i => i.symbol === 'SPCX')!
ok('idea cost age from the contract quote_time', /^quote Oct 21 16:00 ET · 19 h old$/.test(spcx.costAge))
for (const label of ['Premium', 'Total cost', 'Floor']) ok(`SPCX ${label} tile states its quote time`, /quote Oct 21 16:00 ET/.test(spcx.econ.find(e => e.label === label)?.note || ''))
eq('served request-time age used when there is no quote_time', quoteFreshness({ quote_age_s: 30 }, NOW).text, 'quote 30 s old')
eq('generation-time age is labelled', quoteFreshness({ quote_age_seconds: 600 }, NOW).text, 'quote 10 min old at generation')
eq('nothing served → says so', quoteFreshness({}, NOW).text, 'quote time not provided by this server version')
const pr = planIdeas(plans)
ok('plan rows state their match quote time', pr.every(r => /^quote /.test(r.costAge)))
const chips = freshnessChips(FIXTURE.proposals, raw, NOW, OPEN)
const oc = chips.find(c => c.key === 'open')!
eq('open-positions chip', [oc.value, oc.tone], ['monitored 10:45 ET', 'success'])
ok('open chip detail has the count and age', /4 open leg\(s\); monitor run 15 min old/.test(oc.detail))
const staleOpen = freshnessChips(FIXTURE.proposals, raw, new Date('2026-10-24T15:00:00Z'), OPEN).find(c => c.key === 'open')!
eq('monitor older than a day warns', staleOpen.tone, 'warning')
const counts = laneCounts(FIXTURE.proposals, ideas, FIXTURE.intents, OPEN, NOW)
eq('step 7 count from the monitor', counts.find(c => c.key === 'open')!.n, 4)
ok('every lane count states its as-of (or that none is served)', counts.every(c => /as of|monitored|not provided/.test(c.note)))

// ── Glossary coverage for everything this adds ──────────────────────────────────────────────────
for (const k of MODEL_GLOSSARY_KEYS) ok(`glossary has ${k}`, hasGlossary(k))
const emitted = new Set<string>()
for (const r of open) { emitted.add(r.stuckKey); r.econ.forEach(e => emitted.add(e.glossaryKey)); r.checks.forEach(c => emitted.add(c.glossaryKey)) }
chips.forEach(c => emitted.add(c.glossaryKey))
for (const k of emitted) ok(`glossary has emitted ${k}`, hasGlossary(k))

if (failed) { console.error(`optionsLifecycleDesk: ${failed} failure(s)`); throw new Error('optionsLifecycleDesk tests failed') }
console.log('optionsLifecycleDesk: ok')
