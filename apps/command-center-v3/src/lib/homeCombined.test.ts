// Combined Home (operator order 2026-11-13): the reconciliation the appended operational section applies (A01–A04 +
// the verdict rule). Synthetic fixtures only: placeholder ids, symbols and accounts.
//   - a confirmed blocker stays NO; NO whose only causes are stale / unread required rows is UNKNOWN with the reason;
//     nothing here produces YES; UNKNOWN is never upgraded;
//   - A04 the Schedulers row draws the `schedulers` gate (same state, clock, source) instead of a hard-coded UNKNOWN;
//   - A03 the raw stop read and the derived coverage product are separate rows; stale coverage is "proof missing",
//     never a confirmed gap and never current;
//   - A02 a p0 gate OK that disagrees with the listed P0 population is UNKNOWN with both counts;
//   - A01 a protection category is drawn only when the item's typed fields support it; old detections carry a date.
import assert from 'node:assert/strict'
import { buildModel, type HomeV010Inputs, type Read } from './homeV010.ts'
import { detectedText, incidentCategory, reconcileModel, staleOnlyNo } from './homeCombined.ts'

const NOW = Date.parse('2026-11-13T19:00:00Z')
const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString()
const ok = <T,>(source: string, data: T): Read<T> => ({ state: 'OK', data, error: null, at: iso(0), source })
const gate = (id: string, state: string, extra: Record<string, unknown> = {}) =>
  ({ id, label: id, required: id !== 'schedulers', state, source_id: `src:${id}`, as_of: iso(60_000), ...extra })

function inputs(status: unknown, items: unknown[] = []): HomeV010Inputs {
  return {
    sinceClose: ok('/api/v2/home/since-close', { status: 'ok' } as never),
    approvals: ok('/api/v2/home' + '/approvals/summary', { count: 0 }),
    incidents: ok('/api/v2/home/incidents', { state: 'OK', items: items as never, data_integrity_24h: null }),
    lastSeen: ok('/api/v2/ui/prefs/get?key=home.last_seen', { read: { status: 'MISSING' } }),
    status: ok('/api/v2/home/status', status as never),
  }
}
const allGates = (over: Record<string, ReturnType<typeof gate>> = {}) =>
  ['p0', 'p1_blocking', 'portfolio', 'orders', 'data', 'schedulers', 'alerts'].map(id => over[id] ?? gate(id, 'OK', id === 'p0' ? { value: 0 } : {}))

function run(status: unknown, items: unknown[] = []) {
  const inp = inputs(status, items)
  const base = buildModel(inp, NOW, {})
  return { base, ...reconcileModel(base, inp, NOW) }
}

// ── verdict: stale-only NO -> UNKNOWN; confirmed blocker stays NO ────────────────────────────────────
{
  const status = { trade_ready: { verdict: 'NO', cause: 'Orders: age 14534.3 s > threshold 900 s', computed_at: iso(10_000) },
    gates: allGates({ orders: gate('orders', 'STALE', { reason: 'coverage last observed 10:04' }) }),
    blockers: [{ kind: 'row', input: 'orders', state: 'STALE', category: 'Stop coverage', cause: 'age 14534.3 s > threshold 900 s' }] }
  const r = run(status)
  assert.equal(r.base.tradeReady, 'NO', 'precondition: the served verdict is NO')
  assert.equal(r.model.tradeReady, 'UNKNOWN', 'stale proof without a confirmed blocker is UNKNOWN, not NO')
  assert.match(r.model.tradeReadyCause, /proof missing or stale, no confirmed blocker/)
  assert.match(r.model.tradeReadyCause, /stale/)
  assert.equal(r.model.why.blockers[0].category, 'Server NO shown as UNKNOWN')
}
{
  const status = { trade_ready: { verdict: 'NO', cause: 'open P0', computed_at: iso(10_000) },
    gates: allGates({ p0: gate('p0', 'GAP', { value: 1 }) }),
    blockers: [{ kind: 'count', input: 'p0', state: 'GAP', category: 'P0', cause: '1 open', count: 1 }] }
  const r = run(status)
  assert.equal(r.model.tradeReady, 'NO', 'a confirmed blocker stays NO')
  assert.equal(r.notes.verdictDowngraded, null)
}
{
  // a stale row PLUS a required gate in GAP: still NO
  const status = { trade_ready: { verdict: 'NO', cause: 'x', computed_at: iso(10_000) },
    gates: allGates({ orders: gate('orders', 'STALE'), portfolio: gate('portfolio', 'GAP') }),
    blockers: [{ kind: 'row', input: 'orders', state: 'STALE' }] }
  assert.equal(run(status).model.tradeReady, 'NO', 'a required GAP gate confirms the NO')
}
{
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'unread', computed_at: iso(10_000) }, gates: allGates() }
  assert.equal(run(status).model.tradeReady, 'UNKNOWN', 'UNKNOWN is never upgraded')
}
assert.equal(staleOnlyNo({ tradeReady: 'YES', gates: [] } as never, { blockers: [] }), null, 'never touches YES')

