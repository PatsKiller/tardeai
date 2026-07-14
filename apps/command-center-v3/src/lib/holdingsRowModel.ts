import type { StopStatusTone } from './holdingsTerminalTokens'
import { buildStopLogic, type StopLogic } from './stopManagement'

export interface HoldingsRowInput {
  h: any
  pr?: any
  confirmedStop?: any
  monitored?: any
  llmHealth?: string | null
}

export interface HoldingsRowModel {
  key: string
  symbol: string
  account: string
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
  stopStatus: StopStatusTone
  stopDistPct: number | null
  stopPrice: number | null
  liveStopPrice: number | null
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
  llmHealth: string | null
  llmAction: string | null
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

function acctShort(account: string): string {
  const a = (account || 'unknown').replace(/_/g, ' ')
  if (a.includes('schwab taxable')) return 'Schwab Tx'
  if (a.includes('schwab roth')) return 'Schwab Roth'
  if (a.includes('fidelity rollover')) return 'Fid IRA'
  if (a.includes('fidelity')) return 'Fidelity'
  if (a.includes('401')) return '401k'
  const parts = a.split(' ')
  return parts.length > 2 ? `${parts[0]} ${parts[1]}` : a
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

  const logic = buildStopLogic({
    h,
    pr: pr ?? {},
    monitored: input.monitored,
    confirmedStop: input.confirmedStop,
    sourceTimestamp: h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at ?? h?.price_timestamp,
  })

  const liveStopPrice = logic.liveStop
  const hasLiveBroker = Boolean(logic.liveStop != null && input.confirmedStop?.order_id)

  const copy = stopCopyFromLogic(logic, { isFidelity, isSchwab, health, signal, needsSellAll, shares: sh })
  const stopStatus = stopStatusFromLogic(logic, health, signal, stopDist)
  const primary = primaryFromLogic(logic, sym, acct, {
    isFidelity, isSchwab, hasLiveBroker, health, signal, needsSellAll, shares: sh,
    instruction: copy.instruction,
  })

  const needsAction = primary.tone === 'amber' || primary.tone === 'red'
  const stopLabel = stopStatus === 'stable' ? 'Stable' : stopStatus === 'concern' ? 'Concern' : 'Action'

  return {
    key,
    symbol: sym,
    account: acct,
    accountShort: acctShort(acct),
    marketValue: Number(h.market_value) || 0,
    dayPct,
    portfolioPct: h.portfolio_pct != null ? Number(h.portfolio_pct) : null,
    price: cur,
    cost: buy,
    pl$,
    plPct,
    signal,
    shares: sh || null,
    stopStatus,
    stopDistPct: stopDist,
    stopPrice,
    liveStopPrice,
    stopLabel,
    stopInstruction: copy.instruction,
    stopContext: copy.context,
    stopAdvisory: copy.context ? `${copy.instruction} · ${copy.context}` : copy.instruction,
    stopTooltip: copy.tooltip,
    primaryAction: { label: primary.label, tone: primary.tone },
    primaryActionTooltip: primary.tooltip,
    needsAction,
    llmHealth: h.llm_health ?? null,
    llmAction: h.llm_action ?? null,
  }
}