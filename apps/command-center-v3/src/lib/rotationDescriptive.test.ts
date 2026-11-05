// Descriptive rotation data stays visible while the advisory is withheld.
//   node --experimental-strip-types src/lib/rotationDescriptive.test.ts
import { fmtUsd, rotationDescriptive } from './rotationDescriptive.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (n: string, got: unknown, want: unknown) => check(n, got === want, got)

const withData = {
  generated_at: '2026-11-02T21:52:00Z', portfolio_total: 1234567,
  sector_overweights: [{ theme: 'Materials', pct: 12.4, target: 10, excess_dollars: 21000, top_holdings: ['AAA', 'BBB'] }],
  sector_underweights: [{ theme: 'Staples', pct: 4.1, floor: 6, gap_pct: -1.9 }],
  degraded_holdings: [{ symbol: 'XYZ' }, { symbol: 'ABC' }, 'not-a-row'],
}

const d = rotationDescriptive(withData)
eq('has data', d.hasAny, true)
eq('portfolio total', d.portfolioTotal, '$1,234,567')
eq('as of', d.asOf, '2026-11-02T21:52:00Z')
eq('three blocks', d.blocks.length, 3)
eq('overweight row label', d.blocks[0].rows[0].label, 'Materials')
eq('overweight value shows target', d.blocks[0].rows[0].value, '+12.4% vs +10.0% target')
check('overweight detail carries excess and top holdings', /excess \$21,000/.test(d.blocks[0].rows[0].detail ?? '') && /AAA, BBB/.test(d.blocks[0].rows[0].detail ?? ''))
eq('underweight row', d.blocks[1].rows[0].value, '+4.1% vs +6.0% floor')
eq('underweight gap', d.blocks[1].rows[0].detail, 'gap -1.9%')
check('degraded count excludes unreadable rows and says so', d.blocks[2].empty === '2 holding(s) flagged; 1 unreadable entry not counted', d.blocks[2].empty)
eq('one gap names the unreadable degraded row', d.gaps.length, 1)
check('the unreadable row is named in the gap', /degraded holdings: 1 unreadable entry out of 3/.test(d.gaps[0]), d.gaps)

const empty = rotationDescriptive({ sector_overweights: [], sector_underweights: [], degraded_holdings: [] })
eq('empty has no rows', empty.hasAny, false)
check('empty says so per block', empty.blocks.every(b => b.rows.length === 0) && empty.blocks[0].empty.includes('No overweight'))
eq('empty total unknown', empty.portfolioTotal, null)

const bad = rotationDescriptive({ sector_overweights: 'nope', sector_underweights: {}, degraded_holdings: 7 })
eq('non-list fields are gaps, not crashes', bad.gaps.length, 3)
eq('and nothing is invented', bad.hasAny, false)

// A list that carries unreadable entries is malformed evidence, not a measured "none" (CX1).
const malformed = rotationDescriptive({ publication: { status: 'READY', reasons: [] },
  sector_overweights: [null], sector_underweights: [7], degraded_holdings: ['bad-row'] })
const mBlock = (k: string) => malformed.blocks.find(b => b.key === k)?.empty ?? ''
check('malformed overweight says unreadable, never "No overweight"', /could not be read/.test(mBlock('overweight')) && !/No overweight/.test(mBlock('overweight')), mBlock('overweight'))
check('malformed underweight says unreadable, never "No underweight"', /could not be read/.test(mBlock('underweight')) && !/No underweight/.test(mBlock('underweight')), mBlock('underweight'))
check('malformed flagged holdings says unreadable, never "none flagged"', /could not be read/.test(mBlock('degraded')) && !/none flagged/.test(mBlock('degraded')), mBlock('degraded'))
eq('malformed entries become three gaps', malformed.gaps.filter(g => /unreadable/.test(g)).length, 3)
eq('nothing invented from malformed lists', malformed.hasAny, false)

// Readable rows beside an unreadable entry still render; the loss is stated as a gap.
const partial = rotationDescriptive({ sector_overweights: [null, { theme: 'Y', pct: 2 }], sector_underweights: [] })
eq('readable rows survive an unreadable sibling', partial.blocks[0].rows.length, 1)
check('the unreadable sibling is a stated gap', partial.gaps.some(g => /sector overweights: 1 unreadable entry out of 2/.test(g)), partial.gaps)

