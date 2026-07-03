/** Advisory position sizing for watchlist propose modal — 1–2% of available cash/buying power. */

export type RiskPct = 1 | 2

export type ProposalAccount = {
  account_key: string
  display_name?: string
  broker?: string
  account_type?: string
  is_retirement?: boolean
  account_value?: number | null
  equity_source?: string
  cash?: number | null
  buying_power?: number | null
  sizing_base?: number | null
  sizing_base_label?: string
  balances_status?: string
}

export type SizedPosition = {
  shares: number
  dollarRisk: number
  investment: number
  profitAtTarget: number
  riskPerShare: number
  pctOfEquity: number
  pctOfCash: number
  exceedsCash: boolean
  cashCapShares: number
  sizingBase: number
}

export function resolveSizingBase(acct?: ProposalAccount | null): number {
  if (!acct) return 0
  const base = acct.sizing_base ?? acct.cash ?? acct.buying_power ?? 0
  return Number.isFinite(Number(base)) && Number(base) > 0 ? Number(base) : 0
}

export function resolveEquity(acct?: ProposalAccount | null): number {
  if (!acct) return 0
  const eq = acct.account_value ?? 0
  return Number.isFinite(Number(eq)) && Number(eq) > 0 ? Number(eq) : 0
}

export function computeRiskSizedShares(args: {
  sizingBase: number
  equity: number
  entry: number
  stop: number
  target: number
  riskPct: RiskPct
}): SizedPosition {
  const { sizingBase, equity, entry, stop, target, riskPct } = args
  const riskPerShare = entry - stop
  const empty: SizedPosition = {
    shares: 0, dollarRisk: 0, investment: 0, profitAtTarget: 0, riskPerShare: 0,
    pctOfEquity: 0, pctOfCash: 0, exceedsCash: false, cashCapShares: 0, sizingBase: 0,
  }
  if (!Number.isFinite(sizingBase) || sizingBase <= 0 || riskPerShare <= 0) return empty

  const budget = sizingBase * (riskPct / 100)
  let shares = Math.max(0, Math.floor(budget / riskPerShare))
  const cashCapShares = entry > 0 ? Math.max(0, Math.floor(sizingBase / entry)) : 0
  if (cashCapShares > 0) shares = Math.min(shares, cashCapShares)

  const dollarRisk = shares * riskPerShare
  const investment = shares * entry
  const rewardPerShare = target > entry ? target - entry : 0

  return {
    shares,
    dollarRisk,
    investment,
    profitAtTarget: shares * rewardPerShare,
    riskPerShare,
    pctOfEquity: equity > 0 ? (dollarRisk / equity) * 100 : 0,
    pctOfCash: (dollarRisk / sizingBase) * 100,
    exceedsCash: investment > sizingBase + 0.01,
    cashCapShares,
    sizingBase,
  }
}

export function sizingFromShares(args: {
  sizingBase: number
  equity: number
  entry: number
  stop: number
  target: number
  shares: number
}): SizedPosition {
  const { sizingBase, equity, entry, stop, target, shares } = args
  const riskPerShare = entry - stop
  const sh = Math.max(0, Math.floor(shares))
  const dollarRisk = sh * riskPerShare
  const investment = sh * entry
  const rewardPerShare = target > entry ? target - entry : 0
  const cashCapShares = entry > 0 && sizingBase > 0 ? Math.max(0, Math.floor(sizingBase / entry)) : 0
  return {
    shares: sh,
    dollarRisk,
    investment,
    profitAtTarget: sh * rewardPerShare,
    riskPerShare,
    pctOfEquity: equity > 0 ? (dollarRisk / equity) * 100 : 0,
    pctOfCash: sizingBase > 0 ? (dollarRisk / sizingBase) * 100 : 0,
    exceedsCash: sizingBase > 0 && investment > sizingBase + 0.01,
    cashCapShares,
    sizingBase,
  }
}

/** Primary gate: risk as % of available cash (not equity). */
export function exceedsMaxRisk(pctOfCash: number, maxPct = 2): boolean {
  return pctOfCash > maxPct + 0.05
}

export function acctLabel(key: string): string {
  if (!key) return '—'
  return key.replace('schwab_', '').replace('fidelity_', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export function acctOptionLabel(a: ProposalAccount): string {
  const name = a.display_name || acctLabel(a.account_key)
  const type = a.account_type ? ` · ${a.account_type}` : ''
  const cash = a.cash ?? a.sizing_base
  const cashStr = cash != null ? ` · cash $${fmtCompact(cash)}` : ''
  const eqStr = a.account_value != null ? ` · eq $${fmtCompact(a.account_value)}` : ''
  return `${name}${type}${cashStr}${eqStr}`
}

function fmtCompact(n: number): string {
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(0)
}