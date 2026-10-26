// Ticker Prospectus view model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/prospectusModel.test.ts
// Synthetic tickers and made-up numbers only (public repo).
import {
  budgetView, chartRows, detailState, filePath, filterItems, mdBlocks, modelLabel, orderedSections, pageRoute, priceLines,
  scopeCounts, splitCitations, statusOf, targetRange, totals, whenEt, type ProspectusIndexItem,
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
eq('scope counts', scopeCounts(items), { holdings: 2, watch: 2, all: 4 })
eq('totals counted when server omits', totals({ items }), { ready: 2, queued: 0, running: 0, failed: 1, missing: 1 })
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
eq('price lines tone', priceLines({ id: 'p', type: 'line', title: 'p', series: [], annotations: [{ kind: 'stop', label: 'Stop', y: 10 }, { kind: 'entry', label: 'Entry', y: 12 }] }).map(l => l.tone), ['danger', 'info'])

eq('detail ready', detailState({ loading: false, doc: { symbol: 'A', sections: [{ id: 's', title: 's', body_md: 'x' }] } }), 'ready')
eq('detail 404 → missing', detailState({ loading: false, httpStatus: 404 }), 'missing')
eq('detail failed from row', detailState({ loading: false, row: { symbol: 'A', scope: 'watch', status: 'failed' } }), 'failed')
eq('detail loading', detailState({ loading: true }), 'loading')

console.log(`prospectusModel: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
