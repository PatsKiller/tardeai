// Pure-logic tests for tradeAiOpportunities.ts (Trade AI opportunities page, 2026-10-22).
//   node --experimental-strip-types src/lib/tradeAiOpportunities.test.ts
import {
  applyFilters, buildTiles, chgText, filterChips, floatBand, floatText, l2View, latestAlertFor, NO_FILTERS,
  normDecision, sortOpportunities, stars, toOpportunity, l2Brief, catalystVerdictOf, readinessOf,
} from './tradeAiOpportunities.ts'
import { TRADE_AI_FIXTURE } from './tradeAiOpportunities.fixture.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('tradeAiOpportunities')
const all = (TRADE_AI_FIXTURE.scanner.tickers as unknown as any[]).map(toOpportunity)

check('decisions normalised', normDecision('MANUAL_REVIEW') === 'MANUAL' && normDecision('NO-GO') === 'AVOID' && normDecision('go') === 'GO')
check('float from float_m', all.find(r => r.sym === 'BHVN')?.float === 128.56)
check('zero float is unknown, not micro', toOpportunity({ symbol: 'Z', float_m: '0' }).float === null && toOpportunity({ symbol: 'Z', float_m: 0.0 }).float === null)
check('empty catalyst is null, never ""', all.find(r => r.sym === 'HTCO')?.catalyst === null)
check('Gate 2 fields are null until served', all.every(r => r.catalystGrade === null && r.act === null && r.validation === null && r.catalystType === null))
const tiles = buildTiles(all, NO_FILTERS)
check('six tiles', tiles.length === 6)
check('GO tile counts GO rows', tiles[0].value === all.filter(r => r.decision === 'GO').length)
check('decision tiles name today\'s universe, not the latest run', ['go', 'wait', 'manual'].every(k => {
  const t = tiles.find(x => x.key === k)
  return !!t && t.hint.startsWith(`today's universe · ${all.length} rows`) && /LATEST RUN/.test(t.tip ?? '')
}))
check('grade tile disabled without Gate 2', tiles.find(t => t.key === 'grade')?.disabled === true && tiles.find(t => t.key === 'grade')?.value === null)
check('float tile counts < 5M', tiles.find(t => t.key === 'float')?.value === all.filter(r => r.float != null && r.float < 5).length)
const micro = applyFilters(all, { ...NO_FILTERS, floatMax: 5 })
check('float filter', micro.length > 0 && micro.every(r => (r.float ?? 99) < 5))
const hot = applyFilters(all, { ...NO_FILTERS, rvolMin: 10, dec: 'MANUAL' })
check('combined filters', hot.every(r => (r.rvol ?? 0) >= 10 && r.decision === 'MANUAL'))
check('sector filter', applyFilters(all, { ...NO_FILTERS, sector: 'Healthcare' }).every(r => r.sector === 'Healthcare'))
check('chips name each filter', filterChips({ ...NO_FILTERS, floatMax: 5, rvolMin: 10 }).map(c => c.label).join('|') === 'Float < 5M|RVOL ≥ 10×')
const byFloat = sortOpportunities(all, 'float')
check('float sort ascending, unknown last', (byFloat[0].float ?? 0) <= (byFloat[1].float ?? 0) && byFloat[byFloat.length - 1].float === null || byFloat.every(r => r.float != null))
check('default sort puts GO first', sortOpportunities(all, 'score')[0].decision === 'GO')
check('rvol sort descending', (sortOpportunities(all, 'rvol')[0].rvol ?? 0) >= (sortOpportunities(all, 'rvol')[1].rvol ?? 0))
check('float band', floatBand(0.5) === 5 && floatBand(12) === 20 && floatBand(50) === null && floatBand(null) === null)
check('formatting', floatText(3.97) === '3.97M' && floatText(128.56) === '128.6M' && chgText(25) === '+25.0%' && stars(3) === '★★★☆☆' && stars(null) === '—')

