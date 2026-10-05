/** Option chain truth (reviewer 2026-09-28) — the pure half of OptionChainPanel.
 *
 *  Formatting and typed-state mapping only. Rules: a price is "Mid" only when both sides of a
 *  current quote exist; a lone last/bid/ask is labelled as what it is and marked not
 *  executable. Executable net for a spread = sell the short leg at its bid, buy the long leg
 *  at its ask; any missing side refuses to price and names the leg. Never a React import, so
 *  `node src/lib/optionChainTruth.test.ts` runs it. */
import type { Tone } from './designTokens'

export type ChainRow = {
  exp: string; strike: number; side: 'call' | 'put'
  bid?: number | null; ask?: number | null; last?: number | null; mark?: number | null
  iv?: number | null; delta?: number | null; oi?: number | null; volume?: number | null; dte?: number | null
  quote_time?: string | null; trade_time?: string | null; two_sided?: boolean | null; spread_pct?: number | null
  symbol?: string | null; multiplier?: number | null; nonstandard?: boolean | null
}
export type ChainStatus = 'ok' | 'empty' | 'needs_account_link' | 'needs_reauth' | 'degraded' | 'needs_account_hash' | 'needs_mapping'
  | 'rate_limited' | 'not_found' | 'broker_error' | 'broker_error_payload' | 'NOT_PROVEN' | 'error' | string

const pos = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0

/** What number to show for a row and what to call it. */
export function quoteLabel(r: Pick<ChainRow, 'bid' | 'ask' | 'last' | 'two_sided'>): { value: number | null; label: 'Mid' | 'Last' | 'Bid only' | 'Ask only' | '—'; executable: boolean } {
  const two = r.two_sided ?? (pos(r.bid) && pos(r.ask) && (r.ask as number) > (r.bid as number))
  if (two && pos(r.bid) && pos(r.ask)) return { value: ((r.bid as number) + (r.ask as number)) / 2, label: 'Mid', executable: false }
  if (pos(r.last)) return { value: r.last as number, label: 'Last', executable: false }
  if (pos(r.bid)) return { value: r.bid as number, label: 'Bid only', executable: false }
  if (pos(r.ask)) return { value: r.ask as number, label: 'Ask only', executable: false }
  return { value: null, label: '—', executable: false }
}

export function spreadPct(r: Pick<ChainRow, 'bid' | 'ask' | 'spread_pct'>): number | null {
  if (typeof r.spread_pct === 'number') return r.spread_pct
  if (!pos(r.bid) || !pos(r.ask) || (r.ask as number) <= (r.bid as number)) return null
  const mid = ((r.bid as number) + (r.ask as number)) / 2
  return Math.round((1000 * ((r.ask as number) - (r.bid as number))) / mid) / 10
}

export function quoteAgeSeconds(iso: string | null | undefined, now: number = Date.now()): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 1000))
}

