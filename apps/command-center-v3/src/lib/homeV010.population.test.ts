// Home v010 — Action required (campaign item 4): "nothing needs action" is a claim about a population.
//
// Engineering Constitution: unknown beats wrong; UI may not contradict reality. The empty state is only ever
// claimed over a KNOWN population, and the model carries that population so the page can print it:
//   * incidents / approvals / stop advice each carry how many rows the input was READ over (null = not read), and
//     the incidents population is tallied by the account each row names ('account unknown' has its own bucket);
//   * stop advice the brief carried that the stops read did not confirm is NOT drawn as an action, so it must block
//     the empty state explicitly (`stopUnverified`) instead of vanishing from it;
//   * an input that was not read is a null, never a zero: a failed read can never look like an empty population.
// Synthetic fixtures only (no real accounts, symbols or values).
import assert from 'node:assert/strict'
import { API, buildModel, type HomeV010Inputs, type Read } from './homeV010.ts'

const NOW = Date.parse('2026-11-13T15:00:00Z')
const AT = '2026-11-13T14:59:00Z'
const read = <T,>(source: string, data: T): Read<T> => ({ state: 'OK', data, error: null, at: AT, source })

function inputs(extra: Partial<HomeV010Inputs> = {}): HomeV010Inputs {
  return {
    sinceClose: read(API.sinceClose, {
      status: 'ok', freshness: { age_seconds: 30, stale: false, window_current: true },
      cio_brief: { status: 'available', stop_advice: [], stop_read: { status: 'read', as_of: AT } },
    } as never),
    approvals: read(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } } as never),
    incidents: read(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } } as never),
    lastSeen: read(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } } as never),
    ...extra,
  }
}

// 1. The empty state carries its population: three inputs read, zero rows each.
{
  const m = buildModel(inputs(), NOW)
  assert.equal(m.actionEmpty, true)
  assert.deepEqual(m.population, {
    incidents: 0, approvals: 0, stopAdvice: 0, stopUnverified: 0, incidentAccounts: [],
  })
  console.log('ok - empty action area carries a known population (three inputs, zero rows)')
}

// 2. Rows that were read but need nothing are still counted: 3 incidents (2 accounts) with no P0/P1 is evidence,
//    not silence, and the account tally never folds 'account unknown' into a named account.
{
  const items = [
    { incident_id: 1, priority: 'INFO', alert_type: 'note', account_label: 'acct_alpha' },
    { incident_id: 2, priority: 'INFO', alert_type: 'note', account_label: 'acct_alpha' },
    { incident_id: 3, priority: 'INFO', alert_type: 'note' },
  ]
  const m = buildModel(inputs({
    incidents: read(API.incidents, { state: 'OK', items, counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } } as never),
  }), NOW)
  assert.equal(m.population.incidents, 3)
  assert.deepEqual(m.population.incidentAccounts, [{ account: 'acct_alpha', count: 2 }, { account: 'account unknown', count: 1 }])
  assert.equal(m.actionEmpty, true, 'INFO rows need no action; the population is what says so')
  console.log('ok - read rows are counted even when none is actionable, tallied by account label')
}

// 3. An unread input is null, never zero — and it keeps the card out of the empty state.
{
  const approvals = { state: 'UNKNOWN' as const, data: null, error: 'HTTP 503', at: AT, source: API.approvals }
  const m = buildModel(inputs({ approvals }), NOW)
  assert.equal(m.population.approvals, null)
  assert.equal(m.actionEmpty, false)
  assert.ok(m.unread.some(u => u.label === 'approvals'))
  console.log('ok - an unread approvals input is null (not zero) and blocks the empty state')
}

// 4. Advice the brief carried with no stop read is not an action row, so it must block the empty state itself.
{
  const sinceClose = read(API.sinceClose, {
    status: 'ok', freshness: { age_seconds: 30, stale: false, window_current: true },
    cio_brief: {
      status: 'available', stop_read: { status: 'missing' },
      stop_advice: [
        { symbol: 'aaa', answer: 'ADD_STOP', reason: 'no stop on the book' },
        { symbol: 'bbb', answer: 'RAISE', reason: 'floor below structure' },
      ],
    },
  } as never)
  const m = buildModel(inputs({ sinceClose }), NOW)
  assert.equal(m.stops.length, 0, 'unreconciled advice is never drawn as an action')
  assert.equal(m.population.stopAdvice, 2)
  assert.equal(m.population.stopUnverified, 2)
  assert.equal(m.actionEmpty, false, 'two unreconciled advices can never read as "nothing needs action"')
  console.log('ok - advice without a stop read blocks the empty state as UNKNOWN, never as silence')
}

// 5. A read stop makes the same advice an action (and clears stopUnverified): the pairing is the read, not the count.
{
  const sinceClose = read(API.sinceClose, {
    status: 'ok', freshness: { age_seconds: 30, stale: false, window_current: true },
    cio_brief: {
      status: 'available', stop_read: { status: 'read', as_of: AT },
      stop_advice: [{ symbol: 'aaa', answer: 'ADD_STOP', reason: 'no stop on the book' }],
    },
  } as never)
  const m = buildModel(inputs({ sinceClose }), NOW)
  assert.equal(m.population.stopAdvice, 1)
  assert.equal(m.population.stopUnverified, 0)
  assert.equal(m.stops.length, 1)
  assert.equal(m.actionEmpty, false)
  console.log('ok - advice paired with a stop read is an action, not an unverified population')
}

// 6. A stop read the page could not perform keeps the advice unverified (status 'unread': an unread source, so the
//    card is already out of the empty state — but the population still refuses to drop the rows).
{
  const sinceClose = read(API.sinceClose, {
    status: 'ok', freshness: { age_seconds: 30, stale: false, window_current: true },
    cio_brief: {
      status: 'available', stop_read: { status: 'unread', checked_at: AT },
      stop_advice: [{ symbol: 'aaa', answer: 'ADD_STOP', reason: 'no stop on the book' }],
    },
  } as never)
  const m = buildModel(inputs({ sinceClose }), NOW)
  assert.equal(m.population.stopUnverified, 1)
  assert.equal(m.actionEmpty, false)
  console.log('ok - a failed stop read leaves the advice unverified and named')
}

// 7. Review item-4 C1: the null-vs-zero contract is pinned for incidents too — a failed incidents read is a null,
//    never a zero, so no surface can print "0 incidents" under its own UNKNOWN line.
{
  const incidents = { state: 'UNKNOWN' as const, data: null, error: 'HTTP 503', at: AT, source: API.incidents }
  const m = buildModel(inputs({ incidents }), NOW)
  assert.equal(m.population.incidents, null)
  assert.equal(m.population.incidentAccounts, null)
  assert.equal(m.actionEmpty, false)
  assert.ok(m.unread.some(u => u.label === 'incidents'))
  console.log('ok - an unread incidents input is null (not zero) and blocks the empty state')
}

// 8. Review item-4 C1: and for stop advice — a failed since-close read is a null population, not an empty one.
{
  const sinceClose = { state: 'TIMED OUT' as const, data: null, error: 'timed out after 30 s', at: AT, source: API.sinceClose }
  const m = buildModel(inputs({ sinceClose }), NOW)
  assert.equal(m.population.stopAdvice, null)
  assert.equal(m.actionEmpty, false)
  assert.ok(m.unread.some(u => u.label === 'stop advice'))
  console.log('ok - an unread since-close input is a null stop-advice population, never zero')
}

console.log('homeV010.population: ok')
