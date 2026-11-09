// LQ-20261107-1269 — the CIO bottom line must read the LQ-1257 producer's OWN shape. That producer (cc-deepseek-3,
// scripts/cio_overnight_brief.py build_synopsis) sends each row as a BLOCK with its one-line summary under `line`
// ({line, tier, score, source_ids, as_of}), and the tier inside the market block. The card was written against
// strings, so without this a live synopsis would have drawn the verdict and NONE of its five rows.
// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
}
import { synopsisModel } from './synopsis.ts'

const NOW = Date.parse('2031-03-10T15:00:00Z')
const at = (h: number, m = 0) => `2031-03-10T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00Z`

// ---- the producer's block shape, verbatim from build_synopsis's return
const BLOCKS = {
  posture: 'Defensive — de-risk into the tier',
  verdict: 'ORANGE holds: cut two stops and keep the book light before the CPI print.',
  book: { line: 'Book: 4 positions, $20,000, one unprotected at $2,400.', source_ids: ['holdings'] },
  market: { line: 'Market: Orange, score 61, sector selloff rather than market-wide.', tier: 'ORANGE', score: 61, source_ids: ['market_risk:2031-03-10T14:50:00Z'] },
  reentry: { line: 'Re-entry: none ready tonight.', source_ids: [] },
  this_week: { line: 'This week: CPI Tuesday 08:30 ET.', macro: [], earnings: [], source_ids: ['macro_calendar'] },
  do_now: { line: '1 stop item, 1 needing a decision; first: DEMOA in Example Income — ADD_STOP', stop_advice_count: 1, actionable_count: 1, first: null, source_ids: [] },
  changes_if: 'the tier falls below ORANGE with breadth improving',
  as_of: at(14, 30),
  advisory_only: true,
  source_ids: ['holdings', 'market_risk:2031-03-10T14:50:00Z', 'macro_calendar'],
}
{
  const m = synopsisModel(BLOCKS, null, NOW)
  assert.equal(m.state, 'ok', 'a fresh producer synopsis is ok')
  assert.equal(m.verdict, BLOCKS.verdict)
  assert.equal(m.posture, 'Defensive — de-risk into the tier')
  assert.equal(m.risk, 'ORANGE', 'the tier lives in the market block')
  assert.equal(m.builtAt, at(14, 30), 'as_of is the build time')
  assert.equal(m.rows.length, 5, 'all five blocks draw a row')
  assert.equal(m.rows.map(r => r.key).join(','), 'book,market,reentry,this_week,do_now')
  assert.equal(m.rows[0].label, 'Book')
  assert.equal(m.rows[0].text, BLOCKS.book.line, 'the block\'s own line is the row text')
  assert.equal(m.rows[3].text, BLOCKS.this_week.line)
  assert.equal(m.notice, null)
}

// ---- a block with no readable line is not drawn, and never renders as "[object Object]"
{
  const m = synopsisModel({ verdict: 'x', book: { source_ids: [] }, market: 'Market: plain string still works.' }, null, NOW)
  assert.equal(m.rows.length, 1, 'only the row with text is drawn')
  assert.equal(m.rows[0].key, 'market')
  assert.equal(m.rows[0].text, 'Market: plain string still works.')
  assert.equal(m.risk, null, 'no tier anywhere is null, not a guess')
}

// ---- the string shape the card was first written against still works untouched
{
  const m = synopsisModel({ posture: 'Neutral', risk: 'GREEN', verdict: 'Nothing needs you.', book: 'Up 0.4%', market: 'Calm', this_week: 'FOMC', do_now: 'none' }, null, NOW)
  assert.equal(m.rows.length, 4, 'no re-entry string in this fixture: four rows, not five')
  assert.equal(m.rows[1].label, 'Market')
  assert.equal(m.rows[1].text, 'Calm')
  assert.equal(m.risk, 'GREEN')
}

// ---- an old producer synopsis is still called out, on its as_of
{
  const m = synopsisModel({ ...BLOCKS, as_of: '2031-03-09T09:00:00Z' }, null, NOW)
  assert.equal(m.state, 'stale')
  assert.ok(/past/.test(m.notice ?? '') || /not built since/.test(m.notice ?? ''), 'the stale synopsis is said in amber')
  assert.equal(m.rows.length, 5, 'a stale synopsis still draws its rows')
}

// ---- LQ-20261107-1318: the writer stamps the synopsis with the brief's run_id; it is metadata, never a row, and an
//      unstamped synopsis still draws (the card's run notice is what says the pieces cannot be tied to one build)
{
  const stamped = synopsisModel({ ...BLOCKS, run_id: 'cio-brief-aaa111' }, null, NOW)
  assert.equal(stamped.rows.length, 5, 'a run stamp is not drawn as a row')
  assert.equal(stamped.rows.map(r => r.key).join(','), 'book,market,reentry,this_week,do_now')
  assert.equal(stamped.verdict, BLOCKS.verdict)
}

console.log('synopsisShape LIVEFIX-LQ1269')
