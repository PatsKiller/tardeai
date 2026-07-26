import { useMemo } from 'react'
import { useApi } from './useApi'
import {
  EXIT_CACHE_KEY,
  finite,
  prefValue,
  text,
  type ExitEvidenceField,
  type ExitEvidenceRow,
} from '../lib/reentrySharedContext'

export const REENTRY_EVIDENCE_CONTRACT = 'reentry-evidence-v3'

export type ExitEvidenceSource = {
  key: string
  label: string
  rows: number
  available: boolean
  error?: string | null
}

export type ExitFieldCoverage = Record<ExitEvidenceField, number>

export type ReEntryExitEvidence = {
  rows: ExitEvidenceRow[]
  loading: boolean
  refreshing: boolean
  errors: string[]
  sources: ExitEvidenceSource[]
  sourceFieldCoverage: Record<string, ExitFieldCoverage>
  fullFidelity: boolean
  generatedAt: string
  contractVersion: string
  refetch: () => void
}

type Candidate = { row: ExitEvidenceRow; priority: number }

const EVIDENCE_FIELDS: ExitEvidenceField[] = [
  'account', 'trade_date', 'trade_time', 'quantity', 'price', 'proceeds_usd', 'action', 'description',
]

function unwrap(value: any): any {
  let result = value
  for (let index = 0; index < 4 && result?.data && typeof result.data === 'object'; index += 1) result = result.data
  return result ?? {}
}

function recordsFrom(value: any, keys: string[]): any[] {
  const payload = unwrap(value)
  for (const key of keys) {
    const candidate = payload?.[key]
    if (Array.isArray(candidate)) return candidate
    if (candidate && typeof candidate === 'object') return Object.values(candidate)
  }
  if (Array.isArray(payload)) return payload
  if (payload && typeof payload === 'object') {
    const values = Object.values(payload)
    if (values.length && values.every(item => item && typeof item === 'object')) return values
  }
  return []
}

function isoDay(value: any): string {
  const raw = text(value)
  if (!raw) return ''
  const parsed = new Date(raw)
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString().slice(0, 10) : raw.slice(0, 10)
}

function isoTime(value: any): string {
  const raw = text(value)
  if (!raw) return ''
  const match = raw.match(/(?:T|\s)(\d{2}:\d{2}(?::\d{2})?)/)
  return match?.[1] ?? (/^\d{2}:\d{2}/.test(raw) ? raw.slice(0, 8) : '')
}

function nestedObjects(raw: any): any[] {
  return [
    raw,
    raw?.metadata,
    raw?.transaction,
    raw?.activity,
    raw?.trade,
    raw?.execution,
    raw?.fill,
    raw?.order,
    raw?.broker,
    raw?.details,
    raw?.raw,
    raw?.source_record,
  ].filter(value => value && typeof value === 'object')
}

function pickNumber(objects: any[], keys: string[]): number | null {
  for (const object of objects) for (const key of keys) {
    const value = key.split('.').reduce((current: any, part) => current?.[part], object)
    const parsed = finite(value)
    if (parsed !== null) return parsed
  }
  return null
}

function pickText(objects: any[], keys: string[]): string {
  for (const object of objects) for (const key of keys) {
    const value = key.split('.').reduce((current: any, part) => current?.[part], object)
    const parsed = text(value)
    if (parsed) return parsed
  }
  return ''
}

function accountIdentity(value: any): string {
  let key = text(value).toLowerCase()
  if (!key) return ''
  key = key
    .replace(/\*+/g, '')
    .replace(/\b(charles\s+schwab|schwab|fidelity|alpaca|moomoo|brokerage)\b/g, '')
    .replace(/\b(account|acct)\b/g, '')
    .replace(/[^a-z0-9]+/g, '')
  const aliases: Record<string, string> = {
    rolloverira: 'rolloverira',
    traditionalira: 'rolloverira',
    ira: 'rolloverira',
    taxable: 'taxable',
    individual: 'taxable',
    brokerage: 'taxable',
    rothira: 'rothira',
    roth: 'rothira',
  }
  return aliases[key] ?? key
}

