import type { PlanWarning } from './exitLadder'

export function watchlistNeedsRefresh(it: any, stale: boolean) {
  if (stale) return true
  if (it.final_synthesis_status === 'pending') return true
  return ['maria_status', 'steph_status', 'risk_status'].some(k => {
    const s = it[k]
    return s && String(s).toLowerCase() !== 'completed'
  })
}

/** Price this far (%) from the plan limit = the plan's levels are stale — rebuild before acting.
 *  Mirrors PLAN_DRIFT_REPLAN_PCT in scripts/plan_drift_revalidator.py (nightly auto re-plan). */
export const PLAN_DRIFT_PCT = 15

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
  | 'REC_INTEL'
  | 'ENSEMBLE'
  | 'NONE'

export type ActionWarning = { text: string; severity: 'red' | 'amber' | 'info' }

export type ButtonVariant = 'solid-green' | 'outline-amber' | 'outline-red' | 'neutral'

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
  /** Prominent banner aligned with the decision matrix row for this state. */
  warning?: ActionWarning
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
    warning?: ActionWarning
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
    warning: opts.warning,
  }
}

/**
 * Detailed-card decision matrix — priority order matches operator spec.
 * Primary button + warning banner always align with hero "Recommended Action" text.
 */
export function deriveRecommendedAction(args: {
  it: any
  hasPlan: boolean
  rr: number | null
  warns: PlanWarning[]
  stale: boolean
  enriched: boolean
  entry: number | null
  adv?: { advisory_flag?: string; note?: string } | null
  pa?: { divergence?: string; rec?: string } | null
  dataDoubt?: string
  needsRefresh?: boolean
}): CardAction {
  const { it, hasPlan, rr, warns, stale, enriched, entry, adv, pa, dataDoubt, needsRefresh } = args
  const advNote = adv?.note ? String(adv.note).trim() : undefined
  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  const analystDivergent = pa?.divergence === 'divergent'

  if (it.private_nontradeable) {
    return action('VIEW_INTEL', 'SKIP', 'Do not trade — private ticker', {
      subtext: it.private_note || it.private_company,
      urgency: 'red',
      primaryLabel: 'View Intel',
      buttonVariant: 'neutral',
      warning: { text: 'Private / non-tradeable ticker', severity: 'red' },
    })
  }

  // ── CANONICAL ACTION POLICY (2026-07-21) ────────────────────────────────────
  // When a valid decision packet exists, the backend action-policy is the SOLE
  // authority for action eligibility (it.action_policy, computed by
  // decision_action_policy.py and delivered inline). The card renders its result
  // and therefore CANNOT advertise an action the API refuses — closing the
  // display-vs-behaviour contradiction where cioAvoid(IGNORE) still gated the
  // buttons under a "constructive" packet. Legacy cioAvoid applies ONLY when no
  // packet exists (flagged "LEGACY FALLBACK — PACKET REQUIRED" below).
  const ap = it.action_policy
  if (ap && ap.policy_version) {
    const trig = (ap.warnings || []).join(' · ')
    if (ap.action === 'PROPOSE_ENTRY' && ap.allowed) {
      return action('PROPOSE_ENTRY', 'READY', 'Open MAIN Setup Desk', {
        subtext: 'advisory — opens MAIN desk; broker queue only via Entry Desk / bridge',
        urgency: 'green', primaryLabel: 'Open MAIN Desk', buttonVariant: 'solid-green', allowPrimary: true,
      })
    }
    if (ap.action === 'RESEARCH_OPTIONS' && ap.allowed) {
      return action('VIEW_INTEL', 'READY', 'Research options — structure eligible', {
        subtext: ap.reason, urgency: 'green', primaryLabel: 'Research Options',
        buttonVariant: 'neutral', allowPrimary: true,
      })
    }
    if (ap.state === 'STALE' || ap.action === 'REFRESH') {
      return action('REFRESH_DATA', 'FIX', 'Refresh — packet stale', {
        subtext: (ap.blocks || []).join(' · ') || ap.reason,
        urgency: 'amber', primaryLabel: 'Refresh', buttonVariant: 'neutral', allowPrimary: true,
      })
    }
    // CONDITIONAL / BLOCKED / NO_ACTION / MONITOR — expose the condition, never a
    // ready entry. A conditional plan states its trigger but does not offer entry.
    const blocked = ap.state === 'BLOCKED'
    return action('VIEW_INTEL', blocked ? 'SKIP' : 'WAIT',
      ap.action === 'NO_ACTION' ? 'No trade — nothing eligible'
        : blocked ? 'Blocked — event/data' : 'Conditional — watch the trigger', {
      subtext: trig || ap.reason,
      urgency: blocked ? 'red' : 'amber',
      primaryLabel: 'View Intel', buttonVariant: 'neutral', allowPrimary: false,
      warning: (trig || ap.blocks?.length)
        ? { text: trig || (ap.blocks || []).join(' · '), severity: blocked ? 'red' : 'amber' }
        : undefined,
    })
  }

  const noStop = warns.some(w => w.text.includes('NO STOP'))
  if (noStop) {
    return action('ADJUST_PLAN', 'FIX', 'Set stop before entry', {
      subtext: 'Risk undefined without a planned stop',
      urgency: 'red',
      primaryLabel: 'Adjust Plan',
      buttonVariant: 'outline-red',
      warning: { text: 'No stop on plan — risk undefined', severity: 'red' },
    })
  }

  // Stale-plan defects — MUST rank above the R:R branches: the stored entry_rr was computed at
  // plan time and is meaningless once the plan is incoherent or the price has left the zone
  // (SSTK audit 2026-07-03: limit $13.50 / target $13.20 / price $9.80 still showed "1.3R").
  const planTargetNum = it.entry_target != null ? Number(it.entry_target) : null
  if (hasPlan && entry != null && planTargetNum != null && planTargetNum <= entry) {
    return action('BUILD_PLAN', 'FIX', 'Rebuild plan · target ≤ limit', {
      subtext: 'Plan incoherent — stale levels',
      urgency: 'red',
      primaryLabel: 'Rebuild Plan',
      buttonVariant: 'outline-red',
      warning: { text: `Plan incoherent — target ${planTargetNum.toFixed(2)} at/below limit ${entry.toFixed(2)}; auto re-plan queues nightly`, severity: 'red' },
    })
  }
  // Drift = movement since the plan was WRITTEN (price_at_plan), not distance from the limit.
  // A pullback plan's limit sits deliberately 15-20% below price, so limit-distance flagged every
  // deep-pullback plan as stale and "Rebuild Plan" just minted another one — an endless FIX loop
  // (FATN audit 2026-07-06). Legacy plans without price_at_plan fall back to the old metric.
  const priceNum = it.price != null ? Number(it.price) : null
  const planBase = it.entry_price_at_plan != null && Number(it.entry_price_at_plan) > 0
    ? Number(it.entry_price_at_plan) : entry
  const driftPct = hasPlan && planBase && priceNum ? Math.abs(priceNum / planBase - 1) * 100 : null
  if (driftPct != null && driftPct > PLAN_DRIFT_PCT) {
    return action('BUILD_PLAN', 'FIX', `Rebuild plan · price ${priceNum! < planBase! ? '−' : '+'}${driftPct.toFixed(0)}% since plan`, {
      subtext: 'Price left the planned structure',
      urgency: 'amber',
      primaryLabel: 'Rebuild Plan',
      buttonVariant: 'outline-amber',
      warning: { text: `Price ${money(priceNum)} has moved ${driftPct.toFixed(0)}% since the plan was built (at ${money(planBase)}) — levels are stale; rebuild or wait for tonight's auto re-plan`, severity: 'amber' },
    })
  }

  if (rr != null && rr < 1) {
    return action('ADJUST_PLAN', 'FIX', `Fix plan · R:R ${rr.toFixed(2)}`, {
      subtext: 'Reward < risk',
      urgency: 'red',
      primaryLabel: 'Adjust Plan',
      buttonVariant: 'outline-red',
      warning: { text: `R:R ${rr.toFixed(2)} below threshold — reward < risk`, severity: 'red' },
    })
  }

  if (rr != null && rr < 1.5) {
    // Advisory FIX (amber urgency) — amber banner + amber corrective primary.
    return action('ADJUST_PLAN', 'FIX', `Fix plan · R:R ${rr.toFixed(2)}`, {
      subtext: 'Thin edge',
      urgency: 'amber',
      primaryLabel: 'Adjust Plan',
      buttonVariant: 'outline-amber',
      warning: { text: `R:R ${rr.toFixed(2)} below 1.5 — thin edge`, severity: 'amber' },
    })
  }

  // Exit-ladder review is a HELD-position action — "keep runner" is meaningless with zero shares,
  // and on a watch-only name it preempted the honest CIO-avoid branch below (MRLN audit 2026-07-06:
  // FIX "Review exit ladder" on a 0-share name the CIO said AVOID). A conservative target on an
  // unopened plan is not a defect; unheld names fall through to avoid/divergence/ready branches.
  const planCapWarn = warns.find(w => w.text.includes('plan target') && w.text.includes('Street'))
  if (planCapWarn && hasPlan && Boolean(it.in_portfolio)) {
    return action('REVIEW_EXIT', 'FIX', 'Review exit ladder', {
      subtext: 'Plan target below Street',
      detail: planCapWarn.text,
      urgency: 'amber',
      primaryLabel: 'Review Exit',
      buttonVariant: 'outline-amber',
      warning: { text: 'Plan target below Street mean — keep runner', severity: 'amber' },
    })
  }

  // Data quality beats cautious holds — refresh before View Intel on stale/doubt cards.
  if (stale) {
    return action('REFRESH_DATA', 'STALE', 'Refresh first', {
      subtext: hasPlan ? 'Stale technicals' : 'Stale enrichment',
      urgency: 'amber',
      primaryLabel: 'Refresh Data',
      buttonVariant: 'outline-amber',
      warning: { text: 'Data stale — refresh before acting', severity: 'amber' },
    })
  }
  if (dataDoubt) {
    return action('REFRESH_DATA', 'STALE', 'Refresh first', {
      subtext: 'CIO flagged data doubt',
      detail: dataDoubt,
      urgency: 'amber',
      primaryLabel: 'Refresh Data',
      buttonVariant: 'outline-amber',
      warning: { text: `Data doubt — ${dataDoubt}`, severity: 'amber' },
    })
  }
  if (!enriched || needsRefresh) {
    return action('REFRESH_DATA', 'STALE', 'Refresh first', {
      subtext: !enriched ? 'Awaiting enrichment' : 'Agents pending',
      urgency: 'amber',
      primaryLabel: 'Refresh Data',
      buttonVariant: 'outline-amber',
      warning: { text: !enriched ? 'Awaiting enrichment' : 'Agent synthesis pending', severity: 'amber' },
    })
  }

  if (cioAvoid(it.latest_recommendation)) {
    // LEGACY FALLBACK — reached ONLY when no decision packet exists (the policy
    // branch above returns first when it does). The one-word label gates here as
    // a compatibility path until this symbol is analysed; it is not the packet
    // authority. Labelled so the operator can see the card is not packet-governed.
    return action('VIEW_INTEL', 'SKIP', 'Do not add', {
      subtext: `LEGACY FALLBACK — packet required · CIO ${cioLabel(it.latest_recommendation)}`,
      urgency: 'amber',
      primaryLabel: 'Review Risks',
      buttonVariant: 'neutral',
      warning: { text: `LEGACY FALLBACK — build a decision packet · CIO ${cioLabel(it.latest_recommendation)}`, severity: 'red' },
    })
  }

  if (analystDivergent) {
    return action('VIEW_INTEL', 'WAIT', 'Hold off', {
      subtext: 'CIO disagrees with Street consensus',
      urgency: 'amber',
      primaryLabel: 'View Intel',
      buttonVariant: 'outline-amber',
      warning: { text: 'CIO ≠ Street — review disagreement before sizing', severity: 'amber' },
    })
  }

  if (adv?.advisory_flag === 'caution') {
    return action('VIEW_INTEL', 'WAIT', 'Hold off', {
      subtext: hasPlan ? 'Advisory caution — plan on file' : 'Advisory caution · no plan',
      detail: advNote,
      urgency: 'amber',
      primaryLabel: 'View Intel',
      buttonVariant: 'outline-amber',
      warning: { text: advNote ? `Advisory caution — ${truncateWords(advNote, 10)}` : 'Advisory caution', severity: 'amber' },
    })
  }

  if (conf != null && Number(conf) < 0.5) {
    return action('VIEW_INTEL', 'WAIT', 'Hold off', {
      subtext: hasPlan ? `Low conf ${Number(conf).toFixed(2)} — plan on file` : `Low conf ${Number(conf).toFixed(2)}`,
      urgency: 'amber',
      primaryLabel: 'View Intel',
      buttonVariant: 'outline-amber',
      warning: { text: `Low CIO confidence ${Number(conf).toFixed(2)}`, severity: 'amber' },
    })
  }

  const urgency = it.entry_urgency
  if ((urgency === 'ready' || urgency === 'near_entry') && hasPlan && entry != null) {
    return action('PROPOSE_ENTRY', 'READY', urgency === 'ready' ? `Ready · ${money(entry)}` : `Near entry · ${money(entry)}`, {
      subtext: urgency === 'ready' ? 'Validated plan · limit ready' : 'Validated plan · near trigger',
      urgency: urgency === 'ready' ? 'green' : 'amber',
      primaryLabel: 'Open MAIN Desk',
      buttonVariant: 'solid-green',
    })
  }

  if (!hasPlan) {
    return action(
      enriched ? 'BUILD_PLAN' : 'REFRESH_DATA',
      enriched ? 'BUILD' : 'STALE',
      enriched ? 'Build plan' : 'Enriching',
      {
        subtext: enriched ? 'No validated entry plan' : undefined,
        urgency: 'none',
        primaryLabel: enriched ? 'Build Plan' : 'Refresh Data',
        buttonVariant: enriched ? 'outline-amber' : 'neutral',
        warning: enriched ? { text: 'No validated entry plan', severity: 'info' } : { text: 'Awaiting enrichment', severity: 'amber' },
      },
    )
  }

  if (entry != null) {
    return action('VIEW_INTEL', 'WATCH', `Monitor ${money(entry)}`, {
      subtext: 'Plan on file — await trigger',
      urgency: 'none',
      primaryLabel: 'View Intel',
      buttonVariant: 'neutral',
    })
  }

  return action('VIEW_INTEL', 'WAIT', 'Review setup', {
    subtext: 'Plan on file — confirm before sizing',
    urgency: 'amber',
    primaryLabel: 'View Intel',
    buttonVariant: 'outline-amber',
  })
}

