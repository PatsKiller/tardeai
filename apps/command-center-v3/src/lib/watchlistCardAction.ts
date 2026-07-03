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
export type PrimaryActionKind = 'propose' | 'adjust' | 'refresh' | 'intel' | 'review' | 'build'

export type RecommendedAction = {
  text: string
  subtext?: string
  urgency: ActionUrgency
  primaryLabel: string
  primaryKind: PrimaryActionKind
}

function cioAvoid(rec?: string | null): boolean {
  const s = String(rec ?? '').toUpperCase()
  return ['AVOID', 'IGNORE', 'SELL', 'TRIM'].some(k => s.includes(k))
}

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `$${Number(v).toFixed(2)}`
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
}): RecommendedAction {
  const { it, hasPlan, rr, warns, stale, enriched, entry, adv } = args

  if (it.private_nontradeable) {
    return {
      text: 'Do not trade — private / non-public ticker',
      subtext: it.private_note || it.private_company,
      urgency: 'red',
      primaryLabel: 'Open Intel',
      primaryKind: 'intel',
    }
  }

  const noStop = warns.some(w => w.text.includes('NO STOP'))
  if (noStop) {
    return {
      text: 'Do not enter — define a stop before proposing',
      subtext: 'Risk is undefined without a planned stop',
      urgency: 'red',
      primaryLabel: 'Adjust Plan',
      primaryKind: 'adjust',
    }
  }

  if (stale && hasPlan) {
    return {
      text: 'Refresh before acting — technical enrichment is stale',
      subtext: 'Finviz RSI and setup advisory may not reflect current price',
      urgency: 'amber',
      primaryLabel: 'Refresh',
      primaryKind: 'refresh',
    }
  }

  if (adv?.advisory_flag === 'caution') {
    const note = adv.note ? String(adv.note).slice(0, 120) : 'setup advisory flagged caution'
    if (!hasPlan) {
      return {
        text: `Caution — ${note}`,
        subtext: 'Monitor only until a validated entry plan exists',
        urgency: 'amber',
        primaryLabel: 'Review Setup',
        primaryKind: 'review',
      }
    }
  }

  if (cioAvoid(it.latest_recommendation)) {
    return {
      text: `Monitor only — CIO view is ${String(it.latest_recommendation).replace(/_/g, ' ').toLowerCase()}`,
      subtext: hasPlan ? 'Existing plan is advisory; align with CIO before sizing' : undefined,
      urgency: 'amber',
      primaryLabel: 'Open Intel',
      primaryKind: 'intel',
    }
  }

  if (rr != null && rr < 1) {
    return {
      text: 'Review exit ladder — reward smaller than risk at this entry',
      subtext: rr != null ? `R:R ${rr.toFixed(2)} — rework target or skip` : undefined,
      urgency: 'red',
      primaryLabel: 'Adjust Plan',
      primaryKind: 'adjust',
    }
  }

  if (rr != null && rr < 1.5) {
    return {
      text: 'Thin edge — consider raising plan target or tightening stop',
      subtext: `R:R ${rr.toFixed(2)} · below 1.5 is marginal for the risk taken`,
      urgency: 'amber',
      primaryLabel: 'Adjust Plan',
      primaryKind: 'adjust',
    }
  }

  const planCapWarn = warns.find(w => w.text.includes('plan target') && w.text.includes('Street'))
  if (planCapWarn && hasPlan) {
    return {
      text: 'Review exit ladder — plan target may be too conservative',
      subtext: 'Keep a runner toward Street mean; do not exit entire position at plan target',
      urgency: 'amber',
      primaryLabel: 'Review Exit',
      primaryKind: 'adjust',
    }
  }

  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  if (conf != null && Number(conf) < 0.5 && !hasPlan) {
    return {
      text: 'Monitor only — low conviction',
      subtext: `Research confidence ${Number(conf).toFixed(2)} · gather more evidence before sizing`,
      urgency: 'none',
      primaryLabel: 'Open Intel',
      primaryKind: 'intel',
    }
  }

  const urgency = it.entry_urgency
  if (urgency === 'ready' && hasPlan && entry != null) {
    return {
      text: `Ready to propose — limit ${money(entry)}${it.entry_stop != null ? `, stop ${money(Number(it.entry_stop))}` : ''}`,
      subtext: rr != null ? `Disciplined limit order · R:R ${rr.toFixed(1)}` : 'Disciplined limit order',
      urgency: 'green',
      primaryLabel: 'Propose Entry',
      primaryKind: 'propose',
    }
  }

  if (urgency === 'near_entry' && hasPlan && entry != null) {
    return {
      text: `Consider adding on weakness near ${money(entry)} limit`,
      subtext: rr != null ? `NEAR-ENTRY · R:R ${rr.toFixed(1)} · ${it.entry_setup || 'limit order'}` : `NEAR-ENTRY · ${it.entry_setup || 'limit order'}`,
      urgency: 'amber',
      primaryLabel: 'Propose Entry',
      primaryKind: 'propose',
    }
  }

  if (!hasPlan) {
    return {
      text: enriched ? 'Monitor only — no validated entry plan yet' : 'Awaiting enrichment — refresh or wait for agent queue',
      subtext: enriched ? 'Build limit, stop, and target before proposing' : undefined,
      urgency: 'none',
      primaryLabel: enriched ? 'Build Plan' : 'Refresh',
      primaryKind: enriched ? 'build' : 'refresh',
    }
  }

  if (entry != null) {
    return {
      text: `Hold for plan trigger at ${money(entry)} limit`,
      subtext: rr != null ? `R:R ${rr.toFixed(1)} · ${it.entry_model || 'entry model pending'}` : it.entry_model,
      urgency: 'none',
      primaryLabel: 'Propose Entry',
      primaryKind: 'propose',
    }
  }

  return {
    text: 'Monitor — review intel before acting',
    urgency: 'none',
    primaryLabel: 'Open Intel',
    primaryKind: 'intel',
  }
}