function withSource(target: Partial<Record<ExitEvidenceField, string>>, field: ExitEvidenceField, value: any, source: string) {
  if (value !== null && value !== undefined && value !== '') target[field] = source
}

function normalizeExit(raw: any, index: number, source: string): ExitEvidenceRow | null {
  const objects = nestedObjects(raw)
  const symbol = pickText(objects, [
    'symbol', 'sold_symbol', 'ticker', 'security_symbol', 'instrument.symbol', 'security.symbol', 'asset.symbol',
  ]).toUpperCase()
  if (!symbol) return null

  const dateRaw = pickText(objects, [
    'sold_at', 'stopped_at', 'triggered_at', 'close_date', 'trade_date', 'closed_at', 'executed_at',
    'transaction_date', 'activity_date', 'settlement_date', 'date', 'filled_at', 'fill_time', 'execution_time',
    'timestamp', 'created_at', 'occurred_at', 'posted_at',
  ])
  const account = pickText(objects, [
    'account', 'account_key', 'account_name', 'account_label', 'broker_account', 'account_id_masked',
    'account_display_name', 'portfolio_account', 'source_account',
  ])
  let quantity = pickNumber(objects, [
    'shares_sold', 'shares', 'quantity', 'qty', 'filled_quantity', 'filled_qty', 'executed_quantity',
    'execution_quantity', 'fill_quantity', 'shares_closed', 'closed_shares', 'sell_quantity', 'quantity_sold',
    'units', 'closed_quantity', 'position_quantity', 'total_quantity', 'net_quantity',
  ])
  quantity = quantity === null ? null : Math.abs(quantity)
  let proceeds = pickNumber(objects, [
    'proceeds_usd', 'net_proceeds_usd', 'gross_proceeds_usd', 'proceeds', 'net_proceeds', 'gross_proceeds',
    'amount', 'amount_usd', 'net_amount', 'net_amount_usd', 'gross_amount', 'gross_amount_usd', 'cash_amount',
    'net_cash', 'settlement_amount', 'principal', 'principal_amount', 'value',
  ])
  proceeds = proceeds === null ? null : Math.abs(proceeds)
  let price = pickNumber(objects, [
    'sell_price', 'exit_price', 'stop_fill_price', 'price', 'unit_price', 'trade_price', 'avg_price',
    'average_price', 'execution_price', 'executed_price', 'fill_price', 'avg_fill_price', 'average_fill_price',
    'close_price', 'filled_avg_price', 'net_price',
  ])
  price = price === null ? null : Math.abs(price)

  const derivedFields: string[] = []
  if (price === null && proceeds !== null && quantity !== null && quantity > 0) {
    price = proceeds / quantity
    derivedFields.push('price = proceeds ÷ shares')
  }
  if (quantity === null && proceeds !== null && price !== null && price > 0) {
    quantity = proceeds / price
    derivedFields.push('shares = proceeds ÷ price')
  }
  if (proceeds === null && quantity !== null && price !== null) {
    proceeds = quantity * price
    derivedFields.push('proceeds = shares × price')
  }

  const description = pickText(objects, [
    'description', 'exit_reason', 'sell_reason', 'reason', 'stop_reason', 'dismiss_reason', 'strategy',
    'classification', 'memo', 'note', 'notes', 'order_description', 'activity_description', 'transaction_description',
  ])
  const action = pickText(objects, [
    'action', 'transaction_type', 'activity_type', 'order_type', 'type', 'side', 'instruction', 'event_type',
  ])
  const externalId = pickText(objects, [
    'transaction_id', 'transactionId', 'execution_id', 'executionId', 'fill_id', 'fillId', 'trade_id', 'tradeId',
    'order_id', 'orderId', 'broker_order_id', 'activity_id', 'activityId', 'event_id', 'matched_event_id',
    'dedupe_key', 'trade_key', 'source_record_id',
  ])
  const tradeDate = isoDay(dateRaw)
  const tradeTime = isoTime(dateRaw) || pickText(objects, ['trade_time', 'time', 'execution_time', 'fill_time'])
  const eventKey = text(
    raw?.event_key,
    externalId ? `external:${source}:${externalId}` : '',
    `${source}:${symbol}:${tradeDate}:${accountIdentity(account)}:${proceeds ?? quantity ?? price ?? index}`,
  )
  const fieldSources: Partial<Record<ExitEvidenceField, string>> = {}
  withSource(fieldSources, 'account', account, source)
  withSource(fieldSources, 'trade_date', tradeDate, source)
  withSource(fieldSources, 'trade_time', tradeTime, source)
  withSource(fieldSources, 'quantity', quantity, derivedFields.some(value => value.startsWith('shares')) ? `${source} (derived)` : source)
  withSource(fieldSources, 'price', price, derivedFields.some(value => value.startsWith('price')) ? `${source} (derived)` : source)
  withSource(fieldSources, 'proceeds_usd', proceeds, derivedFields.some(value => value.startsWith('proceeds')) ? `${source} (derived)` : source)
  withSource(fieldSources, 'action', action, source)
  withSource(fieldSources, 'description', description, source)

  const row: ExitEvidenceRow = {
    event_key: eventKey,
    external_id: externalId || null,
    symbol,
    account: account || null,
    trade_date: tradeDate || null,
    trade_time: tradeTime || null,
    quantity,
    price,
    proceeds_usd: proceeds,
    action: action || null,
    description: description || null,
    import_source: source,
    matched_event_id: finite(raw?.matched_event_id),
    reconciliation: pickText(objects, ['reconciliation', 'reconciliation_state']) || null,
    event_status: pickText(objects, ['event_status', 'status']) || null,
    completion_status: pickText(objects, ['completion_status']) || null,
    operator_status: pickText(objects, ['operator_status']) || null,
    field_sources: fieldSources,
    derived_fields: derivedFields,
  }
  row.evidence_gaps = evidenceGaps(row)
  return row
}

