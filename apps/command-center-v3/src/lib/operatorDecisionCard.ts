/**
 * operatorDecisionCard.ts — translate a decision packet + action policy into
 * one operator-facing conclusion. The packet is the audit record; this is the
 * primary card contract.
 *
 * Primary states (only these control color/CTA):
 *   READY | WAIT | REFRESH | BLOCKED | NO TRADE | MANAGE POSITION
 *
 * Pure presentation. No orders. No 2FA.
 */

export type OperatorState =
  | 'READY'
  | 'WAIT'
  | 'REFRESH'
  | 'BLOCKED'
  | 'NO TRADE'
  | 'MANAGE POSITION'

export type OperatorPlan = {
  key: string
  title: string
  statusLabel: string
  why?: string
}

export type OperatorMechanics = {
  entry?: string
  limit?: string
  stop?: string
  target?: string
  rr?: string
  summary: string
  previous?: boolean
}

export type OperatorPresentation = {
  state: OperatorState
  headline: string
  thesisLine: string
  mechanics: OperatorMechanics | null
  whyLines: string[]
  chips: string[]
  primaryCta: string
  secondaryCta: string
  primaryFamily: OperatorPlan | null
  alternative: OperatorPlan | null
  whyNot: { title: string; reason: string }[]
  stale: boolean
  held: boolean
  audit: {
    packet: any
    actionPolicy: any
    families: any
    legacy: any
    modelReview: any
    ownership: any
    currentValidity: any
    inputHashes: { packet?: string; current?: string }
  }
}

const n = (v: any, d = 2) => {
  if (v == null || v === '') return null
  const x = Number(v)
  return Number.isFinite(x) ? x.toFixed(d) : null
}

function money(v: any): string | null {
  const s = n(v, 2)
  return s != null ? `$${s}` : null
}

function zone(lo: any, hi: any): string | null {
  const a = money(lo)
  const b = money(hi)
  if (a && b) return `${a}–${b}`
  return a || b
}

function thesisWords(ts: string): string {
  const m: Record<string, string> = {
    STRONG_CONVICTION: 'strong conviction',
    CONSTRUCTIVE: 'constructive',
    SPECULATIVE_CONSTRUCTIVE: 'speculative constructive',
    NEUTRAL: 'neutral',
    DETERIORATING: 'deteriorating',
    FUNDAMENTALLY_UNATTRACTIVE: 'fundamentally unattractive',
    INSUFFICIENT_EVIDENCE: 'insufficient evidence',
  }
  return m[ts] || ts.replace(/_/g, ' ').toLowerCase()
}

function timingWords(t: string): string {
  const m: Record<string, string> = {
    READY: 'setup ready',
    STARTER_ONLY: 'starter only',
    WAIT_FOR_PULLBACK: 'wait for pullback',
    WAIT_FOR_BREAKOUT: 'wait for breakout',
    BREAKOUT_CONFIRMATION: 'breakout confirmation',
    EXTENDED: 'extended',
    RANGE_BOUND: 'range-bound',
    REVERSAL_WATCH: 'reversal watch',
    EVENT_BLOCKED: 'event blocked',
    NO_VALID_SETUP: 'no valid setup',
  }
  return m[t] || t.replace(/_/g, ' ').toLowerCase()
}