// Provenance class at the point of display (AGENTS §9.5) — CX2.
const PROVENANCE = ['D', 'T', 'M', 'A', 'S']
check('every block declares a provenance class', d.blocks.every(b => PROVENANCE.includes(b.provenance.class)), d.blocks.map(b => b.provenance))
check('every provenance class has a label', d.blocks.every(b => b.provenance.label.trim().length > 0))
eq('sector exposure is deterministic', d.blocks[0].provenance.class, 'D')
eq('underweight is deterministic', d.blocks[1].provenance.class, 'D')
eq('flagged count is deterministic', d.blocks[2].provenance.class, 'D')
eq('deterministic label', d.blocks[0].provenance.label, 'deterministic')

eq('no summary at all', rotationDescriptive(null).gaps[0], 'no rotation summary in the response')
eq('array summary is not a record', rotationDescriptive([]).hasAny, false)
eq('unnamed group is explicit', rotationDescriptive({ sector_overweights: [{ pct: 3 }] }).blocks[0].rows[0].label, 'unnamed group')
eq('unknown share is stated', rotationDescriptive({ sector_overweights: [{ theme: 'X' }] }).blocks[0].rows[0].value, 'share unknown')
eq('null portfolio total is not $0', rotationDescriptive({ portfolio_total: null }).portfolioTotal, null)
eq('fmtUsd rounds', fmtUsd(1234.7), '$1,235')
eq('fmtUsd rejects strings', fmtUsd('1234'), null)

// Harder shapes: a date-only clock, cached_at fallback, and rows with hostile values.
const dateOnly = rotationDescriptive({ generated_at: '2026-11-02', sector_overweights: [{ theme: 'X', pct: 1 }] })
eq('date-only clock is carried as-is', dateOnly.asOf, '2026-11-02')
eq('cached_at fills a missing generated_at', rotationDescriptive({ cached_at: '2026-11-02T20:00:00Z' }).asOf, '2026-11-02T20:00:00Z')
eq('a numeric clock is not a clock', rotationDescriptive({ generated_at: 1730000000 }).asOf, null)
eq('NaN share is "share unknown"', rotationDescriptive({ sector_overweights: [{ theme: 'X', pct: Number.NaN }] }).blocks[0].rows[0].value, 'share unknown')
eq('string share is "share unknown"', rotationDescriptive({ sector_overweights: [{ theme: 'X', pct: '12%' }] }).blocks[0].rows[0].value, 'share unknown')
eq('null rows are skipped', rotationDescriptive({ sector_overweights: [null, { theme: 'Y', pct: 2 }] }).blocks[0].rows.length, 1)
eq('top-holdings non-list is ignored', rotationDescriptive({ sector_overweights: [{ theme: 'X', pct: 1, top_holdings: 'AAA' }] }).blocks[0].rows[0].detail, null)
eq('portfolio total zero is shown, not unknown', rotationDescriptive({ portfolio_total: 0 }).portfolioTotal, '$0')
check('zero total still counts as data', rotationDescriptive({ portfolio_total: 0 }).hasAny)

// ── neutral market projection (RotationMarketResearch@v1) ───────────────────────────────────────────────
const mrOk = {
  available: true, computed_at: '2026-11-02T21:52:00Z', quote_as_of: null, freshness: 'UNKNOWN', source_gap: 'quotes not stored',
  sectors: [{ etf: 'XLB', name: 'Materials', return_1m: 2.2, return_3m: 6.2, return_6m: 9.1, rs_raw: 1.42, rs_score: 87, data_quality: 1, quality_status: 'OK' }],
  industries: [{ sector: 'Materials', industries: [{ name: 'Chemicals', return_1m: 1.1, return_3m: 3.3, return_6m: 5.5, rs_raw: 0.9, rs_score: 61, data_quality: 1 }] }],
}
const m = rotationDescriptive({ market_research: mrOk })
check('market meta present', !!m.market && m.market.available && m.market.computedAt === '2026-11-02T21:52:00Z')
eq('quotes unknown with gap', m.market?.freshness, 'UNKNOWN')
eq('source gap carried', m.market?.sourceGap, 'quotes not stored')
eq('market sector row', m.blocks.find(b => b.key === 'market-sectors')?.rows[0].label, 'Materials · XLB')
eq('returns labelled 1m/3m/6m', m.blocks.find(b => b.key === 'market-sectors')?.rows[0].value, '1m +2.2% · 3m +6.2% · 6m +9.1%')
eq('rs line from evidence', m.blocks.find(b => b.key === 'market-sectors')?.rows[0].detail, 'raw 1.42 · score 87')
eq('industry row', m.blocks.find(b => b.key === 'market-industries')?.rows[0].label, 'Materials · Chemicals')
eq('market counts as data', m.hasAny, true)
eq('market sectors are snapshot-derived', m.blocks.find(b => b.key === 'market-sectors')?.provenance.class, 'S')
eq('market industries are snapshot-derived', m.blocks.find(b => b.key === 'market-industries')?.provenance.class, 'S')
eq('snapshot-derived label', m.blocks.find(b => b.key === 'market-sectors')?.provenance.label, 'snapshot-derived')
// A default score without return evidence is not proven strength.
const mrDefault = { available: true, computed_at: '2026-11-02T21:52:00Z',
  sectors: [{ name: 'Ghost', return_1m: null, return_3m: null, return_6m: null, rs_score: 50, data_quality: 1 }] }
