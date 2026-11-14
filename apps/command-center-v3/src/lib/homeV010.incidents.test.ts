// Combined Home item 2 (campaign 8H): ONE typed, account-aware incident projection.
//   * the identity of a row is its class + subject + account, drawn from TYPED fields — a position class that names
//     no symbol says "position not named", a row with no account says "account unknown";
//   * a dotted ticker is one symbol (BRK.B stays BRK.B);
//   * a condition the source has not re-observed is labelled STALE with its age — still shown, never fresh;
//   * counts come from priority/stale fields only: no text ever produces an "all clear"; digests are not P0s.
// Synthetic fixtures only (no real accounts, symbols or values).
import assert from 'node:assert/strict'
import { API, buildModel, incidentDetail, incidentTitle, type HomeV010Inputs, type IncidentItem, type Read } from './homeV010.ts'

const NOW = Date.parse('2026-11-14T05:00:00Z')
const AT = '2026-11-14T04:59:00Z'
const read = <T,>(source: string, data: T): Read<T> => ({ state: 'OK', data, error: null, at: AT, source })
const CLEAR = (items: IncidentItem[]): HomeV010Inputs => ({
  sinceClose: read(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } } as never),
  approvals: read(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } } as never),
  incidents: read(API.incidents, { state: 'OK', items, counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } } as never),
  lastSeen: read(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } } as never),
})
// A function declaration (not an arrow returning `({…})`): an arrow-returned object literal directly above a `{`
// block is mis-parsed by tsc as a type (TS1003 at the first value). Runtime is identical.
function item(extra: Partial<IncidentItem> = {}): IncidentItem {
  return {
    incident_id: 1, alert_type: 'orphaned_stop', category: 'Orphaned Stop', priority: 'P1',
    symbol: null, account_label: null, first_seen_at: '2026-11-01T00:00:00Z', last_seen_at: '2026-11-02T05:00:00Z',
    failed_checks: 3, cause: 'synthetic cause', stale_condition: true, ttl_h: 24, ...extra,
  }
}

// 1. A position-class row that names no position says so, and says whose account is not known.
{
  const t = incidentTitle(item({}))
  assert.equal(t, 'Orphaned Stop · position not named · account unknown')
  const d = incidentDetail(item({}), NOW)
  assert.ok(d.some(x => /^Condition: STALE — not re-observed for 12 d \(ttl 24 h\)/.test(x)), d.join(' | '))
}

// 2. A dotted ticker is one symbol, upper-cased, never split at the dot.
{
  const t = incidentTitle(item({ alert_type: 'position_unprotected', category: 'Unprotected Position', priority: 'P0', symbol: 'brk.b', account_label: 'acct_alpha' }))
  assert.equal(t, 'Unprotected Position · BRK.B · acct_alpha')
  assert.match(t, /BRK\.B/, 'the dot stays in the symbol')
}

// 3. A re-observed condition carries no STALE line; an unverified one says age not verified.
{
  assert.doesNotMatch(incidentDetail(item({ stale_condition: false }), NOW).join(' | '), /STALE/)
  assert.match(incidentDetail(item({ stale_condition: null, ttl_h: null }), NOW).join(' | '), /Condition: age not verified \(the producer carries no ttl for this class\)/)
}

// 4. Digest classes are not P0s and do not become action rows: the projection reads typed priorities only.
{
  const digests: IncidentItem[] = [
    item({ incident_id: 11, alert_type: 'research_update', category: 'Research Update', priority: 'INFO', cause: 'STOP HEALTH — no orphans found; naked positions: 0' }),
    item({ incident_id: 12, alert_type: 'paper_proposal', category: 'Paper Proposal', priority: 'INFO' }),
    item({ incident_id: 13, alert_type: 'job_telemetry', category: 'Job Telemetry', priority: 'INFO' }),
  ]
  const m = buildModel(CLEAR(digests), NOW)
  assert.equal(m.p0.length, 0)
  assert.equal(m.p1Count, 0)
  assert.equal(m.actionEmpty, true, 'no typed action row -> the clear line, and it is not text-derived')
}

// 5. NO TEXT EVER CLEARS THE PAGE. A P1 whose own words say "no orphans found" still counts, and its cause text
//    cannot lower the count. (The inverse of the false all-clear this campaign exists to remove.)
{
  const m = buildModel(CLEAR([item({ cause: 'STOP HEALTH — no orphans found; naked positions: 0; orphaned stops: none' })]), NOW)
  assert.equal(m.p1Count, 1)
  assert.equal(m.p1Stale, 1)
  assert.equal(m.actionEmpty, false)
  assert.match(m.p1Accounts![0].account, /account unknown/)
}

// 6. The account-aware tally: per account label, stale split, and rows with no account are their own bucket —
//    never folded into a real account.
{
  const m = buildModel(CLEAR([
    item({ incident_id: 21, account_label: 'acct_alpha', stale_condition: false }),
    item({ incident_id: 22, account_label: 'acct_alpha', stale_condition: true }),
    item({ incident_id: 23, account_label: null, stale_condition: false }),
  ]), NOW)
  assert.equal(m.p1Count, 3)
  assert.equal(m.p1Stale, 1)
  assert.deepEqual([...m.p1Accounts!].sort((a, b) => a.account.localeCompare(b.account)), [
    { account: 'account unknown', count: 1, stale: 0 },
    { account: 'acct_alpha', count: 2, stale: 1 },
  ])
}

// 7. A P0 is drawn with the same identity + condition lines (the view's header marks STALE from the row flag).
{
  const m = buildModel(CLEAR([item({ alert_type: 'position_unprotected', category: 'Unprotected Position', priority: 'P0', account_label: 'acct_beta' })]), NOW)
  assert.equal(m.p0.length, 1)
  assert.equal(m.p0[0].title, 'Unprotected Position · position not named · acct_beta')
  assert.equal(m.p0[0].stale, true)
  assert.ok(m.p0[0].detail.some(d => /not re-observed/.test(d)))
}

console.log('homeV010.incidents: ok')