function nearlyEqual(a: number | null, b: number | null, relativeTolerance = 0.015): boolean {
  if (a === null || b === null) return true
  const scale = Math.max(1, Math.abs(a), Math.abs(b))
  return Math.abs(a - b) / scale <= relativeTolerance
}

function accountsCompatible(a: ExitEvidenceRow, b: ExitEvidenceRow): boolean {
  if (!a.account || !b.account) return true
  return accountIdentity(a.account) === accountIdentity(b.account)
}

function compatible(a: ExitEvidenceRow, b: ExitEvidenceRow): boolean {
  if (a.symbol !== b.symbol) return false
  if (a.trade_date && b.trade_date && a.trade_date !== b.trade_date) return false
  if (!accountsCompatible(a, b)) return false
  if (a.external_id && b.external_id) return a.external_id === b.external_id
  const quantityA = finite(a.quantity); const quantityB = finite(b.quantity)
  const priceA = finite(a.price); const priceB = finite(b.price)
  const proceedsA = finite(a.proceeds_usd); const proceedsB = finite(b.proceeds_usd)
  if (!nearlyEqual(quantityA, quantityB)) return false
  if (!nearlyEqual(priceA, priceB)) return false
  if (!nearlyEqual(proceedsA, proceedsB)) return false
  if (proceedsA !== null && quantityB !== null && priceB !== null && !nearlyEqual(proceedsA, quantityB * priceB, .025)) return false
  if (proceedsB !== null && quantityA !== null && priceA !== null && !nearlyEqual(proceedsB, quantityA * priceA, .025)) return false
  return true
}

function lineage(...values: Array<string | null | undefined>): string {
  return Array.from(new Set(values.flatMap(value => String(value || '').split(',')).map(value => value.trim()).filter(Boolean))).join(', ')
}

