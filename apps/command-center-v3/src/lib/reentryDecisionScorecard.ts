/**
 * Re-Entry decision scorecard v1 (WP-R1).
 * Pure functions — no React, no network. Fail-closed: missing evidence → UNAVAILABLE, never fake PASS.
 *
 * READY  = all hard gates PASS (or soft-only fails)
 * NEAR   = location near + at most one hard WAIT, no BLOCK
 * WAIT   = otherwise (including held / stale / missing plan handled as states)
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
}

export type ScorecardResult = {
  lane: 'NOW' | 'NEAR' | 'WATCH'
  state: 'READY TO REVIEW' | 'NEAR ENTRY' | 'WAIT' | 'CURRENTLY HELD' | 'STALE' | 'MISSING PLAN' | 'MISSING MARKET'
  action: string
  reason: string
  gates: ScoreGate[]
  hardPass: number
  hardTotal: number
  softPass: number
  softTotal: number
  unavailable: number
  distancePct: number | null
  scoreLabel: string
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
  return n === null ? 'unavailable' : `$${n.toFixed(2)}`
}

function gate(id: string, label: string, kind: GateKind, state: GateState, current: string, threshold: string, why: string): ScoreGate {
  return { id, label, kind, state, current, threshold, why }
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

export function buildReEntryScorecard(input: ScorecardInput): ScorecardResult {
  const maxAge = input.maxAgeHours ?? 96
  const hours = ageHours(input.asOf)
  const stale = hours === null || hours > maxAge
  const { price, rsi, entryLow, entryHigh, held } = input

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

  const gates: ScoreGate[] = []

  // Hard: market
  if (price === null || rsi === null) {
    gates.push(gate('market', 'Market quote + RSI', 'hard', 'UNAVAILABLE',
      `px ${money(price)} · RSI ${rsi === null ? '—' : rsi.toFixed(1)}`,
      'price and RSI present', 'Current price and RSI are required before a re-entry review.'))
  } else {
    gates.push(gate('market', 'Market quote + RSI', 'hard', 'PASS',
      `px ${money(price)} · RSI ${rsi.toFixed(1)}`,
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

  // Hard: plan
  if (entryLow === null || entryHigh === null) {
    gates.push(gate('plan', 'Validated entry zone', 'hard', 'UNAVAILABLE',
      'unavailable', 'entry low–high present', 'No validated entry range — build a candidate plan first.'))
  } else {
    gates.push(gate('plan', 'Validated entry zone', 'hard', 'PASS',
      `${money(entryLow)}–${money(entryHigh)}`, 'entry low–high present', 'Entry zone is present on the decision packet / plan.'))
  }

  // Hard: location
  if (entryLow === null || entryHigh === null || distancePct === null) {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'UNAVAILABLE',
      money(price), 'in zone or ≤3% above', 'Cannot score location without price and zone.'))
  } else if (inZone) {
    gates.push(gate('location', 'Price vs entry zone', 'hard', 'PASS',
      'inside zone', 'in zone or ≤3% above', 'Price is inside the validated entry zone.'))
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

  // Hard: momentum RSI band for pullback re-entry (not overbought)
  if (rsi === null) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'UNAVAILABLE', '—', 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI required.'))
  } else if (rsi > 70) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'WAIT', rsi.toFixed(1), 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is overbought — wait for a calmer retest.'))
  } else if (rsi <= 45) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'PASS', rsi.toFixed(1), 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is not extended — constructive for a pullback re-entry review.'))
  } else if (rsi <= 55) {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'WAIT', rsi.toFixed(1), 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is moderate — near setup, not fully calm.'))
  } else {
    gates.push(gate('momentum', 'RSI not extended', 'hard', 'WAIT', rsi.toFixed(1), 'RSI ≤ 50 (ready) / ≤ 55 (near)', 'RSI is elevated for a disciplined pullback re-entry.'))
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

  // Soft: resistance (not crushed under heavy overhead without hold)
  if (input.resistance === null || price === null) {
    gates.push(gate('resistance', 'Resistance context', 'soft', 'UNAVAILABLE', 'unavailable', 'not stuck mid-test without plan', 'No resistance level.'))
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

  // Soft: valuation (extreme only)
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

  // Held override
  if (held) {
    return {
      lane: 'WATCH',
      state: 'CURRENTLY HELD',
      action: 'Manage as an existing holding',
      reason: 'This symbol is currently held and is not a clean re-entry-only candidate.',
      gates,
      hardPass: gates.filter(g => g.kind === 'hard' && g.state === 'PASS').length,
      hardTotal: gates.filter(g => g.kind === 'hard').length,
      softPass: gates.filter(g => g.kind === 'soft' && g.state === 'PASS').length,
      softTotal: gates.filter(g => g.kind === 'soft').length,
      unavailable: gates.filter(g => g.state === 'UNAVAILABLE').length,
      distancePct,
      scoreLabel: 'HELD',
    }
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

  // Terminal states from hard unavailables
  if (price === null || rsi === null) {
    return fin('WATCH', 'MISSING MARKET', 'Refresh market evidence',
      'Current price and RSI are required before a re-entry review.',
      gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct)
  }
  if (stale) {
    return fin('WATCH', 'STALE', 'Refresh inputs',
      `The market/technical evidence is ${hours === null ? 'missing a timestamp' : `${Math.round(hours)}h old`}.`,
      gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct)
  }
  if (entryLow === null || entryHigh === null) {
    return fin('WATCH', 'MISSING PLAN', 'Build a candidate entry zone',
      'Market evidence exists, but no current validated entry range is available.',
      gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct)
  }

  // READY: in zone + all hard PASS (no wait/block/una on hard)
  const hardAllPass = hard.length > 0 && hard.every(g => g.state === 'PASS')
  if (inZone && hardAllPass && rsi !== null && rsi <= 50) {
    return fin('NOW', 'READY TO REVIEW', 'Review re-entry now',
      'Price is inside the entry zone and hard gates pass (momentum not extended).',
      gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct)
  }

  // NEAR: near band + at most one hard WAIT, zero hard BLOCK, plan+market present
  if ((nearAbove || nearBelow || inZone) && hardBlock === 0 && hardUna === 0 && hardWait <= 2) {
    const why = nearAbove
      ? `Price is ${distancePct!.toFixed(1)}% above the entry zone — prepare the review.`
      : nearBelow
        ? `Price is ${Math.abs(distancePct!).toFixed(1)}% below the entry zone — watch for reclaim.`
        : 'Price is in zone but momentum/structure still soft — near, not ready.'
    return fin('NEAR', 'NEAR ENTRY', 'Prepare the review', why,
      gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct)
  }

  return fin('WATCH', 'WAIT', 'Keep monitoring',
    'Current price has not reached validated entry conditions with hard gates green.',
    gates, hardPass, hard.length, softPass, softTotal, unavailable, distancePct)
}

function fin(
  lane: 'NOW' | 'NEAR' | 'WATCH',
  state: ScorecardResult['state'],
  action: string,
  reason: string,
  gates: ScoreGate[],
  hardPass: number,
  hardTotal: number,
  softPass: number,
  softTotal: number,
  unavailable: number,
  distancePct: number | null,
): ScorecardResult {
  return {
    lane, state, action, reason, gates, hardPass, hardTotal, softPass, softTotal, unavailable, distancePct,
    scoreLabel: `${hardPass}/${hardTotal} hard · ${softPass}/${softTotal} soft${unavailable ? ` · ${unavailable} n/a` : ''}`,
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
    // fallback from legacy state strings
    const s = String(row.intel?.state || '')
    if (lane === 'NOW') return s === 'READY TO REVIEW'
    if (lane === 'NEAR') return s === 'NEAR ENTRY'
    return s !== 'READY TO REVIEW' && s !== 'NEAR ENTRY'
  })
}
