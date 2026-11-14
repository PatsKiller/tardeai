// LQ-20261107 H4 — the strip must not print a frozen "next refresh" that is already in the past, and its staleness
// limit must follow the cadence the producer is registered at, not one fixed number. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { stampModel, type StampWire } from './sinceCloseStamp.ts'

const at = (iso: string): number => Date.parse(iso)

/** Sunday 2026-11-08 on the registered weekend cadence (every 6 h: 00/06/12/18 ET = 05/11/17/23Z). A function
 *  declaration, not an arrow const: an object-literal arrow followed by a bare top-level block re-parses in tsc. */
function weekend(o: Partial<StampWire> = {}): StampWire {
  return {
    updated_at: '2026-11-08T17:00:00Z', updated_text: 'Sun 11-08 · 12:00 PM ET',
    next_refresh_at: '2026-11-08T19:00:00Z', next_refresh_text: 'Sun 11-08 · 2:00 PM ET',
    sources: [], any_warn: false,
    schedule: {
      trading_day: false,
      fixed: [
        { at: '2026-11-08T05:00:00Z', text: '12:00 AM' },
        { at: '2026-11-08T11:00:00Z', text: '6:00 AM' },
        { at: '2026-11-08T17:00:00Z', text: '12:00 PM' },
        { at: '2026-11-08T23:00:00Z', text: '6:00 PM' },
      ],
      cio: [], market_open: null, market_close: null, grace_min: 30,
    },
    ...o,
  }
}

// --- the operator's complaint: at 16:29 ET the strip said "next … 2:00 PM ET", a time already 2.5 h gone. The frozen
//     value is not one of the schedule's slots (an older table wrote it), so the strip must not claim a refresh missed
//     that was never scheduled: it names the next real slot and stays silent about the phantom.
{
  const m = stampModel(weekend(), at('2026-11-08T21:29:00Z'))!
  assert.equal(m.nextText, 'next 6:00 PM', 'the next FUTURE slot, not the frozen past one')
  assert.equal(m.nextText.includes('2:00 PM'), false, 'a past refresh must never be drawn as "next"')
  assert.equal(m.missedRefreshText, null, 'a time no slot carries is not a missed refresh')
}

// --- a frozen next_refresh_at that IS one of today's slots and is past: the lane failed to run it, and the strip says so
{
  const m = stampModel(weekend({ next_refresh_at: '2026-11-08T17:00:00Z', next_refresh_text: 'Sun 11-08 · 12:00 PM ET' }), at('2026-11-08T21:29:00Z'))!
  assert.equal(m.nextText, 'next 6:00 PM')
  assert.equal(m.missedRefreshText, 'The Sun 11-08 · 12:00 PM ET refresh did not run — the next slot is 6:00 PM')
}

// --- a past next_refresh_at with no later slot today: say that, and do not invent the next one
{
  const m = stampModel(weekend({ next_refresh_at: '2026-11-08T23:00:00Z', next_refresh_text: 'Sun 11-08 · 6:00 PM ET' }), at('2026-11-09T00:10:00Z'))! // Sun 19:10 ET
  assert.equal(m.nextText, 'no further slot scheduled today')
  assert.equal(m.missedRefreshText, 'The Sun 11-08 · 6:00 PM ET refresh did not run — no later slot is scheduled today')
}

// --- a next_refresh_at still ahead: the server's sentence stands unchanged, no false miss
{
  const m = stampModel(weekend({ next_refresh_at: '2026-11-08T23:00:00Z', next_refresh_text: 'Sun 11-08 · 6:00 PM ET' }), at('2026-11-08T21:29:00Z'))!
  assert.equal(m.nextText, 'next Sun 11-08 · 6:00 PM ET')
  assert.equal(m.missedRefreshText, null)
}

// --- staleness on a six-hourly day: 4.5 h is healthy (the old 4 h limit called it stale), 7 h is not
{
  const fresh = stampModel(weekend(), at('2026-11-08T21:30:00Z'))! // 4.5 h since the 12:00 build
  assert.equal(fresh.stale, false, 'a healthy 6-hourly snapshot must not be flagged stale mid-cycle')
  assert.equal(fresh.staleLimitText, '6.5 h while the market is closed')
  const late = stampModel(weekend(), at('2026-11-09T00:00:00Z'))! // 7 h since the 12:00 build
  assert.equal(late.stale, true)
  assert.match(late.staleText ?? '', /7 h ago — past the 6\.5 h while the market is closed limit/)
}

// --- a payload written by an older table that declares a two-hourly weekend no scheduler fires: the operator's 4 h
//     limit is a floor, so a healthy snapshot is not called stale by the payload's own bad cadence
{
  const old = weekend({
    schedule: {
      ...weekend().schedule,
      fixed: Array.from({ length: 12 }, (_, i) => ({ at: new Date(Date.UTC(2026, 10, 8, 5 + 2 * i)).toISOString(), text: `${i}:00` })),
    },
  })
  const m = stampModel(old, at('2026-11-08T21:30:00Z'))! // 4.5 h after the build
  assert.equal(m.staleLimitText, '4 h while the market is closed')
  assert.equal(m.stale, true, 'the floor applies, not a 2.5 h limit')
}

// --- a wire that carries no slot list keeps the operator's fixed 4 h limit (no cadence to derive one from)
{
  const m = stampModel(weekend({ schedule: { ...weekend().schedule, fixed: [] } }), at('2026-11-08T21:30:00Z'))!
  assert.equal(m.staleLimitText, '4 h while the market is closed')
  assert.equal(m.stale, true, '4.5 h is past the fixed 4 h limit')
}

// --- inside the regular session the 30 min limit still wins over any slot-derived cadence
{
  const td = weekend({
    updated_at: '2026-11-10T14:00:00Z', next_refresh_at: '2026-11-10T20:00:00Z',
    schedule: {
      trading_day: true,
      fixed: [
        { at: '2026-11-10T11:00:00Z', text: '6:00 AM' },
        { at: '2026-11-10T13:15:00Z', text: '8:15 AM' },
        { at: '2026-11-10T20:00:00Z', text: '3:00 PM' },
      ],
      cio: [], market_open: '2026-11-10T14:30:00Z', market_close: '2026-11-10T21:00:00Z', grace_min: 30,
    },
  })
  const m = stampModel(td, at('2026-11-10T15:00:00Z'))! // 1 h after the build, market open
  assert.equal(m.staleLimitText, '30 min during market hours')
  assert.equal(m.stale, true)
}

console.log('sinceCloseStamp H2H4-LQ20261107')
