// Levels & valuation — adapter for GET /api/v2/indicators/levels?symbol=X (one symbol per call).
// Pure. A stored-cache miss is BUILDING, never a known-empty result or a request to analyze.
// Valuation (valuation-assessment@1) is not wired, so it is never shown.
import type { Envelope } from '../../../api/client'

export const LEVELS_PATH = '/api/v2/indicators/levels'
export const SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/

export function levelsPathFor(symbol: string): string | null {
  const s = symbol.trim().toUpperCase()
  return SYMBOL_RE.test(s) ? `${LEVELS_PATH}?symbol=${encodeURIComponent(s)}` : null
}

export interface Level { type: string; label: string; price: number }
export interface LevelsModel { symbol: string; levels: Level[]; groups: { name: string; levels: Level[] }[] }
export type LevelsState =
  | { kind: 'idle' }
  | { kind: 'loading'; symbol: string }
  | { kind: 'building'; symbol: string; reason: string }
  | { kind: 'error'; symbol: string; message: string; lastGoodAt: string | null }
  | { kind: 'empty'; symbol: string; fetchedAt: string }
  | { kind: 'ok'; model: LevelsModel; fetchedAt: string }

const GROUPS: [string, (t: string) => boolean][] = [
  ['Fibonacci', t => t.startsWith('fib_')],
  ['Pivots', t => t.startsWith('pivot_')],
  ['Bollinger', t => t.startsWith('bb_')],
  ['Stop and target (from the confluence cache)', t => t === 'stop' || t === 'target'],
]

export function adaptLevels(symbol: string, env: Envelope<unknown> | null): LevelsState {
  if (env === null) return { kind: 'loading', symbol }
  if (!env.ok) return { kind: 'error', symbol, message: env.error ?? 'the read failed', lastGoodAt: env.lastGoodAt }
  const b = env.data
  if (b === null || typeof b !== 'object' || Array.isArray(b)) return { kind: 'error', symbol, message: 'the producer answered with no body', lastGoodAt: env.lastGoodAt }
  const root = b as Record<string, unknown>
  if (root.ok === false) return { kind: 'error', symbol, message: typeof root.error === 'string' ? root.error : 'the producer declared the read unavailable', lastGoodAt: env.lastGoodAt }
  const o = root.data !== null && typeof root.data === 'object' && !Array.isArray(root.data) ? root.data as Record<string, unknown> : root
  if (o.ok === false) return { kind: 'error', symbol, message: typeof o.error === 'string' ? o.error : 'the producer declared the read unavailable', lastGoodAt: env.lastGoodAt }
  if (o.status === 'BUILDING') return { kind: 'building', symbol, reason: typeof o.reason === 'string' ? o.reason : 'Stored levels are not built yet' }
  const raw = Array.isArray(o.levels) ? o.levels : []
  const levels: Level[] = []
  for (const r of raw) {
    if (r === null || typeof r !== 'object') continue
    const x = r as Record<string, unknown>
    if (typeof x.price !== 'number' || !Number.isFinite(x.price) || x.price === 0) continue
    levels.push({ type: typeof x.type === 'string' ? x.type : 'level', label: typeof x.label === 'string' ? x.label : 'Level', price: x.price })
  }
  if (levels.length === 0) return { kind: 'empty', symbol, fetchedAt: env.fetchedAt }
  const groups = GROUPS.map(([name, f]) => ({ name, levels: levels.filter(l => f(l.type)) })).filter(g => g.levels.length > 0)
  const other = levels.filter(l => !GROUPS.some(([, f]) => f(l.type)))
  if (other.length > 0) groups.push({ name: 'Other', levels: other })
  return { kind: 'ok', fetchedAt: env.fetchedAt, model: { symbol: typeof o.symbol === 'string' ? o.symbol : symbol, levels, groups } }
}
