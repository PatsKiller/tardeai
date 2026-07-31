/**
 * Re-Entry decision scorecard v1.5 (WP-R1 + R1.5 narrative).
 * Pure functions — no React, no network. Fail-closed: missing evidence → UNAVAILABLE, never fake PASS.
 *
 * READY  = in zone + all hard gates PASS (incl. plan integrity) + RSI ≤ 50
 * NEAR   = location near + limited hard WAIT, no BLOCK
 * WAIT   = otherwise (held / stale / missing plan handled as states)
 *
 * reason is always symbol-specific (numbers + structure), never a single global template.
 */

export type GateState = 'PASS' | 'WAIT' | 'BLOCK' | 'UNAVAILABLE'
export type GateKind = 'hard' | 'soft'
export type ReEntryLane = 'NOW' | 'NEAR' | 'WATCH' | 'ALL'

export type ScoreGate = {
  id: string
  label: string
  kind: GateKind
  state: GateState
  current: string
  threshold: string
  why: string
}

export type ScorecardInput = {
  price: number | null
  asOf: string
  rsi: number | null
  trend: string
  entryLow: number | null
  entryHigh: number | null
  stop: number | null
  target: number | null
  support: number | null
  resistance: number | null
  resistanceDistancePct: number | null
  resistanceSide: string
  ma20: number | null
  ma50: number | null
  ma200: number | null
  macdHistogram: number | null
  macdSlope: number | null
  relativeStrength: number | null
  pe: number | null
  forwardPe: number | null
  held: boolean
  regimeLabel: string
  /** max age of asOf before STALE (hours) */
  maxAgeHours?: number
  /** optional narrative context — never invents if absent */
  avgExit?: number | null
  exitDate?: string | null
  mandate?: string
  flags?: string[]
  classified?: string
  eventGaps?: number
  analystRec?: string
  analystTarget?: number | null
  analystCount?: number | null
}

export type ScorecardResult = {
  lane: 'NOW' | 'NEAR' | 'WATCH'
  state: 'READY TO REVIEW' | 'NEAR ENTRY' | 'WAIT' | 'CURRENTLY HELD' | 'STALE' | 'MISSING PLAN' | 'MISSING MARKET'
  action: string
  /** Symbol-specific decision narrative (collapsed row primary “why”) */
  reason: string
  /** Short chips for secondary line (≤ ~6) */
  highlights: string[]
  gates: ScoreGate[]
  hardPass: number
  hardTotal: number
  softPass: number
  softTotal: number
  unavailable: number
  distancePct: number | null
  scoreLabel: string
  /** Risk:reward when stop/target/price allow (null if not computable or invalid) */
  riskReward: number | null
  rsiBand: 'oversold' | 'pullback' | 'neutral' | 'elevated' | 'overbought' | 'unavailable'
  vsExitPct: number | null
  planIntegrityOk: boolean
}

function finite(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function ageHours(asOf: string): number | null {
  if (!asOf) return null
  const t = new Date(asOf).getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, (Date.now() - t) / 36e5)
}

function money(n: number | null): string {
  return n === null ? 'n/a' : `$${n.toFixed(2)}`
}

function gate(id: string, label: string, kind: GateKind, state: GateState, current: string, threshold: string, why: string): ScoreGate {
  return { id, label, kind, state, current, threshold, why }
}

export function rsiBandOf(rsi: number | null): ScorecardResult['rsiBand'] {
  if (rsi === null) return 'unavailable'
  if (rsi <= 30) return 'oversold'
  if (rsi <= 45) return 'pullback'
  if (rsi <= 55) return 'neutral'
  if (rsi <= 70) return 'elevated'
  return 'overbought'
}

