// Home v007 additive context (HomeMarketRiskContext@v1) — display model.
//
// Reads the OPTIONAL `home_v007` object on GET /api/v2/market-risk/latest. Every fact carries
// value/state/as_of/source/age_seconds and, when not ok, reason + remediation. This module never invents a value:
// unknown/missing/future renders as unknown with its reason; stale keeps the value AND its age; not_applicable says
// so rather than looking like a gap. Advisory only — no size, order or stop level.
// Runs under node --experimental-strip-types (homeV007.test.ts).

export type FactState = 'measured' | 'unknown' | 'not_applicable'

export type Fact = {
  state: FactState
  asOf: string | null
  source: string | null
  ageSeconds: number | null
  reason: string | null
  remediation: string | null
}

export type QuoteLine = Fact & {
  price: number | null
  session: string | null
  sessionDate: string | null
  expectedSessionDate: string | null
  basis: string | null
}

export type SymbolContext = {
  symbol: string
  quote: QuoteLine
  dayChange: { usd: number | null; pct: number | null; referenceDate: string | null } & Fact
  sinceExit: { usd: number | null; pct: number | null; exitPrice: number | null; exitDate: string | null } & Fact
  references: Array<{ label: string; price: number | null; distanceUsd: number | null; distancePct: number | null } & Fact>
  headlines: Array<{ title: string; source: string | null; publishedAt: string | null; ageSeconds: number | null }>
  nextEvent: { label: string | null; at: string | null } & Fact
  cio: { stance: string | null; conviction: string | number | null; storeLabel: string | null; stale: boolean } & Fact
  marketStance: { value: string | null; headline?: string | null } & Fact
  volume: { ratio: number | null; sampleDates: string[]; notTimeAdjusted: boolean } & Fact
}

export type BudgetRow = {
  key: string
  label: string
  current: number | null
  budget: number | null
  unit: string | null
  clearsWhen: string | null
  breach: boolean
  /** The canonical scope the measurement belongs to, when the payload names one. */
  scopeId: string | null
  /** RAW owner binding: when the numbers were measured, and the source hash they were read from. */
  sourceAsOf: string | null
  sourceSha: string | null
  /** COMPOSITE binding the decision route is scoped to; display keeps it distinct from the raw binding. */
  presentationSha: string | null
  operatorDecision: 'available' | 'unavailable'
  decisionRemediation: string | null
  /** An operator's intentional budget decision: shown, never offered. No button exists for it. */
  decision: {
    active: boolean
    intentionalUntil: string | null
    actor: string | null
    receipt: string | null
    history: number
  }
} & Fact

export type HomeV007 = {
  present: boolean
  symbols: SymbolContext[]
  positions: Array<{ symbol: string; account: string | null; pctAccount: number | null; denominator: string | null; stopDistancePct: number | null; stopState: string | null }>
  risk: {
    score: number | null
    categories: Array<{ key: string; label: string; chip: string | null; state: FactState; asOf: string | null; reason: string | null }>
    nextEvaluation: { at: string | null; basis: string | null } | null
  }
  hedge: { triggers: Array<{ label: string; current: number | null; threshold: number | null; met: boolean | null }>; inverse: Array<{ symbol: string; dayPct: number | null; state: FactState }> }
  budgets: BudgetRow[]
  /** Top-level decision ledger. ``complete: false`` means the per-row history counts are partial. */
  decisionHistory: { complete: boolean | null; count: number | null; history: number }
  gaps: Array<{ member: string; key: string; reason: string | null; remediation: string | null }>
  readErrors: Array<{ member: string; code: string; remediation: string | null }>
}

const rec = (v: unknown): Record<string, unknown> | null => (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)
const bool = (v: unknown): boolean => v === true
const STATES: FactState[] = ['measured', 'unknown', 'not_applicable']

function remediationText(v: unknown): string | null {
  const o = rec(v)
  if (o) return [str(o.action), str(o.key) ? `(${str(o.key)})` : null].filter(Boolean).join(' ') || null
  return str(v)
}

function fact(o: Record<string, unknown> | null): Fact {
  const rawWord = str(o?.state)?.toLowerCase()
  // The 2506 contract emits measured | unknown | not_applicable.
  const raw = (rawWord === 'ok' ? 'measured' : rawWord === 'stale' ? 'measured' : rawWord === 'missing' ? 'unknown' : rawWord) as FactState | undefined
  const asOf = str(o?.as_of)
  const future = asOf ? (() => { const t = Date.parse(asOf); return Number.isFinite(t) && t > Date.now() + 60_000 })() : false
  return {
    state: future ? 'unknown' : (raw && STATES.includes(raw) ? raw : 'unknown'),
    asOf,
    source: str(o?.source),
    ageSeconds: num(o?.age_seconds),
    reason: future ? 'clock skew: as_of is in the future' : str(o?.reason),
    remediation: future ? null : remediationText(o?.remediation),
  }
}

