import type { PlanWarning } from './exitLadder'

export function watchlistNeedsRefresh(it: any, stale: boolean) {
  if (stale) return true
  if (it.final_synthesis_status === 'pending') return true
  return ['maria_status', 'steph_status', 'risk_status'].some(k => {
    const s = it[k]
    return s && String(s).toLowerCase() !== 'completed'
  })
}

export type ActionUrgency = 'none' | 'amber' | 'green' | 'red'

export type CardVerdict = 'READY' | 'WAIT' | 'SKIP' | 'STALE' | 'FIX' | 'BUILD' | 'WATCH'

export type CardActionType =
  | 'PROPOSE_ENTRY'
  | 'QUEUE_PROPOSAL'
  | 'ADJUST_PLAN'
  | 'BUILD_PLAN'
  | 'REFRESH_DATA'
  | 'VIEW_INTEL'
  | 'REVIEW_SETUP'
  | 'REVIEW_EXIT'
  | 'WATCH_ON_DESK'
  | 'NONE'

export type ButtonVariant = 'solid-green' | 'outline-amber' | 'neutral'

/** Unified verdict + hero + primary CTA — derived together. */
export type CardAction = {
  type: CardActionType
  verdict: CardVerdict
  heroText: string
  subtext?: string
  /** Long advisory/CIO note — tooltip or drawer only, never the hero line. */
  detail?: string
  urgency: ActionUrgency
  primaryLabel: string
  buttonVariant: ButtonVariant
  allowPrimary: boolean
}

/** @deprecated Use CardAction — kept for gradual migration */
export type RecommendedAction = CardAction & { text: string; primaryKind: string }

function cioAvoid(rec?: string | null): boolean {
  const s = String(rec ?? '').toUpperCase()
  return ['AVOID', 'IGNORE', 'SELL', 'TRIM'].some(k => s.includes(k))
}

function cioLabel(rec?: string | null): string {
  return String(rec ?? 'watch').replace(/_/g, ' ').toLowerCase()
}

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `$${Number(v).toFixed(2)}`
}

function action(
  type: CardActionType,
  verdict: CardVerdict,
  heroText: string,
  opts: {
    subtext?: string
    detail?: string
    urgency?: ActionUrgency
    primaryLabel: string
    buttonVariant: ButtonVariant
    allowPrimary?: boolean
  },
): CardAction {
  let variant = opts.buttonVariant
  if ((verdict === 'SKIP' || verdict === 'WAIT') && variant === 'solid-green') variant = 'neutral'
  return {
    type,
    verdict,
    heroText,
    subtext: opts.subtext,
    detail: opts.detail,
    urgency: opts.urgency ?? 'none',
    primaryLabel: opts.primaryLabel,
    buttonVariant: variant,
    allowPrimary: opts.allowPrimary ?? true,
  }
}

