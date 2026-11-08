// LQ-20261107-1269 — the age-based STALE badge. The operator: "make sure it's not static". A producer that fires and
// writes nothing missed no fixed slot, so the slot table looks calm while the page shows three-hour-old facts. The
// snapshot's OWN clock decides: 30 min while the regular session is open, 4 h otherwise.
// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
  match(s: string, re: RegExp, m?: string) { if (!re.test(s)) fail(m ?? `expected ${JSON.stringify(s)} to match ${re}`) },
}
import { stampModel, STALE_MARKET_MS, STALE_CLOSED_MS, type StampWire } from './sinceCloseStamp.ts'

// The fixture clock: Monday 2031-03-10, regular session 09:30–16:00 ET = 13:30–20:00 UTC.
const OPEN = '2031-03-10T13:30:00Z'
const CLOSE = '2031-03-10T20:00:00Z'
const at = (h: number, m = 0) => `2031-03-10T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00Z`

const stamp = (updated: string, o: { trading_day?: boolean; open?: string | null; close?: string | null; fixed?: string[] } = {}): StampWire => ({
  updated_at: updated, updated_text: '', next_refresh_at: at(22), next_refresh_text: 'Mon 03-10 · 6:00 PM ET', any_warn: false,
  sources: [], schedule: {
    trading_day: o.trading_day ?? true, market_open: o.open === undefined ? OPEN : o.open, market_close: o.close === undefined ? CLOSE : o.close,
    fixed: (o.fixed ?? []).map(t => ({ at: t, text: t.slice(11, 16) })), cio: [], grace_min: 30,
  },
})

const ms = (iso: string) => new Date(iso).getTime()

// ---- market hours: 30 min, on the snapshot clock
{
  const m = stampModel(stamp(at(14, 50)), ms(at(15, 0)))!
  assert.equal(m.stale, false, '10 min old in market hours is fresh')
  assert.equal(m.staleText, null)
  assert.equal(m.staleLimitText, '30 min during market hours')
}
{
  const m = stampModel(stamp(at(14, 20)), ms(at(15, 0)))!   // 40 min
  assert.equal(m.stale, true, '40 min old during the session is STALE')
  assert.match(m.staleText!, /40 min ago|40 min/)
  assert.match(m.staleText!, /30 min during market hours/)
  assert.equal(m.missed, false, 'no fixed slot was missed: the age alarm is a separate signal')
}
// exactly at the limit is not stale (the producer may be mid-run); one ms past it is
{
  const now = ms(at(15, 0))
  assert.equal(stampModel(stamp(new Date(now - STALE_MARKET_MS).toISOString()), now)!.stale, false, 'at the limit is not stale')
  assert.equal(stampModel(stamp(new Date(now - STALE_MARKET_MS - 1).toISOString()), now)!.stale, true, 'past the limit is stale')
}

// ---- closed: 4 h. Overnight, weekends and holidays run on the slower producer cadence; 30 min would cry wolf.
{
  const m = stampModel(stamp(at(17, 0)), ms(at(22, 0)))!      // 5 h after the close
  assert.equal(m.stale, true)
  assert.equal(m.staleLimitText, '4 h while the market is closed')
  assert.match(m.staleText!, /5 h/)
}
{
  const m = stampModel(stamp(at(19, 0)), ms(at(22, 0)))!      // 3 h after the close
  assert.equal(m.stale, false, '3 h overnight is inside the 4 h limit')
  assert.equal(stampModel(stamp(at(18, 30)), ms(at(22, 30)))!.stale, false)
}
// before the open on a trading day is "closed" too (the overnight recap is the newest thing there is)
{
  const m = stampModel(stamp(at(6, 0)), ms(at(12, 0)))!       // 6 h, pre-open
  assert.equal(m.stale, true)
  assert.equal(m.staleLimitText, '4 h while the market is closed')
}
// a weekend/holiday day has no session at all
{
  const m = stampModel(stamp('2031-03-09T18:00:00Z', { trading_day: false }), ms('2031-03-10T01:00:00Z'))!
  assert.equal(m.stale, true, 'a 7 h old weekend snapshot is stale')
  assert.equal(m.staleLimitText, '4 h while the market is closed')
}
// a missing market clock never invents market hours: the slower 4 h limit applies, so 40 min is still fresh
{
  const m = stampModel(stamp(at(14, 20), { open: null, close: null }), ms(at(15, 0)))!
  assert.equal(m.stale, false, 'no market clock means the closed-market limit, not a market-hours alarm')
  assert.equal(m.staleLimitText, '4 h while the market is closed')
  assert.equal(stampModel(stamp(at(10, 0), { open: null, close: null }), ms(at(15, 0)))!.stale, true, '5 h old with no clock is stale')
}
// a wire with no schedule at all is no model at all (unchanged)
assert.equal(stampModel({ updated_at: at(15, 0) } as StampWire, ms(at(16, 0))), null)

// the limits are the operator's numbers, exported so the badge and any surface quote the same ones
assert.equal(STALE_MARKET_MS, 30 * 60_000)
assert.equal(STALE_CLOSED_MS, 4 * 3_600_000)
console.log('sinceCloseStamp LIVEFIX-LQ1269-R')
