/** Format stop/protection review timestamps for native title tooltips. */

import { formatPricingTime } from './pricingStamp.ts'

export type StopReviewMeta = {
  advisoryAt?: string | null
  advisoryModel?: string | null
  priceAt?: string | null
  brokerFetchedAt?: string | null
  brokerOrderId?: string | null
  confirmedAt?: string | null
  protectionAt?: string | null
}

export function formatReviewStamp(raw?: string | null): string | null {
  if (!raw) return null
  return formatPricingTime(raw) ?? String(raw).slice(0, 19)
}

export function stopReviewTooltip(meta: StopReviewMeta): string {
  const lines: string[] = []
  const broker = formatReviewStamp(meta.brokerFetchedAt)
  const advisory = formatReviewStamp(meta.advisoryAt ?? meta.protectionAt)
  const price = formatReviewStamp(meta.priceAt)
  const confirmed = formatReviewStamp(meta.confirmedAt)

  if (broker) {
    lines.push(`Broker stop last read: ${broker} (Schwab API, 60s cache)`)
    if (meta.brokerOrderId) lines.push(`Order #${meta.brokerOrderId}`)
  }
  if (advisory) {
    lines.push(`Protection advisory last reviewed: ${advisory}${meta.advisoryModel ? ` · ${meta.advisoryModel}` : ''}`)
  }
  if (price) lines.push(`Quote as of: ${price}`)
  if (confirmed) lines.push(`Operator confirmed stop: ${confirmed}`)
  if (!lines.length) return 'Stop data — refresh page if values look stale'
  return lines.join('\n')
}

function _atMs(v: any): number | null {
  const s = String(v ?? '').trim()
  if (!s) return null
  const t = Date.parse(s)
  return Number.isFinite(t) ? t : null
}

export function mergeLiveStop(confirmed?: any, live?: any): any {
  if (!live && !confirmed) return undefined
  if (!live) return confirmed
  if (!confirmed) return live
  if (live.source === 'broker') return { ...confirmed, ...live, source: 'broker', broker_verified: true }
  // Neither side is a live broker read. The NEWER observation wins: a stored broker observation captured after the
  // operator's confirmation is fresher evidence, and returning the older confirmation would show a superseded level.
  // The stored observation keeps its own provenance (source 'stop_last_known', broker_verified false) — a stored
  // observation is never relabelled as a broker-verified live read.
  const liveAt = _atMs(live.fetched_at ?? live.captured_at ?? live.as_of)
  const confirmedAt = _atMs(confirmed.confirmed_at ?? confirmed.fetched_at ?? confirmed.as_of ?? confirmed.at)
  if (liveAt != null && (confirmedAt == null || liveAt > confirmedAt)) return live
  return confirmed
}