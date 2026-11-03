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
  key: 'overweight' | 'underweight' | 'degraded' | 'market-sectors' | 'market-industries'
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
  /** The neutral market projection (RotationMarketResearch@v1), independent of the advisory gates. */
  market: {
    present: boolean
    available: boolean
    computedAt: string | null
    quoteAsOf: string | null
    freshness: string
    sourceGap: string | null
    /** Age of the stored snapshot the projection was built from, when the contract states it. */
    cacheAgeS: number | null
    note: string
  } | null
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
    return { hasAny: false, portfolioTotal: null, asOf: null, blocks: [], gaps: ['no rotation summary in the response'], market: null }
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

  // ── neutral market projection (RotationMarketResearch@v1) — independent of the advisory gates ──────
  const mr = isRecord(data.market_research) ? data.market_research : null
  const zoned = (v: unknown): string | null =>
    typeof v === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v)) ? v : null
  let market: RotationDescriptive['market'] = null
  const marketBlocks: DescriptiveBlock[] = []
  if (mr) {
    const computedAt = zoned(mr.computed_at)
    const quoteAsOf = zoned(mr.quote_as_of)
    const freshness = typeof mr.freshness === 'string' && mr.freshness ? mr.freshness.toUpperCase() : 'UNKNOWN'
    const sourceGap = typeof mr.source_gap === 'string' && mr.source_gap ? mr.source_gap
      : typeof mr.sourcegap === 'string' && mr.sourcegap ? mr.sourcegap : null
    const cache = isRecord(mr.cache) ? mr.cache : null
    const cacheAgeS = num(cache?.build_age_seconds)
    if (Array.isArray(mr.gaps)) for (const g of mr.gaps) if (typeof g === 'string' && g) gaps.push(`market: ${g}`)
    if (!computedAt) gaps.push('market projection has no zoned computed_at')
    if (!quoteAsOf) gaps.push(`market quotes are ${freshness}${sourceGap ? ` (${sourceGap})` : ''}`)
    const rsLine = (row: Record<string, unknown>): string => {
      const quality = num(row.data_quality)
      const status = typeof row.quality_status === 'string' ? row.quality_status.toUpperCase() : ''
      const returns = [num(row.return_1m), num(row.return_3m), num(row.return_6m)].filter((x): x is number => x !== null)
      // The final contract allows quality_status KNOWN|UNKNOWN; a default score without return evidence is
      // not proven strength, and zero returns with positive quality is a real zero.
      const statusOk = status === 'OK' || status === 'KNOWN'
      const proven = returns.length > 0 && quality !== 0 && (quality !== null || statusOk)
      if (!proven) return `RS UNKNOWN${status ? ` (quality ${status.toLowerCase()})` : quality === 0 ? ' (quality 0)' : ' (no return evidence)'}`
      const raw = num(row.rs_raw)
      const score = num(row.rs_score)
      if (raw === null && score === null) return 'RS not provided'
      return [raw == null ? null : `raw ${raw.toFixed(2)}`, score == null ? null : `score ${score.toFixed(0)}`].filter(Boolean).join(' · ')
    }
    const returnsLine = (row: Record<string, unknown>): string => {
      const r1 = pct(row.return_1m), r3 = pct(row.return_3m), r6 = pct(row.return_6m)
      return [r1 ? `1m ${r1}` : '1m unknown', r3 ? `3m ${r3}` : '3m unknown', r6 ? `6m ${r6}` : '6m unknown'].join(' · ')
    }
    const sectors = Array.isArray(mr.sectors) ? mr.sectors.filter(isRecord).slice(0, 60) : []
    const industries = Array.isArray(mr.industries) ? mr.industries.filter(isRecord).slice(0, 60) : []
    marketBlocks.push({
      key: 'market-sectors', title: 'Market sectors · market-group observations',
      note: 'Neutral market projection from the same response. 1m/3m/6m relative returns — not portfolio weights, not advice.',
      rows: sectors.map(row => ({ label: [row.name, row.etf].filter(x => typeof x === 'string' && x).join(' · ') || 'unnamed sector',
        value: returnsLine(row), detail: rsLine(row) })),
      empty: mr.available === true ? 'No sector rows in this projection.' : 'Market projection not available in this response.',
    })
    const industryRows: DescriptiveRow[] = []
    for (const group of industries) {
      const sector = typeof group.sector === 'string' && group.sector ? group.sector : 'unnamed sector'
      const list = Array.isArray(group.industries) ? group.industries.filter(isRecord).slice(0, 40) : []
      for (const row of list) industryRows.push({
        label: `${sector} · ${typeof row.name === 'string' && row.name ? row.name : 'unnamed industry'}`,
        value: returnsLine(row), detail: rsLine(row),
      })
    }
    marketBlocks.push({
      key: 'market-industries', title: 'Market industries',
      note: 'Same projection at industry level. 1m/3m/6m relative returns — not advice.',
      rows: industryRows, empty: 'No industry rows in this projection.',
    })
    market = {
      present: true, available: mr.available === true, computedAt, quoteAsOf, freshness, sourceGap, cacheAgeS,
      note: computedAt ? 'Market projection is neutral and independent of the advisory gates.' : 'Market projection clock not stated.',
    }
  }

  const blocks: DescriptiveBlock[] = [
    { key: 'overweight', title: 'Sector exposure · overweight', note: 'Descriptive: share of the book vs its target. Not a recommendation.', rows: overweight, empty: 'No overweight sector in this response.' },
    { key: 'underweight', title: 'Sector exposure · underweight', note: 'Descriptive: share of the book vs its floor. Not a recommendation.', rows: underweight, empty: 'No underweight sector in this response.' },
    degraded,
    ...marketBlocks,
  ]
  const hasAny = overweight.length + underweight.length + degradedCount > 0 || fmtUsd(data.portfolio_total) !== null
    || marketBlocks.some(b => b.rows.length > 0)
  const asOfRaw = typeof data.generated_at === 'string' ? data.generated_at
    : typeof data.cached_at === 'string' ? data.cached_at : null
  return {
    hasAny,
    portfolioTotal: fmtUsd(data.portfolio_total),
    asOf: asOfRaw,
    blocks,
    gaps,
    market,
  }
}