/** Long-plan integrity: stop < entry ≤ target with non-inverted risk. */
export function checkPlanIntegrity(
  entryLow: number | null,
  entryHigh: number | null,
  stop: number | null,
  target: number | null,
): { ok: boolean; why: string } {
  if (entryLow === null || entryHigh === null) return { ok: false, why: 'entry zone missing' }
  if (entryLow > entryHigh) return { ok: false, why: `inverted zone ${money(entryLow)}>${money(entryHigh)}` }
  if (stop !== null && target !== null && stop >= target) {
    return { ok: false, why: `stop ${money(stop)} ≥ target ${money(target)}` }
  }
  if (stop !== null && stop >= entryLow) {
    return { ok: false, why: `stop ${money(stop)} not below entry ${money(entryLow)}` }
  }
  if (target !== null && target <= entryHigh) {
    return { ok: false, why: `target ${money(target)} not above entry ${money(entryHigh)}` }
  }
  return { ok: true, why: 'stop < entry < target' }
}

export function computeRiskReward(
  price: number | null,
  stop: number | null,
  target: number | null,
): number | null {
  if (price === null || stop === null || target === null) return null
  const risk = price - stop
  const reward = target - price
  if (risk <= 0 || reward <= 0) return null
  return reward / risk
}

export function daysSince(exitDate: string | null | undefined): number | null {
  if (!exitDate) return null
  const t = new Date(exitDate.slice(0, 10) + 'T12:00:00Z').getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.round((Date.now() - t) / 864e5))
}

/** Extract levels from watch/card-like objects (best-effort, shared paths). */
export function extractLevelsFromContext(watch: any, card: any): Partial<ScorecardInput> {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const mechanics = packet?.selected_family?.mechanics ?? packet?.current_mechanics ?? packet?.mechanics ?? watch?.reentry_plan ?? card?.reentry_plan ?? {}
  const fund = watch?.fundamentals ?? packet?.blind_facts?.fundamentals ?? card?.fundamentals ?? {}
  const tech = packet?.technical_state ?? watch?.technicals ?? card?.technicals ?? {}
  const objs = [watch ?? {}, card ?? {}, packet ?? {}, mechanics ?? {}, tech ?? {}, fund ?? {}]

  const pickN = (paths: string[]): number | null => {
    for (const o of objs) {
      for (const p of paths) {
        const parts = p.split('.')
        let cur: any = o
        for (const part of parts) cur = cur?.[part]
        const n = finite(cur)
        if (n !== null) return n
      }
    }
    return null
  }
  const pickT = (paths: string[]): string => {
    for (const o of objs) {
      for (const p of paths) {
        const parts = p.split('.')
        let cur: any = o
        for (const part of parts) cur = cur?.[part]
        if (cur !== null && cur !== undefined && String(cur).trim()) return String(cur).trim()
      }
    }
    return ''
  }

  let entryLow = pickN(['entry_zone_low', 'reentry_zone_low', 'entry_low', 'mechanics.entry_low'])
  let entryHigh = pickN(['entry_zone_high', 'reentry_zone_high', 'entry_high', 'mechanics.entry_high'])
  const entry = pickN(['entry_limit', 'reentry_price', 'entry_price', 'mechanics.entry'])
  if (entryLow === null) entryLow = entry
  if (entryHigh === null) entryHigh = entry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) [entryLow, entryHigh] = [entryHigh, entryLow]

  const trigger = pickT(['horizons.tactical.trigger', 'horizons.swing.trigger', 'selected_family.mechanics.trigger', 'trigger'])
  const resMatch = trigger.match(/resistance\s+\$?([0-9]+(?:\.[0-9]+)?)/i)
  const supMatch = trigger.match(/support\s+\$?([0-9]+(?:\.[0-9]+)?)/i)

  return {
    price: pickN(['price', 'last_price', 'price_live', 'current_price', 'quote.last']),
    asOf: pickT(['price_as_of', 'last_enriched_at', 'computed_at', 'decision_packet_at', 'as_of']),
    rsi: pickN(['rsi', 'rsi_14', 'technical.rsi', 'technicals.rsi', 'current_rsi']),
    trend: pickT(['trend_state', 'trend_direction', 'overall_direction', 'technical_state.overall_direction', 'technicals.trend']).replace(/_/g, ' ').toUpperCase() || 'UNAVAILABLE',
    entryLow,
    entryHigh,
    stop: pickN(['entry_stop', 'reentry_stop', 'stop_price', 'mechanics.stop']),
    target: pickN(['entry_target', 'reentry_target', 'target_price', 'mechanics.target']),
    support: pickN(['support', 'support_price', 'sc_support', 'technical.support', 'technicals.support']) ?? (supMatch ? finite(supMatch[1]) : null),
    resistance: pickN(['resistance', 'resistance_level', 'resistance_price', 'sc_resistance', 'technical.resistance']) ?? (resMatch ? finite(resMatch[1]) : null),
    ma20: pickN(['ma20', 'sma20', 'technicals.sma20', 'technical.ma20', 'sma20_pct']),
    ma50: pickN(['ma50', 'sma50', 'technicals.sma50', 'technical.ma50']),
    ma200: pickN(['ma200', 'sma200', 'technicals.sma200', 'technical.ma200']),
    macdHistogram: pickN(['macd_histogram', 'macd_hist', 'technicals.macd_histogram']),
    macdSlope: pickN(['macd_histogram_change', 'macd_slope', 'technicals.macd_histogram_change']),
    relativeStrength: pickN(['relative_strength', 'rs_score', 'relative_strength_pct', 'technicals.relative_strength']),
    pe: pickN(['pe', 'trailing_pe', 'pe_ratio']),
    forwardPe: pickN(['forward_pe', 'forwardPe', 'fwd_pe']),
  }
}