export function deriveRecommendedAction(args: {
  it: any
  hasPlan: boolean
  rr: number | null
  warns: PlanWarning[]
  stale: boolean
  enriched: boolean
  entry: number | null
  adv?: { advisory_flag?: string; note?: string } | null
}): CardAction {
  const { it, hasPlan, rr, warns, stale, enriched, entry, adv } = args
  const advNote = adv?.note ? String(adv.note).trim() : undefined

  if (it.private_nontradeable) {
    return action('VIEW_INTEL', 'SKIP', 'Do not trade — private ticker', {
      subtext: it.private_note || it.private_company,
      urgency: 'red',
      primaryLabel: 'View intel',
      buttonVariant: 'neutral',
    })
  }

  const noStop = warns.some(w => w.text.includes('NO STOP'))
  if (noStop) {
    return action('ADJUST_PLAN', 'FIX', 'Set stop before entry', {
      subtext: 'Risk undefined without a planned stop',
      urgency: 'red',
      primaryLabel: 'Fix plan',
      buttonVariant: 'outline-amber',
    })
  }

  if (stale && hasPlan) {
    return action('REFRESH_DATA', 'STALE', 'Refresh first', {
      subtext: 'Stale technicals',
      urgency: 'amber',
      primaryLabel: 'Refresh',
      buttonVariant: 'neutral',
    })
  }

  if (cioAvoid(it.latest_recommendation)) {
    return action('VIEW_INTEL', 'SKIP', 'No add', {
      subtext: `CIO ${cioLabel(it.latest_recommendation)}`,
      urgency: 'amber',
      primaryLabel: 'Intel',
      buttonVariant: 'neutral',
    })
  }

  if (rr != null && rr < 1) {
    return action('ADJUST_PLAN', 'FIX', `Fix plan · R:R ${rr.toFixed(2)}`, {
      subtext: 'Reward < risk',
      urgency: 'red',
      primaryLabel: 'Fix plan',
      buttonVariant: 'outline-amber',
    })
  }

  if (rr != null && rr < 1.5) {
    return action('ADJUST_PLAN', 'FIX', `Fix plan · R:R ${rr.toFixed(2)}`, {
      subtext: 'Thin edge',
      urgency: 'amber',
      primaryLabel: 'Fix plan',
      buttonVariant: 'outline-amber',
    })
  }

  const planCapWarn = warns.find(w => w.text.includes('plan target') && w.text.includes('Street'))
  if (planCapWarn && hasPlan) {
    return action('REVIEW_EXIT', 'FIX', 'Fix exit ladder', {
      subtext: 'Plan target below Street',
      detail: planCapWarn.text,
      urgency: 'amber',
      primaryLabel: 'Review exit',
      buttonVariant: 'outline-amber',
    })
  }

  if (adv?.advisory_flag === 'caution' && !hasPlan) {
    return action('REVIEW_SETUP', 'WAIT', 'Hold off', {
      subtext: 'Advisory caution · no plan',
      detail: advNote,
      urgency: 'amber',
      primaryLabel: 'Review',
      buttonVariant: 'neutral',
    })
  }

  if (adv?.advisory_flag === 'caution' && hasPlan) {
    return action('VIEW_INTEL', 'WAIT', 'Hold off', {
      subtext: 'Advisory caution',
      detail: advNote,
      urgency: 'amber',
      primaryLabel: 'Intel',
      buttonVariant: 'neutral',
    })
  }

  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  if (conf != null && Number(conf) < 0.5 && !hasPlan) {
    return action('VIEW_INTEL', 'WAIT', 'Hold off', {
      subtext: `Low conf ${Number(conf).toFixed(2)}`,
      urgency: 'none',
      primaryLabel: 'Intel',
      buttonVariant: 'neutral',
    })
  }

  const urgency = it.entry_urgency
  if (urgency === 'ready' && hasPlan && entry != null) {
    return action('PROPOSE_ENTRY', 'READY', `Propose ${money(entry)}`, {
      subtext: 'Limit ready',
      urgency: 'green',
      primaryLabel: 'Propose',
      buttonVariant: 'solid-green',
    })
  }

  if (urgency === 'near_entry' && hasPlan && entry != null) {
    return action('PROPOSE_ENTRY', 'READY', `Propose ${money(entry)}`, {
      subtext: 'Near entry',
      urgency: 'amber',
      primaryLabel: 'Propose',
      buttonVariant: 'solid-green',
    })
  }

  if (!hasPlan) {
    return action(
      enriched ? 'BUILD_PLAN' : 'REFRESH_DATA',
      enriched ? 'BUILD' : 'STALE',
      enriched ? 'Build plan' : 'Enriching',
      {
        subtext: enriched ? 'No limit/stop/target' : undefined,
        urgency: 'none',
        primaryLabel: enriched ? 'Build' : 'Refresh',
        buttonVariant: enriched ? 'outline-amber' : 'neutral',
      },
    )
  }

  if (entry != null) {
    return action('WATCH_ON_DESK', 'WATCH', `Watch ${money(entry)}`, {
      subtext: 'Await trigger',
      urgency: 'none',
      primaryLabel: 'Desk',
      buttonVariant: 'neutral',
    })
  }

  return action('VIEW_INTEL', 'WAIT', 'Review', {
    urgency: 'none',
    primaryLabel: 'Intel',
    buttonVariant: 'neutral',
  })
}

export type ActionProminence = {
  heroScale: 'large' | 'medium'
  ladderDefaultOpen: boolean
  showLadder: boolean
  metricsMuted: boolean
}

export function actionProminence(action: CardAction, hasPlan: boolean): ActionProminence {
  const tradeFocus = ['PROPOSE_ENTRY', 'ADJUST_PLAN', 'BUILD_PLAN', 'REVIEW_EXIT'].includes(action.type)
  const passive = ['VIEW_INTEL', 'REVIEW_SETUP', 'REFRESH_DATA', 'WATCH_ON_DESK', 'QUEUE_PROPOSAL', 'NONE'].includes(action.type)
    || (action.urgency === 'none' && !tradeFocus)

  return {
    heroScale: tradeFocus ? 'large' : 'medium',
    ladderDefaultOpen: tradeFocus && hasPlan && action.type !== 'BUILD_PLAN',
    showLadder: hasPlan && action.type !== 'REFRESH_DATA',
    metricsMuted: passive && !hasPlan,
  }
}

