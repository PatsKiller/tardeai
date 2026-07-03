// ── advisory exit ladder: layered scale-out derived from entry/stop/plan-target + Street mean target ──
// Pure read-only math shared by the Manual ToS desk and the Watchlist cards: the single-target plan from
// the entry engine is the floor, not the whole exit. T1 banks +1R and de-risks, T2 is the plan target,
// T3 keeps a runner toward the Street mean with a trailing stop instead of capping the trade at T1.
// Advisory-only — nothing here places, queues or modifies an order.

export type LadderStep = { px: number; label: string; action: string }
export type Ladder = { R: number; steps: LadderStep[] }
export type PlanWarning = { text: string; color: string }

const RED = '#ef5350'
const AMBER = '#f5a623'

// Order-type names match lib/schwabTickets.ts + the Open Trades protection buttons: tranche scale-outs
// are SELL LIMIT GTC; the protective exit is a fixed SELL STOP that ratchets up; the runner rides a
// native SELL TRAILING STOP. Naming the type (not just "trail") keeps the vocabulary identical everywhere.
export const MONITOR_RULES = '+1R → move SELL STOP to breakeven · T1 filled → SELL TRAILING STOP 1R (or prior-day low) · close below stop = exit, never average down · no +0.5R within 5 sessions → time-stop review'

export function exitLadder(entry: number | null, stop: number | null, planTarget: number | null, streetTarget: number | null): Ladder | null {
  if (!entry || !stop || entry <= stop) return null
  const R = entry - stop
  const t1 = entry + R
  const t2 = planTarget && planTarget > t1 + 0.01 ? planTarget : entry + 2 * R
  const steps: LadderStep[] = [
    { px: t1, label: 'T1 (+1R)', action: 'SELL LIMIT ⅓ · then move SELL STOP → breakeven' },
    { px: t2, label: planTarget && planTarget > t1 + 0.01 ? 'T2 (plan target)' : 'T2 (+2R)', action: 'SELL LIMIT ⅓ · then trail SELL STOP to T1' },
    streetTarget && streetTarget > t2 * 1.03
      ? { px: streetTarget, label: 'T3 (Street mean)', action: 'runner · SELL TRAILING STOP (offset 1R) or prior-day low' }
      : { px: t2 + R, label: 'T3 (runner)', action: 'runner · SELL TRAILING STOP (offset 1R) or prior-day low' },
  ]
  return { R, steps }
}

export function planWarnings(o: { entry: number | null; stop: number | null; planTarget: number | null; rr: number | null; pctCash: number | null; streetTarget: number | null; analystUpside: number | null }): PlanWarning[] {
  const w: PlanWarning[] = []
  if (o.entry && !o.stop) w.push({ text: 'NO STOP — risk undefined; set a stop before entering', color: RED })
  if (o.rr != null && o.rr < 1) w.push({ text: `R:R ${o.rr.toFixed(2)} < 1 — reward smaller than risk; rework target or skip`, color: RED })
  else if (o.rr != null && o.rr < 1.5) w.push({ text: `R:R ${o.rr.toFixed(2)} < 1.5 — thin edge for the risk taken`, color: AMBER })
  if (o.streetTarget && o.planTarget && o.streetTarget > o.planTarget * 1.1) w.push({ text: `plan target ${o.planTarget.toFixed(2)} caps below Street mean $${o.streetTarget} — keep a runner, don't exit all at the plan target`, color: AMBER })
  if (o.analystUpside != null && Number(o.analystUpside) < 0) w.push({ text: 'price is ABOVE the Street mean target — no analyst headroom at this entry', color: AMBER })
  if (o.pctCash != null && o.pctCash > 100) w.push({ text: `notional is ${o.pctCash.toFixed(0)}% of available cash — oversized for this account`, color: RED })
  return w
}