function quote(base: Record<string, unknown> | null): QuoteLine {
  const q = rec(base?.quote)
  const f = fact(q)
  const value = rec(q?.value)
  const sessionDate = str(q?.session_date)
  const expected = str(q?.expected_session_date)
  const mismatched = !!(sessionDate && expected && sessionDate !== expected)
  // Only the measured-and-stale-case is ours to downgrade: an unknown fact keeps its own reason, which says more
  // than the session mismatch does.
  const downgrade = mismatched && f.state === 'measured'
  return {
    ...f,
    state: downgrade ? 'unknown' : f.state,
    reason: downgrade ? `quote belongs to session ${sessionDate}, expected ${expected}` : f.reason,
    price: num(value?.price) ?? num(q?.value),
    session: str(q?.session),
    sessionDate,
    expectedSessionDate: expected,
    basis: str(q?.basis),
  }
}

/** Inverse-fund moves arrive two ways: the producer's {symbol: symbol-context} map, or an array of move facts. */
function inverseMoves(raw: unknown): Array<{ symbol: string; dayPct: number | null; state: FactState }> {
  const map = rec(raw)
  if (map && !Array.isArray(map.value)) {
    return Object.entries(map).slice(0, 12).map(([symbol, v]) => {
      const o = rec(v) ?? {}
      const day = rec(o.day_change)
      return { symbol, dayPct: num(rec(day?.value)?.pct) ?? num(day?.value), state: fact(rec(o.quote) ?? o).state }
    })
  }
  const list = Array.isArray(rec(raw)?.value) ? (rec(raw)!.value as unknown[]) : (Array.isArray(raw) ? raw : [])
  return list.filter(rec).map(f => {
    const o = rec(f) as Record<string, unknown>
    return { symbol: str(o.symbol) ?? '?', dayPct: num(o.day_pct ?? o.day_change_pct), state: fact(o).state }
  })
}

