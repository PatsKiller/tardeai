/** Advisory position sizing for watchlist propose modal — 1–2% equity risk rule. */

export type RiskPct = 1 | 2

export type SizedPosition = {
  shares: number
  dollarRisk: number
  pctOfEquity: number
  riskPerShare: number
  investment: number
  profitAtTarget: number
}

export function computeRiskSizedShares(args: {
  equity: number
  entry: number
  stop: number
  target: number
  riskPct: RiskPct
}): SizedPosition {
  const { equity, entry, stop, target, riskPct } = args
  const riskPerShare = entry - stop
  const empty: SizedPosition = {
    shares: 0, dollarRisk: 0, pctOfEquity: 0, riskPerShare: 0, investment: 0, profitAtTarget: 0,
  }
  if (!Number.isFinite(equity) || equity <= 0 || riskPerShare <= 0) return empty

  const budget = equity * (riskPct / 100)
  const shares = Math.max(0, Math.floor(budget / riskPerShare))
  const dollarRisk = shares * riskPerShare
  const rewardPerShare = target > entry ? target - entry : 0

  return {
    shares,
    dollarRisk,
    pctOfEquity: (dollarRisk / equity) * 100,
    riskPerShare,
    investment: shares * entry,
    profitAtTarget: shares * rewardPerShare,
  }
}

export function sizingFromShares(args: {
  equity: number
  entry: number
  stop: number
  target: number
  shares: number
}): SizedPosition {
  const { equity, entry, stop, target, shares } = args
  const riskPerShare = entry - stop
  const sh = Math.max(0, Math.floor(shares))
  const dollarRisk = sh * riskPerShare
  const rewardPerShare = target > entry ? target - entry : 0
  return {
    shares: sh,
    dollarRisk,
    pctOfEquity: equity > 0 ? (dollarRisk / equity) * 100 : 0,
    riskPerShare,
    investment: sh * entry,
    profitAtTarget: sh * rewardPerShare,
  }
}

export function exceedsMaxRisk(pctOfEquity: number, maxPct = 2): boolean {
  return pctOfEquity > maxPct + 0.05
}

export function acctLabel(key: string): string {
  if (!key) return '—'
  return key.replace('schwab_', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}