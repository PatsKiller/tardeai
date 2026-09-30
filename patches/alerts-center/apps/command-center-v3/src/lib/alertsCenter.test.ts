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
eq('entry href scopes ADV to Scalp', entryPrimaryHref('ADV'), '/v3/trading?tab=Scalp&symbol=ADV')
eq('entry href never ALERT dossier', entryPrimaryHref('ALERT'), '/v3/trading?tab=Scalp')
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
eq('ADV primary is Scalp', entryRows[0].href, '/v3/trading?tab=Scalp&symbol=ADV')
ok('ALERT packet has empty symbols', entryRows[1].symbols.length === 0)
ok('ALERT packet primary is Scalp root', entryRows[1].href === '/v3/trading?tab=Scalp')
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

if (failed) throw new Error(`alertsCenter: ${failed} failed`)
console.log('[alertsCenter] ok')