function humanBlock(code: string): string {
  const c = String(code || '')
  const up = c.toUpperCase()
  if (up.includes('TECHNICAL')) return 'Technical snapshot changed after this plan was built'
  if (up.includes('FUNDAMENTAL')) return 'Fundamentals changed after this plan was built'
  if (up.includes('OWNERSHIP')) return 'Ownership changed after this plan was built'
  if (up.includes('EARNINGS') || up.includes('EVENT')) return 'Event / earnings data changed'
  if (up.includes('PRICE')) return 'Price moved beyond the plan’s tolerance'
  if (up.includes('TTL') || up.includes('OLD')) return 'Plan is older than the allowed refresh window'
  if (up.includes('DATA_QUALITY') || up.includes('STALE')) return 'Underlying market data is stale'
  // strip enum noise
  return c
    .replace(/^[A-Z_]+:\s*/i, '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim() || 'Strategy inputs changed'
}

function swingMechanics(s: any, previous = false): OperatorMechanics | null {
  if (!s) return null
  const entry = zone((s.entry_zone || [])[0], (s.entry_zone || [])[1])
  const limit = money(s.limit_price)
  const stop = money(s.stop_price)
  const tgt = money((s.targets || [])[0])
  const rr = s.risk_reward != null ? `${Number(s.risk_reward).toFixed(1)}` : null
  const parts = [
    entry ? `Entry ${entry}` : null,
    limit ? `Limit ${limit}` : null,
    stop ? `Stop ${stop}` : null,
    tgt ? `Target ${tgt}` : null,
    rr ? `${rr}R` : null,
  ].filter(Boolean) as string[]
  if (!parts.length) return null
  return {
    entry: entry || undefined,
    limit: limit || undefined,
    stop: stop || undefined,
    target: tgt || undefined,
    rr: rr || undefined,
    summary: parts.join(' · '),
    previous,
  }
}

function longTermMechanics(s: any, previous = false): OperatorMechanics | null {
  if (!s) return null
  const z = s.starter_entry?.price_or_zone || []
  const entry = zone(z[0], z[1])
  const stop = money(s.stop_or_invalidation?.price)
  const tgt = money((s.targets || [])[0]?.price)
  const rr = s.reward_to_risk != null ? `${Number(s.reward_to_risk).toFixed(1)}` : null
  const parts = [
    entry ? `Starter ${entry}` : null,
    stop ? `Stop ${stop}` : null,
    tgt ? `Target ${tgt}` : null,
    rr ? `${rr}R` : null,
  ].filter(Boolean) as string[]
  if (!parts.length) return null
  return {
    entry: entry || undefined,
    stop: stop || undefined,
    target: tgt || undefined,
    rr: rr || undefined,
    summary: parts.join(' · '),
    previous,
  }
}

function familyWhyNot(key: string, fam: any): string {
  const r = (fam?.rejection_reasons || fam?.blocks || [])[0]
  if (r) return String(r).slice(0, 90)
  const st = String(fam?.decision_state || fam?.state || '').toUpperCase()
  if (st === 'DATA_UNAVAILABLE') {
    if (key === 'options') return 'Option chain unavailable'
    if (key === 'bearish') return 'No short structure defined'
    return 'Not enough data'
  }
  if (st === 'REJECTED') {
    if (key === 'long_term') return 'Long-term ownership rejected'
    if (key === 'bearish') return 'No bearish setup / constraints failed'
    if (key === 'options') return 'No liquid eligible contract'
    return 'Rejected'
  }
  if (st === 'NOT_APPLICABLE') return 'Not applicable'
  return st.replace(/_/g, ' ').toLowerCase() || 'Unavailable'
}

function operatorStatusLabel(fam: any, stale: boolean): string {
  if (stale) return 'previous plan'
  const act = String(fam?.action_state || '').toUpperCase()
  const dec = String(fam?.decision_state || fam?.state || '').toUpperCase()
  if (act === 'READY' && dec === 'ELIGIBLE') return 'ready'
  if (act === 'BLOCKED') return 'blocked'
  if (act === 'STALE') return 'needs refresh'
  if (dec === 'CONDITIONAL' || act === 'CONDITIONAL') return 'waiting'
  if (dec === 'REJECTED') return 'rejected'
  if (dec === 'DATA_UNAVAILABLE') return 'unavailable'
  return dec.replace(/_/g, ' ').toLowerCase() || '—'
}

/**
 * Derive the single operator presentation for a watchlist card.
 */
export function buildOperatorPresentation(opts: {
  packet: any
  actionPolicy?: any
  held?: boolean
  price?: number | null
}): OperatorPresentation | null {
  const packet = opts.packet
  if (!packet || typeof packet !== 'object') return null

  const ap = opts.actionPolicy || {}
  const fams = packet.plan_families || {}
  const lt = fams.long_term || {}
  const sw = fams.swing || {}
  const be = fams.bearish || {}
  const op = fams.options || {}
  const nt = fams.no_trade || {}
  const horizons = packet.horizons || {}
  const thesis = String(horizons.long_term?.thesis_state || 'INSUFFICIENT_EVIDENCE')
  const timing = String(horizons.tactical?.timing || 'NO_VALID_SETUP')
  const earn = packet.event_state?.earnings || {}
  const earnDate = earn.date ? String(earn.date).slice(5).replace('-', ' ') : null // MM-DD-ish
  const earnLabel = earn.date
    ? `earnings ${new Date(earn.date + 'T12:00:00Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
    : null
  const cv = packet.current_validity || {}
  const cvState = String(cv.state || '').toUpperCase()
  // Policy should_be_stale is the time-based gate (RTH ~4h for star/buy plans).
  const ageStale = ap.should_be_stale === true
  const inputsStale =
    cvState === 'STALE' ||
    cvState === 'INVALIDATED' ||
    ap.state === 'STALE' ||
    ap.action === 'REFRESH' ||
    ap.inputs_match === false ||
    ageStale
  const held = !!(opts.held ?? packet.ownership?.held)

  const swStruct = (sw.structures || [])[0]
  const ltStruct = (lt.structures || [])[0]
  const swMech = swingMechanics(swStruct, inputsStale)
  const ltMech = longTermMechanics(ltStruct, inputsStale)

  // ── Primary state ────────────────────────────────────────────────────────
  let state: OperatorState = 'WAIT'
  let headline = 'Wait for a clearer setup'
  let whyLines: string[] = []
  let primaryCta = 'Details'
  let secondaryCta = 'Refresh'
  let mechanics: OperatorMechanics | null = null
  let primaryFamily: OperatorPlan | null = null
  let alternative: OperatorPlan | null = null

  if (inputsStale) {
    state = 'REFRESH'
    const reasons = (ap.invalidation_reasons || ap.blocks || cv.invalidation_reasons || [])
      .map((x: any) => humanBlock(String(x)))
    headline = 'Strategy inputs changed'
    whyLines = reasons.length
      ? reasons.slice(0, 2)
      : [humanBlock(ap.reason || 'Inputs changed since this strategy was built')]
    primaryCta = 'Refresh Strategy'
    secondaryCta = 'View Previous Plan'
    mechanics = swMech || ltMech
    if (mechanics) mechanics = { ...mechanics, previous: true }
    primaryFamily = {
      key: 'refresh',
      title: 'Previous plan',
      statusLabel: 'not current',
      why: whyLines[0],
    }
  } else if (held) {
    state = 'MANAGE POSITION'
    if (String(ap.state || '').toUpperCase() === 'BLOCKED' || timing === 'EVENT_BLOCKED') {
      headline = 'Hold — event risk on new activity'
      whyLines = [
        earnLabel ? `${earnLabel} is inside the decision window` : 'Event risk blocks new entries',
        'Manage the existing position; do not size a new starter from this card',
      ]
      primaryCta = 'Review Event Risk'
    } else {
      headline = 'Position management first'
      whyLines = [
        'You already hold this symbol — lead with hold / add / trim / hedge, not a new starter allocation',
        swMech ? `Swing context: ${swMech.summary}` : 'No active swing plan',
      ]
      primaryCta = 'Review Position'
    }
    secondaryCta = 'Details'
    mechanics = swMech
    primaryFamily = {
      key: 'held',
      title: 'Held position',
      statusLabel: 'manage',
      why: whyLines[0],
    }
    if (String(lt.decision_state || '').toUpperCase() === 'ELIGIBLE' ||
        String(lt.decision_state || '').toUpperCase() === 'CONDITIONAL') {
      alternative = {
        key: 'long_term',
        title: 'Long-term staged shares',
        statusLabel: operatorStatusLabel(lt, false),
        why: familyWhyNot('long_term', lt),
      }
    }
  } else if (String(ap.state || '').toUpperCase() === 'BLOCKED' || timing === 'EVENT_BLOCKED') {
    state = 'BLOCKED'
    headline = earnLabel
      ? `Earnings blocks a new entry`
      : 'New entry blocked'
    whyLines = [
      earnLabel
        ? `${earnLabel} is inside the intended holding window`
        : humanBlock((ap.blocks || [])[0] || ap.reason || 'Event / data block'),
    ]
    primaryCta = 'Review Event Risk'
    secondaryCta = 'Details'
    mechanics = swMech || ltMech
    if (mechanics) mechanics = { ...mechanics, previous: true }
    primaryFamily = {
      key: 'blocked',
      title: 'Event risk',
      statusLabel: 'blocked',
      why: whyLines[0],
    }
  } else if (ap.action === 'NO_ACTION') {
    // Preferred no-trade only when the action policy says so — not merely because
    // the alternative is available while a plan is CONDITIONAL (WAIT).
    state = 'NO TRADE'
    headline = 'No trade — nothing eligible'
    whyLines = [
      humanBlock(nt.reason || ap.reason || 'No eligible constructible plan'),
      thesis === 'FUNDAMENTALLY_UNATTRACTIVE'
        ? 'Long-term ownership is not recommended'
        : thesis === 'INSUFFICIENT_EVIDENCE'
          ? 'Not enough evidence for long-term ownership'
          : '',
    ].filter(Boolean)
    primaryCta = 'Details'
    secondaryCta = 'Refresh'
    primaryFamily = {
      key: 'no_trade',
      title: 'No trade',
      statusLabel: 'preferred',
      why: whyLines[0],
    }
  } else if (ap.action === 'PROPOSE_ENTRY' && ap.allowed) {
    state = 'READY'
    const ltRej = String(lt.decision_state || '').toUpperCase() === 'REJECTED'
    headline = ltRej ? 'Tactical swing only' : 'Swing entry confirmed'
    whyLines = [
      ltRej ? 'Long-term ownership rejected' : 'Swing blueprint is eligible with resolved mechanics',
      ltRej ? 'Short-term setup confirmed' : (horizons.tactical?.trigger ? `Trigger: ${horizons.tactical.trigger}` : ''),
    ].filter(Boolean)
    mechanics = swMech
    primaryCta = 'Review Swing Proposal'
    secondaryCta = ltRej ? 'Why not long term?' : 'Details'
    primaryFamily = {
      key: 'swing',
      title: 'Swing entry',
      statusLabel: 'ready',
      why: whyLines[0],
    }
    if (ltRej) {
      alternative = {
        key: 'long_term',
        title: 'Long-term ownership',
        statusLabel: 'rejected',
        why: familyWhyNot('long_term', lt),
      }
    }
  } else {
    // WAIT / conditional monitor
    state = 'WAIT'
    const pullback = timing === 'WAIT_FOR_PULLBACK' || timing === 'EXTENDED'
    const noSetup = timing === 'NO_VALID_SETUP'
    if (pullback) {
      headline = 'Pullback required'
      whyLines = [
        'Price is above the planned entry zone — do not chase',
        swMech?.entry ? `Enter only on pullback into ${swMech.entry}` : 'Wait for the entry zone',
      ]
      primaryCta = 'Set Entry Alert'
    } else if (noSetup) {
      headline = 'No valid tactical setup'
      whyLines = [
        'No confirmed entry right now',
        String(lt.decision_state || '').toUpperCase() === 'ELIGIBLE'
          ? 'Long-term plan exists but is not an entry signal'
          : 'Watch for a defined trigger',
      ]
      primaryCta = 'Set Alert'
    } else {
      headline = 'Waiting for confirmation'
      whyLines = [
        horizons.tactical?.trigger
          ? `Trigger: ${horizons.tactical.trigger}`
          : 'Conditional — trigger not met',
        horizons.tactical?.invalidation
          ? `Invalidates: ${horizons.tactical.invalidation}`
          : '',
      ].filter(Boolean)
      primaryCta = 'Set Alert'
    }
    secondaryCta = 'Refresh'
    mechanics = swMech || ltMech
    primaryFamily = {
      key: swMech ? 'swing' : 'long_term',
      title: swMech ? 'Swing pullback' : 'Long-term staged shares',
      statusLabel: operatorStatusLabel(swMech ? sw : lt, false),
      why: whyLines[0],
    }
    if (swMech && ltMech) {
      alternative = {
        key: 'long_term',
        title: 'Long-term staged shares',
        statusLabel: operatorStatusLabel(lt, false),
      }
    }
  }

  // Built-age stamp + clock time (always visible — operator asked for timestamps)
  const builtAt = ap.generated_at || packet.evaluated_at || packet.facts_as_of
  const ageH = typeof ap.packet_age_hours === 'number'
    ? ap.packet_age_hours
    : (builtAt
      ? (Date.now() - new Date(String(builtAt).replace(' ', 'T')).getTime()) / 36e5
      : null)
  let ageLabel: string | null = null
  let clockLabel: string | null = null
  if (builtAt) {
    const d = new Date(String(builtAt).replace(' ', 'T'))
    if (Number.isFinite(d.getTime())) {
      try {
        clockLabel = d.toLocaleTimeString('en-US', {
          hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York',
          timeZoneName: 'short',
        })
      } catch {
        clockLabel = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    }
  }
  if (ageH != null && Number.isFinite(ageH) && ageH >= 0) {
    ageLabel = ageH < 1
      ? `built ${Math.max(1, Math.round(ageH * 60))}m ago`
      : ageH < 48
        ? `built ${ageH.toFixed(1)}h ago`
        : `built ${Math.round(ageH / 24)}d ago`
  }
  const ttlH = typeof ap.ttl_hours_applied === 'number' ? ap.ttl_hours_applied : null
  const stampLine = [
    clockLabel ? `as of ${clockLabel}` : null,
    ageLabel,
    ttlH != null && !inputsStale ? `TTL ${ttlH}h${ap.rth ? ' RTH' : ''}` : null,
  ].filter(Boolean).join(' · ')

  // Thesis line (always operator language)
  const thesisLine = [
    `Long term ${thesisWords(thesis)}`,
    `tactical ${timingWords(timing)}`,
    earnLabel || null,
    inputsStale ? 'needs refresh' : (stampLine || 'data current'),
  ].filter(Boolean).join(' · ')

  // Chips (max 3) — timestamp chip when current
  const chips: string[] = []
  if (inputsStale) chips.push('NEEDS REFRESH')
  else if (clockLabel && ageLabel) {
    chips.push(`${clockLabel} · ${ageLabel.replace(/^built /, '')}`.toUpperCase())
  } else if (ageLabel) chips.push(ageLabel.toUpperCase().replace('BUILT ', ''))
  else chips.push('CURRENT')
  if (earnLabel) chips.push(earnLabel.toUpperCase())
  if (held) chips.push('HELD')
  else if (thesis === 'FUNDAMENTALLY_UNATTRACTIVE') chips.push('LT REJECTED')
  else if (timing === 'EXTENDED' || timing === 'WAIT_FOR_PULLBACK') chips.push('NO CHASE')
  const finalChips = chips.slice(0, 3)

  // Why-not alternatives (compact)
  const whyNot: { title: string; reason: string }[] = []
  if (!inputsStale) {
    if (primaryFamily?.key !== 'options' && String(op.decision_state || op.state || '').toUpperCase() !== 'ELIGIBLE') {
      whyNot.push({ title: 'Why not options?', reason: familyWhyNot('options', op) })
    }
    if (primaryFamily?.key !== 'bearish' && String(be.decision_state || be.state || '').toUpperCase() !== 'ELIGIBLE') {
      whyNot.push({ title: 'Why not short?', reason: familyWhyNot('bearish', be) })
    }
    if (primaryFamily?.key !== 'long_term' &&
        ['REJECTED', 'DATA_UNAVAILABLE'].includes(String(lt.decision_state || '').toUpperCase())) {
      whyNot.push({ title: 'Why not long term?', reason: familyWhyNot('long_term', lt) })
    }
  }

  return {
    state,
    headline,
    thesisLine,
    mechanics,
    whyLines: whyLines.slice(0, 3),
    chips: finalChips,
    primaryCta,
    secondaryCta,
    primaryFamily,
    alternative,
    whyNot: whyNot.slice(0, 3),
    stale: inputsStale,
    held,
    audit: {
      packet,
      actionPolicy: ap,
      families: fams,
      legacy: packet.legacy_summary,
      modelReview: packet.model_review,
      ownership: packet.ownership,
      currentValidity: cv,
      inputHashes: {
        packet: ap.packet_input_hash || packet.input_hash,
        current: ap.current_input_hash || cv.current_input_hash,
      },
    },
  }
}

export function operatorStateColor(state: OperatorState): string {
  if (state === 'READY') return '#22c55e'
  if (state === 'REFRESH' || state === 'WAIT' || state === 'MANAGE POSITION') return '#ffb000'
  if (state === 'BLOCKED' || state === 'NO TRADE') return '#ef4444'
  return '#94a3b8'
}
