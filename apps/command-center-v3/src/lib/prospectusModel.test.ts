// Ticker Prospectus view model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/prospectusModel.test.ts
// Synthetic tickers and made-up numbers only (public repo).
import {
  coverageTone, needsRewrite, peerCell, relWindows, rowStatus, verdictTiles,
  budgetView, chartRows, detailState, filePath, filterItems, mdBlocks, modelLabel, orderedSections, pageRoute, priceLines,
  scopeCounts, splitCitations, statusOf, targetRange, totals, whenEt, type ProspectusIndexItem,
  cleanProse, coverageGroups, displayName, footnotes, isBlankValue, isFundDoc, monthLabel, monthTicks, relRows,
  footnoteLabel, sectionFootnotes, splitFootnotes, type ProspectusDoc,
} from './prospectusModel.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, JSON.stringify(got) === JSON.stringify(want), got)

const items: ProspectusIndexItem[] = [
  { symbol: 'BETA', name: 'Beta Widgets', scope: 'watch', status: 'ready', verdict_line: 'Accumulate on dips' },
  { symbol: 'ACME', name: 'Acme Corp', scope: 'holding', status: 'ready', stale: true },
  { symbol: 'GAMMA', name: 'Gamma Labs', scope: 'holding', status: 'failed' },
  { symbol: 'DELTA', name: 'Delta Rail', scope: 'watch', status: 'missing' },
]
eq('holdings filter, failures first', filterItems(items, 'holdings', '').map(i => i.symbol), ['GAMMA', 'ACME'])
eq('watch filter', filterItems(items, 'watch', '').map(i => i.symbol), ['BETA', 'DELTA'])
eq('all: holdings before watch', filterItems(items, 'all', '').map(i => i.symbol), ['GAMMA', 'ACME', 'BETA', 'DELTA'])
eq('search by name', filterItems(items, 'all', 'widg').map(i => i.symbol), ['BETA'])
eq('search by verdict', filterItems(items, 'all', 'dips').map(i => i.symbol), ['BETA'])
eq('status filter', filterItems(items, 'all', '', 'missing').map(i => i.symbol), ['DELTA'])
eq('scope counts', scopeCounts(items), { holdings: 2, watch: 2, all: 4, rewrite: 2 })
eq('totals counted when server omits', totals({ items }), { partial: 0, ready: 2, queued: 0, running: 0, failed: 1, missing: 1 })
eq('server totals win', totals({ items, totals: { ready: 9 } }).ready, 9)

const b = budgetView({ credit_remaining_usd: '120.5', today_used_usd: 4, daily_cap_usd: 20 })
eq('budget strings', [b.remaining, b.used, b.cap], ['$120.50', '$4.00', '$20.00'])
eq('budget fill + tone', [b.fill, b.tone], [0.2, 'success'])
eq('budget near cap warns', budgetView({ today_used_usd: 17, daily_cap_usd: 20 }).tone, 'warning')
eq('budget missing is neutral, never zero', [budgetView(null).remaining, budgetView(null).tone], ['—', 'neutral'])

eq('Opus chip', modelLabel('claude-opus-5-5').label, 'Opus')
eq('Fable chip', modelLabel('claude-fable-5-1').label, 'Fable')
eq('no model', modelLabel(null).tier, 'none')
eq('unknown status → missing', statusOf('weird'), 'missing')

eq('file href', filePath('acme', 'pdf'), '/api/v2/prospectus/ACME/file/pdf')
eq('file href with version', filePath('ACME', 'docx', '20261026T0100Z'), '/api/v2/prospectus/ACME/file/docx?version=20261026T0100Z')
eq('page route', pageRoute('acme'), '/prospectus/ACME')
eq('ET time, never ISO', whenEt('2026-10-26T14:00:00Z'), 'Oct 26 10:00 ET')
eq('no time', whenEt(null), '—')

const secs = orderedSections([
  { id: 'risks', title: 'Risks', body_md: 'r' },
  { id: 'summary_verdict', title: 'Summary', body_md: 's' },
  { id: 'empty', title: 'Empty', body_md: '   ' },
  { id: 'position_and_plan', title: 'Plan', body_md: 'p' },
], 'watch')
eq('sections ordered, empty + watch-plan dropped', secs.map(s => s.id), ['summary_verdict', 'risks'])

eq('md blocks', mdBlocks('## Head\nline one\nline two\n\n- a\n-  \n1. b').map(b => b.kind), ['h', 'p', 'li', 'oli'])
eq('citations split', splitCitations('Rev grew 12% [c1] and [x] stays [^c2].', new Set(['c1', 'c2'])),
  [{ text: 'Rev grew 12% ' }, { cite: 'c1' }, { text: ' and [x] stays ' }, { cite: 'c2' }, { text: '.' }])
eq('link not a citation', splitCitations('[c1](http://x)', new Set(['c1'])), [{ text: '[c1](http://x)' }])

eq('chart rows', chartRows([{ name: 'Rev', points: [['2025', 10], ['2026', 12]] }, { name: 'EPS', points: [['2026', 1.5]] }]),
  [{ x: '2025', Rev: 10 }, { x: '2026', Rev: 12, EPS: 1.5 }])