function mergeFieldSources(preferred: ExitEvidenceRow, fallback: ExitEvidenceRow, merged: ExitEvidenceRow): Partial<Record<ExitEvidenceField, string>> {
  const result: Partial<Record<ExitEvidenceField, string>> = {}
  for (const field of EVIDENCE_FIELDS) {
    const preferredValue = preferred[field]
    const fallbackValue = fallback[field]
    if (preferredValue !== null && preferredValue !== undefined && preferredValue !== '') result[field] = preferred.field_sources?.[field] || preferred.import_source || 'preferred source'
    else if (fallbackValue !== null && fallbackValue !== undefined && fallbackValue !== '') result[field] = fallback.field_sources?.[field] || fallback.import_source || 'fallback source'
    else if (merged[field] !== null && merged[field] !== undefined && merged[field] !== '') result[field] = 'derived'
  }
  return result
}

function evidenceGaps(row: ExitEvidenceRow): string[] {
  const gaps: string[] = []
  if (!row.account) gaps.push('account unavailable from all reporting exit sources')
  if (!row.trade_date) gaps.push('exit date unavailable from all reporting exit sources')
  if (finite(row.quantity) === null) gaps.push('shares unavailable: no event source or compatible ticker aggregate supplied quantity')
  if (finite(row.price) === null) gaps.push('execution price unavailable: neither source price nor proceeds ÷ shares can be proved')
  if (finite(row.proceeds_usd) === null) gaps.push('proceeds unavailable: neither source cash nor shares × price can be proved')
  if (!row.description) gaps.push('exit reason unavailable from broker/journal descriptions')
  return gaps
}

function mergeRow(preferred: ExitEvidenceRow, fallback: ExitEvidenceRow): ExitEvidenceRow {
  const quantity = finite(preferred.quantity) ?? finite(fallback.quantity)
  const price = finite(preferred.price) ?? finite(fallback.price)
  const proceeds = finite(preferred.proceeds_usd) ?? finite(fallback.proceeds_usd)
  const derivedFields = Array.from(new Set([...(preferred.derived_fields ?? []), ...(fallback.derived_fields ?? [])]))
  let resolvedQuantity = quantity
  let resolvedPrice = price
  let resolvedProceeds = proceeds
  if (resolvedPrice === null && resolvedProceeds !== null && resolvedQuantity !== null && resolvedQuantity > 0) { resolvedPrice = resolvedProceeds / resolvedQuantity; derivedFields.push('price = proceeds ÷ shares') }
  if (resolvedQuantity === null && resolvedProceeds !== null && resolvedPrice !== null && resolvedPrice > 0) { resolvedQuantity = resolvedProceeds / resolvedPrice; derivedFields.push('shares = proceeds ÷ price') }
  if (resolvedProceeds === null && resolvedQuantity !== null && resolvedPrice !== null) { resolvedProceeds = resolvedQuantity * resolvedPrice; derivedFields.push('proceeds = shares × price') }

  const merged: ExitEvidenceRow = {
    ...fallback,
    ...preferred,
    event_key: preferred.external_id ? preferred.event_key : fallback.external_id ? fallback.event_key : preferred.event_key || fallback.event_key,
    external_id: preferred.external_id || fallback.external_id,
    symbol: preferred.symbol || fallback.symbol,
    account: preferred.account || fallback.account,
    trade_date: preferred.trade_date || fallback.trade_date,
    trade_time: preferred.trade_time || fallback.trade_time,
    quantity: resolvedQuantity,
    price: resolvedPrice,
    proceeds_usd: resolvedProceeds,
    action: preferred.action || fallback.action,
    description: preferred.description || fallback.description,
    import_source: lineage(preferred.import_source, fallback.import_source),
    matched_event_id: preferred.matched_event_id ?? fallback.matched_event_id,
    reconciliation: preferred.reconciliation || fallback.reconciliation,
    event_status: preferred.event_status || fallback.event_status,
    completion_status: preferred.completion_status || fallback.completion_status,
    operator_status: preferred.operator_status || fallback.operator_status,
    derived_fields: Array.from(new Set(derivedFields)),
  }
  merged.field_sources = mergeFieldSources(preferred, fallback, merged)
  merged.evidence_gaps = evidenceGaps(merged)
  return merged
}

