// Home v007 additive context (HomeMarketRiskContext@v1) — display model.
//
// Reads the OPTIONAL `home_v007` object on GET /api/v2/market-risk/latest. Every fact carries
// value/state/as_of/source/age_seconds and, when not ok, reason + remediation. This module never invents a value:
// unknown/missing/future renders as unknown with its reason; stale keeps the value AND its age; not_applicable says
// so rather than looking like a gap. Advisory only — no size, order or stop level.
// Runs under node --experimental-strip-types (homeV007.test.ts).

export type FactState = 'ok' | 'stale' | 'unknown' | 'missing' | 'not_applicable'

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
  marketStance: { value: string | null } & Fact
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
  operatorDecision: 'available' | 'unavailable'
  decisionRemediation: string | null
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
  gaps: Array<{ member: string; key: string; reason: string | null; remediation: string | null }>
  readErrors: Array<{ member: string; code: string; remediation: string | null }>
}

const rec = (v: unknown): Record<string, unknown> | null => (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)
const bool = (v: unknown): boolean => v === true
const STATES: FactState[] = ['ok', 'stale', 'unknown', 'missing', 'not_applicable']

function fact(o: Record<string, unknown> | null): Fact {
  const raw = str(o?.state)?.toLowerCase() as FactState | undefined
  const asOf = str(o?.as_of)
  const future = asOf ? (() => { const t = Date.parse(asOf); return Number.isFinite(t) && t > Date.now() + 60_000 })() : false
  return {
    state: future ? 'unknown' : (raw && STATES.includes(raw) ? raw : 'unknown'),
    asOf,
    source: str(o?.source),
    ageSeconds: num(o?.age_seconds),
    reason: future ? 'clock skew: as_of is in the future' : str(o?.reason),
    remediation: str(o?.remediation),
  }
}

function quote(base: Record<string, unknown> | null): QuoteLine {
  const q = rec(base?.quote)
  const f = fact(q)
  const value = rec(q?.value)
  const sessionDate = str(q?.session_date)
  const expected = str(q?.expected_session_date)
  const mismatched = !!(sessionDate && expected && sessionDate !== expected)
  return {
    ...f,
    state: mismatched && f.state === 'ok' ? 'unknown' : f.state,
    reason: mismatched ? `quote belongs to session ${sessionDate}, expected ${expected}` : f.reason,
    price: num(value?.price) ?? num(value),
    session: str(q?.session),
    sessionDate,
    expectedSessionDate: expected,
    basis: str(q?.basis),
  }
}

export function parseHomeV007(raw: unknown): HomeV007 {
  const ctx = rec(raw)
  const gaps: HomeV007['gaps'] = []
  const readErrors: HomeV007['readErrors'] = []
  if (!ctx) return { present: false, symbols: [], positions: [], risk: { score: null, categories: [], nextEvaluation: null }, hedge: { triggers: [], inverse: [] }, budgets: [], gaps: [{ member: 'home_v007', key: 'absent', reason: 'the response carries no home_v007 block', remediation: 'wait for the additive reader' }], readErrors }

  for (const g of (Array.isArray(ctx.gaps) ? ctx.gaps : [])) {
    const o = rec(g); if (o) gaps.push({ member: str(o.member) ?? '?', key: str(o.key) ?? '?', reason: str(o.reason), remediation: str(o.remediation) })
  }
  for (const e of (Array.isArray(ctx.read_errors) ? ctx.read_errors : [])) {
    const o = rec(e); if (o) readErrors.push({ member: str(o.member) ?? '?', code: str(o.code) ?? '?', remediation: str(o.remediation) })
  }

  const symbolsRaw = rec(ctx.symbols) ?? {}
  const symbols: SymbolContext[] = Object.entries(symbolsRaw).map(([symbol, v]) => {
    const s = rec(v) ?? {}
    const dc = rec(s.day_change); const dcVal = rec(dc?.value)
    const se = rec(s.since_exit); const seVal = rec(se?.value)
    const cioRaw = rec(s.cio)
    const vol = rec(s.volume_vs_20d); const volVal = rec(vol?.value)
    return {
      symbol,
      quote: quote(s),
      dayChange: { ...fact(dc), usd: num(dcVal?.usd), pct: num(dcVal?.pct), referenceDate: str(dcVal?.reference_date) },
      sinceExit: { ...fact(se), usd: num(seVal?.usd), pct: num(seVal?.pct), exitPrice: num(seVal?.exit_price), exitDate: str(seVal?.exit_date) },
      references: (Array.isArray(s.analysis_references) ? s.analysis_references : []).filter(rec).slice(0, 12).map(r => {
        const o = rec(r) as Record<string, unknown>
        return { ...fact(o), label: str(o.label) ?? '?', price: num(o.price), distanceUsd: num(o.distance_usd), distancePct: num(o.distance_pct) }
      }),
      headlines: (Array.isArray(s.headlines) ? s.headlines : []).filter(rec).slice(0, 4).map(h => {
        const o = rec(h) as Record<string, unknown>
        return { title: str(o.title) ?? '(untitled)', source: str(o.source), publishedAt: str(o.published_at), ageSeconds: num(o.age_seconds) }
      }),
      nextEvent: { ...fact(rec(s.next_event)), label: str(rec(s.next_event)?.label), at: str(rec(s.next_event)?.at) },
      cio: { ...fact(cioRaw), stance: str(cioRaw?.stance), conviction: num(cioRaw?.conviction) ?? str(cioRaw?.conviction), storeLabel: str(cioRaw?.store_label), stale: bool(cioRaw?.stale) },
      marketStance: { ...fact(rec(s.market_risk_stance)), value: str(rec(s.market_risk_stance)?.value) },
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
      return { key: str(o.key) ?? '?', label: str(o.label) ?? '?', chip: str(o.chip), state: f.state, asOf: f.asOf, reason: f.reason }
    }),
    nextEvaluation: (() => { const n = rec(riskRaw.next_evaluation); return n ? { at: str(n.at), basis: str(n.basis) } : null })(),
  }

  const hRaw = rec(ctx.hedge) ?? {}
  const hedge = {
    triggers: (Array.isArray(hRaw.triggers) ? hRaw.triggers : []).filter(rec).map(t => {
      const o = rec(t) as Record<string, unknown>
      return { label: str(o.label) ?? '?', current: num(o.current), threshold: num(o.threshold), met: typeof o.met === 'boolean' ? o.met : null }
    }),
    inverse: (Array.isArray(hRaw.inverse_funds) ? hRaw.inverse_funds : []).filter(rec).map(f => {
      const o = rec(f) as Record<string, unknown>
      return { symbol: str(o.symbol) ?? '?', dayPct: num(o.day_pct), state: fact(o).state }
    }),
  }

  const budgets: BudgetRow[] = (Array.isArray(ctx.budgets) ? ctx.budgets : []).filter(rec).slice(0, 10).map(b => {
    const o = rec(b) as Record<string, unknown>
    const od = rec(o.operator_decision)
    return {
      ...fact(o),
      key: str(o.key) ?? '?', label: str(o.label) ?? '?', current: num(o.current), budget: num(o.budget), unit: str(o.unit),
      clearsWhen: str(o.clears_when), breach: bool(o.breach),
      operatorDecision: str(od?.state) === 'available' ? 'available' : 'unavailable',
      decisionRemediation: str(od?.remediation),
    }
  })

  return { present: true, symbols, positions, risk, hedge, budgets, gaps, readErrors }
}
