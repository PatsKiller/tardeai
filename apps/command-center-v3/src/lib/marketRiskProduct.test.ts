// No node:assert: CI's tsc has no @types/node (same local check as marketRisk.test.ts).
function t(ok: unknown, m: string) { if (!ok) throw new Error(m) }
import { riskBannerVisible, riskTierWord, selectMarketRisk } from './marketRiskProduct.ts'

const base = { state: 'evaluated', tier: 'RED', score: 83, as_of: '2026-11-13T19:45:00Z', age_hours: 0.05, stale: false, contributors: [], categories: [] }

const fresh = selectMarketRisk({ ok: true, data: base })
t(!fresh.unknown && !fresh.stale && riskBannerVisible(fresh) && riskTierWord(fresh) === 'RED', 'fresh RED: banner, RED')

// API serve_market_risk_latest: stored product STALE -> stale true, state stale, product_stale
const stale = selectMarketRisk({ ok: true, data: { ...base, state: 'stale', stale: true, product_stale: { status: 'STALE', greyed: false, age_s: 200, as_of: base.as_of } } })
t(stale.stale && riskBannerVisible(stale), 'stale RED: the banner must not clear')
t(riskTierWord(stale) === 'RED', 'stale RED still renders RED')
t(/^stale — last evaluation /.test(stale.staleLabel), 'stale RED is marked stale')

const expired = selectMarketRisk({ ok: true, data: { ...base, state: 'stale', stale: true, product_stale: { status: 'UNKNOWN', greyed: true, age_s: 400, as_of: base.as_of } } })
t(expired.stale && riskBannerVisible(expired) && riskTierWord(expired) === 'RED', 'expired (greyed) RED stays RED with banner')
t(/past expiry/.test(expired.staleLabel), 'expired is labelled past expiry')

// engine-level stale (legacy reader path) keeps the tier too
const engineStale = selectMarketRisk({ ...base, state: 'stale', stale: true })
t(riskBannerVisible(engineStale) && riskTierWord(engineStale) === 'RED' && engineStale.stale, 'engine-stale RED keeps banner')

// MISSING (API: tier UNKNOWN, unknown true) -> UNKNOWN, no banner, never a tier
const missing = selectMarketRisk({ ok: true, data: { state: 'not_evaluated', tier: 'UNKNOWN', score: null, stale: false, unknown: true, reason: 'market risk record unavailable: product not built yet (no stored copy)' } })
t(missing.unknown && !riskBannerVisible(missing) && riskTierWord(missing) === 'UNKNOWN', 'missing risk renders UNKNOWN')
t(selectMarketRisk(null).unknown && riskTierWord(selectMarketRisk(null)) === 'UNKNOWN', 'no response renders UNKNOWN')

// YELLOW / GREEN never get the ORANGE/RED banner, fresh or stale
t(!riskBannerVisible(selectMarketRisk({ ...base, tier: 'YELLOW', state: 'stale', stale: true })), 'stale YELLOW: no RED banner')
// product_stale alone marks stale even if a proxy/older API left state 'evaluated' (selector must not rely on state)
const markedOnly = selectMarketRisk({ ok: true, data: { ...base, product_stale: { status: 'STALE', greyed: false, age_s: 200, as_of: base.as_of } } })
t(markedOnly.stale && /^stale — /.test(markedOnly.staleLabel) && riskBannerVisible(markedOnly), 'product_stale alone marks RED stale, banner stays')
const flagOnly = selectMarketRisk({ ok: true, data: { ...base, stale: true } })
t(flagOnly.stale && riskTierWord(flagOnly) === 'RED', 'stale flag alone marks RED stale')
console.log('marketRiskProduct.test ok')
