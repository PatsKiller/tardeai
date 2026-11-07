/** Market Event Re-entry (WP5) — the typed MarketEvent@v1 read model and the pure view logic over it.
 *
 *  Source: GET /api/v2/market-event/active (SPEC_MARKET_EVENT_REENTRY_20261107 §4.4). Advisory only: nothing here
 *  places, sizes or stops anything. A missing value is "not on file", never 0. Account labels only, never numbers.
 *  Pure functions (no React) so the rules are testable under `node --experimental-strip-types`. */
import type { Tone } from './designTokens.ts'

export const MARKET_EVENT_ACTIVE_API = '/api/v2/market-event/active'
export const MARKET_EVENT_SCHEMA = 'MarketEvent@v1'

export type EpisodeState = 'OPEN' | 'STABILIZING' | 'RECOVERING' | 'CLOSED'
export type CandidateState = 'WATCH' | 'STABILIZING' | 'READY' | 'ENTERED' | 'INVALIDATED'

export interface TrancheLeg { n: number; pct: number | null; account_label: string; shares: number | null; usd: number | null; entry_low: number | null; entry_high: number | null; condition: string | null; status: string | null }
export interface CandidatePlan { tranches: TrancheLeg[]; invalidation: number | null; risk_usd: number | null; risk_budget_usd: number | null; notes: string[] }
export interface Gate { id: string; label: string; state: 'pass' | 'partial' | 'fail' | 'unknown' }
export interface Candidate {
  symbol: string; state: CandidateState | 'UNKNOWN'; rank: number | null
  baseline_price: number | null; last_price: number | null; drawdown_pct: number | null; beta_expected_drawdown_pct: number | null
  quality_score: number | null; discount_score: number | null
  fwd_pe: number | null; sector_median_pe: number | null; peg: number | null; roic_pct: number | null
  orders_backlog: string | null; fell_for_reason: boolean; reason_evidence: string | null
  universe: string | null; gates: Gate[]; plan: CandidatePlan | null; source: string[]
}
export interface Episode { id: string; state: EpisodeState; title: string; tier: string | null; opened_at: string | null; baseline_date: string | null; summary: string | null }
export interface MarketGate { state: string | null; chips: Gate[] }
export interface AccountCash { account_label: string; deployable_usd: number | null; reserve_usd: number | null }
export interface MarketEvent {
  schema: string; episode: Episode | null; market_gate: MarketGate; candidates: Candidate[]
  accounts: AccountCash[]; computed_at: string | null; stale: boolean
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)
const arr = (v: unknown): any[] => (Array.isArray(v) ? v : [])
const GATE_STATES = ['pass', 'partial', 'fail', 'unknown']

function gates(v: unknown): Gate[] {
  return arr(v).map((g: any) => ({ id: str(g?.id) ?? str(g?.label) ?? 'gate', label: str(g?.label) ?? str(g?.id) ?? 'Gate', state: GATE_STATES.includes(g?.state) ? g.state : 'unknown' }))
}

function plan(p: any): CandidatePlan | null {
  if (!p || typeof p !== 'object') return null
  return {
    tranches: arr(p.tranches).map((t: any, i: number) => ({
      n: num(t?.n) ?? i + 1, pct: num(t?.pct), account_label: str(t?.account_label) ?? 'Account not on file', shares: num(t?.shares), usd: num(t?.usd),
      entry_low: num(t?.entry_low), entry_high: num(t?.entry_high), condition: str(t?.condition), status: str(t?.status),
    })),
    invalidation: num(p.invalidation), risk_usd: num(p.risk_usd), risk_budget_usd: num(p.risk_budget_usd), notes: arr(p.notes).map(String),
  }
}

function candidate(c: any): Candidate {
  return {
    symbol: str(c?.symbol) ?? '—', state: ['WATCH', 'STABILIZING', 'READY', 'ENTERED', 'INVALIDATED'].includes(c?.state) ? c.state : 'UNKNOWN',
    rank: num(c?.rank), baseline_price: num(c?.baseline_price), last_price: num(c?.last_price), drawdown_pct: num(c?.drawdown_pct),
    beta_expected_drawdown_pct: num(c?.beta_expected_drawdown_pct), quality_score: num(c?.quality_score), discount_score: num(c?.discount_score),
    fwd_pe: num(c?.fwd_pe), sector_median_pe: num(c?.sector_median_pe), peg: num(c?.peg), roic_pct: num(c?.roic_pct),
    orders_backlog: str(c?.orders_backlog), fell_for_reason: c?.fell_for_reason === true, reason_evidence: str(c?.reason_evidence),
    universe: str(c?.universe), gates: gates(c?.gates), plan: plan(c?.plan), source: arr(c?.source).map(String),
  }
}