export function verdictColor(v: CardVerdict): string {
  const map: Record<CardVerdict, string> = {
    READY: '#16a34a',
    WAIT: '#d97706',
    SKIP: '#94a3b8',
    STALE: '#d97706',
    FIX: '#dc2626',
    BUILD: '#d97706',
    WATCH: '#60a5fa',
  }
  return map[v]
}

export function buttonStyle(variant: ButtonVariant, compact = false): Record<string, string | number> {
  const green = '#16a34a'
  const amber = '#d97706'
  const muted = '#94a3b8'
  const tagBorder = 'rgba(71,85,105,.45)'
  const pad = compact ? '6px 12px' : '9px 18px'
  const fs = compact ? 11 : 12
  const minW = compact ? 72 : 132
  if (variant === 'solid-green') {
    return {
      fontSize: fs, fontWeight: 800, padding: pad, borderRadius: 6, cursor: 'pointer',
      minWidth: minW, border: `1px solid ${green}`, background: green, color: '#fff', whiteSpace: 'nowrap',
    }
  }
  if (variant === 'outline-amber') {
    return {
      fontSize: fs, fontWeight: 800, padding: pad, borderRadius: 6, cursor: 'pointer',
      minWidth: minW, border: `1px solid ${amber}`, background: 'rgba(217,119,6,.1)', color: '#fcd34d', whiteSpace: 'nowrap',
    }
  }
  return {
    fontSize: fs, fontWeight: 800, padding: pad, borderRadius: 6, cursor: 'pointer',
    minWidth: minW, border: `1px solid ${tagBorder}`, background: 'transparent', color: muted, whiteSpace: 'nowrap',
  }
}

export function rrTooltip(entry: number | null, stop: number | null, planTarget: number | null, rr: number | null): string {
  if (!entry || !stop || !planTarget || rr == null) {
    return 'Reward-to-risk: (plan target − entry) ÷ (entry − stop). Requires limit, stop, and target.'
  }
  return [
    `Reward-to-risk: (plan target − entry) ÷ (entry − stop).`,
    `Your plan: ${money(planTarget)} target, ${money(entry)} entry, ${money(stop)} stop → ${rr.toFixed(2)}R.`,
    'Desk rule: below 1.5R = review; below 1.0R = block.',
  ].join(' ')
}

export function confidenceTooltip(it: any): string {
  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  const modelNote = it.models_agree === true
    ? '2 models (Grok + ChatGPT agree)'
    : it.models_agree === false
      ? '2 models split — cautious view used'
      : 'Partial model coverage (Hermes + enrichment)'
  const updated = it.last_enriched_at ? new Date(it.last_enriched_at).toLocaleString() : 'not yet enriched'
  return [
    conf != null ? `Composite confidence ${Number(conf).toFixed(2)}.` : 'Confidence not yet computed.',
    modelNote,
    `Last enriched ${updated}.`,
    '0.7+ actionable · 0.5–0.7 caution · below 0.5 low conviction.',
  ].join(' ')
}

export function planValidatedTooltip(it: any): string {
  const at = it.entry_planned_at || it.last_validated_at
  if (!at) return 'Not validated — watchlist_entry_planner checks limit, stop, target, and R:R after validation.'
  return `Validated by watchlist_entry_planner ${new Date(at).toLocaleString()}. Does not replace manual review.`
}

export function enrichedTooltip(it: any): string {
  if (!it.last_enriched_at) return 'Finviz RSI/trend not refreshed. Stale after 1h in market hours. Does not replace CIO synthesis.'
  return `Finviz RSI/trend refreshed ${new Date(it.last_enriched_at).toLocaleString()}. Stale after 1h — refresh before acting on technicals.`
}

export function cioViewTooltip(it: any): string {
  const rec = it.latest_recommendation || 'watch'
  return `Final synthesis after Maria (fundamental), Steph (technical), and Risk review. "${rec}" is advisory — ${String(rec).includes('ADD') || String(rec).includes('BUY') ? 'add on plan, not market chase' : 'monitor conviction before sizing'}.`
}

export function dataDoubtTooltip(doubt: string): string {
  return `Action: verify before sizing. CIO data doubt: ${doubt}. Monitoring is still OK.`
}

export function cioRecColor(rec?: string | null): string {
  const u = String(rec ?? '').toUpperCase()
  if (['BUY', 'STRONG_BUY', 'ADD', 'ADD_ON_PULLBACK', 'ACCUMULATE'].some(k => u.includes(k))) return '#16a34a'
  if (['AVOID', 'IGNORE', 'SELL', 'TRIM'].some(k => u.includes(k))) return '#dc2626'
  if (['HOLD', 'RESEARCH_MORE', 'WAIT'].some(k => u.includes(k))) return '#d97706'
  return '#94a3b8'
}

