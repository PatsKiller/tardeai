// Home v2 WS-D: the plain-English dictionary — the brain speaks operator.
// ADDITIVE rendering: raw states stay in tooltips/data attributes; a state with no
// confident translation renders through rawChip() (the Reports v3 producer pattern)
// and belongs in the findings log as visible debt.

export const STATE_LABELS: Record<string, string> = {
  market_relist_monitor: 'monitoring for re-entry',
  reentry_candidate: 're-entry candidate',
  hold_for_reentry: 'holding for re-entry',
  HUMAN_REVIEW: 'needs your review',
  ROTATION_REVIEW: 'rotation review',
  ADD_REVIEW: 'add-more review',
  MANUAL_REVIEW: 'manual review',
  read_only: 'analysis only — no action armed',
  'synthesis→human_review': 'awaiting your review',
  unknown_sync: 'adopted from broker sync',
  pullback_macd_reversal: 'pullback reversal setup',
  dividend_growth_compounder: 'dividend growth',
  high_yield_income_bdc: 'high-yield income BDC',
  core_index: 'core index',
  defense_thesis: 'defense thesis',
  risk_off: 'defensive regime',
  risk_on: 'risk-on',
  'risk on trend': 'risk-on trend',
  RUN_UNDERFILLED: 'scan ran thin (few symbols)',
  kill_switch_db_unavailable: 'trading halted — database was unreachable',
  RISK_BLOCKED: 'blocked by risk gate',
  APPROVED_FOR_PAPER_TEST: 'approved for validation',
  EXPIRED: 'expired unreviewed',
  PENDING: 'awaiting review',
  REJECTED: 'rejected',
  // CIO / inbox action verbs
  ADD_ON_PULLBACK: 'add on a pullback',
  ADD: 'add',
  BUY: 'buy',
  HOLD: 'hold',
  TRIM: 'trim',
  SELL: 'sell',
  AVOID: 'avoid',
  RESEARCH_MORE: 'research more',
  NEUTRAL: 'neutral',
  REBALANCE: 'rebalance',
  // strategy tags commonly embedded in inbox detail
  high_yield_income: 'high-yield income',
  income_covered_call: 'income / covered call',
}

export function plain(raw?: string | null): string | null {
  if (!raw) return null
  return STATE_LABELS[raw] ?? STATE_LABELS[String(raw).toUpperCase()] ?? null
}

export function count(n: any): string {
  const v = Number(n)
  return Number.isFinite(v) ? String(Math.round(v)) : '—'
}

