// node --experimental-strip-types src/lib/watchProspectsModel.test.ts
// The Watch prospects page model on the captured 2026-10-22 fixture (src/fixtures/watchProspects.fixture.ts).
declare const process: { exit(code?: number): never }
import { FIXTURE as FIX } from '../fixtures/watchProspects.fixture.ts'
import {
  LANE_ORDER, alertIntel, allRows, conflictCount, convictionPlainText, convictionTone, drawers, freshnessLine, headerChips, laneById, orphanWhy,
  proposeSeed, stancePlainText, stanceTone, stepTone, tieAlerts, TOOLTIPS, unwrap, type ProspectRow,
  asksCio, cioReviewNote, detailNextLine, etStamp, reviewStateText, reviewStateTone, cioMemoryState,
} from './watchProspectsModel.ts'
import { WORKFLOW_LABELS, WORKFLOW_ORDER, workflowStrip } from './watchWorkflowModel.ts'

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

// An alert remains tied when its prospect is on another server page.
const paged = { ...P, lane_membership: Object.fromEntries(P.lanes.flatMap(l => [...l.items.map(r => [r.symbol, l.id]), ...l.overflow.map(sym => [sym, l.id])])),
  conflict_count: conflictCount(P), lanes: P.lanes.map(l => ({ ...l, items: [], overflow: [] })) }
const pagedTies = tieAlerts(paged, FIX.alerts)
eq('paging does not manufacture orphaned alerts', pagedTies.orphans.map(a => a.alert.symbol), T.orphans.map(a => a.alert.symbol))
eq('paging retains full curated conflict count', conflictCount(paged), conflictCount(P))
eq('missing canonical conflict check stays unknown', headerChips({ ...paged, conflict_count: null }).find(c => c.key === 'conflicts')?.value, 'check unavailable')

// Batch 31: a missing CIO view asks the CIO (actionable) without being called a conflict; request state is visible.
ok('resolve_conflict asks the CIO', asksCio('resolve_conflict'))
ok('cio_missing asks the CIO', asksCio('cio_missing'))
ok('propose does not ask the CIO', !asksCio('propose') && !asksCio(null))
eq('cio_missing is not a warning-toned conflict', stepTone('cio_missing'), 'info')
eq('no request → no chip', reviewStateText({ status: 'none', label: 'Not requested', open: false }), null)
eq('no state → no chip', reviewStateText(null), null)
const blocked = { status: 'blocked', label: 'Blocked: waiting for evidence — no contradicting evidence on file yet', open: true,
  queued_at: '2026-10-24T04:54:05+00:00', expires_at: '2026-10-31T04:54:05+00:00',
  last_attempt: { status: 'BLOCKED', at: '2026-10-25T08:25:03+00:00', block_reason: 'BLOCKED_PENDING_ACQUISITION_AND_CURATION' } }
eq('blocked reads plainly with its times', reviewStateText(blocked),
  'Blocked: waiting for evidence — no contradicting evidence on file yet · asked Oct 24, 12:54 AM ET · expires Oct 31, 12:54 AM ET · last run Oct 25, 4:25 AM ET')
eq('an unzoned request time is not labeled UTC', reviewStateText({ ...blocked, queued_at: '2026-10-24 04:54', expires_at: '2026-10-31 04:54',
  last_attempt: { ...blocked.last_attempt, at: '2026-10-25 08:25' } }),
  'Blocked: waiting for evidence — no contradicting evidence on file yet · asked timezone unavailable · expires timezone unavailable · last run timezone unavailable')
eq('a zoned instant is Eastern Time', etStamp('2026-10-24T04:54:05+00:00'), 'Oct 24, 12:54 AM ET')
eq('unavailable conflict check is not a resolve step', detailNextLine(
  { kind: 'resolve_conflict', label: 'Resolve conflict', reason: 'flags disagree' },
  { headline: null, findings: [], gap: { reason: 'engine result not supplied for this security' } }),
  'Conflict check unavailable — engine result not supplied for this security')
eq('a recorded finding keeps its next step', detailNextLine(
  { kind: 'resolve_conflict', label: 'Resolve conflict', reason: 'flags disagree' },
  { headline: 'One finding', findings: [{}], gap: null }),
  'Resolve conflict — flags disagree')
eq('blocked tone', reviewStateTone(blocked), 'warning')
eq('queued tone', reviewStateTone({ status: 'queued', label: 'Queued for the CIO', open: true }), 'info')
eq('note carries the gap', cioReviewNote({ conflicts: [], next_action: { kind: 'cio_missing', label: 'x', reason: 'r', gap: { reason: 'CIO stance missing' } } }),
  'Watch: no CIO view — CIO stance missing')
eq('note carries the flags', cioReviewNote({ conflicts: [{ kind: 'k', summary: 'A vs B', a: { value: 1, source: null, at: null }, b: { value: 2, source: null, at: null } }],
  next_action: { kind: 'resolve_conflict', label: 'x', reason: 'r' } }), 'Watch conflict: A vs B')