// ── A04 schedulers from the gate ─────────────────────────────────────────────────────────────────────
{
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(10_000) },
    gates: allGates({ schedulers: gate('schedulers', 'WARN', { reason: '34 LATE, 1 FAILING, 5 STALE', source_id: 'lane_health_current' }) }) }
  const r = run(status)
  const before = r.base.status.find(s => s.id === 'row-schedulers')!
  const after = r.model.status.find(s => s.id === 'row-schedulers')!
  // 3046 A04: v010 itself now draws the schedulers gate, from the same lane_health_current row as the gate
  // (it was a hard-coded UNKNOWN before). The combined reconcile must agree with it, not create it.
  assert.equal(before.state, 'WARN', 'precondition: v010 itself draws the schedulers gate state, not a hard-coded UNKNOWN')
  assert.equal(before.source, 'lane_health_current', 'precondition: v010 draws it from lane_health_current, the gate row')
  assert.match(before.cause || '', /34 LATE/, 'precondition: v010 carries the gate cause')
  assert.equal(after.state, 'WARN', 'the row now draws the schedulers gate')
  assert.equal(after.source, 'lane_health_current')
  assert.match(after.cause || '', /34 LATE/)
  const g = r.model.gates!.find(x => x.id === 'schedulers')!
  assert.equal(after.state, g.state, 'System Status and Trading gates show one projection')
}
{
  // no schedulers gate in the read: the UNKNOWN row stays (never invented)
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(10_000) }, gates: allGates().filter(g => g.id !== 'schedulers') }
  assert.equal(run(status).model.status.find(s => s.id === 'row-schedulers')!.state, 'UNKNOWN')
}

// ── A03 stop read vs coverage ────────────────────────────────────────────────────────────────────────
{
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(10_000) },
    gates: allGates({ orders: gate('orders', 'STALE', { as_of: iso(4 * 3600_000), reason: 'age 14534 s > 900 s' }) }) }
  const r = run(status)
  const raw = r.model.status.find(s => s.id === 'row-orders')!
  const cov = r.model.status.find(s => s.id === 'row-coverage')!
  assert.equal(raw.name, 'Stop read (raw)')
  assert.equal(cov.name, 'Stop coverage (derived)')
  assert.equal(cov.state, 'STALE', 'a stale coverage product is never shown current')
  assert.match(cov.cause || '', /Proof missing, not a confirmed gap/)
  assert.ok(r.model.status.findIndex(s => s.id === 'row-coverage') === r.model.status.findIndex(s => s.id === 'row-orders') + 1)
}
{
  const status = { trade_ready: { verdict: 'NO', cause: 'gap', computed_at: iso(10_000) },
    gates: allGates({ orders: gate('orders', 'GAP', { reason: '2 positions without a stop' }) }),
    blockers: [{ kind: 'row', input: 'orders', state: 'GAP' }] }
  const r = run(status)
  const cov = r.model.status.find(s => s.id === 'row-coverage')!
  assert.equal(cov.state, 'GAP', 'a confirmed coverage gap stays a gap')
  assert.doesNotMatch(cov.cause || '', /not a confirmed gap/)
  assert.equal(r.model.tradeReady, 'NO')
}

// ── A02 P0 populations ───────────────────────────────────────────────────────────────────────────────
{
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(10_000) }, gates: allGates() }
  const items = [{ incident_id: 'aaa111', priority: 'P0', alert_type: 'position_unprotected', category: 'Unprotected Position', symbol: 'DEMO', cause: 'no stop resting', first_seen_at: iso(3600_000) }]
  const r = run(status, items)
  const g = r.model.gates!.find(x => x.id === 'p0')!
  assert.equal(r.model.p0.length, 1)
  assert.equal(g.state, 'UNKNOWN', 'gate OK with 0 while the list shows 1: the gate cannot vouch for "no P0"')
  assert.match(g.reason || '', /gate read 0 open P0.*lists 1/)
  assert.ok(r.notes.p0Disagreement)
  assert.equal(r.model.why.blockers.some(b => b.category === 'P0 populations disagree'), true)
}
{
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(10_000) }, gates: allGates() }
  const r = run(status, [])
  assert.equal(r.model.gates!.find(x => x.id === 'p0')!.state, 'OK', 'agreeing populations keep OK')
  assert.equal(r.notes.p0Disagreement, null)
}

