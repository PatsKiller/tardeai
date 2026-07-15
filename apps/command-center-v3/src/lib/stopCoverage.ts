/** Stop qty vs shares held — GTC stops do NOT auto-resize when you add/trim. */

export type StopCoverageKind = 'full' | 'partial' | 'oversized' | 'unknown'

export type StopCoverage = {
  kind: StopCoverageKind
  stopQty: number | null
  heldQty: number
  /** Shares unprotected (partial) or excess stop shares (oversized). */
  gap: number
  /** Whole-share target for replace (floor of held). */
  targetQty: number
  label: string
  shortLabel: string
  tip: string
}

/** Material gap threshold: ignore fractional residuals under 1 share (e.g. SCHD 4155 vs 4155.25). */
const MATERIAL_SHARES = 0.99

export function computeStopCoverage(stopQtyRaw: unknown, heldQtyRaw: unknown): StopCoverage | null {
  const heldQty = Number(heldQtyRaw)
  if (!Number.isFinite(heldQty) || heldQty <= 0) return null
  const stopQty = Number(stopQtyRaw)
  if (!Number.isFinite(stopQty) || stopQty <= 0) {
    return {
      kind: 'unknown',
      stopQty: null,
      heldQty,
      gap: heldQty,
      targetQty: Math.floor(heldQty),
      label: 'NO STOP QTY',
      shortLabel: 'no stop qty',
      tip: 'Live stop quantity is unknown — verify at broker before replacing.',
    }
  }
  const targetQty = Math.max(1, Math.floor(heldQty))
  if (stopQty + MATERIAL_SHARES < heldQty) {
    const gap = heldQty - stopQty
    return {
      kind: 'partial',
      stopQty,
      heldQty,
      gap,
      targetQty,
      label: `PARTIAL · ${fmtSh(stopQty)}/${fmtSh(heldQty)} sh`,
      shortLabel: `PARTIAL · ${fmtSh(stopQty)}/${fmtSh(heldQty)}`,
      tip: `Stop covers only ${fmtSh(stopQty)} of ${fmtSh(heldQty)} shares held. ${fmtSh(gap)} sh unprotected. Click to replace stop at full size via 2FA.`,
    }
  }
  if (stopQty > heldQty + MATERIAL_SHARES) {
    const gap = stopQty - heldQty
    return {
      kind: 'oversized',
      stopQty,
      heldQty,
      gap,
      targetQty,
      label: `OVERSIZED · ${fmtSh(stopQty)}/${fmtSh(heldQty)} sh`,
      shortLabel: `OVERSIZED · ${fmtSh(stopQty)}/${fmtSh(heldQty)}`,
      tip: `Stop covers ${fmtSh(stopQty)} sh but you hold ${fmtSh(heldQty)}. On trigger may short/reject the extra ${fmtSh(gap)}. Click to replace at full held size via 2FA.`,
    }
  }
  return {
    kind: 'full',
    stopQty,
    heldQty,
    gap: 0,
    targetQty,
    label: `FULL · ${fmtSh(stopQty)} sh`,
    shortLabel: `FULL · ${fmtSh(stopQty)}`,
    tip: `Stop qty matches held shares (${fmtSh(stopQty)}).`,
  }
}

function fmtSh(n: number): string {
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n - Math.round(n)) < 1e-6) return String(Math.round(n))
  return n.toFixed(2).replace(/\.?0+$/, '')
}