eq('target range from annotation', targetRange({ id: 't', type: 'range', title: 't', series: [{ name: 'Mean', points: [['mean', 50]] }],
  annotations: [{ kind: 'range', low: 40, high: 60 }, { kind: 'current', y: 45 }] }), { low: 40, mean: 50, high: 60, current: 45 })
eq('price lines tone', priceLines({ id: 'p', type: 'line', title: 'p', series: [], annotations: [{ kind: 'stop', label: 'Stop', y: 10 }, { kind: 'entry', label: 'Entry', y: 12 }] }).map(l => l.tone), ['danger', 'success'])

eq('detail ready', detailState({ loading: false, doc: { symbol: 'A', sections: [{ id: 's', title: 's', body_md: 'x' }] } }), 'ready')
eq('detail 404 → missing', detailState({ loading: false, httpStatus: 404 }), 'missing')
eq('detail failed from row', detailState({ loading: false, row: { symbol: 'A', scope: 'watch', status: 'failed' } }), 'failed')
eq('detail loading', detailState({ loading: true }), 'loading')

eq('needs-rewrite filter: stale or failed', filterItems(items, 'rewrite', '').map(i => i.symbol), ['GAMMA', 'ACME'])
eq('stale ready row reads Needs rewrite', rowStatus({ status: 'ready', stale: true }).label, 'Needs rewrite')
eq('missing row', rowStatus({ status: 'missing' }).label, 'Missing')
eq('partial is its own state', detailState({ loading: false, doc: { symbol: 'A', status: 'partial', sections: [{ id: 's', title: 's', body_md: 'x' }] } }), 'partial')
eq('coverage tones', ['used', 'stale', 'not_applicable', 'empty', 'failed'].map(coverageTone), ['success', 'warning', 'neutral', 'neutral', 'danger'])
eq('peer cells', [peerCell('market_cap_b', 12.345), peerCell('forward_pe', 18), peerCell('roe_pct', 21.04), peerCell('consensus', null)], ['$12.3B', '18.0×', '21.0%', '—'])
eq('rel windows only with lines', relWindows({ series: { '3M': [], '1Y': [{ name: 'A', points: [['d', 100]] }] } }), ['1Y'])
const tiles = verdictTiles({ symbol: 'ACME', scope: 'holding', verdict_line: 'HOLD — fine', facts: [
  { id: 'F1', label: 'CIO conviction', value: 72 }, { id: 'F2', label: 'Last close', value: 51 },
  { id: 'F3', label: 'Market value $', value: 1000 }, { id: 'F4', label: 'Unrealized P/L %', value: 12.5 },
  { id: 'F5', label: 'Recorded protective stop level (Example, broker)', value: 42 }, { id: 'F6', label: 'Distance from last close to stop % (Example)', value: -17.6 }] })
eq('tile verdict', [tiles[0].value, tiles[0].sub], ['HOLD', 'CIO conviction 72/100'])
eq('tile price', tiles[1].value, '$51.00')
eq('tile stop', [tiles[3].value, tiles[3].sub], ['$42.00', '17.6% below'])
eq('tile yield absent → null (not available yet)', tiles[4].value, null)
eq('watch tile position', verdictTiles({ symbol: 'B', scope: 'watch' })[2].value, 'Not held')
eq('server tiles win', verdictTiles({ symbol: 'B', blocks: { verdict_tiles: { verdict: { value: 'ADD', tone: 'success' } } } })[0].value, 'ADD')
check('needsRewrite', needsRewrite({ stale: false, status: 'failed' }) && !needsRewrite({ status: 'ready' }))

