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
  sizing_ready?: boolean
  /** Per-account position cap from account_automation_policies — percent of EQUITY, matching
   *  compute_sizing's semantics (mis-applying it to cash capped every card at ~$6.6k, 2026-07-03). */
  max_position_pct_of_equity?: number | null
}

export type DeployCap = { dollars: number; label: string }

/** Effective deployment cap in DOLLARS. The account's backend policy (percent of equity) wins;
 *  the desk fallback (percent of available cash) fills in when no policy row / equity exists. */
export function deployCapFor(acct: ProposalAccount | undefined | null, fallbackPctOfCash: number): DeployCap | null {
  const eqPct = Number(acct?.max_position_pct_of_equity)
  const eq = Number(acct?.account_value)
  if (Number.isFinite(eqPct) && eqPct > 0 && Number.isFinite(eq) && eq > 0) {
    return { dollars: eq * eqPct / 100, label: `${eqPct}% of equity` }
  }
  const base = resolveSizingBase(acct)
  if (base > 0 && fallbackPctOfCash > 0) {
    return { dollars: base * fallbackPctOfCash / 100, label: `${fallbackPctOfCash}% of cash` }
  }
  return null
}

/** Normalize GET /api/v2/proposal-accounts (useApi already unwraps {ok,data}). */
export function parseProposalAccounts(raw: unknown): ProposalAccount[] {
  if (!raw || typeof raw !== 'object') return []
  const o = raw as Record<string, unknown>
  const nested = o.data
  const payload = (nested && typeof nested === 'object' ? nested : o) as Record<string, unknown>
  const list = payload.accounts
  return Array.isArray(list) ? (list as ProposalAccount[]) : []
}

export function pickDefaultProposalAccount(accounts: ProposalAccount[]): ProposalAccount | null {
  if (!accounts.length) return null
  return accounts.find(a => resolveSizingBase(a) > 0 && !a.is_retirement)
    ?? accounts.find(a => resolveSizingBase(a) > 0)
    ?? accounts[0]
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
  /** true when the desk deployment cap (max % of cash per position) bounded the size. */
  concentrationCapped: boolean
}

/** Cash / buying power for risk budget — never total equity. */
export function resolveSizingBase(acct?: ProposalAccount | null): number {
  if (!acct) return 0
  // Retirement: cash only — no margin / buying-power assumption.
  if (acct.is_retirement) {
    const cash = acct.cash ?? acct.sizing_base ?? 0
    return Number.isFinite(Number(cash)) && Number(cash) > 0 ? Number(cash) : 0
  }
  const base = acct.sizing_base ?? acct.cash ?? acct.buying_power ?? 0
  return Number.isFinite(Number(base)) && Number(base) > 0 ? Number(base) : 0
}

export function riskBudgetDollars(sizingBase: number, riskPct: RiskPct): number {
  return sizingBase > 0 ? sizingBase * (riskPct / 100) : 0
}

export function formatSizingBreakdown(args: {
  sizingBase: number
  equity: number
  riskPct: RiskPct
  entry: number
  stop: number
  shares: number
  sizingLabel?: string
}): string {
  const { sizingBase, equity, riskPct, entry, stop, shares, sizingLabel = 'cash' } = args
  const budget = riskBudgetDollars(sizingBase, riskPct)
  const rps = entry - stop
  const pctCash = sizingBase > 0 ? (shares * rps / sizingBase) * 100 : 0
  const pctEq = equity > 0 ? (shares * rps / equity) * 100 : 0
  return [
    `${riskPct}% × ${money(sizingBase)} ${sizingLabel} = ${money(budget)} risk budget`,
    `${money(budget)} ÷ ${money(rps)}/sh stop = ${shares.toLocaleString()} shares`,
    `Actual risk: ${pctCash.toFixed(2)}% of ${sizingLabel} · ${pctEq.toFixed(2)}% of equity (reference)`,
  ].join(' · ')
}

