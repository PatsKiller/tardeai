// Rotation page — the DESCRIPTIVE data that stays visible when the advisory is withheld.
//
// The operator bug (2026-11-02): a withheld advisory left the Rotation page blank. The advisory text and
// every action stay gated — that is the financial-advisory guard and this module never touches it — but the
// descriptive facts the same response already carries (portfolio total, sector exposure vs target) are not
// advice and must remain readable. This module is display-only: no order, size, stop or recommendation, and
// an unknown value renders as unknown with a reason, never as a number.
//
// Runs under `node --experimental-strip-types` (rotationDescriptive.test.ts).

export type DescriptiveRow = { label: string; value: string; detail: string | null }
export type DescriptiveBlock = {
  key: 'overweight' | 'underweight' | 'degraded'
  title: string
  note: string
  rows: DescriptiveRow[]
  empty: string
}
export type RotationDescriptive = {
  hasAny: boolean
  portfolioTotal: string | null
  asOf: string | null
  blocks: DescriptiveBlock[]
  /** Why the descriptive view may be thin — shown beside it, never instead of it. */
  gaps: string[]
}

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export function fmtUsd(v: unknown): string | null {
  const n = num(v)
  if (n === null) return null
  return `$${Math.round(n).toLocaleString('en-US')}`
}

const pct = (v: unknown): string | null => {
  const n = num(v)
  return n === null ? null : `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

/** Text or an explicit unknown — never a fabricated label. */
const theme = (row: Record<string, unknown>): string => {
  const t = typeof row.theme === 'string' ? row.theme.trim() : ''
  return t || 'unnamed group'
}

export function rotationDescriptive(summary: unknown): RotationDescriptive {
  const gaps: string[] = []
  const data = isRecord(summary) ? summary : null
  if (!data) {
    return { hasAny: false, portfolioTotal: null, asOf: null, blocks: [], gaps: ['no rotation summary in the response'] }
  }
  const overRaw = data.sector_overweights
  const underRaw = data.sector_underweights
  const degradedRaw = data.degraded_holdings
  if (overRaw !== undefined && !Array.isArray(overRaw)) gaps.push('sector overweights are not a list')
  if (underRaw !== undefined && !Array.isArray(underRaw)) gaps.push('sector underweights are not a list')
  if (degradedRaw !== undefined && !Array.isArray(degradedRaw)) gaps.push('degraded holdings are not a list')

  const overweight: DescriptiveRow[] = (Array.isArray(overRaw) ? overRaw : []).filter(isRecord).slice(0, 40).map(row => {
    const p = pct(row.pct)
    const target = pct(row.target)
    const excess = num(row.excess_dollars)
    return {
      label: theme(row),
      value: p == null ? 'share unknown' : target ? `${p} vs ${target} target` : p,
      detail: [excess != null && `excess ${fmtUsd(excess)}`, Array.isArray(row.top_holdings) && row.top_holdings.length ? `top: ${(row.top_holdings as unknown[]).slice(0, 5).map(String).join(', ')}` : null]
        .filter(Boolean).join(' · ') || null,
    }
  })
  const underweight: DescriptiveRow[] = (Array.isArray(underRaw) ? underRaw : []).filter(isRecord).slice(0, 40).map(row => {
    const p = pct(row.pct)
    const floor = pct(row.floor)
    const gap = pct(row.gap_pct)
    return {
      label: theme(row),
      value: p == null ? 'share unknown' : floor ? `${p} vs ${floor} floor` : p,
      detail: gap == null ? null : `gap ${gap}`,
    }
  })
  const degradedCount = Array.isArray(degradedRaw) ? degradedRaw.filter(isRecord).length : 0
  const degraded: DescriptiveBlock = {
    key: 'degraded', title: 'Holdings flagged for review',
    note: 'Descriptive count from the same response; the review itself stays withheld.',
    rows: [], empty: degradedCount ? `${degradedCount} holding(s) flagged` : 'none flagged in this response',
  }

  const blocks: DescriptiveBlock[] = [
    { key: 'overweight', title: 'Sector exposure · overweight', note: 'Descriptive: share of the book vs its target. Not a recommendation.', rows: overweight, empty: 'No overweight sector in this response.' },
    { key: 'underweight', title: 'Sector exposure · underweight', note: 'Descriptive: share of the book vs its floor. Not a recommendation.', rows: underweight, empty: 'No underweight sector in this response.' },
    degraded,
  ]
  const hasAny = overweight.length + underweight.length + degradedCount > 0 || fmtUsd(data.portfolio_total) !== null
  const asOfRaw = typeof data.generated_at === 'string' ? data.generated_at
    : typeof data.cached_at === 'string' ? data.cached_at : null
  return {
    hasAny,
    portfolioTotal: fmtUsd(data.portfolio_total),
    asOf: asOfRaw,
    blocks,
    gaps,
  }
}