// ── v001.1 polish ──────────────────────────────────────────────────────────────────────────────────────────────────
const fdoc: ProspectusDoc = {
  symbol: 'ZETA', name: 'ZETA', scope: 'holding', verdict_line: 'HOLD — steady [F9].',
  facts: [{ id: 'F2', label: 'Revenue growth %', value: 12, unit: '%', source: 'synthetic store', as_of: '2026-01-02' },
    { id: 'F9', label: 'Last close', value: 10, source: 'synthetic prices' }, { id: 'F5', label: 'Margin', value: 30, unit: '%' }],
  sections: [
    { id: 'risks', title: 'Risks', body_md: 'Margin risk [F5] and growth [F2].' },
    { id: 'summary_verdict', title: 'Summary', body_md: 'Growth [F2, F9] holds; [x] stays prose.' },
  ],
  blocks: { scenarios: { cases: [{ case: 'base', narrative: 'Flat [F77].' }] } },
}
const fns = footnotes(fdoc)
eq('footnotes: order of first use (verdict, sections in reading order, blocks)', fns.map(f => [f.n, f.id]), [[1, 'F9'], [2, 'F2'], [3, 'F5'], [4, 'F77']])
eq('footnote carries label, value, source, as-of', [fns[1].label, fns[1].value, fns[1].source, fns[1].as_of], ['Revenue growth %', '12%', 'synthetic store', '2026-01-02'])
eq('unknown internal id still numbered, labelled honestly', fns[3].label, 'Source not recorded')
const byId = new Map(fns.map(f => [f.id, f]))
const parts = splitFootnotes('Growth [F2, F9] holds; [x] stays prose.', byId)
eq('split: no raw F-id survives; group becomes one ref', parts.map(p => 'notes' in p ? p.notes.map(n => n.n) : p.text), ['Growth', [2, 1], ' holds; [x] stays prose.'])
eq('split: muted "not reliable (…)"', splitFootnotes('Effect not reliable (t -0.4) here', byId).map(p => 'muted' in p && p.muted ? `~${p.text}` : 'text' in p ? p.text : ''), ['Effect ', '~not reliable (t -0.4)', ' here'])
eq('section footnotes ascending', sectionFootnotes(fdoc.sections![0], byId).map(f => f.n), [2, 3])
eq('presentation footnotes win', footnotes({ ...fdoc, presentation: { footnotes: [{ n: 1, id: 'F5', label: 'x' }] } } as ProspectusDoc).map(f => f.id), ['F5'])
eq('cleanProse: empty bullets, doubled spaces, space before punctuation', cleanProse('- \nA  sentence , here .\n-  real item\n*'), 'A sentence, here.\n- real item')
eq('display name: never the symbol twice', displayName(fdoc), '')
eq('display name: presentation wins', displayName({ ...fdoc, presentation: { display_name: 'Zeta Income Fund' } } as ProspectusDoc), 'Zeta Income Fund')
check('fund: fund_profile block → fund', isFundDoc({ symbol: 'Z', blocks: { fund_profile: { category: 'x' } } as never }) && !isFundDoc(fdoc))
check('fund: presentation flag wins', !isFundDoc({ symbol: 'Z', blocks: { fund_profile: { category: 'x' } }, presentation: { is_fund: false } } as never))
const cg = coverageGroups({ symbol: 'Z', source_coverage: { domains: [{ domain: 'quote_price', status: 'used' }, { domain: 'supervisor_heartbeats', status: 'not_applicable' }, { domain: 'news', status: 'empty' }, { domain: 'web', status: 'failed' }] } })
eq('coverage: n/a hidden, grouped', [cg.counts, cg.hidden], [{ used: 1, stale: 0, failed: 1, missing: 1 }, 1])
check('blank values', isBlankValue('— / —') && isBlankValue('— · —') && isBlankValue('n/a') && !isBlankValue('0.0%') && !isBlankValue('$1.00'))
eq('chartRows: merged on sorted dates', chartRows([{ name: 'A', points: [['2026-01-03', 1], ['2026-01-05', 2]] }, { name: 'B', points: [['2026-01-02', 3], ['2026-01-04', 4]] }]).map(r => r.x), ['2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05'])
eq('chartRows: categorical order kept', chartRows([{ name: 'A', points: [['Q3', 1], ['Q1', 2]] }]).map(r => r.x), ['Q3', 'Q1'])
eq('month label', [monthLabel('2026-01-14'), monthLabel('Q1')], ['Jan 26', 'Q1'])
const days: string[] = []; for (let m = 1; m <= 12; m++) for (const d of ['03', '15']) days.push(`2025-${String(m).padStart(2, '0')}-${d}`)
eq('month ticks: evenly spaced month starts', monthTicks(days, 6).map(monthLabel), ['Jan 25', 'Mar 25', 'May 25', 'Jul 25', 'Sep 25', 'Nov 25'])
eq('rel rows: empty series hidden', relRows({ series: { '1Y': [{ name: 'A', points: [['2026-01-02', 100]] }, { name: 'B', points: [['2026-01-02', null]] }] } }, '1Y').names, ['A'])
const fundTiles = verdictTiles({ symbol: 'Z', blocks: { fund_profile: { dividend_yield_pct: 3.24, expense_ratio_pct: 0.06 } } as never })
eq('yield tile reads the fund profile', fundTiles[4].value, '3.24% · 0.06%')
const stopTiles = verdictTiles({ symbol: 'Z', scope: 'holding', blocks: { stop_plan: { recommended: { level: 9.5 }, broker: { level: 9.8, state: 'resting', other_accounts: 'Acct B: filled $10.10' } }, verdict_tiles: { stop: { value: '$9.80', sub: 'resting · house $9.50 · other accounts: Acct B: filled $10.10' } } } })
eq('stop tile concise; other accounts not in the tile', [stopTiles[3].value, stopTiles[3].sub], ['$9.80 · resting', 'house $9.50'])
eq('footnote label compresses runs', [footnoteLabel([117, 118, 119, 120, 121]), footnoteLabel([3, 4]), footnoteLabel([1, 2, 3, 7])], ['117–121', '3,4', '1–3,7'])
eq('my history cites come right after the verdict', footnotes({ symbol: 'Z', verdict_line: 'x [F1]', sections: [{ id: 'summary_verdict', title: 's', body_md: 'y [F3]' }], blocks: { scenarios: { cases: [{ case: 'base', narrative: 'z [F4]' }] }, my_history: { writer_note: { summary: 'w [F2]' } } } as never }).map(f => f.id), ['F1', 'F2', 'F3', 'F4'])

console.log(`prospectusModel: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
