/** Intel consolidation (intel/v001) + Strategy two tabs (strategy/v001): redirect map, nav count, conflict rule.
 *  Synthetic fixtures only (public repo): tickers are placeholders (AAA, BBB …), values invented. */
import {
  INTEL_REDIRECTS, intelligenceRedirect, recIntelRedirect, keepQueryRedirect,
  isRealConflict, markConflictGaps, realConflictMessages, isHiddenAdvisoryRow, verdictMix,
  splitAegisByHeld, heldSymbolSet, resolveResearchIntelTab, RESEARCH_INTEL_TABS,
  groupTrades, summarizeTrades, earningsQuality, relGapPct,
} from './intelConsolidation.ts'
import { NAV, sectionPages, locateNav } from './navConfig.ts'
import { CIO_HUB_TABS, resolveCioHubTab, resolveEvidenceSubtab } from './cioHubTabs.ts'

declare const process: { exit(code?: number): never; getBuiltinModule(id: 'node:fs'): { readFileSync(p: URL, enc: 'utf8'): string } }
const readFileSync = process.getBuiltinModule('node:fs').readFileSync
let pass = 0, fail = 0
function check(name: string, cond: boolean, detail = '') { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name} ${detail}`) } }
const eq = (name: string, got: unknown, want: unknown) => check(name, JSON.stringify(got) === JSON.stringify(want), `got ${JSON.stringify(got)} want ${JSON.stringify(want)}`)

// ── Redirect map ──
eq('redirect table', INTEL_REDIRECTS.map(r => `${r.from}→${r.to}`), [
  '/advisory→/cio?tab=holdings', '/intelligence→/research-intelligence', '/closed-loop→/research-intelligence?tab=lineage',
  '/rec-intel→/strategy?tab=setups', '/hermes→/ops/engines',
])
eq('intelligence bare', intelligenceRedirect(''), '/research-intelligence')
eq('intelligence closed-loop', intelligenceRedirect('?tab=closed-loop'), '/research-intelligence?tab=lineage')
eq('intelligence inferences', intelligenceRedirect('?tab=inferences'), '/research-intelligence?tab=thesis')
eq('intelligence news', intelligenceRedirect('?tab=news'), '/research-intelligence?tab=news')
eq('intelligence research', intelligenceRedirect('?tab=research'), '/research-intelligence?tab=briefs')
eq('intelligence sources', intelligenceRedirect('?tab=sources'), '/research-intelligence?tab=sources')
eq('intelligence workflow → Ops jobs', intelligenceRedirect('?tab=workflow'), '/ops/jobs?view=workflow')
eq('intelligence command', intelligenceRedirect('?tab=command'), '/research-intelligence')
eq('intelligence quality', intelligenceRedirect('?tab=quality'), '/research-intelligence')
eq('intelligence rotation keeps its redirect', intelligenceRedirect('?tab=rotation'), '/rotation')
eq('intelligence unknown', intelligenceRedirect('?tab=zzz'), '/research-intelligence')
eq('rec-intel bare', recIntelRedirect(''), '/strategy?tab=setups')
eq('rec-intel symbol', recIntelRedirect('?symbol=aaa'), '/prospectus/AAA')
eq('rec-intel junk symbol', recIntelRedirect('?symbol=<x>'), '/strategy?tab=setups')
eq('keep query', keepQueryRedirect('/ops/engines', '?tab=Provenance&symbol=AAA'), '/ops/engines?tab=Provenance&symbol=AAA')
eq('keep query none', keepQueryRedirect('/ops/engines', ''), '/ops/engines')
eq('keep query merge', keepQueryRedirect('/a?x=1', '?y=2'), '/a?x=1&y=2')

// Every redirect target and every retired route resolves to a menu page.
const menu = new Set(NAV.flatMap(s => sectionPages(s, true)).map(p => p.to))
for (const r of INTEL_REDIRECTS) {
  const target = r.to.split('?')[0]
  check(`redirect target ${target} is a menu page or under one`, !!locateNav(target) && menu.has(locateNav(target)!.page.to))
  check(`retired ${r.from} is no longer a menu page`, !menu.has(r.from))
  check(`retired ${r.from} still locates to its new home`, !!locateNav(r.from))
}
for (const tab of ['closed-loop', 'inferences', 'news', 'research', 'sources', 'workflow', 'command', 'quality']) {
  const to = intelligenceRedirect(`?tab=${tab}`).split('?')[0]
  check(`intelligence ?tab=${tab} lands on a menu page`, !!locateNav(to) && menu.has(locateNav(to)!.page.to), to)
}

// App.tsx wires each retired route to its redirect.
const app = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8')
check('App: /advisory → /cio?tab=holdings', /path="advisory" element=.*<Navigate to="\/cio\?tab=holdings" replace/.test(app))
check('App: /closed-loop → lineage', /path="closed-loop" element=.*<Navigate to="\/research-intelligence\?tab=lineage" replace/.test(app))
check('App: /intelligence → IntelligenceRedirect', /path="intelligence" element=.*<IntelligenceRedirect \/>/.test(app))
check('App: /rec-intel → RecIntelRedirect', /path="rec-intel" element=.*<RecIntelRedirect \/>/.test(app))
check('App: /hermes → /ops/engines (query kept)', /path="hermes" element=.*<KeepQueryRedirect to="\/ops\/engines" \/>/.test(app))
check('App: /ops/engines renders the Hermes engine room', /path="ops\/engines" element=.*<HermesHub /.test(app))

// ── Nav count ──
const intel = NAV.find(s => s.id === 'intel')!
eq('Intel pages', sectionPages(intel, false).map(p => p.label), ['CIO Desk', 'Research Intel', 'Prospectus', 'Reports', 'Communications'])
const trade = NAV.find(s => s.id === 'trade')!
check('Strategy stays under Trade', sectionPages(trade, false).some(p => p.to === '/strategy'))
const ops = NAV.find(s => s.id === 'ops')!
check('Ops › Engines present', sectionPages(ops, false).some(p => p.to === '/ops/engines' && p.label === 'Engines'))
eq('/hermes locates to Ops › Engines', locateNav('/hermes')?.page.to, '/ops/engines')
eq('/advisory locates to CIO Desk', locateNav('/advisory')?.page.to, '/cio')
eq('/closed-loop locates to Research Intel', locateNav('/closed-loop')?.page.to, '/research-intelligence')
eq('/rec-intel locates to Strategy', locateNav('/rec-intel')?.page.to, '/strategy')

// ── CIO tabs ──
eq('CIO tabs', [...CIO_HUB_TABS], ['today', 'holdings', 'questions', 'report'])
eq('legacy overview → today', resolveCioHubTab('overview'), 'today')
eq('legacy decisions → today', resolveCioHubTab('decisions'), 'today')
eq('legacy research → report', resolveCioHubTab('research'), 'report')
eq('legacy capital-policy → report', resolveCioHubTab('capital-policy'), 'report')
eq('advisory alias → holdings', resolveCioHubTab('advisory'), 'holdings')
eq('research sub', resolveEvidenceSubtab('research'), 'research')
eq('capital sub', resolveEvidenceSubtab('capital-policy'), 'capital-policy')

// ── Research Intel tabs ──
eq('RI tabs', RESEARCH_INTEL_TABS.map(t => t.label), ['Briefs', 'News', 'Thesis watch', 'Lineage', 'Sources'])
eq('RI default', resolveResearchIntelTab(null), 'briefs')
eq('RI closed-loop alias', resolveResearchIntelTab('closed-loop'), 'lineage')

// ── Conflict rule (threshold synthetic: the payload serves it from config) ──
const T = 0.5
const analystOnly = { data_quality: { conflicts: ['DATA CONFLICT — ACTION SUPPRESSED', 'Analyst upside uses a different denominator than canonical current price'], action_suppressed: true } }
check('analyst-denominator note alone is not a conflict', !isRealConflict(analystOnly, T))
check('analyst note alone is not a conflict even without a threshold', !isRealConflict(analystOnly, null))
const tinyGap = { data_quality: { conflicts: ['DATA CONFLICT — ACTION SUPPRESSED', 'shares×price (10010.00) ≠ market_value (10000.00)'] } }
check('0.1% MV gap is below the threshold', !isRealConflict(tinyGap, T))
check('fails closed without a threshold', isRealConflict(tinyGap, undefined))
const zeroMv = { data_quality: { conflicts: ['canonical mark (1.00) ≠ implied-from-MV (0.00)', 'shares×price (500.00) ≠ market_value (1.00)'] } }
check('mark vs implied-from-MV near zero is real', isRealConflict(zeroMv, T))
check('gap values measured', markConflictGaps(zeroMv).every(g => g != null && g > 99))
const factsBased = { canonical_financial_facts: { current_mark: 20, implied_price_from_mv: 20.5, conflicts: ['canonical mark (20.00) ≠ implied-from-MV (20.50)'] } }
check('2.4% mark gap from facts is real', isRealConflict(factsBased, T))
const dual = { canonical_financial_facts: { price_fields: { a: 10, b: 10.01 }, conflicts: ['Dual price fields disagree: {...}'] } }
check('dual fields 0.1% apart is not real', !isRealConflict(dual, T))
const dualUnmeasured = { canonical_financial_facts: { price_fields: {}, conflicts: ['Dual price fields disagree: {...}'] } }
check('dual fields with no values stays a conflict', isRealConflict(dualUnmeasured, T))
eq('messages drop banner and analyst note', realConflictMessages({ data_quality: { conflicts: [...analystOnly.data_quality.conflicts, 'shares×price (2.00) ≠ market_value (1.00)'] } }), ['shares×price (2.00) ≠ market_value (1.00)'])
check('no conflicts → not real', !isRealConflict({}, T))
eq('relGap', relGapPct(100, 99), 1)

// ── Hidden rows + verdict mix ──
check('allocation row hidden', isHiddenAdvisoryRow({ row_class: 'allocation', symbol: 'ALLOC:equity' }))
check('ALLOC cash row hidden', isHiddenAdvisoryRow({ row_class: 'holding', symbol: 'ALLOC:cash:acct_x' }))
check('paper account row hidden', isHiddenAdvisoryRow({ row_class: 'holding', symbol: 'AAA', account: 'alpaca_x' }))
check('real holding kept', !isHiddenAdvisoryRow({ row_class: 'holding', symbol: 'AAA', account: 'broker_ira' }))
eq('verdict mix', verdictMix([
  { verdict: 'HOLD' }, { verdict: 'HOLD' }, { verdict: 'TRIM' }, { verdict: 'HOLD', verdict_suppressed: true }, { verdict: 'WAIT', row_class: 'allocation' },
]), [{ verdict: 'HOLD', count: 2 }, { verdict: 'INSUFFICIENT_DATA', count: 1 }, { verdict: 'TRIM', count: 1 }])

// ── Aegis split ──
const held = heldSymbolSet([{ symbol: 'aaa' }, { symbol: 'CASH', is_cash: true }])
const split = splitAegisByHeld([
  { inference_type: 'aegis_thesis', subject: 'AAA' }, { inference_type: 'aegis_thesis', subject: 'BBB' },
  { inference_type: 'aegis_thesis', subject: 'portfolio' }, { inference_type: 'risk', subject: 'CCC' },
], held)
eq('aegis held', split.held.map(r => r.subject), ['AAA'])
eq('aegis not held', split.notHeld.map(r => r.subject), ['BBB'])

// ── Setups ──
const now = Date.parse('2026-01-31T00:00:00Z')
const trades = [
  { account: 'broker_a', setup: 'swing', origin: 'watchlist', pnl: 100, pnl_pct: 10, close_date: '2026-01-30' },
  { account: 'broker_a', setup: 'swing', origin: 'screener', pnl: -50, pnl_pct: -5, close_date: '2025-06-01' },
  { account: 'broker_b', setup: '', origin: '', pnl: 20, pnl_pct: 2, close_date: '2026-01-20' },
  { account: 'alpaca_paper', setup: 'swing', origin: 'watchlist', pnl: 999, pnl_pct: 99, close_date: '2026-01-30' },
]
const bySetup = groupTrades(trades, 'setup', { nowMs: now, untagged: 'Not yet tagged' })
eq('setups exclude paper', bySetup.map(g => `${g.key}:${g.trades}`), ['swing:2', 'Not yet tagged:1'])
eq('setups 30d window', groupTrades(trades, 'setup', { nowMs: now, days: 30, untagged: 'Not yet tagged' }).map(g => `${g.key}:${g.trades}`), ['Not yet tagged:1', 'swing:1'])
const s = summarizeTrades('x', trades.slice(0, 2))
eq('summary', [s.trades, s.wins, s.winRatePct, s.profitFactor, s.perTrade, s.total], [2, 1, 50, 2, 25, 50])
eq('by origin', groupTrades(trades, 'origin', { nowMs: now, untagged: 'Unattributed' }).map(g => g.key).sort(), ['Unattributed', 'screener', 'watchlist'])

// ── Earnings quality ──
const eqRows = earningsQuality([
  { symbol: 'AAA', pe: 40, forward_pe: 20 }, { symbol: 'AAA', pe: 1, forward_pe: 1 }, { symbol: 'BBB', pe: null, forward_pe: 15 },
  { symbol: 'CCC', pe: null, forward_pe: null }, { symbol: 'CASH', is_cash: true },
])
eq('earnings rows', eqRows.map(r => `${r.symbol}:${r.impliedEpsGrowthPct == null ? '-' : r.impliedEpsGrowthPct.toFixed(0)}`), ['AAA:100', 'BBB:-', 'CCC:-'])
check('no-trailing note', eqRows[1].note.startsWith('No trailing earnings'))

console.log(`intelConsolidation: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