/**
 * Build a symbol-specific decision narrative from scored inputs.
 * Deterministic templates only — no LLM. Omits missing facts instead of inventing them.
 */
export function composeDecisionNarrative(
  input: ScorecardInput,
  opts: {
    state: ScorecardResult['state']
    distancePct: number | null
    riskReward: number | null
    rsiBand: ScorecardResult['rsiBand']
    vsExitPct: number | null
    planIntegrityOk: boolean
    planIntegrityWhy: string
    resistanceSuspect: boolean
  },
): { reason: string; highlights: string[]; action: string } {
  const { price, rsi, entryLow, entryHigh, stop, target, support, resistance, resistanceSide, resistanceDistancePct } = input
  const parts: string[] = []
  const highlights: string[] = []

  // Location
  if (price !== null && entryLow !== null && entryHigh !== null) {
    if (opts.distancePct === 0) {
      const mid = (entryLow + entryHigh) / 2
      const pos = price < mid - (entryHigh - entryLow) * 0.15 ? 'low-zone' : price > mid + (entryHigh - entryLow) * 0.15 ? 'high-zone' : 'mid-zone'
      parts.push(`${money(price)} inside ${money(entryLow)}–${money(entryHigh)} (${pos})`)
      highlights.push(`in zone ${money(entryLow)}–${money(entryHigh)}`)
    } else if (opts.distancePct !== null && opts.distancePct > 0) {
      parts.push(`${money(price)} is ${opts.distancePct.toFixed(1)}% above ${money(entryLow)}–${money(entryHigh)}`)
      highlights.push(`+${opts.distancePct.toFixed(1)}% above zone`)
    } else if (opts.distancePct !== null) {
      parts.push(`${money(price)} is ${Math.abs(opts.distancePct).toFixed(1)}% below ${money(entryLow)}–${money(entryHigh)}`)
      highlights.push(`${opts.distancePct.toFixed(1)}% below zone`)
    }
  } else if (price !== null) {
    parts.push(`px ${money(price)} · entry zone n/a`)
  }

  // Momentum
  if (rsi !== null) {
    const bandNote =
      opts.rsiBand === 'oversold' ? 'oversold — calm retest' :
      opts.rsiBand === 'pullback' ? 'pullback-friendly' :
      opts.rsiBand === 'neutral' ? 'neutral momentum' :
      opts.rsiBand === 'elevated' ? 'elevated — not full ready' :
      opts.rsiBand === 'overbought' ? 'overbought — wait' :
      'RSI'
    parts.push(`RSI ${rsi.toFixed(1)} ${bandNote}`)
    highlights.push(`RSI ${rsi.toFixed(1)} ${opts.rsiBand}`)
  }

  // Vs exit
  if (opts.vsExitPct !== null && input.avgExit != null) {
    const sign = opts.vsExitPct >= 0 ? '+' : ''
    const days = daysSince(input.exitDate)
    const dayBit = days === null ? '' : ` · ${days}d since exit`
    parts.push(`${sign}${opts.vsExitPct.toFixed(1)}% vs exit avg ${money(input.avgExit)}${dayBit}`)
    highlights.push(`${sign}${opts.vsExitPct.toFixed(0)}% vs exit`)
  }

  // Structure / risk
  const structBits: string[] = []
  if (resistance !== null) {
    const side = (resistanceSide || '').toUpperCase() || 'n/a'
    const d = resistanceDistancePct
    structBits.push(
      opts.resistanceSuspect
        ? `res ${money(resistance)} suspect (${side}${d == null ? '' : ` ${d >= 0 ? '+' : ''}${d.toFixed(0)}%`})`
        : `${side} res ${money(resistance)}${d == null ? '' : ` (${d >= 0 ? '+' : ''}${d.toFixed(1)}%)`}`,
    )
  }
  if (support !== null) structBits.push(`sup ${money(support)}`)
  if (stop !== null) structBits.push(`stop ${money(stop)}`)
  if (target !== null) structBits.push(`tgt ${money(target)}`)
  if (opts.riskReward !== null) {
    structBits.push(`R:R ${opts.riskReward.toFixed(1)}`)
    highlights.push(`R:R ${opts.riskReward.toFixed(1)}`)
  }
  if (structBits.length) parts.push(structBits.join(' · '))

  // Classification note early so it survives length caps
  const needsClassify = opts.state === 'READY TO REVIEW'
    && (!input.classified || input.classified === 'UNCLASSIFIED' || input.classified === 'AUTO-TAGGED')
  if (needsClassify) {
    parts.push('Unclassified — classify before size')
    highlights.push('unclassified')
  }

  // Soft / context
  const softBits: string[] = []
  if (input.ma50 === null && input.ma200 === null) softBits.push('MA n/a')
  else if (input.ma50 !== null && price !== null) softBits.push(price >= input.ma50 ? '≥MA50' : '<MA50')
  if (input.macdHistogram === null) softBits.push('MACD n/a')
  else softBits.push(input.macdHistogram >= 0 ? 'MACD+' : 'MACD−')
  if (input.pe === null && input.forwardPe === null) softBits.push('P/E n/a')
  else softBits.push(`P/E ${((input.forwardPe ?? input.pe) as number).toFixed(0)}`)
  if (input.trend && input.trend !== 'UNAVAILABLE') softBits.push(input.trend)
  if (input.analystRec && input.analystRec !== 'unavailable' && input.analystRec !== 'UNAVAILABLE') {
    const n = input.analystCount != null ? ` ${input.analystCount}` : ''
    softBits.push(`Street ${input.analystRec}${n}`)
  }
  if (input.mandate && input.mandate !== 'unclassified') softBits.push(input.mandate.replace(/_/g, ' '))
  if (input.flags?.length) softBits.push(input.flags.slice(0, 3).join('/'))
  if (typeof input.eventGaps === 'number' && input.eventGaps > 0) softBits.push(`${input.eventGaps} gaps`)
  if (!opts.planIntegrityOk) softBits.push(`plan fail: ${opts.planIntegrityWhy}`)
  if (opts.resistanceSuspect) softBits.push('resistance scale suspect')
  if (softBits.length) parts.push(softBits.join(' · '))

  // Action
  let action = 'Keep monitoring'
  if (opts.state === 'READY TO REVIEW') action = 'Review re-entry now'
  else if (opts.state === 'NEAR ENTRY') action = 'Prepare the review'
  else if (opts.state === 'CURRENTLY HELD') action = 'Manage as an existing holding'
  else if (opts.state === 'STALE') action = 'Refresh inputs'
  else if (opts.state === 'MISSING PLAN') action = 'Build a candidate entry zone'
  else if (opts.state === 'MISSING MARKET') action = 'Refresh market evidence'
  else if (!opts.planIntegrityOk) action = 'Rebuild invalid entry plan'

  let reason = parts.filter(Boolean).join('. ')
  if (reason.length > 320) reason = reason.slice(0, 317) + '…'
  if (!reason) reason = 'Insufficient evidence for a symbol-specific re-entry narrative.'

  return { reason, highlights: highlights.slice(0, 6), action }
}