function money(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(2)}`
}

export function resolveEquity(acct?: ProposalAccount | null): number {
  if (!acct) return 0
  const eq = acct.account_value ?? 0
  return Number.isFinite(Number(eq)) && Number(eq) > 0 ? Number(eq) : 0
}

/** Desk sizing policy from GET /api/v2/proposal-accounts — operator-tunable, never hardcoded here. */
export type SizingPolicy = { maxDeployPctOfCash: number; maxRiskPct: number }

export function parseSizingPolicy(raw: unknown): SizingPolicy {
  const o = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>
  const p = (o.data && typeof o.data === 'object' ? o.data : o).sizing_policy || {}
  const dep = Number(p.max_deploy_pct_of_cash)
  const risk = Number(p.max_risk_pct)
  return {
    maxDeployPctOfCash: Number.isFinite(dep) && dep > 0 ? dep : 20,
    maxRiskPct: Number.isFinite(risk) && risk > 0 ? risk : 2,
  }
}

/** Stop wider than typical → suggest a reduced effective risk %. Stop-distance is the direct
 *  volatility proxy already on the card; returns null when the stop is in the normal band. */
export function volatilityRiskSuggestion(entry: number | null, stop: number | null): { stopPct: number; suggestPct: number } | null {
  if (!entry || !stop || entry <= stop) return null
  const stopPct = ((entry - stop) / entry) * 100
  if (stopPct > 10) return { stopPct, suggestPct: 0.5 }
  if (stopPct > 7) return { stopPct, suggestPct: 0.75 }
  return null
}

export function computeRiskSizedShares(args: {
  sizingBase: number
  equity: number
  entry: number
  stop: number
  target: number
  riskPct: RiskPct
  /** Hard concentration cap: max % of available cash deployed in one position (desk policy). */
  maxDeployPctOfCash?: number
  /** Hard concentration cap in DOLLARS (from deployCapFor — policy %-of-equity or fallback). Wins over the pct form. */
  maxDeployDollars?: number
}): SizedPosition {
  const { sizingBase, equity, entry, stop, target, riskPct, maxDeployPctOfCash, maxDeployDollars } = args
  const riskPerShare = entry - stop
  const empty: SizedPosition = {
    shares: 0, dollarRisk: 0, investment: 0, profitAtTarget: 0, riskPerShare: 0,
    pctOfEquity: 0, pctOfCash: 0, exceedsCash: false, cashCapShares: 0, sizingBase: 0,
    concentrationCapped: false,
  }
  if (!Number.isFinite(sizingBase) || sizingBase <= 0 || riskPerShare <= 0) return empty

  const budget = sizingBase * (riskPct / 100)
  let shares = Math.max(0, Math.floor(budget / riskPerShare))
  const cashCapShares = entry > 0 ? Math.max(0, Math.floor(sizingBase / entry)) : 0
  if (cashCapShares > 0) shares = Math.min(shares, cashCapShares)
  // Concentration cap — deployment (shares × entry), not risk, bounded to desk policy.
  // Dollar form wins (policy %-of-equity via deployCapFor); pct-of-cash kept for callers
  // that still pass the env fallback directly.
  let concentrationCapped = false
  const capDollars = (maxDeployDollars && maxDeployDollars > 0)
    ? maxDeployDollars
    : (maxDeployPctOfCash && maxDeployPctOfCash > 0 ? sizingBase * maxDeployPctOfCash / 100 : 0)
  if (capDollars > 0 && entry > 0) {
    const deployCapShares = Math.max(0, Math.floor(capDollars / entry))
    if (shares > deployCapShares) {
      shares = deployCapShares
      concentrationCapped = true
    }
  }

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
    concentrationCapped,
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
    concentrationCapped: false,   // manual size — the modal blocks over-cap instead of silently capping
  }
}

/** Primary gate: risk as % of available cash (not equity). */
export function exceedsMaxRisk(pctOfCash: number, maxPct = 2): boolean {
  return pctOfCash > maxPct + 0.05
}

/** Hard deployment gate against the dollar cap from deployCapFor. */
export function exceedsDeployDollars(investment: number, cap: DeployCap | null): boolean {
  if (!cap || cap.dollars <= 0) return false
  return investment > cap.dollars + 0.01
}

/** Hard deployment gate: investment as % of available cash vs desk concentration policy. */
export function exceedsDeployCap(investment: number, sizingBase: number, maxDeployPctOfCash: number): boolean {
  if (!sizingBase || !maxDeployPctOfCash) return false
  return investment > sizingBase * (maxDeployPctOfCash / 100) + 0.01
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