eq('no return evidence → RS UNKNOWN', rotationDescriptive({ market_research: mrDefault }).blocks.find(b => b.key === 'market-sectors')?.rows[0].detail, 'RS UNKNOWN (no return evidence)')
const mrQ0 = { available: true, computed_at: '2026-11-02T21:52:00Z',
  sectors: [{ name: 'Q0', return_1m: 1, return_3m: 1, return_6m: 1, rs_score: 50, data_quality: 0, quality_status: 'DEGRADED' }] }
eq('quality 0 → RS UNKNOWN', rotationDescriptive({ market_research: mrQ0 }).blocks.find(b => b.key === 'market-sectors')?.rows[0].detail, 'RS UNKNOWN (quality degraded)')
eq('naive computed_at is not a clock', rotationDescriptive({ market_research: { ...mrOk, computed_at: '2026-11-02 21:52' } }).market?.computedAt, null)
check('naive clock becomes a gap', rotationDescriptive({ market_research: { ...mrOk, computed_at: '2026-11-02 21:52' } }).gaps.some(g => g.includes('computed_at')))
eq('no market_research → null', rotationDescriptive({}).market, null)
// F5 of the Rotation-A review: a cached empty/malformed market_research must not look like data.
const mrEmpty = rotationDescriptive({ market_research: { available: false, sectors: [], industries: [], gaps: ['snapshot empty'] } })
eq('unavailable projection has no rows', mrEmpty.blocks.find(b => b.key === 'market-sectors')?.rows.length, 0)
eq('and says so', mrEmpty.blocks.find(b => b.key === 'market-sectors')?.empty, 'Market projection not available in this response.')
eq('available flag carried as false', mrEmpty.market?.available, false)
check('its gap is stated', mrEmpty.gaps.some(g => g.includes('market: snapshot empty')))
const mrMalformed = rotationDescriptive({ market_research: { sectors: 'nope', industries: {} } })
eq('malformed lists do not throw', mrMalformed.blocks.find(b => b.key === 'market-sectors')?.rows.length, 0)
eq('absent available is not true', mrMalformed.market?.available, false)
// Final contract details: quality_status KNOWN|UNKNOWN, NULL rs fields, market gaps and cache age.
const mrKnown = { available: true, computed_at: '2026-11-02T21:52:00Z',
  sectors: [{ name: 'K', return_1m: 1, return_3m: 2, return_6m: 3, rs_raw: 0.5, rs_score: 55, quality_status: 'KNOWN' }] }
eq('quality_status KNOWN with returns proves RS', rotationDescriptive({ market_research: mrKnown }).blocks.find(b => b.key === 'market-sectors')?.rows[0].detail, 'raw 0.50 · score 55')
const mrZero = { available: true, computed_at: '2026-11-02T21:52:00Z',
  sectors: [{ name: 'Z', return_1m: 0, return_3m: 0, return_6m: 0, rs_raw: 0, rs_score: 0, data_quality: 1 }] }
eq('a real zero with positive quality stays zero', rotationDescriptive({ market_research: mrZero }).blocks.find(b => b.key === 'market-sectors')?.rows[0].detail, 'raw 0.00 · score 0')
const mrNullRs = { available: true, computed_at: '2026-11-02T21:52:00Z',
  sectors: [{ name: 'N', return_1m: 1, return_3m: 1, return_6m: 1, rs_raw: null, rs_score: null, data_quality: 1 }] }
