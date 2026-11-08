/** LQ-20261107-1253 amendment 5 — the CIO bottom line at the top of the since-close card. Pure: the LQ-1257 synopsis{}
 *  field in, a verdict sentence and labelled rows out. Rows the CIO left null are not drawn; a missing or old synopsis
 *  is said, in amber, with the time it was last built. Advisory only. */

export const SYNOPSIS_MAX_AGE_MS = 24 * 3_600_000

export interface SynopsisModel {
  state: 'ok' | 'missing' | 'stale'
  posture: string | null; risk: string | null; verdict: string | null
  rows: Array<{ key: string; label: string; text: string }>
  builtAt: string | null; notice: string | null
}

const ROWS: Array<[string, string, string[]]> = [
  ['book', 'Book', ['book', 'portfolio', 'holdings']],
  ['market', 'Market', ['market', 'macro']],
  ['reentry', 'Re-entry', ['reentry', 're_entry', 'reentries']],
  ['this_week', 'This week', ['this_week', 'week', 'week_ahead']],
  ['do_now', 'Do now', ['do_now', 'actions', 'action']],
]
const str = (v: unknown): string | null => {
  if (typeof v === 'string') return v.trim() || null
  if (Array.isArray(v)) return v.map(str).filter(Boolean).join(' · ') || null
  // LQ-1257's producer sends each row as a block carrying its own one-line summary under `line`
  // ({line, tier, score, source_ids}). Take that line; a block with no readable line draws nothing.
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    return str(o.line ?? o.text ?? o.summary ?? o.label)
  }
  return null
}
const pick = (o: Record<string, unknown>, keys: string[]): unknown => keys.map(k => o[k]).find(v => v !== undefined && v !== null && v !== '')

const etClock = (iso: string): string => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : `${d.toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: '2-digit' })} ET`
}

export function synopsisModel(syn: unknown, fallbackBuiltAt: string | null, nowMs: number = Date.now()): SynopsisModel {
  const o = syn && typeof syn === 'object' && !Array.isArray(syn) ? syn as Record<string, unknown> : null
  const built = (o ? str(pick(o, ['generated_at', 'as_of', 'built_at'])) : null) ?? fallbackBuiltAt
  const verdict = o ? str(pick(o, ['verdict', 'bottom_line', 'headline', 'summary'])) : null
  const empty = { posture: null, risk: null, verdict: null, rows: [] as SynopsisModel['rows'], builtAt: built }
  if (!o || !verdict) return { state: 'missing', ...empty, notice: built ? `CIO synopsis not built since ${etClock(built)}` : 'CIO synopsis not built yet' }
  const age = built ? nowMs - new Date(built).getTime() : 0
  const stale = built != null && Number.isFinite(age) && age > SYNOPSIS_MAX_AGE_MS
  // The tier may be its own key, or nested in the producer's market block ({line, tier, ...}); accept both.
  const risk = pick(o, ['risk', 'risk_tier', 'tier'])
    ?? (o.market && typeof o.market === 'object' ? pick(o.market as Record<string, unknown>, ['tier', 'level', 'label']) : undefined)
  return {
    state: stale ? 'stale' : 'ok',
    posture: str(pick(o, ['posture', 'stance'])),
    risk: str(risk) ?? (risk && typeof risk === 'object' ? str(pick(risk as Record<string, unknown>, ['tier', 'level', 'label'])) : null),
    verdict,
    rows: ROWS.flatMap(([key, label, aliases]) => { const t = str(pick(o, aliases)); return t ? [{ key, label, text: t }] : [] }),
    builtAt: built,
    notice: stale && built ? `CIO synopsis not built since ${etClock(built)}` : null,
  }
}
