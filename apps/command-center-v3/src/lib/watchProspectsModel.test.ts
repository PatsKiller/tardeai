// node --experimental-strip-types src/lib/watchProspectsModel.test.ts
// The Watch prospects page model on the captured 2026-10-22 fixture (src/fixtures/watchProspects.fixture.ts).
declare const process: { exit(code?: number): never }
import { FIXTURE as FIX } from '../fixtures/watchProspects.fixture.ts'
import {
  LANE_ORDER, alertIntel, allRows, conflictCount, convictionTone, drawers, headerChips, laneById, orphanWhy,
  proposeSeed, stanceTone, stepTone, tieAlerts, TOOLTIPS, unwrap, type ProspectRow,
} from './watchProspectsModel.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const P = unwrap(FIX.prospects)!
ok('payload unwraps', P && P.lanes.length === 5)
ok('unwrap accepts the {ok,data} envelope', unwrap({ ok: true, data: FIX.prospects }) !== null)
eq('lane order', P.lanes.map(l => l.id), LANE_ORDER)
eq('interim is labelled', [P.interim, P.source_label], [true, 'interim — CIO prospect store not live'])

// One membership: no symbol appears in two lanes (items or overflow).
const seen = new Map<string, string>()
let dup = ''
for (const l of P.lanes) for (const s of [...l.items.map(r => r.symbol), ...l.overflow]) {
  if (seen.has(s) && seen.get(s) !== l.id) dup = s
  seen.set(s, l.id)
}
eq('one lane per security', dup, '')
for (const l of P.lanes) ok(`${l.id} count = items + overflow`, l.count === l.items.length + l.overflow.length)

// Held names are only in Manage; Manage holds only held names.
const rows = allRows(P)
ok('every held row is in manage', rows.filter(r => r.held).every(r => r.lane === 'manage'))
ok('manage holds only held rows', laneById(P, 'manage')!.items.every(r => r.held))
ok('no held row is offered Propose', rows.filter(r => r.held).every(r => r.next_action.kind !== 'propose'))

// Sorted by conviction within each lane (missing conviction last).
for (const l of P.lanes) {
  const c = l.items.map(r => r.conviction ?? -1)
  ok(`${l.id} sorted by conviction`, c.every((v, i) => i === 0 || c[i - 1] >= v))
}

// The audit cases render as the mockup reads them.
const by = (s: string) => rows.find(r => r.symbol === s) as ProspectRow
eq('NAVN: held, protect first, conflicts shown', [by('NAVN').lane, by('NAVN').next_action.label, by('NAVN').conflicts.map(c => c.kind)],
  ['manage', 'Protect first', ['stance_vs_synthesis', 'ownership']])
eq('SPCX: ADD vs review HOLD is a conflict, both values kept', [by('SPCX').stance, by('SPCX').conflicts[0].a.value, by('SPCX').conflicts[0].b.value],
  ['ADD', 'ADD', 'HOLD'])
eq('FATN: re-entry blocked by Trade AI', [by('FATN').lane, by('FATN').conflicts[0].kind], ['reentry', 'trade_ai_block'])
eq('CACI: re-entry desk READY is actionable with Propose', [by('CACI').lane, by('CACI').next_action.kind], ['actionable', 'propose'])

// Seeds for the existing forms are reference levels.
const seed = proposeSeed(by('CACI'))
eq('CACI propose seed', [seed.it.symbol, seed.entry, seed.stop, seed.planTarget], ['CACI', 628, 604, 690])
ok('CACI R:R from the seed', seed.rr != null && Math.abs(seed.rr - (690 - 628) / (628 - 604)) < 1e-9)
const kbr = by('KBR')
eq('KBR set alert seed', [kbr.next_action.kind, alertIntel(kbr).entryLow, alertIntel(kbr).entryHigh], ['set_alert', 36, 36.8])

// Conflicts count excludes expired rows.
const nConf = rows.filter(r => r.lane !== 'expired').reduce((n, r) => n + r.conflicts.length, 0)
eq('conflict count', conflictCount(P), nConf)
const chips = headerChips(P)
eq('chips', chips.map(c => c.key), ['source', 'updated', 'holdings', 'conflicts'])
ok('source chip warns while interim', chips[0].tone === 'warning' && chips[0].value.includes('interim'))
ok('conflict chip says shown, not hidden', chips[3].value === `${nConf} shown, not hidden`)

// Alerts: every armed alert is tied or listed as an orphan.
const T = tieAlerts(P, FIX.alerts)
eq('armed', T.armed.length, FIX.alerts.data.active_count)
eq('tied + orphans = armed', T.tied.length + T.orphans.length, T.armed.length)
ok('QCOM alert ties to the QCOM prospect', T.tied.some(t => t.symbol === 'QCOM' && t.lane === 'reentry'))
ok('ladder alerts are orphans with the ladder named', T.orphans.some(o => /trim-ladder alert \(ladder#\d+/.test(o.why)))
eq('orphanWhy without a note', orphanWhy({ id: 1, symbol: 'X', condition_type: 'rsi_below', threshold: 30, active: true }),
  'its symbol is not a prospect on this page')
const d = drawers(P, T)
eq('drawers', d.map(x => x.id), ['alerts', 'expired', 'how'])
ok('alerts drawer summary', d[0].summary === `${T.armed.length} armed → ${T.tied.length} belong to a prospect · ${T.orphans.length} orphaned`)
ok('expired drawer counts the lane', d[1].summary.startsWith(`${laneById(P, 'expired')!.count} ·`))
eq('tie with no payload orphans everything', tieAlerts(null, FIX.alerts).orphans.length, T.armed.length)

// Tones (token names only).
eq('conviction tones', [convictionTone(81), convictionTone(58), convictionTone(44), convictionTone(null)], ['success', 'warning', 'danger', 'neutral'])
eq('stance tones', [stanceTone('ADD'), stanceTone('RE_ENTER'), stanceTone('HOLD'), stanceTone('WATCH'), stanceTone('EXIT')], ['success', 'ai', 'info', 'warning', 'danger'])
eq('step tones', [stepTone('propose'), stepTone('protect'), stepTone('resolve_conflict'), stepTone('set_alert')], ['success', 'danger', 'warning', 'info'])

// Tooltips say what the server does (and never claim an order).
ok('trigger tooltip: reference level, never an order', /never an order/.test(TOOLTIPS.trigger))
ok('manage tooltip: held always manage', /managed, never entered/.test(TOOLTIPS.lane.manage))
ok('source tooltip names the interim inputs', /opportunity projection/.test(TOOLTIPS.source(P)) && /re-entry desk/.test(TOOLTIPS.source(P)))
ok('step tooltip: you size it', /you size it/.test(TOOLTIPS.step))

if (failed) { console.error(`watchProspectsModel: ${failed} failure(s)`); process.exit(1) }
console.log('watchProspectsModel: all checks passed')
