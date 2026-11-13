/** Stored-product aware market-risk selectors (home-products rework, operator 13 Nov 2026).
 *  Pure. Wraps ./marketRisk.ts without changing it (that file is under another session's claim):
 *  - a RED/ORANGE tier whose data went stale (engine `state: 'stale'`, or the stored product STALE / past hard expiry,
 *    marked by the API as `stale: true` + `product_stale`) keeps its tier and its banner, labelled stale. Staleness
 *    never clears a warning.
 *  - a MISSING record (no stored row, store down, incompatible schema: API `tier: 'UNKNOWN'`, `unknown: true`) is
 *    UNKNOWN, never a tier and never "no risk".
 *  Wiring into MarketRiskBanner.tsx (bannerVisible -> riskBannerVisible) is a follow-up for the session holding it. */
import { ACTIONABLE, renderedTier, shortTime, unwrapMarketRisk, type MarketRisk } from './marketRisk.ts'

export interface ProductMarketRisk { mr: MarketRisk | null; unknown: boolean; stale: boolean; staleLabel: string }

export function selectMarketRisk(resp: unknown): ProductMarketRisk {
  const raw: any = resp && typeof resp === 'object' && 'data' in (resp as any) ? (resp as any).data : resp
  const mr = unwrapMarketRisk(resp)
  const unknown = !mr || raw?.unknown === true || String(raw?.tier || '').toUpperCase() === 'UNKNOWN'
  if (unknown) return { mr, unknown: true, stale: false, staleLabel: '' }
  const ps = raw?.product_stale
  const stale = mr!.stale || mr!.state === 'stale' || !!ps
  const when = ps?.as_of ?? mr!.as_of
  const staleLabel = !stale ? '' : ps?.greyed ? `stale — past expiry, last evaluation ${shortTime(when)}` : `stale — last evaluation ${shortTime(when)}`
  return { mr, unknown: false, stale, staleLabel }
}

/** The ORANGE/RED banner stays up while the tier stands, fresh or stale. Unknown never shows a tier banner. */
export function riskBannerVisible(sel: ProductMarketRisk): boolean {
  const mr = sel.mr
  if (sel.unknown || !mr) return false
  return (mr.state === 'evaluated' || mr.state === 'stale') && ACTIONABLE.includes(mr.tier)
}

/** The word on the risk chip: UNKNOWN for a missing record, else the tier (a stale tier stays its tier). */
export function riskTierWord(sel: ProductMarketRisk): string {
  if (sel.unknown || !sel.mr) return 'UNKNOWN'
  if (sel.mr.state === 'not_evaluated') return 'NOT EVALUATED'
  return renderedTier(sel.mr.tier, sel.mr.score, sel.mr.uplift)
}