export function buildReEntryScorecard(input: ScorecardInput): ScorecardResult {
  const maxAge = input.maxAgeHours ?? 96
  const hours = ageHours(input.asOf)
  const stale = hours === null || hours > maxAge
  const { price, rsi, entryLow, entryHigh, held } = input
  const rsiBand = rsiBandOf(rsi)
  const planCheck = checkPlanIntegrity(entryLow, entryHigh, input.stop, input.target)
  const riskReward = computeRiskReward(price, input.stop, input.target)
  let vsExitPct: number | null = null
  if (price !== null && input.avgExit != null && input.avgExit > 0) {
    vsExitPct = ((price - input.avgExit) / input.avgExit) * 100
  }

  let distancePct: number | null = null
  if (price !== null && entryLow !== null && entryHigh !== null && entryLow > 0 && entryHigh > 0) {
    distancePct = price > entryHigh
      ? ((price - entryHigh) / entryHigh) * 100
      : price < entryLow
        ? -((entryLow - price) / entryLow) * 100
        : 0
  }

  const inZone = distancePct === 0
  const nearAbove = distancePct !== null && distancePct > 0 && distancePct <= 3
  const nearBelow = distancePct !== null && distancePct < 0 && distancePct >= -3

  // Resistance scale suspect: price >50% above marked "resistance" → level likely stale
  let resistanceSuspect = false
  if (input.resistance !== null && price !== null && input.resistance > 0) {
    const gap = (price - input.resistance) / input.resistance
    if (gap > 0.5) resistanceSuspect = true
  }

  const gates: ScoreGate[] = []

  // Hard: market
  if (price === null || rsi === null) {
    gates.push(gate('market', 'Market quote + RSI', 'hard', 'UNAVAILABLE',
      `px ${money(price)} · RSI ${rsi === null ? '—' : rsi.toFixed(1)}`,
      'price and RSI present', 'Current price and RSI are required before a re-entry review.'))
  } else {
    gates.push(gate('market', 'Market quote + RSI', 'hard', 'PASS',
      `px ${money(price)} · RSI ${rsi.toFixed(1)} (${rsiBand})`,
      'price and RSI present', 'Live quote and RSI available.'))
  }

  // Hard: freshness
  if (stale) {
    gates.push(gate('fresh', 'Evidence freshness', 'hard', 'WAIT',
      hours === null ? 'as-of missing' : `${hours.toFixed(0)}h old`,
      `≤ ${maxAge}h`, 'Market/technical evidence is too old to trust for timing.'))
  } else {
    gates.push(gate('fresh', 'Evidence freshness', 'hard', 'PASS',
      hours === null ? 'current' : `${hours.toFixed(0)}h old`,
      `≤ ${maxAge}h`, 'Evidence age is within the trust window.'))
  }

  // Hard: plan present
  if (entryLow === null || entryHigh === null) {
    gates.push(gate('plan', 'Validated entry zone', 'hard', 'UNAVAILABLE',
      'unavailable', 'entry low–high present', 'No validated entry range — build a candidate plan first.'))
  } else {
    gates.push(gate('plan', 'Validated entry zone', 'hard', 'PASS',
      `${money(entryLow)}–${money(entryHigh)}`, 'entry low–high present', 'Entry zone is present on the decision packet / plan.'))
  }

  // Hard: plan integrity (stop/target geometry)
  if (entryLow === null || entryHigh === null) {
    gates.push(gate('plan_integrity', 'Plan integrity', 'hard', 'UNAVAILABLE',
      'no zone', 'stop < entry < target', 'Cannot validate plan geometry without a zone.'))
  } else if (!planCheck.ok) {
    gates.push(gate('plan_integrity', 'Plan integrity', 'hard', 'WAIT',
      planCheck.why, 'stop < entry < target', 'Entry plan geometry is invalid — rebuild before READY.'))
  } else {
    gates.push(gate('plan_integrity', 'Plan integrity', 'hard', 'PASS',
      planCheck.why, 'stop < entry < target', 'Stop, zone, and target are ordered correctly for a long re-entry.'))
  }

  // Hard: location
  if (entryLow === null || entryHigh === null || distancePct === null) {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'UNAVAILABLE',
      money(price), 'in zone or ≤3% above', 'Cannot score location without price and zone.'))
  } else if (inZone) {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'PASS',
      `${money(price)} inside zone`, 'in zone or ≤3% above', 'Price is inside the validated entry zone.'))
  } else if (nearAbove) {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'WAIT',
      `${distancePct!.toFixed(1)}% above zone`, 'in zone or ≤3% above', 'Price is close above the zone — prepare, do not treat as ready.'))
  } else if (nearBelow) {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'WAIT',
      `${Math.abs(distancePct!).toFixed(1)}% below zone`, 'in zone or ≤3% above', 'Price is just below the zone — watch for reclaim into the band.'))
  } else {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'WAIT',
      distancePct! > 0 ? `${distancePct!.toFixed(1)}% above` : `${Math.abs(distancePct!).toFixed(1)}% below`,
      'in zone or ≤3% above', 'Price is outside the near-entry band.'))
  }

  // Hard: momentum RSI
  if (rsi === null) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'UNAVAILABLE', '—', 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI required.'))
  } else if (rsi > 70) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'WAIT', rsi.toFixed(1), 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is overbought — wait for a calmer retest.'))
  } else if (rsi <= 45) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'PASS', `${rsi.toFixed(1)} ${rsiBand}`, 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is not extended — constructive for a pullback re-entry review.'))
  } else if (rsi <= 55) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'WAIT', `${rsi.toFixed(1)} ${rsiBand}`, 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is moderate — near setup, not fully calm.'))
  } else {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'WAIT', `${rsi.toFixed(1)} ${rsiBand}`, 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is elevated for a disciplined pullback re-entry.'))
  }

  // Soft: structure MAs
  if (price === null || (input.ma50 === null && input.ma200 === null)) {
    gates.push(gate('structure', 'MA structure', 'soft', 'UNAVAILABLE', 'MAs unavailable', 'price vs MA50/200', 'Moving averages not present on packet.'))
  } else if (input.ma50 !== null && price! >= input.ma50) {
    gates.push(gate('structure', 'MA structure', 'soft', 'PASS',
      `px ≥ MA50 ${money(input.ma50)}`, 'price ≥ MA50 (soft)', 'Price holds above intermediate trend (MA50).'))
  } else if (input.ma200 !== null && price! >= input.ma200) {
    gates.push(gate('structure', 'MA structure', 'soft', 'WAIT',
      `px < MA50 · ≥ MA200 ${money(input.ma200)}`, 'price ≥ MA50 (soft)', 'Above long-term MA but intermediate structure still soft.'))
  } else {
    gates.push(gate('structure', 'MA structure', 'soft', 'WAIT',
      `px ${money(price)} vs MA50 ${money(input.ma50)}`, 'price ≥ MA50 (soft)', 'Price is below intermediate/long MAs — weaker structure.'))
  }

  // Soft: MACD
  if (input.macdHistogram === null) {
    gates.push(gate('macd', 'MACD histogram', 'soft', 'UNAVAILABLE', 'unavailable', 'hist ≥ 0 or improving', 'MACD not on packet.'))
  } else if (input.macdHistogram >= 0 || (input.macdSlope !== null && input.macdSlope > 0)) {
    gates.push(gate('macd', 'MACD histogram', 'soft', 'PASS',
      `hist ${input.macdHistogram.toFixed(3)}${input.macdSlope === null ? '' : ` · slope ${input.macdSlope.toFixed(3)}`}`,
      'hist ≥ 0 or improving', 'MACD is constructive or improving.'))
  } else {
    gates.push(gate('macd', 'MACD histogram', 'soft', 'WAIT',
      `hist ${input.macdHistogram.toFixed(3)}`, 'hist ≥ 0 or improving', 'MACD still negative without improvement.'))
  }

  // Soft: support
  if (input.support === null || price === null) {
    gates.push(gate('support', 'Above support', 'soft', 'UNAVAILABLE', 'support unavailable', 'price ≥ support', 'No explicit support level on packet.'))
  } else if (price >= input.support) {
    const dist = ((price - input.support) / input.support) * 100
    gates.push(gate('support', 'Above support', 'soft', 'PASS',
      `${money(input.support)} · +${dist.toFixed(1)}%`, 'price ≥ support', 'Price is holding above marked support.'))
  } else {
    const dist = ((input.support - price) / input.support) * 100
    gates.push(gate('support', 'Above support', 'soft', 'WAIT',
      `${money(input.support)} · −${dist.toFixed(1)}%`, 'price ≥ support', 'Price is below marked support — weaker reclaim setup.'))
  }

  // Soft: resistance (+ sanity)
  if (input.resistance === null || price === null) {
    gates.push(gate('resistance', 'Resistance context', 'soft', 'UNAVAILABLE', 'unavailable', 'not stuck mid-test without plan', 'No resistance level.'))
  } else if (resistanceSuspect) {
    const d = input.resistanceDistancePct
    gates.push(gate('resistance', 'Resistance context', 'soft', 'WAIT',
      `suspect ${money(input.resistance)}${d == null ? '' : ` · px ${d >= 0 ? '+' : ''}${d.toFixed(0)}% vs lvl`}`,
      'level scale plausible',
      'Price is more than 50% above marked resistance — level may be stale; do not treat as a clean reclaim.'))
  } else {
    const side = (input.resistanceSide || '').toUpperCase()
    const d = input.resistanceDistancePct
    if (side === 'ABOVE' || (d !== null && d > 0.5)) {
      gates.push(gate('resistance', 'Resistance context', 'soft', 'PASS',
        `above ${money(input.resistance)}`, 'reclaimed or clear air', 'Price is above resistance — reclaim context.'))
    } else if (side === 'TESTING' || (d !== null && Math.abs(d) <= 0.5)) {
      gates.push(gate('resistance', 'Resistance context', 'soft', 'WAIT',
        `testing ${money(input.resistance)}`, 'reclaimed or clear air', 'Price is testing resistance — wait for hold/reclaim.'))
    } else {
      gates.push(gate('resistance', 'Resistance context', 'soft', 'WAIT',
        `below ${money(input.resistance)}${d === null ? '' : ` · ${d.toFixed(1)}%`}`,
        'reclaimed or clear air', 'Price remains under resistance.'))
    }
  }

  // Soft: valuation
  if (input.pe === null && input.forwardPe === null) {
    gates.push(gate('valuation', 'Valuation context', 'soft', 'UNAVAILABLE', 'P/E unavailable', 'not extreme (soft)', 'No P/E on packet.'))
  } else {
    const pe = input.forwardPe ?? input.pe
    if (pe !== null && pe > 80) {
      gates.push(gate('valuation', 'Valuation context', 'soft', 'WAIT',
        `P/E ${pe.toFixed(1)}`, 'not extreme (soft)', 'Valuation is stretched — size carefully if reviewing.'))
    } else {
      gates.push(gate('valuation', 'Valuation context', 'soft', 'PASS',
        `P/E ${pe === null ? '—' : pe.toFixed(1)}`, 'not extreme (soft)', 'Valuation not flagged as extreme on available P/E.'))
    }
  }

  // Soft: regime
  const regime = (input.regimeLabel || '').toUpperCase()
  if (!regime || regime === 'UNKNOWN' || regime === 'UNAVAILABLE') {
    gates.push(gate('regime', 'Risk regime', 'soft', 'UNAVAILABLE', 'unavailable', 'not risk-off/defensive', 'Regime feed unavailable.'))
  } else if (/RISK_OFF|DEFENSIVE|DISRUPT|BEAR/.test(regime)) {
    gates.push(gate('regime', 'Risk regime', 'soft', 'WAIT', regime.replace(/_/g, ' '), 'not risk-off/defensive', 'Regime is defensive — soft caution on aggressive re-entries.'))
  } else {
    gates.push(gate('regime', 'Risk regime', 'soft', 'PASS', regime.replace(/_/g, ' '), 'not risk-off/defensive', 'Regime is not labeled risk-off/defensive.'))
  }

  const hard = gates.filter(g => g.kind === 'hard')
  const soft = gates.filter(g => g.kind === 'soft')
  const hardPass = hard.filter(g => g.state === 'PASS').length
  const hardBlock = hard.filter(g => g.state === 'BLOCK').length
  const hardWait = hard.filter(g => g.state === 'WAIT').length
  const hardUna = hard.filter(g => g.state === 'UNAVAILABLE').length
  const softPass = soft.filter(g => g.state === 'PASS').length
  const softTotal = soft.length
  const unavailable = gates.filter(g => g.state === 'UNAVAILABLE').length

  const narr = (state: ScorecardResult['state']) => composeDecisionNarrative(input, {
    state,
    distancePct,
    riskReward,
    rsiBand,
    vsExitPct,
    planIntegrityOk: planCheck.ok,
    planIntegrityWhy: planCheck.why,
    resistanceSuspect,
  })

  if (held) {
    const n = narr('CURRENTLY HELD')
    return fin('WATCH', 'CURRENTLY HELD', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
  }

  if (price === null || rsi === null) {
    const n = narr('MISSING MARKET')
    return fin('WATCH', 'MISSING MARKET', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
  }
  if (stale) {
    const n = narr('STALE')
    return fin('WATCH', 'STALE', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
  }
  if (entryLow === null || entryHigh === null) {
    const n = narr('MISSING PLAN')
    return fin('WATCH', 'MISSING PLAN', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
  }

  // READY: in zone + all hard PASS + RSI ≤ 50 (plan integrity included in hard)
  const hardAllPass = hard.length > 0 && hard.every(g => g.state === 'PASS')
  if (inZone && hardAllPass && rsi !== null && rsi <= 50) {
    const n = narr('READY TO REVIEW')
    return fin('NOW', 'READY TO REVIEW', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
  }

  // NEAR
  if ((nearAbove || nearBelow || inZone) && hardBlock === 0 && hardUna === 0 && hardWait <= 3) {
    const n = narr('NEAR ENTRY')
    return fin('NEAR', 'NEAR ENTRY', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
  }

  const n = narr('WAIT')
  return fin('WATCH', 'WAIT', n.action, n.reason, n.highlights, gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct, riskReward, rsiBand, vsExitPct, planCheck.ok)
}

function fin(
  lane: 'NOW' | 'NEAR' | 'WATCH',
  state: ScorecardResult['state'],
  action: string,
  reason: string,
  highlights: string[],
  gates: ScoreGate[],
  hardPass: number,
  hardTotal: number,
  softPass: number,
  softTotal: number,
  unavailable: number,
  distancePct: number | null,
  riskReward: number | null,
  rsiBand: ScorecardResult['rsiBand'],
  vsExitPct: number | null,
  planIntegrityOk: boolean,
): ScorecardResult {
  return {
    lane, state, action, reason, highlights, gates, hardPass, hardTotal, softPass, softTotal, unavailable, distancePct,
    scoreLabel: `${hardPass}/${hardTotal} hard · ${softPass}/${softTotal} soft${unavailable ? ` · ${unavailable} n/a` : ''}`,
    riskReward, rsiBand, vsExitPct, planIntegrityOk,
  }
}

export function filterByLane<T extends { score?: { lane?: 'NOW' | 'NEAR' | 'WATCH' }; intel?: { state?: string } }>(
  rows: T[],
  lane: ReEntryLane,
): T[] {
  if (lane === 'ALL') return rows
  return rows.filter(row => {
    const l = row.score?.lane
    if (l) return l === lane
    const s = String(row.intel?.state || '')
    if (lane === 'NOW') return s === 'READY TO REVIEW'
    if (lane === 'NEAR') return s === 'NEAR ENTRY'
    return s !== 'READY TO REVIEW' && s !== 'NEAR ENTRY'
  })
}