export function rrTooltip(entry: number | null, stop: number | null, planTarget: number | null, rr: number | null): string {
  if (!entry || !stop || !planTarget || rr == null) {
    return 'Reward-to-risk: (plan target − entry) ÷ (entry − stop). Requires limit, stop, and target.'
  }
  return [
    `Reward-to-risk: (plan target − entry) ÷ (entry − stop).`,
    `Your plan: ${money(planTarget)} target, ${money(entry)} entry, ${money(stop)} stop → ${rr.toFixed(2)}R.`,
    'Below 1.5R is a thin edge; below 1.0R means risk exceeds reward.',
  ].join(' ')
}

export function confidenceTooltip(it: any): string {
  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  const models = it.models_agree === true ? '2+ models agree' : it.models_agree === false ? 'models split — cautious view used' : 'single or partial model coverage'
  const updated = it.last_enriched_at ? new Date(it.last_enriched_at).toLocaleString() : 'not yet enriched'
  return [
    conf != null ? `Composite research confidence ${Number(conf).toFixed(2)}.` : 'Confidence not yet computed.',
    models,
    `Last enriched ${updated}.`,
    '0.7+ = actionable context; 0.5–0.7 = use with caution; below 0.5 = low conviction.',
  ].join(' ')
}

export function planValidatedTooltip(it: any): string {
  const at = it.entry_planned_at || it.last_validated_at
  if (!at) return 'Entry plan not yet validated — limit, stop, and target checked by entry planner after validation.'
  return `Entry plan last validated ${new Date(at).toLocaleString()}. Validated plans have limit, stop, and target checked against current price and R:R rules.`
}

export function enrichedTooltip(it: any): string {
  if (!it.last_enriched_at) return 'Finviz RSI, trend, and setup advisory not yet refreshed. Stale after 1h during market hours.'
  return `Finviz RSI, trend, and setup advisory refreshed ${new Date(it.last_enriched_at).toLocaleString()}. Stale after 1h during market hours — refresh before acting on technicals.`
}

export function cioViewTooltip(it: any): string {
  const rec = it.latest_recommendation || 'watch'
  return `Final synthesis after Maria (fundamental), Steph (technical), and Risk review. "${rec}" is advisory — ${String(rec).includes('ADD') || String(rec).includes('BUY') ? 'add on plan, not market chase' : 'monitor conviction before sizing'}.`
}

export function dataDoubtTooltip(doubt: string): string {
  return `CIO flagged uncertainty in the synthesis evidence: ${doubt}. Verify before sizing up — does not block monitoring.`
}

export function ladderStepTooltip(label: string, px: number, action: string): string {
  const tier =
    label.startsWith('T1') ? 'First scale-out at +1R. Sell ⅓ via limit, then move stop to breakeven.'
      : label.includes('plan') || label.startsWith('T2') ? 'Plan target. Sell another ⅓, trail stop to T1. Primary profit objective from the entry engine.'
        : label.startsWith('T3') ? 'Runner toward Street mean or extended target. Remaining ⅓ uses trailing stop (1R offset).'
          : ''
  return [tier, `${label} @ $${px.toFixed(2)}`, action].filter(Boolean).join(' ')
}