// CIO-memory linkage (batch 31 follow-up): a review either is linked into the canonical CIO record,
// is recorded but awaiting the CIO decision, or is not linked — never a silent nothing.
eq('no request → no memory chip', cioMemoryState(null), null)
eq('none status → no memory chip', cioMemoryState({ status: 'none', label: 'Not requested', open: false }), null)
eq('publication_verified is tracked in CIO memory', cioMemoryState({ status: 'answered', label: 'x', open: false, publication_verified: true }),
  { tone: 'success', label: 'tracked in CIO memory' })
eq('research_link_verified is CIO decision pending', cioMemoryState({ status: 'answered', label: 'x', open: false, research_link_verified: true }),
  { tone: 'info', label: 'research recorded · CIO decision pending' })
eq('answered without linkage is pending', cioMemoryState({ status: 'answered', label: 'x', open: false }),
  { tone: 'warning', label: 'research published · CIO linkage pending' })
eq('queued is not yet linked', cioMemoryState({ status: 'queued', label: 'x', open: true }),
  { tone: 'neutral', label: 'not yet linked to CIO memory' })
eq('publication_verified beats research_link_verified', cioMemoryState({ status: 'answered', label: 'x', open: false, publication_verified: true, research_link_verified: true }),
  { tone: 'success', label: 'tracked in CIO memory' })

// WS-A: one consolidated freshness line; a null clock reads 'time unknown'.
const caci = by('CACI')
eq('freshness folds evidence/expiry/conviction', freshnessLine(caci),
  'evidence Oct 22 11:00 ET · expires Oct 26 11:00 ET · conviction Oct 22 11:00 ET')
eq('freshness with no signals is time unknown',
  freshnessLine({ stale: false, evidence_at: null, expires_at: null, conviction_as_of: null, review_state: null }), 'time unknown')
ok('stale leads the freshness line',
  freshnessLine({ stale: true, evidence_at: null, expires_at: null, conviction_as_of: null, review_state: null }).startsWith('Stale'))
eq('freshness folds review state and publication', freshnessLine({
  stale: false, evidence_at: null, expires_at: null, conviction_as_of: null,
  review_state: { status: 'answered', label: 'x', open: false, publication_verified: true },
}), 'evidence time unknown · expires time unknown · conviction time unknown · review answered · published')

// WS-B: workflow strip — fixed node order, states derived from real fields only.
eq('workflow key order matches the constant', WORKFLOW_ORDER.join(','), workflowStrip(caci).map(n => n.key).join(','))
eq('workflow label order matches the constant', Object.values(WORKFLOW_LABELS).join(','), workflowStrip(caci).map(n => n.label).join(','))
const caciStates = Object.fromEntries(workflowStrip(caci).map(n => [n.key, n.state]))
eq('CACI workflow states', caciStates, {
  event: 'DARK', security: 'DARK', identity: 'UNWIRED', materiality: 'UNKNOWN', instrument: 'LIVE',
  gap: 'LIVE', judgment: 'LIVE', specialist: 'LIVE', commitment: 'UNKNOWN', product: 'LIVE',
  notification: 'PARTIAL', delivery: 'UNKNOWN', outcome: 'UNKNOWN', scoring: 'LIVE', mbi: 'UNKNOWN',
})
const liveFacts: ProspectRow = {
  ...caci,
  security_guid: 'guid-1', identity_status: 'CONFIRMED',
  company_facts: {
    schema: 'CIOCompanyFacts@v1', company: { value: 'ACME Corp' }, description: { value: 'x' },
    sector: { value: 'Technology' }, industry: { value: 'Software' },
    catalyst: { headline: 'Earnings beat', status: 'CURRENT' },
  },
}
const liveStates = Object.fromEntries(workflowStrip(liveFacts).map(n => [n.key, n.state]))
ok('confirmed identity is LIVE', liveStates.identity === 'LIVE')
ok('current catalyst event is LIVE', liveStates.event === 'LIVE')
ok('security/sector/catalyst all on file is LIVE', liveStates.security === 'LIVE')

// WS-C: tooltips cover freshness, workflow and review.
ok('freshness tooltip explains the one line', /stale flag/.test(TOOLTIPS.freshness) && /time unknown/.test(TOOLTIPS.freshness))
ok('workflow tooltip names the five states', /LIVE\/PARTIAL\/UNWIRED\/DARK\/UNKNOWN/.test(TOOLTIPS.workflow))
ok('review tooltip explains publication', /publication/i.test(TOOLTIPS.review) && /canonical CIO memory/.test(TOOLTIPS.review))

// WS-D: plain text beside terse statuses.
eq('stance plain text', [stancePlainText('ADD'), stancePlainText('RE_ENTER'), stancePlainText('WATCH'), stancePlainText('HOLD'), stancePlainText(null)],
  ['posture is to add — priority only', 'posture is to re-enter on confirmation — priority only', 'posture is to watch — no action yet', 'posture is to hold — priority only', null])
eq('conviction plain text', [convictionPlainText(81), convictionPlainText(58), convictionPlainText(44), convictionPlainText(null)],
  ['high conviction', 'mid conviction', 'low conviction', 'not scored yet'])

if (failed) { console.error(`watchProspectsModel: ${failed} failure(s)`); process.exit(1) }
console.log('watchProspectsModel: all checks passed')