/** "1000 2026-07-17" → "10:00 AM scan · Jul 17" */
export function runLabel(label?: string | null, date?: string | null): string {
  if (!label) return 'no run yet'
  const m = String(label).match(/^(\d{2})(\d{2})$/)
  let t = String(label)
  if (m) {
    const h = parseInt(m[1], 10)
    t = `${h === 0 ? 12 : h > 12 ? h - 12 : h}:${m[2]} ${h >= 12 ? 'PM' : 'AM'} scan`
  }
  if (date) {
    const d = new Date(`${date}T00:00:00`)
    if (!isNaN(d.getTime())) return `${t} · ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
  }
  return t
}

/** True when the trade-ai scan date is older than the current US calendar session day. */
export function isScanStale(runDate?: string | null, now = new Date()): boolean {
  if (!runDate) return true
  const m = String(runDate).match(/(\d{4}-\d{2}-\d{2})/)
  if (!m) return true
  const scan = new Date(`${m[1]}T00:00:00`)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const scanDay = new Date(scan.getFullYear(), scan.getMonth(), scan.getDate())
  return scanDay.getTime() < today.getTime()
}

export function thresholdSentence(label: string, value: number, threshold: number, unit = '%'): string {
  const dir = value > threshold ? 'above' : 'within'
  return `${label} ${value}${unit} — ${dir} your ${threshold}${unit} ceiling`
}

const ALERT_RULES: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/holdings\.json missing last_repriced/i, () => 'Price data incomplete — some holdings not repriced yet'],
  [/Schwab journal ingest log ([\d.]+)h old/i, m => `Trade journal sync is ${Math.round(parseFloat(m[1]))}h behind — closed trades may lag during market hours`],
  [/(\d+) decision-feeding agent jobs queued >2h/i, m => `${m[1]} agent analyses backed up over 2h`],
  [/(\d+) pipeline run failures in 24h/i, m => `${m[1]} pipeline run${m[1] === '1' ? '' : 's'} failed in the last 24h`],
  [/(\d+) orphaned stop orders/i, m => `${m[1]} stop order${m[1] === '1' ? '' : 's'} without a matching position`],
  [/kill_switch_db_unavailable/i, () => 'Trading halted — database was unreachable (auto-clears when healthy)'],
  [/cannot inspect live unlock state/i, () => 'Live-trading state unreadable — failing closed (no orders possible)'],
  [/(\d+) live-adjacent dirty files/i, m => `${m[1]} uncommitted change${m[1] === '1' ? '' : 's'} in live-trading code`],
  [/(\d+) uncommitted change/i, m => `${m[1]} uncommitted change${m[1] === '1' ? '' : 's'} in live-trading code`],
  [/Release manifest status FAIL/i, () => 'Release manifest FAIL — live-adjacent code is dirty or the validator failed'],
  [/executed trade\(s\) in 7d not linked to a proposal/i, () => 'Executed trade in the last 7 days is not linked to a proposal — every ATM trade must appear in Proposals first'],
  [/not linked to a proposal/i, () => 'Executed trade not linked to a proposal — route it through Proposals'],
  [/hermes.?gateway.*(offline|inactive|failed)/i, () => 'Hermes gateway offline (by design — research fleet uses timers, not gateway)'],
  [/gateway.*(offline|inactive)/i, () => 'Hermes gateway offline — research fleet may still be healthy via systemd timers'],
]

export function plainAlert(raw?: string | null): string | null {
  if (!raw) return null
  for (const [rx, fn] of ALERT_RULES) {
    const m = String(raw).match(rx)
    if (m) return fn(m)
  }
  return null
}

/** Fail-closed Home briefing body — reject known corrupt LLM cache shapes. */
export function isValidBriefingProse(raw?: string | null): boolean {
  if (!raw) return false
  let s = String(raw).trim()
  if (s.startsWith('{') && s.includes('content')) {
    try {
      const o = JSON.parse(s)
      s = String(o?.content ?? o?.summary ?? o?.text ?? '').trim()
    } catch { /* keep s */ }
  }
  if (s.length < 40) return false
  if ((s.match(/\*\*##/g) || []).length >= 2) return false
  if ((s.match(/#{2,}/g) || []).length >= 8 && s.length < 400) return false
  const alpha = [...s].filter(c => /[A-Za-z]/.test(c)).length
  return alpha >= s.length * 0.4
}

export function briefingProse(raw: any): string {
  if (raw == null) return ''
  if (typeof raw === 'object') {
    return String(raw.content ?? raw.summary ?? raw.text ?? '').trim()
  }
  let s = String(raw).trim()
  if (s.startsWith('{')) {
    try {
      const o = JSON.parse(s)
      return String(o?.content ?? o?.summary ?? o?.text ?? s).trim()
    } catch { return s }
  }
  return s
}

/** RiskHub-canonical protection counts (reconciled 2026-06-21). */
export function protectionCounts(positions: any[] = []) {
  const list = Array.isArray(positions) ? positions : []
  const noStop = list.filter((p: any) => !p.has_stop).length
  const verified = list.filter((p: any) => p.broker_protected).length
  const plannedOnly = list.filter((p: any) => !p.broker_protected && p.has_stop).length
  return { noStop, verified, plannedOnly, total: list.length }
}

/**
 * Operator Inbox detail → curated natural language.
 * Input examples:
 *   "HUMAN_REVIEW · dividend_growth_compounder ADD_ON_PULLBACK. Signal=0.10 (low). Weight=0.0%. Inco"
 *   "ROTATION_REVIEW · defense_thesis HOLD. Signal=0.62 (critical). Weight=0.0%. Income=0%. Synthesis=H"
 */
export function inboxDetailPlain(raw?: string | null, item?: any): string {
  if (!raw || !String(raw).trim()) {
    // structured fallback from item fields when detail empty
    if (item) {
      const bits: string[] = []
      const decision = plain(item.decision) || plain(item.action) || item.decision || item.action
      const strategy = plain(item.strategy_id) || plain(item.strategy) || item.strategy_id || item.strategy
      if (decision) bits.push(String(decision))
      if (strategy) bits.push(`strategy: ${strategy}`)
      if (bits.length) return bits.join(' · ')
    }
    return 'Review required'
  }
  let s = String(raw).trim()

  // Split decision · strategy ACTION. Signal=… Weight=…
  const headMatch = s.match(/^([A-Z_]+)\s*[·•|]\s*(.+)$/)
  let decisionRaw = ''
  let rest = s
  if (headMatch) {
    decisionRaw = headMatch[1]
    rest = headMatch[2]
  }

  // strategy + action at start of rest: "dividend_growth_compounder ADD_ON_PULLBACK. Signal=..."
  let strategyRaw = ''
  let actionRaw = ''
  const stratAct = rest.match(/^([a-z][a-z0-9_]*)\s+([A-Z][A-Z0-9_]+)\b/)
  if (stratAct) {
    strategyRaw = stratAct[1]
    actionRaw = stratAct[2]
    rest = rest.slice(stratAct[0].length).replace(/^[.\s]+/, '')
  } else {
    const onlyAct = rest.match(/^([A-Z][A-Z0-9_]+)\b/)
    if (onlyAct) {
      actionRaw = onlyAct[1]
      rest = rest.slice(onlyAct[0].length).replace(/^[.\s]+/, '')
    }
  }

  const signalM = rest.match(/Signal\s*=\s*([0-9.]+)\s*(?:\(([^)]+)\))?/i)
  const weightM = rest.match(/Weight\s*=\s*([0-9.]+)\s*%?/i)
  const incomeM = rest.match(/Income\s*=\s*([0-9.]+)\s*%?/i)
  const synthM = rest.match(/Synthesis\s*=\s*([A-Za-z0-9_]+)/i)

  const parts: string[] = []
  const decision = plain(decisionRaw) || (decisionRaw ? decisionRaw.replace(/_/g, ' ').toLowerCase() : '')
  if (decision) parts.push(decision.charAt(0).toUpperCase() + decision.slice(1))

  const strategy = plain(strategyRaw) || (strategyRaw ? strategyRaw.replace(/_/g, ' ') : '')
  const action = plain(actionRaw) || (actionRaw ? actionRaw.replace(/_/g, ' ').toLowerCase() : '')
  if (strategy && action) parts.push(`${strategy} — ${action}`)
  else if (strategy) parts.push(strategy)
  else if (action) parts.push(action)

  if (signalM) {
    const lvl = (signalM[2] || '').toLowerCase()
    const n = Number(signalM[1])
    if (lvl) parts.push(`signal ${lvl} (${n.toFixed(2)})`)
    else parts.push(`signal ${n.toFixed(2)}`)
  }
  if (weightM) {
    const w = Number(weightM[1])
    parts.push(w === 0 ? 'not in book (0% weight)' : `book weight ${w.toFixed(1)}%`)
  }
  if (incomeM) {
    const inc = Number(incomeM[1])
    if (inc > 0) parts.push(`income ${inc.toFixed(0)}%`)
  }
  if (synthM) {
    const syn = plain(synthM[1]) || synthM[1].replace(/_/g, ' ').toLowerCase()
    if (syn && syn.length > 1) parts.push(`synthesis: ${syn}`)
  }

  if (parts.length === 0) {
    // last resort: token-level plain() substitution on underscored tokens
    return s
      .replace(/\b([A-Z][A-Z0-9_]{2,})\b/g, (tok) => plain(tok) || tok.replace(/_/g, ' ').toLowerCase())
      .replace(/\b([a-z]+_[a-z0-9_]+)\b/g, (tok) => plain(tok) || tok.replace(/_/g, ' '))
      .replace(/\s{2,}/g, ' ')
      .trim()
  }
  return parts.join('. ') + '.'
}