export function targetVsStreetLabel(planTarget: number | null, streetTarget: number | null): string | null {
  if (planTarget == null || streetTarget == null || !Number.isFinite(planTarget) || !Number.isFinite(streetTarget)) return null
  const pct = ((planTarget - streetTarget) / streetTarget) * 100
  if (Math.abs(pct) < 3) return `Target ${money(planTarget)} ≈ Street ${money(streetTarget)}`
  if (pct < 0) return `Target ${money(planTarget)} is ${Math.abs(pct).toFixed(0)}% below Street ${money(streetTarget)} — conservative`
  return `Target ${money(planTarget)} is ${pct.toFixed(0)}% above Street ${money(streetTarget)} — aggressive`
}

export function dataQualityFlags(args: {
  it: any
  stale: boolean
  enriched: boolean
  needsRefresh: boolean
  dataDoubt: string
}): { label: string; severity: 'red' | 'amber' | 'none' }[] {
  const { it, stale, enriched, needsRefresh, dataDoubt } = args
  const flags: { label: string; severity: 'red' | 'amber' | 'none' }[] = []
  if (dataDoubt) flags.push({ label: 'Data doubt', severity: 'amber' })
  if (!enriched) flags.push({ label: 'Awaiting enrichment', severity: 'amber' })
  else if (stale) flags.push({ label: 'Stale technicals', severity: 'amber' })
  if (needsRefresh && !stale) flags.push({ label: 'Agents pending', severity: 'amber' })
  if (it.final_synthesis_status === 'pending') flags.push({ label: 'CIO synthesis pending', severity: 'amber' })
  if (it.price == null) flags.push({ label: 'No live price', severity: 'red' })
  return flags
}

/** One-line why — CIO/Hermes vs Street, advisory, plan state. */
export function actionReasoning(args: {
  it: any
  pa?: any
  adv?: { advisory_flag?: string; note?: string } | null
  action: CardAction
  hasPlan: boolean
  rr: number | null
  stale: boolean
  enriched: boolean
}): string {
  const { it, pa, adv, action, hasPlan, rr, stale, enriched } = args
  const parts: string[] = []

  const cio = String(it.latest_recommendation || '').toUpperCase()
  const streetRec = pa?.rec ? String(pa.rec).replace(/_/g, ' ') : null
  if (pa?.divergence === 'divergent') {
    parts.push(`CIO ${cioLabel(it.latest_recommendation)} disagrees with Street ${streetRec || pa?.street || 'consensus'}`)
  } else if (cioAvoid(it.latest_recommendation) && streetRec && /buy/i.test(streetRec)) {
    parts.push(`CIO ${cioLabel(it.latest_recommendation)} — Street still ${streetRec}`)
  }

  if (it.hermes_rank != null) {
    parts.push(`Hermes #${it.hermes_rank}${it.hermes_composite_score != null ? ` (score ${Number(it.hermes_composite_score).toFixed(0)})` : ''}`)
  }

  if (adv?.advisory_flag === 'caution' && adv.note) {
    parts.push(truncateWords(adv.note, 12))
  } else if (adv?.advisory_flag === 'favorable' && adv.note) {
    parts.push(truncateWords(adv.note, 10))
  }

  if (action.detail && !parts.length) parts.push(truncateWords(action.detail, 14))
  if (!hasPlan && enriched) parts.push('No entry plan yet — build limit/stop/target before proposing')
  if (stale && hasPlan) parts.push('Refresh before acting on RSI/advisory')
  if (rr != null && rr < 1.5 && hasPlan) parts.push(`Thin R:R ${rr.toFixed(1)}`)

  if (it.synthesis_narrative_snip && parts.length < 2) {
    parts.push(truncateWords(String(it.synthesis_narrative_snip), 16))
  }

  if (!parts.length && action.subtext) return action.subtext
  return parts.slice(0, 2).join(' · ') || action.subtext || 'Review intel before sizing'
}

function truncateWords(text: string, maxWords: number): string {
  const words = String(text).trim().split(/\s+/)
  if (words.length <= maxWords) return words.join(' ')
  return `${words.slice(0, maxWords).join(' ')}…`
}

export function ladderStepTooltip(label: string, px: number, action: string): string {
  const tier =
    label.startsWith('T1') ? 'First scale-out at +1R. Sell ⅓ via limit, then move stop to breakeven.'
      : label.includes('plan') || label.startsWith('T2') ? 'Plan target. Sell another ⅓, trail stop to T1. Primary profit objective from the entry engine.'
        : label.startsWith('T3') ? 'Runner toward Street mean or extended target. Remaining ⅓ uses trailing stop (1R offset).'
          : ''
  return [tier, `${label} @ $${px.toFixed(2)}`, action].filter(Boolean).join(' ')
}