// ── A01 typed identity + dated detection ─────────────────────────────────────────────────────────────
{
  const digest = { incident_id: 'bbb222', priority: 'P0', alert_type: 'position_unprotected', category: 'Unprotected Position', symbol: null,
    cause: 'PR merge digest — 8 ready', first_seen_at: iso(12 * 86_400_000), stale_condition: true }
  const research = { incident_id: 'ccc333', priority: 'P0', alert_type: 'orphaned_stop', category: 'Orphaned Stop', symbol: null,
    cause: 'Research lane RAW-store health', first_seen_at: iso(54 * 86_400_000) }
  assert.equal(incidentCategory(digest).label, 'Unclassified · position_unprotected', 'no symbol: not drawn as a protection incident')
  assert.match(incidentCategory(digest).mismatch || '', /no symbol/)
  assert.equal(incidentCategory(research).label, 'Unclassified · orphaned_stop')
  assert.equal(incidentCategory({ category: 'Unprotected Position', alert_type: 'position_unprotected', symbol: 'DEMO', cause: 'x' }).mismatch, null,
    'a typed protection incident with a position keeps its category')
  assert.equal(incidentCategory({ category: 'Data Integrity', alert_type: 'data_integrity', symbol: null }).label, 'Data Integrity')
  const status = { trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(10_000) }, gates: allGates({ p0: gate('p0', 'GAP', { value: 2 }) }) }
  const r = run(status, [digest, research])
  assert.equal(r.model.p0[0].title, 'Unclassified · position_unprotected')
  assert.ok(r.model.p0[0].detail.some(d => d.startsWith('Label check:')))
  assert.ok(r.model.p0[0].detail.some(d => /stale_condition/.test(d)), 'the server stale flag is shown')
  const det = r.model.p0[1].detail.find(d => d.startsWith('Detected:'))!
  assert.match(det, /2026/, 'a 54-day-old detection carries its date, not just a weekday')
  assert.match(det, /54 d ago/)
  assert.equal(r.notes.categoryMismatches.length, 2)
  assert.equal(r.model.status.find(s => s.id === 'row-alerts')!.cause, 'Unclassified · position_unprotected')
}
assert.equal(detectedText(iso(3600_000), NOW)!.includes('2026'), false, 'a recent detection keeps the short form')
assert.equal(detectedText(null, NOW), null)

// ── nothing here can produce YES ─────────────────────────────────────────────────────────────────────
for (const v of ['NO', 'UNKNOWN']) {
  const status = { trade_ready: { verdict: v, cause: 'x', computed_at: iso(10_000) }, gates: allGates({ orders: gate('orders', 'STALE') }),
    blockers: [{ kind: 'row', input: 'orders', state: 'STALE' }] }
  assert.notEqual(run(status).model.tradeReady, 'YES')
}
// ── ids: an item without incident_id is matched by its index in the P0-filtered list, as buildModel numbers it ──────
{
  const items = [
    { priority: 'P1', category: 'Orphaned Stop', alert_type: 'raw_store_health', first_seen_at: iso(60_000) },
    { priority: 'P0', category: 'Unprotected Position', alert_type: 'stop_coverage_gap', symbol: 'DEMOA', first_seen_at: iso(60_000) },
  ]
  const r = run({ trade_ready: { verdict: 'NO', cause: 'p0', computed_at: iso(1_000) }, gates: allGates({ p0: gate('p0', 'GAP', { value: 1 }) }) }, items)
  assert.equal(r.model.p0.length, 1)
  assert.match(r.model.p0[0].title, /^Unprotected Position · DEMOA/, 'the P0 row keeps its own (supported) category')
  assert.ok(!r.model.p0[0].detail.some(d => d.startsWith('Label check')), 'never relabelled from the P1 item at full-array index 0')
}
// ── stop read not recorded + open stop advice: the operational section must not say "Nothing needs action" ────────
{
  const inp = inputs({ trade_ready: { verdict: 'UNKNOWN', cause: 'x', computed_at: iso(1_000) }, gates: allGates() })
  inp.sinceClose = ok('/api/v2/home/since-close', { status: 'ok', cio_brief: { status: 'available',
    stop_advice: [{ symbol: 'DEMOB', answer: 'ADD_STOP', qty: 10, last: 5 }] } } as never)
  const base = buildModel(inp, NOW, {})
  const r = reconcileModel(base, inp, NOW)
  assert.equal(r.model.actionEmpty, false, 'classic lists the action under STOPS READ NOT RECORDED: no empty all-clear here')
  assert.ok(r.model.unread.some(u => u.source === '/api/v2/home/since-close' && u.state === 'UNKNOWN' && /stop read not recorded/.test(u.label)))
}

console.log('homeCombined: ok')
