import { dateText, decodeHistory, gapText, historyUrl, money, numberText, percent, provenanceText, segmentGeometry, sortFrom } from './holdingHistoryModel.ts'
import type { HoldingHistoryPayload } from './holdingHistoryModel.ts'
let n = 0
function eq(label: string, actual: unknown, expected: unknown) { n++; if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${label}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`) }
const stats = { times_held: null, known_holding_stretches: null, round_trip_count: null, win_rate_pct: null, realized_pl: null, known_realized_pl: null, avg_hold_days: null, median_hold_days: null, best_trip_pct: null, worst_trip_pct: null }
const p: HoldingHistoryPayload = { schema: 'HoldingHistory@v1', ok: true, as_of: '2026-10-24T20:00:00Z', range: { start_date: '2024-01-01', end_date: '2024-01-11' }, symbols: [], detail: { symbol: 'TEST', company_name: null, stats, trips: [], account_segments: [], gaps: [] }, gaps: [], provider_calls: 0, writes: 0, read_only: true }
eq('valid null stats stay null', decodeHistory(p)?.detail?.stats, stats)
eq('unknown schema refused', decodeHistory({ ...p, schema: 'Other@v1' }), null)
eq('mutation response refused', decodeHistory({ ...p, writes: 1 }), null)
eq('provider response refused', decodeHistory({ ...p, provider_calls: 1 }), null)
eq('non-read-only response refused', decodeHistory({ ...p, read_only: false }), null)
eq('wrong numeric type refused, never coerced into financial truth', decodeHistory({ ...p, detail: { ...p.detail, stats: { ...stats, realized_pl: '0' } } }), null)
eq('explicit range never inherits 30 days', historyUrl(' ax ti ', 'held_now'), '/api/v3/data-broker/holding-history?range=all&sort=held_now&symbol=AX+TI')
eq('server sort vocabulary', sortFrom('realized'), 'realized')
eq('invalid sort is safe default', sortFrom('anything'), 'round_trips')
eq('null number is not zero', numberText(null), '—')
eq('known zero remains zero', numberText(0), '0')
eq('NaN refused', money(NaN), '—')
eq('null percent not zero', percent(null), '—')
eq('format server money only', money(19.37), '$19.37')
eq('date only never shifted to previous ET day', dateText('2024-01-02'), '2024-01-02')
eq('invalid source day rejected', dateText('2024-02-31'), 'Invalid source date')
eq('naive timestamp not assumed UTC', dateText('2024-01-02T13:00:00'), '2024-01-02T13:00:00 · timezone unavailable')
eq('geometry is based on server bounds', segmentGeometry(p.range, { start_date: '2024-01-03', end_date: '2024-01-05' }), { left: 20, width: 20 })
eq('missing endpoint never inferred from today', segmentGeometry(p.range, { start_date: '2024-01-03', end_date: null, status: 'open' }), null)
eq('naive endpoints never guessed', segmentGeometry(p.range, { start_at: '2024-01-03T12:00:00', end_date: '2024-01-05' }), null)
eq('backwards segment rejected', segmentGeometry(p.range, { start_date: '2024-01-06', end_date: '2024-01-05' }), null)
eq('geometry clipped to server range', segmentGeometry(p.range, { start_date: '2023-12-25', end_date: '2024-01-03' }), { left: 0, width: 20 })
eq('provenance whitelist excludes raw account identifiers', provenanceText([{ source: 'stored_fixture', table: 'closed_rows', account_id: 'DO_NOT_RENDER_ACCOUNT_NUMBER', secret: 'not a public field' }]), ['stored_fixture · closed_rows'])
eq('only actual source gap', gapText({ source: 'fixture', reason: 'explicit_missing_capture' }), 'fixture · explicit missing capture')
console.log(`Holding history presentation model: ${n} assertions passed`)