eq('returns but NULL rs fields says so', rotationDescriptive({ market_research: mrNullRs }).blocks.find(b => b.key === 'market-sectors')?.rows[0].detail, 'RS not provided')
const mrMeta = { available: true, computed_at: '2026-11-02T21:52:00Z', gaps: ['snapshot stale'],
  cache: { source: 'stored_snapshot', snapshot_read_only: true, build_age_seconds: 900 } }
eq('cache age is exposed', rotationDescriptive({ market_research: mrMeta }).market?.cacheAgeS, 900)
check('market gaps become stated gaps', rotationDescriptive({ market_research: mrMeta }).gaps.some(g => g.includes('market: snapshot stale')))

// ── the exact payload the producer serves when the advisory is not READY ────────────────────────
// scripts/lib/rotation_publication.py empties WITHHELD_FIELDS (sector_overweights, sector_underweights,
// degraded_holdings, …) and sets summary={} whenever publication.status != READY. Those emptied lists are
// a withholding, so the panel must never report them as "none" or "no sector".
const withheldStale = {
  ok: false, advisory_only: true, stale: true,
  portfolio_total: 1234567, generated_at: '2026-11-02T21:52:00Z', cached_at: '2026-11-02T21:52:00Z',
  sector_overweights: [], sector_underweights: [], degraded_holdings: [], summary: {},
  etf_candidates: [], research_candidates: [], research_rotation_ideas: [], top_rotation_ideas: [],
  top_pairs: [], top_candidates: [], sector_ladders: null, fee_swaps: [], total_annual_fee_usd: null,
  publication: { schema: 'RotationPublication@v1', status: 'STALE', reasons: ['stale_source_clock'] },
}
const w = rotationDescriptive(withheldStale)
const wBlock = (k: string) => w.blocks.find(b => b.key === k)
eq('withheld: portfolio total still shown', w.portfolioTotal, '$1,234,567')
check('withheld: overweight says withheld, not none', /withheld/i.test(wBlock('overweight')?.empty ?? ''), wBlock('overweight')?.empty)
check('withheld: underweight says withheld, not none', /withheld/i.test(wBlock('underweight')?.empty ?? ''), wBlock('underweight')?.empty)
check('withheld: flagged holdings says withheld, not none', /withheld/i.test(wBlock('degraded')?.empty ?? ''), wBlock('degraded')?.empty)
check('withheld: the status is named in the block text', /STALE/.test(wBlock('overweight')?.empty ?? ''), wBlock('overweight')?.empty)
check('withheld: the producer reason is carried', /stale_source_clock/.test(wBlock('overweight')?.empty ?? ''), wBlock('overweight')?.empty)
check('withheld: a gap states why the lists are empty', w.gaps.some(g => /withheld/i.test(g) && /STALE/.test(g)), w.gaps)
check('withheld: block text never claims a measured zero', !/none flagged|No overweight|No underweight/.test(
  [wBlock('overweight')?.empty, wBlock('underweight')?.empty, wBlock('degraded')?.empty].join(' ')))

// An unavailable verdict (not just stale) is the same withholding.
const wU = rotationDescriptive({ ...withheldStale, publication: { schema: 'RotationPublication@v1', status: 'UNAVAILABLE', reasons: ['missing_bound_source_clock'] } })
check('unavailable: still withheld with its reason', /UNAVAILABLE/.test(wU.blocks[0].empty) && /missing_bound_source_clock/.test(wU.blocks[0].empty), wU.blocks[0].empty)

// A field the response does not carry is not the same as an empty one.
const missing = rotationDescriptive({ portfolio_total: 100 })
check('absent overweight list says so', /not carried/.test(missing.blocks[0].empty), missing.blocks[0].empty)
check('absent flagged list says so', /not carried/.test(missing.blocks[2].empty), missing.blocks[2].empty)
check('absent lists become gaps', missing.gaps.filter(g => /not carried/.test(g)).length === 3, missing.gaps)

// The genuinely-empty READY case keeps its plain wording.
const reallyEmpty = rotationDescriptive({ ok: true, publication: { status: 'READY', reasons: [] },
  sector_overweights: [], sector_underweights: [], degraded_holdings: [] })
eq('ready empty keeps the plain wording', reallyEmpty.blocks[0].empty, 'No overweight sector in this response.')
check('ready empty states no withholding', !/withheld/i.test(reallyEmpty.blocks[0].empty))

console.log(`rotationDescriptive: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
