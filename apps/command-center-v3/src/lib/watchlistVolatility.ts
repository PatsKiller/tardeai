/** ATR₂₀ (Maria/Telegram) + ATR₁₄ (Finviz) — plan stop vs volatility context. */

export type VolatilityBand = 'low' | 'moderate' | 'high' | 'extreme'

export type PlanVolContext = {
  atr14: number | null
  atrPct14: number | null
  atr20: number | null
  atrPct20: number | null
  band: VolatilityBand | null
  stopDistPct: number | null
  stopAtrMult14: number | null
  stopAtrMult20: number | null
  tightVsAtr: boolean
}

const BAND_LABEL: Record<VolatilityBand, string> = {
  low: 'Low vol',
  moderate: 'Moderate',
  high: 'High vol',
  extreme: 'Extreme vol',
}

/** True when ATR₂₀ band is extreme (≥10% of price) — used for watchlist KPI filter. */
export function isExtremeVolItem(it: { volatility_band_20?: string; volatility_band?: string; atr_20_pct?: number | null } | null | undefined): boolean {
  if (!it) return false
  const band = (it.volatility_band_20 || it.volatility_band) as VolatilityBand | undefined
  if (band === 'extreme') return true
  const p20 = it.atr_20_pct != null ? Number(it.atr_20_pct) : null
  return p20 != null && Number.isFinite(p20) && p20 >= 10
}

export function volatilityBandFromAtrPct(atrPct: number | null | undefined): VolatilityBand | null {
  if (atrPct == null || !Number.isFinite(Number(atrPct))) return null
  const p = Number(atrPct)
  if (p < 2) return 'low'
  if (p < 5) return 'moderate'
  if (p < 10) return 'high'
  return 'extreme'
}

export function volatilityBandLabel(band: VolatilityBand | null): string {
  return band ? BAND_LABEL[band] : 'Vol'
}

export function volatilityBadgeStyle(band: VolatilityBand | null): { color: string; border: string; bg: string } {
  switch (band) {
    case 'low':
      return { color: '#94a3b8', border: 'rgba(148,163,184,.35)', bg: 'rgba(148,163,184,.08)' }
    case 'moderate':
      return { color: '#60a5fa', border: 'rgba(96,165,250,.35)', bg: 'rgba(96,165,250,.08)' }
    case 'high':
      return { color: '#f5a623', border: 'rgba(245,166,35,.4)', bg: 'rgba(245,166,35,.1)' }
    case 'extreme':
      return { color: '#ef5350', border: 'rgba(239,83,80,.4)', bg: 'rgba(239,83,80,.1)' }
    default:
      return { color: '#64748b', border: 'rgba(100,116,139,.3)', bg: 'transparent' }
  }
}

/** Resolve ATR context from API item fields and/or Finviz strip fallback. */
export function resolvePlanVolContext(
  it: any,
  fv?: { atr?: number | null; atr_pct?: number | null } | null,
  entry?: number | null,
  stop?: number | null,
): PlanVolContext {
  const px = it?.price != null ? Number(it.price) : null
  const atr14 = it?.atr_14 != null ? Number(it.atr_14)
    : (fv?.atr != null ? Number(fv.atr) : null)
  const atrPct14 = it?.atr_pct != null ? Number(it.atr_pct)
    : (fv?.atr_pct != null ? Number(fv.atr_pct)
      : (px && atr14 && atr14 > 0 ? (atr14 / px) * 100 : null))

  const atr20 = it?.atr_20 != null ? Number(it.atr_20) : null
  const atrPct20 = it?.atr_20_pct != null ? Number(it.atr_20_pct)
    : (px && atr20 && atr20 > 0 ? (atr20 / px) * 100 : null)

  const band = (it?.volatility_band_20 as VolatilityBand | undefined)
    ?? volatilityBandFromAtrPct(atrPct20)
    ?? (it?.volatility_band as VolatilityBand | undefined)
    ?? volatilityBandFromAtrPct(atrPct14)

  let stopDistPct = it?.plan_stop_dist_pct != null ? Number(it.plan_stop_dist_pct) : null
  let stopAtrMult14 = it?.plan_stop_atr_mult != null ? Number(it.plan_stop_atr_mult) : null
  let stopAtrMult20 = it?.plan_stop_atr20_mult != null ? Number(it.plan_stop_atr20_mult) : null
  if (entry != null && stop != null && entry > stop) {
    const dist = entry - stop
    if (stopDistPct == null) stopDistPct = (dist / entry) * 100
    if (stopAtrMult14 == null && atr14 && atr14 > 0) stopAtrMult14 = dist / atr14
    if (stopAtrMult20 == null && atr20 && atr20 > 0) stopAtrMult20 = dist / atr20
  }

  const tightVsAtr = it?.plan_stop_tight === true
    || it?.plan_stop_tight_vs_atr20 === true
    || (stopAtrMult20 != null && stopAtrMult20 < 1)
    || (stopAtrMult20 == null && (it?.plan_stop_tight_vs_atr === true || (stopAtrMult14 != null && stopAtrMult14 < 1)))

  const rnd = (n: number | null, dec: number) =>
    n != null && Number.isFinite(n) ? Math.round(n * 10 ** dec) / 10 ** dec : null

  return {
    atr14: rnd(atr14, 4),
    atrPct14: rnd(atrPct14, 1),
    atr20: rnd(atr20, 4),
    atrPct20: rnd(atrPct20, 1),
    band,
    stopDistPct: rnd(stopDistPct, 1),
    stopAtrMult14: stopAtrMult14 != null ? Math.round(stopAtrMult14 * 100) / 100 : null,
    stopAtrMult20: stopAtrMult20 != null ? Math.round(stopAtrMult20 * 100) / 100 : null,
    tightVsAtr,
  }
}