const row = latestAlertFor(TRADE_AI_FIXTURE.alerts, 'bhvn')
check('latest alert row found case-insensitively', row?.symbol === 'BHVN')
const l2 = l2View(row)
check('L2 watched with state', l2.watched && l2.state === 'APPROACHING')
check('spread chip from l2.spread_bps', l2.entry.find(c => c.key === 'spread')?.on === true && l2.entry.find(c => c.key === 'spread')?.value === '6 bps')
check('depth ratio chip', l2.entry.find(c => c.key === 'imbalance')?.value === '2.8 : 1')
check('served signal lit', l2.entry.find(c => c.key === 'volume_acceleration')?.on === true)
check('served signal not lit', l2.entry.find(c => c.key === 'ask_refill')?.on === false)
check('exit signals are not served → null', l2.exit.every(c => c.on === null))
check('summary counts lit entry signals', /entry signals lit/.test(l2.summary))
const none = l2View(latestAlertFor(TRADE_AI_FIXTURE.alerts, 'SKYQ'))
check('unwatched symbol says so', !none.watched && none.state === 'NOT WATCHED' && none.entry.every(c => c.on === null))
check('stale book flagged', l2View({ l2: { age_s: 240 }, signals: {} }).stale === true)

// ── 2026-10-23 alignment (SAIQ): shared catalyst verdict + readiness, honest L2 line ──────────────────────────
const SAIQ = {
  symbol: 'SAIQ', decision: 'MANUAL_REVIEW', catalyst: 'WISeSat.Space and SEALSQ Advance Satellite Cybersecurity',
  catalyst_source: 'yahoo_finance', catalyst_verified: false, catalyst_confidence: 0.0,
  setup_readiness: {
    schema: 'SetupReadiness@v1', status: 'NOT_READY', ready: false, passed: 4, required: 5,
    driven_by: [{ id: 'float', label: 'Float', status: 'PASSED', value_text: '2.21M', rule: '≤ 20M' },
      { id: 'catalyst', label: 'Verified catalyst', status: 'FAILED', value_text: 'unverified headline', rule: 'verified, current session' }],
    missing: ['Verified catalyst: unverified headline — scan marked it NOT verified (yahoo_finance, confidence 0); Hermes 08:25: no clear catalyst (no primary source)'],
    blockers: [], summary: 'NOT READY — needs 5/5, has 4/5 · missing: …',
    catalyst: { status: 'UNVERIFIED_HEADLINE', reason: 'scan marked it NOT verified (yahoo_finance, confidence 0); Hermes 08:25: no clear catalyst (no primary source)', text: 'WISeSat.Space and SEALSQ Advance Satellite Cybersecurity' },
  },
}
const saiq = toOpportunity(SAIQ)
check('SAIQ: served verdict is UNVERIFIED_HEADLINE, never the catalyst', saiq.catalystVerdict.status === 'UNVERIFIED_HEADLINE' && saiq.catalystVerdict.served && saiq.catalystVerdict.label === 'unverified headline')
check('SAIQ: readiness parsed — 4/5, one missing line naming Hermes', saiq.readiness?.status === 'NOT_READY' && saiq.readiness.passed === 4 && /Hermes 08:25/.test(saiq.readiness.missing[0]))
check('no served verdict + verified=false → unverified headline (fallback)', catalystVerdictOf({ catalyst: 'X', catalyst_verified: false }).status === 'UNVERIFIED_HEADLINE')
check('fallback never invents VERIFIED', catalystVerdictOf({ catalyst: 'X', catalyst_verified: true }).status === 'UNVERIFIED_HEADLINE')
check('no headline → UNKNOWN', catalystVerdictOf({}).status === 'UNKNOWN')
check('readiness absent → null', readinessOf({}) === null && readinessOf({ setup_readiness: { schema: 'Other' } }) === null)
const veto = { symbol: 'SAIQ', kind: 'PREMARKET_WATCH', verdict: 'VETO', at: '2026-10-23T08:55:01-04:00',
  veto_reasons: ['BELOW_PM_VWAP', 'L2_ASK_HEAVY'], l2: { spread_bps: 14.9, depth_ratio: 0.191, age_s: 1, source: 'moomoo', levels: 10 }, signals: null }
const b = l2Brief(veto)
check('AT veto is named as AT, not as L2', b.text.startsWith('AT veto') && !/L2 veto/.test(b.text))
check('lit count is over computed signals (2), not 5', b.text.includes('L2 1/2'))
check('veto reasons in the tooltip', /below pm vwap, l2 ask heavy/.test(b.tip) && /08:55 ET/.test(b.tip))
check('unwatched brief', l2Brief(null).text === 'AT · not watched')

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