function mergeCandidates(candidates: Candidate[]): ExitEvidenceRow[] {
  const clusters: Candidate[] = []
  for (const candidate of candidates.sort((a, b) => b.priority - a.priority)) {
    const exactIndex = candidate.row.external_id
      ? clusters.findIndex(cluster => cluster.row.external_id === candidate.row.external_id && cluster.row.symbol === candidate.row.symbol)
      : -1
    const compatibleIndexes = clusters
      .map((cluster, index) => ({ cluster, index }))
      .filter(item => compatible(item.cluster.row, candidate.row))
      .map(item => item.index)
    const targetIndex = exactIndex >= 0 ? exactIndex : compatibleIndexes.length === 1 ? compatibleIndexes[0] : -1
    if (targetIndex < 0) clusters.push(candidate)
    else {
      const prior = clusters[targetIndex]
      const preferred = prior.priority >= candidate.priority ? prior.row : candidate.row
      const fallback = prior.priority >= candidate.priority ? candidate.row : prior.row
      clusters[targetIndex] = { priority: Math.max(prior.priority, candidate.priority), row: mergeRow(preferred, fallback) }
    }
  }
  return clusters.map(cluster => cluster.row)
}

function aggregateRow(raw: any, index: number): ExitEvidenceRow | null {
  return normalizeExit({
    ...raw,
    symbol: raw?.symbol ?? raw?.ticker,
    trade_date: raw?.last_close_date ?? raw?.last_trade_at ?? raw?.last_close ?? raw?.trade_date,
    quantity: raw?.last_shares ?? raw?.last_quantity ?? raw?.shares_sold ?? raw?.total_shares ?? raw?.quantity,
    price: raw?.last_sell_price ?? raw?.last_exit_price ?? raw?.average_exit_price ?? raw?.avg_exit ?? raw?.last_price,
    proceeds_usd: raw?.last_proceeds ?? raw?.proceeds_usd ?? raw?.total_proceeds ?? raw?.last_amount,
    account: raw?.last_account ?? raw?.account ?? raw?.account_key,
    description: raw?.last_description ?? raw?.description,
    event_key: raw?.last_event_key,
  }, index, 'journal-ticker-aggregate')
}

function coverageFor(rows: any[], source: string): ExitFieldCoverage {
  const coverage = Object.fromEntries(EVIDENCE_FIELDS.map(field => [field, 0])) as ExitFieldCoverage
  rows.forEach((raw, index) => {
    const row = normalizeExit(raw, index, source)
    if (!row) return
    for (const field of EVIDENCE_FIELDS) {
      const value = row[field]
      if (value !== null && value !== undefined && value !== '') coverage[field] += 1
    }
  })
  return coverage
}

