import type { StopStatusTone } from './holdingsTerminalTokens'
import { computeStopCoverage, type StopCoverage } from './stopCoverage'
import { buildStopLogic, type StopLogic } from './stopManagement'

export interface HoldingsRowInput {
  h: any
  pr?: any
  confirmedStop?: any
  monitored?: any
  llmHealth?: string | null
  /** Finviz strip map row for this symbol (rsi / perf fallback). */
  fv?: any
  /** Symbol-card payload (news[], earnings{}). */
  card?: any
}

export type RsiZone = 'oversold' | 'overbought' | 'neutral' | null
export type VolTier = 'low' | 'medium' | 'high' | null

export interface HoldingsRowModel {
  key: string
  symbol: string
  /** Short security name (ETF/issuer), may be empty */
  name: string | null
  account: string
  /** Full display name e.g. "Schwab Rollover IRA" */
  accountLabel: string
  /** @deprecated use accountLabel */
  accountShort: string
  marketValue: number
  dayPct: number | null
  portfolioPct: number | null
  price: number | null
  cost: number | null
  pl$: number | null
  plPct: number | null
  signal: string | null
  shares: number | null
  /** Technicals / enrichment (existing sources only) */
  rsi: number | null
  rsiStatus: RsiZone
  volTier: VolTier
  newsTitle: string | null
  newsSource: string | null
  newsAt: string | null
  newsUrl: string | null
  earningsDate: string | null
  /** Short display e.g. "Jul 21" or "21d" */
  earningsLabel: string | null
  stopStatus: StopStatusTone
  stopDistPct: number | null
  stopPrice: number | null
  liveStopPrice: number | null
  /** Realized position P/L if the current stop fills (live broker stop preferred,
   *  advisory fallback). Equals (stop − cost) × shares. Null when unknowable. */
  plIfFired: number | null
  stopLabel: string
  /** Imperative: what to do, e.g. "Tighten stop → $32.43" */
  stopInstruction: string
  /** Context line: e.g. "Live $35.00 now" */
  stopContext: string
  /** @deprecated use stopInstruction — kept for callers migrating */
  stopAdvisory: string
  stopTooltip: string
  primaryAction: { label: string; tone: 'amber' | 'green' | 'red' | 'muted' }
  primaryActionTooltip: string
  needsAction: boolean
  /** Stop order qty vs held shares (partial after size-up). Null when no live stop qty. */
  stopCoverage: StopCoverage | null
  stopQty: number | null
  llmHealth: string | null
  llmAction: string | null
}

/** Normalize RSI zone for color coding (overbought → red, oversold → green). */
export function resolveRsiZone(rsi: number | null, status?: string | null): RsiZone {
  const s = String(status || '').toLowerCase()
  if (s === 'oversold' || s === 'overbought') return s
  if (rsi == null || Number.isNaN(rsi)) return null
  if (rsi <= 30) return 'oversold'
  if (rsi >= 70) return 'overbought'
  return 'neutral'
}

export function resolveVolTier(raw: unknown): VolTier {
  const t = String(raw || '').toLowerCase()
  if (t === 'low' || t === 'medium' || t === 'high') return t
  return null
}