export type SecondaryAction = { type: CardActionType; label: string }

/** Matrix-aligned secondary CTAs — max two, never competing with primary tone. */
export function deriveSecondaryActions(action: CardAction, hasPlan: boolean): SecondaryAction[] {
  const out: SecondaryAction[] = []
  const add = (type: CardActionType, label: string) => {
    if (!out.some(a => a.type === type) && type !== action.type) out.push({ type, label })
  }

  switch (action.type) {
    case 'PROPOSE_ENTRY':
      add('VIEW_INTEL', 'View Intel')
      add('REC_INTEL', 'Rec-Intel')
      break
    case 'REFRESH_DATA':
      add('VIEW_INTEL', 'View Intel')
      break
    case 'VIEW_INTEL':
      add('REC_INTEL', 'Rec-Intel')
      if (['WAIT', 'SKIP'].includes(action.verdict)) add('ENSEMBLE', 'Ensemble')
      if (action.verdict === 'WATCH' && hasPlan) add('WATCH_ON_DESK', 'Monitor')
      break
    case 'ADJUST_PLAN':
    case 'REVIEW_EXIT':
    case 'BUILD_PLAN':
      add('VIEW_INTEL', 'View Intel')
      break
    default:
      add('VIEW_INTEL', 'View Intel')
  }
  return out.slice(0, 2)
}

