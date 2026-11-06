// node src/lib/alertsCenter.test.ts — Alerts Center fan-in (no node:assert)
import {
  dossierHref,
  entryPrimaryHref,
  filterAlerts,
  isChromeSymbol,
  realSymbols,
  rowsFromBuyReadyPackets,
  rowsFromCommunicationsEvents,
  rowsFromTradeAiSummary,
  rowsFromOpsIncidents,
} from './alertsCenter.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: boolean) {
  if (!cond) { failed++; console.error(`FAIL ${name}`) }
}

eq('ALERT is chrome', isChromeSymbol('ALERT'), true)
eq('ENTRY is chrome', isChromeSymbol('ENTRY'), true)
eq('READY is chrome', isChromeSymbol('ready'), true)
eq('ADV is real', isChromeSymbol('ADV'), false)
eq('realSymbols drops chrome', realSymbols(['ALERT', 'ENTRY', 'ADV', 'ALERT', 'TROW']), ['ADV', 'TROW'])
eq('entry href scopes ADV to Scalp', entryPrimaryHref('ADV'), '/v3/active-trader?tab=Scalp&symbol=ADV')
eq('entry href never ALERT dossier', entryPrimaryHref('ALERT'), '/v3/active-trader?tab=Scalp')
eq('dossier suppresses ALERT', dossierHref('ALERT'), null)
eq('dossier keeps ADV', dossierHref('ADV'), '/v3/watch/intelligence/ADV')

const packets = {
  rows: [
    { symbol: 'ADV', state: 'BUY_READY', saved_at: '2026-09-29T17:01:00Z', price: 12.3, zone: { position: 'in_zone', distance_pct: 0 } },
    { symbol: 'ALERT', state: 'BUY_READY', saved_at: '2026-09-29T17:01:00Z' }, // must not deep-link as ALERT
  ],
}
const entryRows = rowsFromBuyReadyPackets(packets)
eq('entry row count', entryRows.length, 2)
eq('ADV primary is Scalp', entryRows[0].href, '/v3/active-trader?tab=Scalp&symbol=ADV')
ok('ALERT packet has empty symbols', entryRows[1].symbols.length === 0)
ok('ALERT packet primary is Scalp root', entryRows[1].href === '/v3/active-trader?tab=Scalp')
ok('ALERT packet has no dossier', entryRows[1].dossierHref == null)

const events = {
  events: [
    {
      event_id: 'e1', direction: 'OUTBOUND', short_summary: 'READY ENTRY ALERT — ADV',
      entity_refs: [{ symbol: 'ALERT' }, { symbol: 'ADV' }, { symbol: 'ENTRY' }],
      created_at: '2026-09-29T17:01:00Z', message_class: 'operator_alert',
    },
    {
      event_id: 'e2', direction: 'INBOUND', short_summary: 'operator question',
      entity_refs: [{ symbol: 'ADV' }],
    },
  ],
}
const tg = rowsFromCommunicationsEvents(events)
eq('telegram outbound only', tg.length, 1)
eq('telegram symbols drop chrome', tg[0].symbols, ['ADV'])
eq('telegram href is communications', tg[0].href, '/v3/communications')

const setups = rowsFromTradeAiSummary({
  setup_run_summary: {
    run_id: '2026-09-29::1313', run_label: '1313',
    go_count: 0, wait_count: 1, nogo_count: 22, classified_count: 23, scanned_count: 23,
    count_integrity: 'RECONCILED', freshness_status: 'OK',
  },
})
eq('one setups row', setups.length, 1)
ok('setups subtitle has 0 GO', String(setups[0].subtitle || '').includes('0 GO') || String(setups[0].subtitle || '').includes('0GO') || /0\s*GO/.test(String(setups[0].subtitle)))
ok('setups does not invent GO cards', setups[0].kind === 'setups' && setups[0].symbols.length === 0)

const all = [...entryRows, ...tg, ...setups]
eq('filter Entry only', filterAlerts(all, { kind: 'entry' }).length, 2)
eq('search ADV finds entry', filterAlerts(all, { query: 'ADV' }).some(r => r.kind === 'entry' && r.symbols.includes('ADV')), true)
eq('empty query + Entry lists packets', filterAlerts(all, { query: '', kind: 'entry' }).length, 2)
eq('search ALERT does not elevate chrome dossier', filterAlerts(all, { query: 'ALERT' }).every(r => r.dossierHref !== '/v3/watch/intelligence/ALERT'), true)

const ops = rowsFromOpsIncidents({ as_of: '2026-10-23T16:20:00Z', incidents: [{id: 'monitor', title: 'Independent monitor unavailable', message: 'No operational receipt', severity: 'warning'}] })
eq('ops source works without notifier or communications', ops.length, 1)
eq('ops incident links to jobs', ops[0].href, '/v3/ops/jobs')
eq('ops filter is independent', filterAlerts([...all, ...ops], {kind: 'ops'}).length, 1)
// FQ-096: the packet index serves one row per (symbol, account). Two accounts' packets for the same symbol in the
// same state must be two alerts with two ids, and the modal's `find(r => r.id === selectedId)` must return the row
// that id names -- never the first account's price under the second account's alert (codex-cloud P1).
const twoAccounts = rowsFromBuyReadyPackets({ rows: [
  { symbol: 'SPCX', account: 'schwab_ira', state: 'BUY_READY', price: 76.19, zone: { position: 'in_zone', distance_pct: 0 } },
  { symbol: 'SPCX', account: 'schwab_taxable', state: 'BUY_READY', price: 19.05, zone: { position: 'in_zone', distance_pct: 0 } },
]})
eq('two accounts are two alerts', twoAccounts.length, 2)
ok('two accounts have two ids', twoAccounts[0].id !== twoAccounts[1].id)
ok('the first alert names its account', String(twoAccounts[0].subtitle).includes('Schwab IRA'))
ok('the second alert names its account', String(twoAccounts[1].subtitle).includes('Schwab Individual'))
ok('the id selects its own row, not the first match',
  String(twoAccounts.find(r => r.id === twoAccounts[1].id)?.subtitle).includes('$19.05'))
ok('the first id still selects the first account',
  String(twoAccounts.find(r => r.id === twoAccounts[0].id)?.subtitle).includes('$76.19'))
// one row with no account keeps the old shape and still works
const noAccount = rowsFromBuyReadyPackets({ rows: [{ symbol: 'ADV', state: 'BUY_READY' }] })
eq('an unscoped packet still has an id', noAccount[0].id, 'entry:ADV:-:BUY_READY')

if (failed) throw new Error(`alertsCenter: ${failed} failed`)
console.log('[alertsCenter] ok')