export function useReEntryExitEvidence(days = 365): ReEntryExitEvidence {
  const from = useMemo(() => {
    const date = new Date()
    date.setUTCDate(date.getUTCDate() - days)
    return date.toISOString().slice(0, 10)
  }, [days])

  const cache = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`, 120_000)
  const journal = useApi<any>('/api/v2/journal', 120_000)
  const byTicker = useApi<any>(`/api/v2/journal/by-ticker?from=${from}`, 120_000)
  const history = useApi<any>(`/api/v2/redeploy/history?days=${days}`, 120_000)
  const book = useApi<any>('/api/v2/redeploy/book?limit=1000&include_dismissed=1', 120_000)
  const stopped = useApi<any>(`/api/v2/stops/reentry-watch?days=${days}`, 120_000)

  const cachePayload = prefValue(cache.data)
  const cacheRows = recordsFrom(cachePayload, ['rows', 'items', 'events', 'transactions'])
  const journalRows = recordsFrom(journal.data, ['trades', 'rows', 'items', 'events', 'transactions', 'closed_trades']).filter(row => {
    const objects = nestedObjects(row)
    const day = isoDay(pickText(objects, ['close_date', 'closed_at', 'sold_at', 'trade_date', 'executed_at', 'activity_date', 'settlement_date']))
    return !day || day >= from
  })
  const historyRows = recordsFrom(history.data, ['rows', 'items', 'events', 'transactions'])
  const bookRows = recordsFrom(book.data, ['rows', 'items', 'events', 'transactions'])
  const stoppedRows = recordsFrom(stopped.data, ['rows', 'items', 'reentry_watch', 'watch', 'events'])
  const tickerRows = recordsFrom(byTicker.data, ['tickers', 'rows', 'items', 'map'])

  const rows = useMemo(() => {
    const candidates: Candidate[] = []
    const add = (rawRows: any[], source: string, priority: number) => rawRows.forEach((raw, index) => {
      const row = normalizeExit(raw, index, source)
      if (row && (!row.trade_date || row.trade_date >= from)) candidates.push({ row, priority })
    })
    add(cacheRows, 'full-fidelity-cache', 100)
    add(journalRows, 'real-closed-trade-journal', 90)
    add(bookRows, 'redeploy-book', 80)
    add(historyRows, 'redeploy-history', 70)
    add(stoppedRows, 'stops-reentry-watch', 60)

    let output = mergeCandidates(candidates)
    const aggregates = tickerRows.map(aggregateRow).filter((row): row is ExitEvidenceRow => Boolean(row))
    for (const aggregate of aggregates) {
      const matches = output.map((row, index) => ({ row, index })).filter(item => compatible(item.row, aggregate))
      if (matches.length === 1) output[matches[0].index] = mergeRow(matches[0].row, aggregate)
      else if (matches.length === 0) {
        const sameSymbolDayAccount = output.filter(row =>
          row.symbol === aggregate.symbol
          && (!aggregate.trade_date || row.trade_date === aggregate.trade_date)
          && accountsCompatible(row, aggregate),
        )
        if (sameSymbolDayAccount.length === 1) {
          const index = output.indexOf(sameSymbolDayAccount[0])
          output[index] = mergeRow(sameSymbolDayAccount[0], aggregate)
        } else if (!output.some(row => row.symbol === aggregate.symbol)) output.push(aggregate)
      }
    }

    return output
      .map(row => ({ ...row, evidence_gaps: evidenceGaps(row) }))
      .sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
  }, [cacheRows, journalRows, historyRows, bookRows, stoppedRows, tickerRows, from])

  const sources: ExitEvidenceSource[] = [
    { key: 'cache', label: 'Full-fidelity cache', rows: cacheRows.length, available: cacheRows.length > 0, error: cache.error },
    { key: 'journal', label: 'Closed-trade journal', rows: journalRows.length, available: journalRows.length > 0, error: journal.error },
    { key: 'book', label: 'Redeploy book', rows: bookRows.length, available: bookRows.length > 0, error: book.error },
    { key: 'history', label: 'Redeploy history', rows: historyRows.length, available: historyRows.length > 0, error: history.error },
    { key: 'stops', label: 'Stopped/re-entry watch', rows: stoppedRows.length, available: stoppedRows.length > 0, error: stopped.error },
    { key: 'ticker', label: 'Ticker aggregates', rows: tickerRows.length, available: tickerRows.length > 0, error: byTicker.error },
  ]
  const sourceFieldCoverage: Record<string, ExitFieldCoverage> = {
    cache: coverageFor(cacheRows, 'full-fidelity-cache'),
    journal: coverageFor(journalRows, 'real-closed-trade-journal'),
    book: coverageFor(bookRows, 'redeploy-book'),
    history: coverageFor(historyRows, 'redeploy-history'),
    stops: coverageFor(stoppedRows, 'stops-reentry-watch'),
    ticker: coverageFor(tickerRows, 'journal-ticker-aggregate'),
  }
  const errors = sources.map(source => source.error).filter((value): value is string => Boolean(value))
  const loading = [cache, journal, byTicker, history, book, stopped].some(source => source.loading)
  const refreshing = [cache, journal, byTicker, history, book, stopped].some(source => source.refreshing)
  const refetch = () => { cache.refetch(); journal.refetch(); byTicker.refetch(); history.refetch(); book.refetch(); stopped.refetch() }

  return {
    rows,
    loading,
    refreshing,
    errors,
    sources,
    sourceFieldCoverage,
    fullFidelity: cacheRows.length > 0,
    generatedAt: text(cachePayload?.generated_at),
    contractVersion: REENTRY_EVIDENCE_CONTRACT,
    refetch,
  }
}