/** Format ISO / date-like earnings for compact table cell. */
export function formatEarningsLabel(raw: string | null | undefined): string | null {
  if (!raw) return null
  const s = String(raw).trim()
  if (!s) return null
  const d = new Date(s.includes('T') ? s : `${s}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return s.slice(0, 10)
  const now = new Date()
  const days = Math.round((d.getTime() - now.getTime()) / 86_400_000)
  const mon = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
  const day = d.getUTCDate()
  if (days >= 0 && days <= 45) return `${mon} ${day} · ${days}d`
  return `${mon} ${day}`
}

function pickNews(h: any, card?: any): {
  title: string | null; source: string | null; at: string | null; url: string | null
} {
  if (h?.news_title) {
    return {
      title: String(h.news_title),
      source: h.news_source != null ? String(h.news_source) : null,
      at: h.news_at != null ? String(h.news_at) : null,
      url: h.news_url != null ? String(h.news_url) : null,
    }
  }
  const n0 = Array.isArray(card?.news) && card.news.length ? card.news[0] : null
  if (n0?.title) {
    return {
      title: String(n0.title),
      source: n0.source != null ? String(n0.source) : null,
      at: n0.at != null ? String(n0.at) : null,
      url: n0.url != null ? String(n0.url) : null,
    }
  }
  return { title: null, source: null, at: null, url: null }
}

function pickEarningsDate(h: any, card?: any): string | null {
  if (h?.next_earnings_date) return String(h.next_earnings_date)
  const e = card?.earnings
  if (e?.next_date) return String(e.next_date)
  if (typeof e === 'string' && e.trim()) return e.trim()
  return null
}

export function plMetrics(h: any): { dollars: number | null; pct: number | null } {
  const cb = h.cost_basis
  if (cb == null || cb <= 0) return { dollars: null, pct: null }
  const dollars = h.gain_loss != null
    ? Number(h.gain_loss)
    : (h.market_value != null ? Number(h.market_value) - Number(cb) : null)
  const pct = h.gain_loss_pct != null
    ? Number(h.gain_loss_pct)
    : (dollars != null ? (dollars / Number(cb)) * 100 : null)
  return { dollars, pct }
}

/** Human full account labels — never abbreviated in the holdings table. */
export function accountFullName(account: string): string {
  const key = (account || 'unknown').trim().toLowerCase().replace(/\s+/g, '_')
  const MAP: Record<string, string> = {
    schwab_taxable: 'Schwab Taxable',
    schwab_rollover_ira: 'Schwab Rollover IRA',
    schwab_roth_ira: 'Schwab Roth IRA',
    schwab_roth: 'Schwab Roth IRA',
    fidelity_rollover_ira: 'Fidelity Rollover IRA',
    fidelity_roth_ira: 'Fidelity Roth IRA',
    fidelity_taxable: 'Fidelity Taxable',
    fidelity_401k: 'Fidelity 401(k)',
  }
  if (MAP[key]) return MAP[key]
  // Title-case unknown keys: schwab_foo → Schwab Foo
  return (account || 'Unknown')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\bIra\b/g, 'IRA')
    .replace(/\bRoth\b/g, 'Roth')
}

/** Brand palette for account pills (Fidelity blue, Schwab green, Roth purple, …). */
export function accountBrand(account: string): { color: string; bg: string; letter: string } {
  const k = (account || '').toLowerCase()
  if (k.includes('fidelity') && k.includes('roth')) {
    return { color: '#a78bfa', bg: 'rgba(167,139,250,0.16)', letter: 'F' }
  }
  if (k.includes('fidelity')) {
    return { color: '#3b82f6', bg: 'rgba(59,130,246,0.16)', letter: 'F' }
  }
  if (k.includes('roth')) {
    return { color: '#c084fc', bg: 'rgba(192,132,252,0.16)', letter: 'S' }
  }
  if (k.includes('rollover') || k.includes('ira')) {
    return { color: '#34d399', bg: 'rgba(52,211,153,0.14)', letter: 'S' }
  }
  if (k.includes('schwab')) {
    return { color: '#22c55e', bg: 'rgba(34,197,94,0.14)', letter: 'S' }
  }
  if (k.includes('401')) {
    return { color: '#38bdf8', bg: 'rgba(56,189,248,0.14)', letter: '4' }
  }
  return { color: '#94a3b8', bg: 'rgba(148,163,184,0.14)', letter: '?' }
}

/** @deprecated prefer accountFullName — kept for any short-label callers */
function acctShort(account: string): string {
  return accountFullName(account)
}

const fmt$ = (n: number) => `$${n.toFixed(2)}`

function stopCopyFromLogic(
  logic: StopLogic,
  opts: { isFidelity: boolean; isSchwab: boolean; health: string; signal: string | null; needsSellAll: boolean; shares: number },
): { instruction: string; context: string; tooltip: string } {
  const adv = logic.advisoryStop
  const live = logic.liveStop
  const tooltip = logic.primary_operator_action || logic.action_summary || ''

  switch (logic.stop_action_decision) {
    case 'PLACE_NEW_STOP':
      return {
        instruction: opts.isFidelity ? `Set stop → ${fmt$(adv!)}` : `Place stop → ${fmt$(adv!)}`,
        context: logic.distancePct != null ? `Target · ${logic.distancePct.toFixed(1)}% below price` : 'No live stop yet',
        tooltip,
      }
    case 'MODIFY_EXISTING_STOP':
      return {
        instruction: opts.isFidelity ? `Modify ticket → ${fmt$(adv!)}` : `Tighten stop → ${fmt$(adv!)}`,
        context: live != null ? `${fmt$(live)} now → ${fmt$(adv!)}` : `Target ${fmt$(adv!)}`,
        tooltip,
      }
    case 'KEEP_EXISTING_STOP':
      if (logic.liveStopIsTrailing && live != null) {
        const trail = logic.liveTrailPct
        return {
          instruction: trail != null ? `Keep trail ${trail}% → ${fmt$(live)}` : `Keep stop → ${fmt$(live)}`,
          context: adv != null && logic.existing_stop_is_tighter_than_advisory
            ? `Tighter than ${fmt$(adv)} advisory`
            : adv != null ? `Advisory ${fmt$(adv)}` : 'Fidelity GTC in place',
          tooltip,
        }
      }
      if (logic.existing_stop_is_tighter_than_advisory && live != null) {
        return {
          instruction: `Keep stop → ${fmt$(live)}`,
          context: adv != null ? `Tighter than ${fmt$(adv)} advisory` : '',
          tooltip,
        }
      }
      return {
        instruction: live != null ? `Stop OK → ${fmt$(live)}` : adv != null ? `Stop OK → ${fmt$(adv)}` : 'Stop in place',
        context: adv != null && live != null ? `Matches ${fmt$(adv)} advisory` : '',
        tooltip,
      }
    case 'BLOCKED_STALE_QUOTE':
      return {
        instruction: adv != null ? `Refresh quote → set ${fmt$(adv)}` : 'Refresh quote first',
        context: 'Quote stale — refresh before placing',
        tooltip,
      }
    case 'BLOCKED_SOURCE_MISMATCH':
      return { instruction: 'Fix broker source mismatch', context: '', tooltip }
    case 'NOT_APPLICABLE':
      return { instruction: 'No live stop (fund/401k)', context: 'Review allocation instead', tooltip }
    default:
      break
  }

  if (opts.needsSellAll && adv != null) {
    return {
      instruction: `Set stop → ${fmt$(adv)}`,
      context: `${opts.shares} sh — whole-share stop required`,
      tooltip: `Schwab whole-share rule: ${opts.shares} shares — may need sell-all stop`,
    }
  }
  if (opts.health === 'CONCERN' || opts.health === 'TRIM') {
    return {
      instruction: adv != null ? `Review → set ${fmt$(adv)}` : 'Review allocation',
      context: `LLM health: ${opts.health}`,
      tooltip: adv != null ? `Review ${opts.health} — advisory stop ${fmt$(adv)}` : `LLM health ${opts.health}`,
    }
  }
  if (opts.signal === 'TRIM' || opts.signal === 'SELL' || opts.signal === 'EXIT') {
    return {
      instruction: adv != null ? `Review → ${fmt$(adv)}` : `Review ${opts.signal}`,
      context: `${opts.signal} signal`,
      tooltip,
    }
  }
  if (adv != null) {
    return {
      instruction: opts.isFidelity ? `Set stop → ${fmt$(adv)}` : `Place stop → ${fmt$(adv)}`,
      context: live != null ? `Live ${fmt$(live)}` : 'No live stop',
      tooltip,
    }
  }
  return {
    instruction: 'No stop target',
    context: logic.liveStop != null ? `Live ${fmt$(logic.liveStop)}` : 'No advisory',
    tooltip: tooltip || 'Manual review — no actionable stop recommendation',
  }
}

function primaryFromLogic(
  logic: StopLogic,
  sym: string,
  acct: string,
  opts: { isFidelity: boolean; isSchwab: boolean; hasLiveBroker: boolean; health: string; signal: string | null; needsSellAll: boolean; shares: number; instruction: string },
): { label: string; tone: 'amber' | 'green' | 'red' | 'muted'; tooltip: string } {
  const as = acctShort(acct)
  const go = (label: string, tip: string, tone: 'amber' | 'green' | 'red' | 'muted' = 'amber') => ({ label, tone, tooltip: tip })

  switch (logic.stop_action_decision) {
    case 'PLACE_NEW_STOP':
      if (opts.isFidelity) return go('Create Ticket', `Open ${sym} (${as}) → Fidelity ticket for ${opts.instruction}`)
      if (opts.isSchwab) return go('Request 2FA Stop', `Open ${sym} (${as}) → ${logic.primary_operator_action}`)
      return go('Place Stop', logic.primary_operator_action, 'amber')
    case 'MODIFY_EXISTING_STOP':
      if (opts.isSchwab && opts.hasLiveBroker) return go('Replace Stop', `Open ${sym} (${as}) → ${logic.primary_operator_action}`)
      if (opts.isFidelity) return go('Modify Ticket', `Open ${sym} (${as}) → ${logic.primary_operator_action}`)
      return go('Tighten Stop', `Open ${sym} (${as}) → ${logic.primary_operator_action}`)
    case 'KEEP_EXISTING_STOP':
      return go('Stable', logic.primary_operator_action, 'green')
    case 'BLOCKED_STALE_QUOTE':
      return go('Refresh Quote', `Open ${sym} (${as}) → refresh quote then ${opts.instruction}`, 'amber')
    default:
      break
  }

  if (opts.needsSellAll && logic.advisoryStop != null) {
    return go('Review', `Open ${sym} (${as}) → whole-share stop (${opts.shares} sh)`, 'amber')
  }
  if (opts.health === 'CONCERN' || opts.health === 'TRIM' || opts.signal === 'TRIM' || opts.signal === 'SELL' || opts.signal === 'EXIT') {
    const tone = opts.signal === 'TRIM' || opts.signal === 'SELL' || opts.signal === 'EXIT' ? 'red' as const : 'amber' as const
    return go('Review', `Open ${sym} (${as}) → ${opts.instruction}`, tone)
  }
  if (logic.advisoryStop != null && !logic.liveStop) {
    if (opts.isFidelity) return go('Create Ticket', `Open ${sym} (${as}) → ${opts.instruction}`)
    if (opts.isSchwab) return go('Request 2FA Stop', `Open ${sym} (${as}) → ${opts.instruction}`)
  }
  if (logic.advisoryStop != null && logic.liveStop && logic.advisory_stop_is_tighter_than_existing) {
    return go(opts.isSchwab ? 'Replace Stop' : 'Tighten Stop', `Open ${sym} (${as}) → ${opts.instruction}`)
  }
  if (logic.liveStop != null && logic.advisoryStop == null) {
    return go('Stable', `Live stop ${fmt$(logic.liveStop)} — no new advisory`, 'green')
  }
  return go('Details', `Open ${sym} (${as}) holding details`, 'muted')
}

function stopStatusFromLogic(
  logic: StopLogic,
  health: string,
  signal: string | null,
  stopDist: number | null,
): StopStatusTone {
  // Stop badge tracks stop-management truth first — do not mark "Action" when the live stop is
  // already aligned (KEEP_EXISTING_STOP) just because LLM health/signal says TRIM elsewhere.
  if (logic.stop_action_decision === 'KEEP_EXISTING_STOP') {
    const nearPrice = (logic.liveStopDistancePct != null && logic.liveStopDistancePct < 5)
      || (stopDist != null && stopDist < 5)
    return nearPrice ? 'concern' : 'stable'
  }
  if (logic.stop_action_decision === 'PLACE_NEW_STOP' || logic.stop_action_decision === 'MODIFY_EXISTING_STOP') return 'action'
  if (logic.stop_action_decision === 'BLOCKED_STALE_QUOTE') return 'concern'
  if (stopDist != null && stopDist < 5) return 'concern'
  if (health === 'CONCERN' || health === 'TRIM' || signal === 'TRIM' || signal === 'SELL' || signal === 'EXIT') return 'action'
  return 'stable'
}

export function buildHoldingsRowModel(input: HoldingsRowInput): HoldingsRowModel {
  const h = input.h
  const pr = input.pr
  const fv = input.fv
  const card = input.card
  const sym = String(h.symbol || '').toUpperCase()
  const acct = String(h.account ?? 'unknown')
  const key = `${sym}:${acct}`
  const { dollars: pl$, pct: plPct } = plMetrics(h)
  const sh = Number(h.shares) || 0
  const cur = h.current_price != null ? Number(h.current_price)
    : sh > 0 && h.market_value != null ? Number(h.market_value) / sh : null
  const buy = sh > 0 && h.cost_basis != null && Number(h.cost_basis) > 0 ? Number(h.cost_basis) / sh : null
  const dayPct = h.day_change_pct != null ? Number(h.day_change_pct) : null

  const stopPrice = pr?.stop_price != null ? Number(pr.stop_price) : null
  const stopDist = pr?.stop_distance_pct != null ? Number(pr.stop_distance_pct) : null
  const health = String(h.llm_health || input.llmHealth || '').toUpperCase()
  const signal = String(h.signal || '').toUpperCase() || null
  const isSchwab = acct.startsWith('schwab')
  const isFidelity = acct.startsWith('fidelity') && acct !== 'fidelity_401k'
  const needsSellAll = isSchwab && sh > 0 && sh < 40

  // RSI: holdings enrichment first, Finviz strip fallback
  let rsi: number | null = h.rsi != null && h.rsi !== '' ? Number(h.rsi) : null
  if (rsi == null || Number.isNaN(rsi)) {
    rsi = fv?.rsi != null && fv.rsi !== '' ? Number(fv.rsi) : null
    if (rsi != null && Number.isNaN(rsi)) rsi = null
  }
  const rsiStatus = resolveRsiZone(rsi, h.rsi_status ?? fv?.rsi_status)
  const volTier = resolveVolTier(pr?.volatility_tier ?? h.volatility_tier)
  const news = pickNews(h, card)
  const earningsDate = pickEarningsDate(h, card)
  const earningsLabel = formatEarningsLabel(earningsDate)

  const logic = buildStopLogic({
    h,
    pr: pr ?? {},
    monitored: input.monitored,
    confirmedStop: input.confirmedStop,
    sourceTimestamp: h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at ?? h?.price_timestamp,
  })

  const liveStopPrice = logic.liveStop
  const hasLiveBroker = Boolean(logic.liveStop != null && input.confirmedStop?.order_id)
  const stopQtyRaw = input.confirmedStop?.qty
  const stopCoverage = (hasLiveBroker || stopQtyRaw != null)
    ? computeStopCoverage(stopQtyRaw, sh)
    : null

  // Realized position P/L if the current stop fills. Prefer the live broker stop;
  // fall back to the advisory/target when there is no live stop yet. Same arithmetic
  // the Stop Management drawer shows: pl$ − shares × (price − stop) = (stop − cost) × shares.
  const stopForPl = liveStopPrice ?? stopPrice
  const plIfFired = (pl$ != null && cur != null && stopForPl != null && sh > 0)
    ? Math.round((pl$ - sh * (cur - stopForPl)) * 100) / 100
    : null
  const sizeMismatch = stopCoverage?.kind === 'partial' || stopCoverage?.kind === 'oversized'

  let copy = stopCopyFromLogic(logic, { isFidelity, isSchwab, health, signal, needsSellAll, shares: sh })
  let stopStatus = stopStatusFromLogic(logic, health, signal, stopDist)
  let primary = primaryFromLogic(logic, sym, acct, {
    isFidelity, isSchwab, hasLiveBroker, health, signal, needsSellAll, shares: sh,
    instruction: copy.instruction,
  })
  // Size mismatch beats KEEP_EXISTING — GTC stop did not resize after buy/trim.
  if (sizeMismatch && stopCoverage) {
    stopStatus = 'action'
    const tgt = stopCoverage.targetQty
    primary = {
      label: stopCoverage.kind === 'partial' ? `Update size → ${tgt}` : `Resize → ${tgt}`,
      tone: stopCoverage.kind === 'oversized' ? 'red' : 'amber',
      tooltip: `${stopCoverage.tip} Opens Stop Management / 2FA replace at full held size.`,
    }
    copy = {
      instruction: stopCoverage.kind === 'partial'
        ? `Resize → ${stopCoverage.stopQty}/${stopCoverage.heldQty} sh`
        : `Oversized → ${stopCoverage.stopQty}/${stopCoverage.heldQty} sh`,
      context: `Target ${tgt} sh via 2FA`,
      tooltip: stopCoverage.tip,
    }
  }

  const needsAction = primary.tone === 'amber' || primary.tone === 'red'
  const stopLabel = sizeMismatch
    ? (stopCoverage!.kind === 'partial' ? 'PARTIAL' : 'OVERSIZE')
    : stopStatus === 'stable' ? 'Stable' : stopStatus === 'concern' ? 'Concern' : 'Action'

  const nameRaw = String(h.name || h.security_name || h.company_name || '').trim()
  const name = nameRaw
    ? (nameRaw.length > 36 ? `${nameRaw.slice(0, 34)}…` : nameRaw)
    : null
  const accountLabel = accountFullName(acct)

  return {
    key,
    symbol: sym,
    name,
    account: acct,
    accountLabel,
    accountShort: accountLabel,
    marketValue: Number(h.market_value) || 0,
    dayPct,
    portfolioPct: h.portfolio_pct != null ? Number(h.portfolio_pct) : null,
    price: cur,
    cost: buy,
    pl$,
    plPct,
    signal,
    shares: sh || null,
    rsi,
    rsiStatus,
    volTier,
    newsTitle: news.title,
    newsSource: news.source,
    newsAt: news.at,
    newsUrl: news.url,
    earningsDate,
    earningsLabel,
    stopStatus,
    stopDistPct: stopDist,
    stopPrice,
    liveStopPrice,
    plIfFired,
    stopLabel,
    stopInstruction: copy.instruction,
    stopContext: copy.context,
    stopAdvisory: copy.context ? `${copy.instruction} · ${copy.context}` : copy.instruction,
    stopTooltip: copy.tooltip,
    primaryAction: { label: primary.label, tone: primary.tone },
    primaryActionTooltip: primary.tooltip,
    needsAction,
    stopCoverage,
    stopQty: stopCoverage?.stopQty ?? (stopQtyRaw != null ? Number(stopQtyRaw) : null),
    llmHealth: h.llm_health ?? null,
    llmAction: h.llm_action ?? null,
  }
}