export function parseHomeV007(raw: unknown): HomeV007 {
  const ctx = rec(raw)
  const gaps: HomeV007['gaps'] = []
  const readErrors: HomeV007['readErrors'] = []
  if (!ctx) return { present: false, symbols: [], positions: [], risk: { score: null, categories: [], nextEvaluation: null }, hedge: { triggers: [], inverse: [] }, budgets: [], decisionHistory: { complete: null, count: null, history: 0 }, gaps: [{ member: 'home_v007', key: 'absent', reason: 'the response carries no home_v007 block', remediation: 'wait for the additive reader' }], readErrors }

  for (const g of (Array.isArray(ctx.gaps) ? ctx.gaps : [])) {
    const o = rec(g); if (o) gaps.push({ member: [str(o.symbol), str(o.field)].filter(Boolean).join('.') || '?', key: remediationText(o.remediation) ?? '?', reason: str(o.reason), remediation: remediationText(o.remediation) })
  }
  for (const e of (Array.isArray(ctx.read_errors) ? ctx.read_errors : [])) {
    const o = rec(e); if (o) readErrors.push({ member: str(o.member) ?? '?', code: str(o.code) ?? '?', remediation: str(o.remediation) })
  }

  const symbolsRaw = rec(ctx.symbols) ?? {}
  const symbols: SymbolContext[] = Object.entries(symbolsRaw).map(([symbol, v]) => {
    const s = rec(v) ?? {}
    const dc = rec(s.day_change); const dcVal = rec(dc?.value)
    const se = rec(s.since_exit); const seVal = rec(se?.value)
    const cioRaw = rec(s.cio); const cioVal = rec(cioRaw?.value)
    const vol = rec(s.volume_vs_20d); const volVal = rec(vol?.value)
    const st = rec(s.market_risk_stance); const stVal = rec(st?.value)
    const refs = rec(s.analysis_references); const refsVal = rec(refs?.value)
    const heads = rec(s.headlines); const headVal = heads?.value
    const ne = rec(s.next_event); const neVal = rec(ne?.value)
    return {
      symbol,
      quote: quote(s),
      dayChange: { ...fact(dc), usd: num(dcVal?.price), pct: num(dcVal?.pct), referenceDate: str(dcVal?.reference_session_date) },
      sinceExit: { ...fact(se), usd: num(seVal?.distance_price), pct: num(seVal?.distance_pct), exitPrice: num(seVal?.reference_price), exitDate: null },
      references: refsVal
        ? Object.entries(refsVal).slice(0, 12).map(([label, v]) => {
            const o = rec(v) ?? {}
            const nested = fact({ ...o, state: o.state ?? refs?.state, as_of: o.price_as_of ?? refs?.as_of, source: refs?.source, age_seconds: refs?.age_seconds, reason: refs?.reason, remediation: o.remediation ?? refs?.remediation })
            return { ...nested, label, price: num(o.reference_price), distanceUsd: num(o.distance_price), distancePct: num(o.distance_pct) }
          })
        : [],
      headlines: Array.isArray(headVal) ? headVal.filter(rec).slice(0, 4).map(h => {
        const o = rec(h) as Record<string, unknown>
        return { title: str(o.title) ?? '(untitled)', source: str(o.source), publishedAt: str(o.published_at), ageSeconds: num(o.age_seconds) }
      }) : [],
      nextEvent: { ...fact(ne), label: str(neVal?.label), at: str(neVal?.at) },
      cio: { ...fact(cioRaw), stance: str(cioVal?.stance), conviction: num(cioVal?.conviction) ?? str(cioVal?.conviction) ?? num(rec(s.conviction)?.value), storeLabel: str(cioVal?.store_label), stale: bool(cioVal?.stale) },
      marketStance: { ...fact(st), value: str(stVal?.stance), headline: str(stVal?.headline) } as SymbolContext['marketStance'],
      volume: { ...fact(vol), ratio: num(volVal?.ratio), sampleDates: Array.isArray(volVal?.sample_dates) ? volVal!.sample_dates.slice(0, 20).map(String) : [], notTimeAdjusted: bool(volVal?.not_time_adjusted) },
    }
  })

  const positions = (Array.isArray(ctx.positions) ? ctx.positions : []).filter(rec).slice(0, 60).map(p => {
    const o = rec(p) as Record<string, unknown>
    const sd = rec(o.stop_distance)
    return { symbol: str(o.symbol) ?? '?', account: str(o.account_label), pctAccount: num(o.pct_account), denominator: str(o.pct_denominator), stopDistancePct: num(sd?.pct), stopState: str(o.stored_stop_state) }
  })

  const riskRaw = rec(ctx.risk) ?? {}
  const risk = {
    score: num(riskRaw.score),
    categories: (Array.isArray(riskRaw.categories) ? riskRaw.categories : []).filter(rec).map(c => {
      const o = rec(c) as Record<string, unknown>
      const f = fact(o)
      const key = str(o.category) ?? str(o.key) ?? '?'
      return { key, label: str(o.label) ?? key.replace(/_/g, ' '), chip: str(o.chip), state: f.state, asOf: f.asOf, reason: f.reason }
    }),
    nextEvaluation: (() => {
      const n = rec(riskRaw.next_evaluation)
      if (!n) return null
      const v = rec(n.value)
      // The producer puts a bare ISO timestamp in ``value``; older payloads nested it as {at, basis}.
      return {
        at: str(v?.at) ?? str(n.value),
        basis: str(v?.basis) ?? str(n.basis) ?? str(n.reason) ?? (fact(n).state === 'unknown' ? 'not declared' : null),
      }
    })(),
  }

  const hRaw = rec(ctx.hedge) ?? {}
  const trig = (key: 'lagging_progress' | 'exposure_progress') => {
    const f = rec(hRaw[key]); const v = rec(f?.value)
    return f ? [{ label: key === 'lagging_progress' ? 'lagging sectors' : 'exposure', current: num(v?.current), threshold: num(v?.threshold), met: typeof v?.met === 'boolean' ? v.met : null }] : []
  }
  const hedge = {
    triggers: [...trig('lagging_progress'), ...trig('exposure_progress')],
    inverse: inverseMoves(hRaw.inverse_moves),
  }

  const budgets: BudgetRow[] = (Array.isArray(ctx.budgets) ? ctx.budgets : []).filter(rec).slice(0, 10).map(b => {
    const o = rec(b) as Record<string, unknown>
    const od = rec(o.operator_decision)
    const sb = rec(o.source_binding), pb = rec(o.presentation_binding)
    const bpd = rec(o.budget_presentation_decision)
    const actual = num(o.actual), limit = num(o.limit)
    return {
      ...fact({ state: actual != null && limit != null ? 'measured' : 'unknown', as_of: str(rec(o.source_binding)?.as_of), source: 'market_risk_budgets', age_seconds: null, reason: null, remediation: null }),
      key: str(o.budget) ?? '?', label: str(o.budget)?.replace(/_/g, ' ') ?? '?', current: actual, budget: limit, unit: str(o.unit),
      clearsWhen: str(o.clears_when),
      breach: typeof o.breached === 'boolean' ? o.breached : actual != null && limit != null && actual > limit,
      operatorDecision: str(od?.state) === 'available' ? 'available' : 'unavailable',
      decisionRemediation: remediationText(od?.remediation),
      scopeId: str(o.scope_id),
      sourceAsOf: str(sb?.as_of),
      sourceSha: str(sb?.sha256),
      presentationSha: str(pb?.sha256),
      decision: {
        active: bool(bpd?.active),
        intentionalUntil: str(bpd?.intentional_until),
        actor: str(bpd?.actor),
        receipt: str(bpd?.receipt),
        history: Array.isArray(bpd?.history) ? bpd!.history.length : 0,
      },
    }
  })

  const dh = rec(ctx.budget_presentation_decisions)
  const decisionHistory = {
    complete: typeof dh?.complete === 'boolean' ? (dh!.complete as boolean) : null,
    count: num(dh?.items) ?? num(dh?.count),
    history: Array.isArray(dh?.history) ? dh!.history.length : 0,
  }

  return { present: true, symbols, positions, risk, hedge, budgets, decisionHistory, gaps, readErrors }
}