/** Wire -> MarketEvent. Returns null when the body is not MarketEvent@v1 (callers show "unavailable", never "no event"). */
export function normalizeMarketEvent(raw: any): MarketEvent | null {
  const d = raw?.data && typeof raw.data === 'object' && !Array.isArray(raw.data) && raw.data.schema ? raw.data : raw
  if (!d || typeof d !== 'object' || d.schema !== MARKET_EVENT_SCHEMA) return null
  const e = d.episode
  const episode: Episode | null = e && typeof e === 'object' ? {
    id: str(e.id) ?? '—', state: ['OPEN', 'STABILIZING', 'RECOVERING', 'CLOSED'].includes(e.state) ? e.state : 'OPEN', title: str(e.title) ?? 'Market event',
    tier: str(e.tier), opened_at: str(e.opened_at), baseline_date: str(e.baseline_date), summary: str(e.summary),
  } : null
  return {
    schema: d.schema, episode, market_gate: { state: str(d.market_gate?.state), chips: gates(d.market_gate?.chips) },
    candidates: arr(d.candidates).map(candidate).sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9)),
    accounts: arr(d.accounts).map((a: any) => ({ account_label: str(a?.account_label) ?? 'Account not on file', deployable_usd: num(a?.deployable_usd), reserve_usd: num(a?.reserve_usd) })),
    computed_at: str(d.computed_at), stale: d.stale === true,
  }
}

export type BannerModel =
  | { kind: 'hidden' }
  | { kind: 'loading' }
  | { kind: 'unavailable'; text: string }
  | { kind: 'event'; tone: Tone; headline: string; detail: string; stale: boolean; stateLabel: string }

/** Hidden only when the API ANSWERED "no episode" (or a CLOSED one). An API failure is "unavailable": a missing banner must never read as all clear. */
export function bannerModel(input: { data: unknown; loading: boolean; error: string | null }): BannerModel {
  const ev = normalizeMarketEvent(input.data)
  if (!ev) {
    if (input.loading && !input.error) return { kind: 'loading' }
    // The route does not exist yet (WP1 not deployed): there is no event feature to report on, so stay quiet. Any other failure is loud.
    if (input.error && /\b404\b|not found/i.test(input.error)) return { kind: 'hidden' }
    return { kind: 'unavailable', text: 'Market event status unavailable' }
  }
  if (!ev.episode || ev.episode.state === 'CLOSED') return { kind: 'hidden' }
  const ready = ev.candidates.filter(c => c.state === 'READY').length
  const tone: Tone = ev.episode.state === 'RECOVERING' ? 'success' : ev.episode.state === 'STABILIZING' ? 'warning' : ev.episode.tier === 'RED' ? 'danger' : ev.episode.tier === 'ORANGE' ? 'elevated' : 'warning'
  const stateLabel = ev.episode.state === 'OPEN' ? (ev.episode.tier ?? 'OPEN') : ev.episode.state
  const detail = ev.stale
    ? `stale · as of ${ev.computed_at ?? 'unknown time'}`
    : `${ev.candidates.length} candidate${ev.candidates.length === 1 ? '' : 's'} · ${ready} ready`
  return { kind: 'event', tone, headline: ev.episode.title, detail, stale: ev.stale, stateLabel }
}

export function candidateTone(state: Candidate['state']): Tone {
  return state === 'READY' ? 'success' : state === 'STABILIZING' ? 'warning' : state === 'INVALIDATED' ? 'danger' : state === 'ENTERED' ? 'info' : 'neutral'
}
export function gateTone(s: Gate['state']): Tone { return s === 'pass' ? 'success' : s === 'partial' ? 'warning' : s === 'fail' ? 'danger' : 'neutral' }

export const fmtNum = (v: number | null, d = 1): string => (v == null ? 'not on file' : v.toFixed(d))
export const fmtPctSigned = (v: number | null): string => (v == null ? 'not on file' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`)
export const fmtUsd = (v: number | null): string => (v == null ? 'not on file' : `$${Math.round(v).toLocaleString('en-US')}`)
export const fmtPrice = (v: number | null): string => (v == null ? 'not on file' : v.toFixed(2))

/** One line under the symbol in the list. Missing parts are left out, not zero-filled. */
export function candidateSubline(c: Candidate): string {
  if (c.fell_for_reason) return `${c.reason_evidence ?? 'Fell for a reason'} · needs your star, never auto-READY`
  const parts: string[] = []
  if (c.fwd_pe != null) parts.push(`Fwd P/E ${c.fwd_pe.toFixed(1)}`)
  if (c.quality_score != null) parts.push(`quality ${Math.round(c.quality_score)}`)
  if (c.universe) parts.push(c.universe)
  return parts.length ? parts.join(' · ') : 'no fundamentals on file'
}

export function trancheStatusLabel(t: TrancheLeg): string { return t.status ?? 'waiting' }