/** @deprecated Use deriveSecondaryActions */
export function deriveSecondaryAction(
  action: CardAction,
  hasPlan: boolean,
  _symbol: string,
): SecondaryAction | null {
  return deriveSecondaryActions(action, hasPlan)[0] ?? null
}

/** Risk / sizing hint when a validated plan exists. */
export function riskSizingHint(action: CardAction, hasPlan: boolean, rr: number | null): string | null {
  if (!hasPlan || rr == null || rr < 1.5) return null
  if (action.type === 'PROPOSE_ENTRY') {
    return `1–2% of available cash sizing · R:R ${rr.toFixed(1)} · Propose opens calculator`
  }
  if (['WAIT', 'WATCH'].includes(action.verdict) && action.type !== 'REFRESH_DATA') {
    return `Plan ready (R:R ${rr.toFixed(1)}) · 1–2% cash sizing after setup clears`
  }
  if (action.verdict === 'FIX') return `Fix plan before sizing · target R:R ≥ 1.5`
  return null
}

export type ActionProminence = {
  heroScale: 'large' | 'medium'
  ladderDefaultOpen: boolean
  showLadder: boolean
  metricsMuted: boolean
}

export function actionProminence(action: CardAction, hasPlan: boolean): ActionProminence {
  const tradeFocus = ['PROPOSE_ENTRY', 'ADJUST_PLAN', 'BUILD_PLAN', 'REVIEW_EXIT'].includes(action.type)
  const waitWithPlan = action.verdict === 'WAIT' && hasPlan

  return {
    heroScale: tradeFocus || waitWithPlan ? 'large' : 'medium',
    ladderDefaultOpen: tradeFocus && hasPlan && action.type !== 'BUILD_PLAN',
    showLadder: hasPlan && action.type !== 'REFRESH_DATA',
    metricsMuted: !hasPlan && !tradeFocus,
  }
}

