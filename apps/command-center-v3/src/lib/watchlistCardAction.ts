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

/** Unified hero + primary CTA — derived together, never independent labels. */
export type CardAction = {
  type: CardActionType
  heroText: string
  subtext?: string
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

function monitorOnlyHero(text: string): boolean {
  const t = text.toLowerCase()
  return t.includes('do not') || t.includes('monitor only')
}

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `$${Number(v).toFixed(2)}`
}

function action(
  type: CardActionType,
  heroText: string,
  opts: {
    subtext?: string
    urgency?: ActionUrgency
    primaryLabel: string
    buttonVariant: ButtonVariant
    allowPrimary?: boolean
  },
): CardAction {
  let variant = opts.buttonVariant
  if (monitorOnlyHero(heroText) && variant === 'solid-green') variant = 'neutral'
  return {
    type,
    heroText,
    subtext: opts.subtext,
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

  if (it.private_nontradeable) {
    return action('VIEW_INTEL', 'Do not trade — private ticker', {
      subtext: it.private_note || it.private_company,
      urgency: 'red',
      primaryLabel: 'View intel',
      buttonVariant: 'neutral',
    })
  }

  const noStop = warns.some(w => w.text.includes('NO STOP'))
  if (noStop) {
    return action('ADJUST_PLAN', 'Define stop before entering', {
      subtext: 'Risk undefined without a planned stop',
      urgency: 'red',
      primaryLabel: 'Fix plan',
      buttonVariant: 'outline-amber',
    })
  }

  if (stale && hasPlan) {
    return action('REFRESH_DATA', 'Refresh before acting — data stale', {
      subtext: 'Technical enrichment may not match current price',
      urgency: 'amber',
      primaryLabel: 'Refresh data',
      buttonVariant: 'neutral',
    })
  }

  if (adv?.advisory_flag === 'caution' && !hasPlan) {
    const note = adv.note ? String(adv.note).slice(0, 80) : 'setup advisory caution'
    return action('REVIEW_SETUP', `Monitor only — ${note}`, {
      subtext: 'No validated entry plan',
      urgency: 'amber',
      primaryLabel: 'Review setup',
      buttonVariant: 'neutral',
    })
  }

  if (adv?.advisory_flag === 'caution' && hasPlan) {
    const note = adv.note ? String(adv.note).slice(0, 80) : 'setup advisory caution'
    return action('VIEW_INTEL', `Monitor only — ${note}`, {
      subtext: 'Plan exists but advisory cautions — verify before proposing',
      urgency: 'amber',
      primaryLabel: 'View intel',
      buttonVariant: 'neutral',
    })
  }

  if (cioAvoid(it.latest_recommendation)) {
    const cv = String(it.latest_recommendation).replace(/_/g, ' ').toLowerCase()
    return action('VIEW_INTEL', `Do not add — CIO view is ${cv}`, {
      subtext: hasPlan ? 'Plan is advisory; align with CIO before sizing' : undefined,
      urgency: 'amber',
      primaryLabel: 'View intel',
      buttonVariant: 'neutral',
    })
  }

  if (rr != null && rr < 1) {
    return action('ADJUST_PLAN', `Rework plan — R:R ${rr.toFixed(2)} below 1.0`, {
      subtext: 'Reward smaller than risk at this entry',
      urgency: 'red',
      primaryLabel: 'Fix plan',
      buttonVariant: 'outline-amber',
    })
  }

  if (rr != null && rr < 1.5) {
    return action('ADJUST_PLAN', `Rework plan — R:R ${rr.toFixed(2)} is thin`, {
      subtext: 'Raise target or tighten stop before proposing',
      urgency: 'amber',
      primaryLabel: 'Fix plan',
      buttonVariant: 'outline-amber',
    })
  }

  const planCapWarn = warns.find(w => w.text.includes('plan target') && w.text.includes('Street'))
  if (planCapWarn && hasPlan) {
    return action('REVIEW_EXIT', 'Raise target or keep runner — plan caps below Street', {
      subtext: 'Do not exit entire position at plan target alone',
      urgency: 'amber',
      primaryLabel: 'Review exit',
      buttonVariant: 'outline-amber',
    })
  }

  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  if (conf != null && Number(conf) < 0.5 && !hasPlan) {
    return action('VIEW_INTEL', 'Monitor only — low conviction', {
      subtext: `Confidence ${Number(conf).toFixed(2)} · gather more evidence`,
      urgency: 'none',
      primaryLabel: 'View intel',
      buttonVariant: 'neutral',
    })
  }

  const urgency = it.entry_urgency
  if (urgency === 'ready' && hasPlan && entry != null) {
    return action('PROPOSE_ENTRY', `Propose limit ${money(entry)} · stop ${money(Number(it.entry_stop))}`, {
      subtext: rr != null ? `READY · R:R ${rr.toFixed(1)}` : 'READY · limit order',
      urgency: 'green',
      primaryLabel: 'Propose Entry',
      buttonVariant: 'solid-green',
    })
  }

  if (urgency === 'near_entry' && hasPlan && entry != null) {
    return action('PROPOSE_ENTRY', `Add on weakness near ${money(entry)}`, {
      subtext: rr != null ? `NEAR-ENTRY · R:R ${rr.toFixed(1)}` : 'NEAR-ENTRY',
      urgency: 'amber',
      primaryLabel: 'Propose Entry',
      buttonVariant: 'solid-green',
    })
  }

  if (!hasPlan) {
    return action(
      enriched ? 'BUILD_PLAN' : 'REFRESH_DATA',
      enriched ? 'Monitor only — no validated plan' : 'Awaiting enrichment',
      {
        subtext: enriched ? 'Build limit, stop, and target first' : undefined,
        urgency: 'none',
        primaryLabel: enriched ? 'Build plan' : 'Refresh data',
        buttonVariant: enriched ? 'outline-amber' : 'neutral',
      },
    )
  }

  if (entry != null) {
    return action('WATCH_ON_DESK', `Hold for trigger at ${money(entry)}`, {
      subtext: rr != null ? `R:R ${rr.toFixed(1)}` : undefined,
      urgency: 'none',
      primaryLabel: 'Watch on desk',
      buttonVariant: 'neutral',
    })
  }

  return action('VIEW_INTEL', 'Monitor — review intel before acting', {
    urgency: 'none',
    primaryLabel: 'View intel',
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

export function buttonStyle(variant: ButtonVariant): Record<string, string | number> {
  const green = '#16a34a'
  const amber = '#d97706'
  const muted = '#94a3b8'
  const tagBorder = 'rgba(71,85,105,.45)'
  if (variant === 'solid-green') {
    return {
      fontSize: 12, fontWeight: 800, padding: '9px 18px', borderRadius: 8, cursor: 'pointer',
      minWidth: 132, border: `1px solid ${green}`, background: green, color: '#fff',
    }
  }
  if (variant === 'outline-amber') {
    return {
      fontSize: 12, fontWeight: 800, padding: '9px 18px', borderRadius: 8, cursor: 'pointer',
      minWidth: 132, border: `1px solid ${amber}`, background: 'rgba(217,119,6,.1)', color: '#fcd34d',
    }
  }
  return {
    fontSize: 12, fontWeight: 800, padding: '9px 18px', borderRadius: 8, cursor: 'pointer',
    minWidth: 132, border: `1px solid ${tagBorder}`, background: 'transparent', color: muted,
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

export function ladderStepTooltip(label: string, px: number, action: string): string {
  const tier =
    label.startsWith('T1') ? 'First scale-out at +1R. Sell ⅓ via limit, then move stop to breakeven.'
      : label.includes('plan') || label.startsWith('T2') ? 'Plan target. Sell another ⅓, trail stop to T1. Primary profit objective from the entry engine.'
        : label.startsWith('T3') ? 'Runner toward Street mean or extended target. Remaining ⅓ uses trailing stop (1R offset).'
          : ''
  return [tier, `${label} @ $${px.toFixed(2)}`, action].filter(Boolean).join(' ')
}