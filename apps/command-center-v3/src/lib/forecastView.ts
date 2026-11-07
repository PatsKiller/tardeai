// Pure view helpers for the Portfolio > Forecast tab (operator 2026-11-06: tab showed $0 projections).
const horizonYears = (h: string) => Number(String(h).replace(/[^0-9.]/g, '')) || 0

/** Longest horizon present in any scenario's `years` map (API sends 1Y/2Y/3Y/5Y). */
export function longestHorizon(proj: Record<string, any>): string | null {
  let best: string | null = null
  for (const v of Object.values(proj || {})) {
    for (const h of Object.keys((v as any)?.years || {})) {
      if (best == null || horizonYears(h) > horizonYears(best)) best = h
    }
  }
  return best
}

/** Projected value at the horizon, or null (rendered as a dash, never as $0). */
export function projectionValue(v: any, horizon: string | null): number | null {
  if (typeof v === 'number') return v
  if (!v || typeof v !== 'object') return null
  const row = horizon ? v.years?.[horizon] : null
  const val = row?.projected_value ?? v.projected_value ?? v.value ?? v.total
  return typeof val === 'number' && Number.isFinite(val) ? val : null
}

/** The API lists one row per account lot; the operator wants one row per symbol. */
export function mergePayers(rows: any[]): any[] {
  const by = new Map<string, any>()
  for (const p of rows || []) {
    const key = String(p?.symbol ?? '')
    const prev = by.get(key)
    if (!prev) { by.set(key, { ...p }); continue }
    prev.annual_income = Number(prev.annual_income ?? 0) + Number(p.annual_income ?? 0)
    prev.value = Number(prev.value ?? 0) + Number(p.value ?? 0)
  }
  return [...by.values()].sort((a, b) => Number(b.annual_income ?? 0) - Number(a.annual_income ?? 0))
}