export function verdictColor(v: CardVerdict): string {
  const map: Record<CardVerdict, string> = {
    READY: '#2dd4bf',
    WAIT: '#f5a623',
    SKIP: '#8b98ac',
    STALE: '#f5a623',
    FIX: '#ef5350',
    BUILD: '#f5a623',
    WATCH: '#8b98ac',
  }
  return map[v]
}

/** Three treatments only: solid teal (READY primary), outline signal (corrective primaries),
 *  quiet neutral (all secondaries). One solid button per card, ever. */
export function buttonStyle(variant: ButtonVariant, compact = false, prominent = false): Record<string, string | number> {
  const teal = '#2dd4bf'
  const amber = '#f5a623'
  const red = '#ef5350'
  const pad = prominent ? '10px 20px' : compact ? '7px 12px' : '9px 16px'
  const fs = prominent ? 13 : compact ? 11.5 : 12
  const minW = prominent ? 148 : compact ? 0 : 120
  const base = {
    fontSize: fs, fontWeight: prominent ? 800 : 700, padding: pad, borderRadius: prominent ? 7 : 6,
    cursor: 'pointer', minWidth: minW, whiteSpace: 'nowrap',
  }
  if (variant === 'solid-green') {
    return { ...base, border: `1px solid ${teal}`, background: teal, color: '#06231f' }
  }
  if (variant === 'outline-amber') {
    return { ...base, border: `1px solid ${amber}`, background: 'transparent', color: amber }
  }
  if (variant === 'outline-red') {
    return { ...base, border: `1px solid ${red}`, background: 'transparent', color: red }
  }
  return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: '#aeb9ca' }
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
    ? '2 models agree'
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
  if (['BUY', 'STRONG_BUY', 'ADD', 'ADD_ON_PULLBACK', 'ACCUMULATE'].some(k => u.includes(k))) return '#2dd4bf'
  if (['AVOID', 'IGNORE', 'SELL', 'TRIM'].some(k => u.includes(k))) return '#ef5350'
  if (['HOLD', 'RESEARCH_MORE', 'WAIT'].some(k => u.includes(k))) return '#f5a623'
  return '#8b98ac'
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
  adv?: { advisory_flag?: string; band?: string } | null
}): { label: string; severity: 'red' | 'amber' | 'none' }[] {
  const { it, stale, enriched, needsRefresh, dataDoubt, adv } = args
  const flags: { label: string; severity: 'red' | 'amber' | 'none' }[] = []
  if (dataDoubt) flags.push({ label: `Data doubt — ${dataDoubt}`, severity: 'amber' })
  if (!enriched) flags.push({ label: 'Awaiting enrichment', severity: 'amber' })
  else if (stale) flags.push({ label: 'Stale technicals', severity: 'amber' })
  else if (it.last_enriched_at) {
    const ageH = (Date.now() - new Date(it.last_enriched_at).getTime()) / 36e5
    if (ageH >= 4) flags.push({ label: `Enriched ${Math.round(ageH)}h ago`, severity: 'amber' })
  }
  if (needsRefresh && !stale) flags.push({ label: 'Agents pending', severity: 'amber' })
  if (it.final_synthesis_status === 'pending') flags.push({ label: 'CIO synthesis pending', severity: 'amber' })
  if (adv?.advisory_flag === 'caution') {
    flags.push({ label: adv.band ? `Advisory caution · ${adv.band}` : 'Advisory caution', severity: 'amber' })
  }
  const conf = it.research_confidence ?? it.hermes_score_components?._confidence
  if (conf != null && Number(conf) < 0.5) {
    flags.push({ label: `Low CIO conf ${Number(conf).toFixed(2)}`, severity: 'amber' })
  }
  if (it.price == null) flags.push({ label: 'No live price', severity: 'red' })
  if (it.plan_stop_tight || it.plan_stop_tight_vs_atr20 || it.plan_stop_tight_vs_atr) {
    const m20 = it.plan_stop_atr20_mult != null ? Number(it.plan_stop_atr20_mult).toFixed(2) : null
    const m14 = it.plan_stop_atr_mult != null ? Number(it.plan_stop_atr_mult).toFixed(2) : null
    const lbl = m20 != null ? `Tight stop (${m20}× ATR₂₀)` : (m14 != null ? `Tight stop (${m14}× ATR₁₄)` : 'Tight stop (<1× ATR)')
    flags.push({ label: lbl, severity: 'amber' })
  }
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
  if (!hasPlan && enriched) {
    // "No entry plan yet" read as a defect — the operator starred BETA and saw
    // an empty plan with no explanation (2026-07-20). Plans are produced by a
    // BATCH: watchlist_entry_planner runs 17:35 ET weekdays, and starred names
    // get a 1-day cadence instead of 7 and sort first. Say when it will arrive
    // rather than implying something is broken or that manual work is required.
    parts.push(it.starred
      ? 'No entry plan yet — starred, queued for tonight’s planner (17:35 ET)'
      : 'No entry plan yet — planner runs 17:35 ET weekdays; star it to move up the queue')
  }
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