export function ageLabel(s: number | null): string {
  if (s == null) return 'no quote time'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

/** Typed state → what the operator sees and does next. `httpOk` false = the API itself failed. */
export function chainStatusMessage(status: ChainStatus | undefined, httpOk: boolean, detail?: string | null, httpStatus?: number | null): { title: string; next: string; tone: Tone } | null {
  if (!httpOk) return { title: `Command Center API error${httpStatus ? ` (HTTP ${httpStatus})` : ''}`, next: 'The chain request never reached Schwab. Retry; if it persists, check portfolio-server.service.', tone: 'danger' }
  switch (status) {
    case 'ok': return null
    case 'empty': return { title: 'Schwab returned no listed contracts', next: detail || 'The symbol may not be optionable, or the expiration/strike window is empty. Widen the window.', tone: 'warning' }
    case 'needs_account_link': return { title: 'No Schwab account is linked for chain reads', next: 'Link the Schwab account on the System page, then retry.', tone: 'danger' }
    case 'needs_reauth':
    case 'degraded': return { title: 'Schwab login needs renewal', next: `${detail || 'The token was rejected or is missing.'} Renew the Schwab link, then retry.`, tone: 'danger' }
    case 'needs_account_hash':
    case 'needs_mapping': return { title: 'Schwab account mapping incomplete', next: detail || 'Resolve the account hash mapping, then retry.', tone: 'danger' }
    case 'rate_limited': return { title: 'Schwab rate limit', next: 'Wait a minute and retry; do not hammer refresh.', tone: 'warning' }
    case 'not_found': return { title: 'Schwab has no such symbol or contract', next: detail || 'Check the symbol; the proposal may reference a contract that no longer lists.', tone: 'warning' }
    case 'broker_error': return { title: 'Schwab server error', next: `${detail || ''} Retry shortly; if it persists the broker is down, not the desk.`.trim(), tone: 'danger' }
    case 'broker_error_payload': return { title: 'Schwab answered with an error', next: detail || 'Broker error object.', tone: 'danger' }
    case 'NOT_PROVEN': return { title: 'Schwab transport not configured', next: detail || 'Live credentials are absent on this host.', tone: 'danger' }
    default: return { title: 'Chain fetch failed', next: detail || String(status || 'unknown state'), tone: 'danger' }
  }
}

export type LegSpec = { role: 'short' | 'long'; side: 'call' | 'put'; strike: number }

/** Conservative executable net for the proposal's legs: sell short legs at bid, buy long legs at ask. */
export function executableNet(legs: LegSpec[], rows: ChainRow[], contracts = 1): { net: number | null; kind: 'credit' | 'debit' | null; perContract: number | null; reason: string | null; legs: Array<LegSpec & { row: ChainRow | null; price: number | null }> } {
  const out: Array<LegSpec & { row: ChainRow | null; price: number | null }> = []
  let total = 0
  let reason: string | null = null
  for (const l of legs) {
    const row = rows.find(r => r.side === l.side && Math.abs(r.strike - l.strike) < 0.005) || null
    let price: number | null = null
    if (!row) reason = reason || `${l.role} ${l.side} $${l.strike} is not in the chain window`
    else if (l.role === 'short') { price = pos(row.bid) ? (row.bid as number) : null; if (price == null) reason = reason || `${l.role} ${l.side} $${l.strike} has no bid` }
    else { price = pos(row.ask) ? (row.ask as number) : null; if (price == null) reason = reason || `${l.role} ${l.side} $${l.strike} has no ask` }
    if (price != null) total += l.role === 'short' ? price : -price
    out.push({ ...l, row, price })
  }
  if (reason || legs.length === 0) return { net: null, kind: null, perContract: null, reason: reason || 'no legs', legs: out }
  const per = Math.round(total * 100) / 100
  return { net: Math.round(per * 100 * contracts * 100) / 100, kind: per >= 0 ? 'credit' : 'debit', perContract: per, reason: null, legs: out }
}

/** Legs implied by a proposal row (server fields only). */
export function legsFromProposal(p: { strategy?: string; option_type?: string; strike?: number; short_strike?: number; long_strike?: number; legs?: Array<{ action?: string; option_type?: string; strike?: number }> }): LegSpec[] {
  if (p.legs?.length) return p.legs.flatMap(leg =>
    leg.strike != null && (leg.option_type === 'call' || leg.option_type === 'put') && ['BUY', 'SELL'].includes(leg.action || '')
      ? [{ role: leg.action === 'SELL' ? 'short' : 'long', side: leg.option_type, strike: leg.strike } as LegSpec] : [])
  const s = String(p.strategy || '')
  const side: 'call' | 'put' = p.option_type === 'put' || /put/.test(s) ? 'put' : 'call'
  if (s === 'credit_spread' && p.short_strike != null && p.long_strike != null) return [{ role: 'short', side, strike: p.short_strike }, { role: 'long', side, strike: p.long_strike }]
  if (s === 'debit_spread' && p.short_strike != null && p.long_strike != null) return [{ role: 'long', side, strike: p.long_strike }, { role: 'short', side, strike: p.short_strike }]
  if (p.strike == null) return []
  if (s === 'covered_call' || s === 'cash_secured_put' || s === 'short_call' || s === 'short_put') return [{ role: 'short', side, strike: p.strike }]
  return [{ role: 'long', side, strike: p.strike }]
}
