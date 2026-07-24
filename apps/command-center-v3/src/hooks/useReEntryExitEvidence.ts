import { useMemo } from 'react'
import { useApi } from './useApi'
import {
  EXIT_CACHE_KEY,
  finite,
  prefValue,
  text,
  type ExitEvidenceRow,
} from '../lib/reentrySharedContext'

export type ExitEvidenceSource = {
  key: string
  label: string
  rows: number
  available: boolean
  error?: string | null
}

export type ReEntryExitEvidence = {
  rows: ExitEvidenceRow[]
  loading: boolean
  refreshing: boolean
  errors: string[]
  sources: ExitEvidenceSource[]
  fullFidelity: boolean
  generatedAt: string
  refetch: () => void
}

function unwrap(value: any): any {
  let result = value
  for (let index = 0; index < 3 && result?.data && typeof result.data === 'object'; index += 1) result = result.data
  return result ?? {}
}

function arrayFrom(value: any, keys: string[]): any[] {
  const payload = unwrap(value)
  for (const key of keys) if (Array.isArray(payload?.[key])) return payload[key]
  return Array.isArray(payload) ? payload : []
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

function normalizeExit(raw: any, index: number, source: string): ExitEvidenceRow | null {
  const symbol = text(raw?.symbol, raw?.sold_symbol, raw?.ticker, raw?.security_symbol).toUpperCase()
  if (!symbol) return null
  const dateRaw = raw?.sold_at ?? raw?.stopped_at ?? raw?.triggered_at ?? raw?.close_date
    ?? raw?.trade_date ?? raw?.closed_at ?? raw?.executed_at ?? raw?.transaction_date ?? raw?.date
  const quantityRaw = finite(raw?.shares_sold, raw?.shares, raw?.quantity, raw?.qty, raw?.filled_quantity)
  const quantity = quantityRaw === null ? null : Math.abs(quantityRaw)
  const proceedsRaw = finite(raw?.proceeds_usd, raw?.net_proceeds_usd, raw?.proceeds, raw?.amount, raw?.net_amount)
  const proceeds = proceedsRaw === null ? null : Math.abs(proceedsRaw)
  let price = finite(raw?.sell_price, raw?.exit_price, raw?.stop_fill_price, raw?.price, raw?.avg_price, raw?.execution_price, raw?.average_price)
  if (price === null && proceeds !== null && quantity !== null && quantity > 0) price = proceeds / quantity
  const metadata = raw?.metadata && typeof raw.metadata === 'object' ? raw.metadata : {}
  const description = text(
    raw?.description, raw?.exit_reason, raw?.sell_reason, raw?.reason, raw?.stop_reason,
    raw?.dismiss_reason, raw?.strategy, raw?.classification, metadata?.description,
  )
  const action = text(raw?.action, raw?.transaction_type, raw?.order_type, raw?.type)
  const eventKey = text(
    raw?.event_key, raw?.trade_key, raw?.dedupe_key, raw?.transaction_id,
    raw?.matched_event_id, raw?.event_id, raw?.id,
    `${source}:${symbol}:${isoDay(dateRaw)}:${text(raw?.account, raw?.account_key)}:${proceeds ?? quantity ?? index}`,
  )
  return {
    event_key: eventKey,
    symbol,
    account: text(raw?.account, raw?.account_key, raw?.account_name, raw?.broker_account) || null,
    trade_date: isoDay(dateRaw) || null,
    trade_time: isoTime(dateRaw) || text(raw?.trade_time, raw?.time) || null,
    quantity,
    price,
    proceeds_usd: proceeds,
    action: action || null,
    description: description || null,
    import_source: text(raw?.import_source, raw?.source_system, raw?.source, source) || source,
    matched_event_id: finite(raw?.matched_event_id),
    reconciliation: text(raw?.reconciliation) || null,
    event_status: text(raw?.event_status, raw?.status) || null,
    completion_status: text(raw?.completion_status) || null,
    operator_status: text(raw?.operator_status) || null,
  }
}

function identity(row: ExitEvidenceRow): string {
  const symbol = String(row.symbol || '').toUpperCase()
  const date = row.trade_date ?? ''
  const account = row.account ?? ''
  const proceeds = finite(row.proceeds_usd)
  const quantity = finite(row.quantity)
  const price = finite(row.price)
  if (symbol && date && account && (proceeds !== null || quantity !== null || price !== null)) {
    return `${symbol}|${date}|${account}|${proceeds ?? ''}|${quantity ?? ''}|${price ?? ''}`
  }
  return row.event_key
}

function mergeRow(preferred: ExitEvidenceRow, fallback: ExitEvidenceRow): ExitEvidenceRow {
  const sources = Array.from(new Set(`${preferred.import_source ?? ''},${fallback.import_source ?? ''}`.split(',').map(value => value.trim()).filter(Boolean))).join(', ')
  return {
    ...fallback,
    ...preferred,
    event_key: preferred.event_key || fallback.event_key,
    symbol: preferred.symbol || fallback.symbol,
    account: preferred.account || fallback.account,
    trade_date: preferred.trade_date || fallback.trade_date,
    trade_time: preferred.trade_time || fallback.trade_time,
    quantity: finite(preferred.quantity) ?? finite(fallback.quantity),
    price: finite(preferred.price) ?? finite(fallback.price),
    proceeds_usd: finite(preferred.proceeds_usd) ?? finite(fallback.proceeds_usd),
    action: preferred.action || fallback.action,
    description: preferred.description || fallback.description,
    import_source: sources || preferred.import_source || fallback.import_source,
    matched_event_id: preferred.matched_event_id ?? fallback.matched_event_id,
    reconciliation: preferred.reconciliation || fallback.reconciliation,
    event_status: preferred.event_status || fallback.event_status,
    completion_status: preferred.completion_status || fallback.completion_status,
    operator_status: preferred.operator_status || fallback.operator_status,
  }
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
  const cacheRows = Array.isArray(cachePayload?.rows) ? cachePayload.rows : []
  const journalRows = arrayFrom(journal.data, ['trades']).filter(row => {
    const day = isoDay(row?.close_date ?? row?.closed_at ?? row?.sold_at ?? row?.trade_date)
    return !day || day >= from
  })
  const historyRows = arrayFrom(history.data, ['rows'])
  const bookRows = arrayFrom(book.data, ['rows'])
  const stoppedRows = arrayFrom(stopped.data, ['rows', 'items', 'reentry_watch', 'watch'])
  const tickerRows = arrayFrom(byTicker.data, ['tickers'])

  const rows = useMemo(() => {
    const collected: Array<{ row: ExitEvidenceRow; priority: number }> = []
    const add = (rawRows: any[], source: string, priority: number) => rawRows.forEach((raw, index) => {
      const row = normalizeExit(raw, index, source)
      if (row && (!row.trade_date || row.trade_date >= from)) collected.push({ row, priority })
    })
    add(cacheRows, 'full-fidelity-cache', 100)
    add(journalRows, 'real-closed-trade-journal', 90)
    add(bookRows, 'redeploy-book', 80)
    add(historyRows, 'redeploy-history', 70)
    add(stoppedRows, 'stops-reentry-watch', 60)

    const merged = new Map<string, { row: ExitEvidenceRow; priority: number }>()
    for (const item of collected.sort((a, b) => b.priority - a.priority)) {
      const key = identity(item.row)
      const prior = merged.get(key)
      if (!prior) merged.set(key, item)
      else merged.set(key, { priority: Math.max(prior.priority, item.priority), row: mergeRow(prior.row, item.row) })
    }

    const latestByTicker = new Map<string, any>()
    for (const aggregate of tickerRows) {
      const symbol = text(aggregate?.symbol, aggregate?.ticker).toUpperCase()
      if (symbol) latestByTicker.set(symbol, aggregate)
    }

    const output = [...merged.values()].map(item => item.row)
    const bySymbol = new Map<string, ExitEvidenceRow[]>()
    for (const row of output) bySymbol.set(row.symbol, [...(bySymbol.get(row.symbol) ?? []), row])
    for (const [symbol, symbolRows] of bySymbol) {
      symbolRows.sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      const latest = symbolRows[0]
      const aggregate = latestByTicker.get(symbol)
      if (!latest || !aggregate) continue
      const aggregateDay = isoDay(aggregate?.last_close_date ?? aggregate?.last_trade_at ?? aggregate?.last_close)
      if (aggregateDay && latest.trade_date && aggregateDay !== latest.trade_date) continue
      latest.price = finite(latest.price) ?? finite(aggregate?.last_sell_price, aggregate?.last_exit_price)
      latest.quantity = finite(latest.quantity) ?? finite(aggregate?.last_shares, aggregate?.shares_sold)
      latest.proceeds_usd = finite(latest.proceeds_usd) ?? finite(aggregate?.last_proceeds, aggregate?.proceeds_usd)
      latest.import_source = Array.from(new Set(`${latest.import_source ?? ''}, journal-by-ticker`.split(',').map(value => value.trim()).filter(Boolean))).join(', ')
    }

    return output.sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
  }, [cacheRows, journalRows, historyRows, bookRows, stoppedRows, tickerRows, from])

  const sources: ExitEvidenceSource[] = [
    { key: 'cache', label: 'Full-fidelity cache', rows: cacheRows.length, available: cacheRows.length > 0, error: cache.error },
    { key: 'journal', label: 'Closed-trade journal', rows: journalRows.length, available: journalRows.length > 0, error: journal.error },
    { key: 'book', label: 'Redeploy book', rows: bookRows.length, available: bookRows.length > 0, error: book.error },
    { key: 'history', label: 'Redeploy history', rows: historyRows.length, available: historyRows.length > 0, error: history.error },
    { key: 'stops', label: 'Stopped/re-entry watch', rows: stoppedRows.length, available: stoppedRows.length > 0, error: stopped.error },
    { key: 'ticker', label: 'Ticker aggregates', rows: tickerRows.length, available: tickerRows.length > 0, error: byTicker.error },
  ]
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
    fullFidelity: cacheRows.length > 0,
    generatedAt: text(cachePayload?.generated_at),
    refetch,
  }
}
