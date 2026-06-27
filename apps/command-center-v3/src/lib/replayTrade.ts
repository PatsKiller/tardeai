/** Canonical replay props — every TradeReplayChart opener should use this. */

export type ReplayTradeInput = {
  symbol: string
  trade_key?: string
  account?: string
  open_date?: string
  close_date?: string
  entry_date?: string | null
  exit_date?: string | null
  entryDate?: string | null
  exitDate?: string | null
  buy_price?: number | string | null
  sell_price?: number | string | null
  entry_price?: number | string | null
  exit_price?: number | string | null
  ep?: number | string | null
  xp?: number | string | null
  entry_time?: string | null
  exit_time?: string | null
  entryTimeFull?: string | null
  exitTimeFull?: string | null
  stop?: number
  stop_loss?: number
  planned_stop?: number
  target?: number
  target_1?: number
  target_price?: number
  exec?: unknown
}

export function buildReplayTrade(row: ReplayTradeInput) {
  const symbol = row.symbol
  const account = row.account
  const entry_date = String(row.entry_date || row.entryDate || row.open_date || row.close_date || '').slice(0, 10)
  const exit_date = String(row.exit_date || row.exitDate || row.close_date || entry_date).slice(0, 10)
  const trade_key = row.trade_key
    || (symbol && account && (row.close_date || exit_date)
      ? `${symbol}:${account}:${String(row.close_date || exit_date).slice(0, 10)}`
      : undefined)
  const ex = row.exec as { entry_time?: string; exit_time?: string } | undefined
  // Prefer journal/EQ fill clocks — never replay at midnight when only a date was passed.
  const entry_time = row.entry_time || row.entryTimeFull || ex?.entry_time || null
  const exit_time = row.exit_time || row.exitTimeFull || ex?.exit_time || null
  return {
    symbol,
    trade_key,
    account,
    entry_date,
    exit_date,
    entry_price: row.entry_price ?? row.ep ?? row.buy_price,
    exit_price: row.exit_price ?? row.xp ?? row.sell_price,
    entry_time,
    exit_time,
    stop: row.stop ?? row.stop_loss ?? row.planned_stop,
    target: row.target ?? row.target_1 ?? row.target_price,
    exec: row.exec,
  }
}