export function volatilityBadgeText(ctx: PlanVolContext): string | null {
  if (ctx.atrPct20 == null && ctx.atrPct14 == null) return null
  const parts: string[] = []
  if (ctx.band) parts.push(volatilityBandLabel(ctx.band))
  if (ctx.atrPct20 != null) parts.push(`ATR₂₀ ${ctx.atrPct20.toFixed(1)}%`)
  if (ctx.atrPct14 != null) parts.push(`ATR₁₄ ${ctx.atrPct14.toFixed(1)}%`)
  return parts.join(' · ')
}

export function stopVolatilityLine(ctx: PlanVolContext): string | null {
  if (ctx.stopDistPct == null) return null
  const parts = [`${ctx.stopDistPct.toFixed(1)}%`]
  if (ctx.stopAtrMult20 != null) parts.push(`${ctx.stopAtrMult20.toFixed(2)}× ATR₂₀`)
  if (ctx.stopAtrMult14 != null) parts.push(`${ctx.stopAtrMult14.toFixed(2)}× ATR₁₄`)
  return parts.join(' · ')
}

export function stopVolatilityTooltip(ctx: PlanVolContext, entry: number | null, stop: number | null): string {
  const lines = [
    'Stop distance from entry limit vs daily ATR.',
    'ATR₂₀ matches Maria/Telegram; ATR₁₄ is Finviz (Wilder 14).',
    'Swing practice: avoid stops inside 1× ATR₂₀ on volatile names — size down instead of tightening.',
  ]
  if (ctx.atrPct20 != null) lines.push(`ATR₂₀ ≈ ${ctx.atrPct20.toFixed(1)}% of price.`)
  if (ctx.atrPct14 != null) lines.push(`ATR₁₄ ≈ ${ctx.atrPct14.toFixed(1)}% of price.`)
  if (ctx.stopAtrMult20 != null) {
    lines.push(`Plan stop = ${ctx.stopAtrMult20.toFixed(2)}× ATR₂₀ (${ctx.stopDistPct?.toFixed(1) ?? '—'}% below limit).`)
  } else if (ctx.stopAtrMult14 != null) {
    lines.push(`Plan stop = ${ctx.stopAtrMult14.toFixed(2)}× ATR₁₄ (${ctx.stopDistPct?.toFixed(1) ?? '—'}% below limit).`)
  }
  if (ctx.tightVsAtr) lines.push('⚠ Tighter than 1× ATR₂₀ — normal daily noise may stop you out.')
  if (entry != null && stop != null) lines.push(`Limit $${entry.toFixed(2)} → stop $${stop.toFixed(2)}.`)
  return lines.join('\n')
}

export function volatilityBadgeTooltip(ctx: PlanVolContext): string {
  const lines = ['Daily volatility as % of price (average true range).']
  if (ctx.atrPct20 != null) {
    lines.push(`ATR₂₀ ${ctx.atrPct20.toFixed(1)}% — same period Maria uses on Telegram.`)
  }
  if (ctx.atrPct14 != null) {
    lines.push(`ATR₁₄ ${ctx.atrPct14.toFixed(1)}% — Finviz/industry stop reference.`)
  }
  if (ctx.band) lines.push(`Band: ${volatilityBandLabel(ctx.band)}.`)
  return lines.join('\n')
}