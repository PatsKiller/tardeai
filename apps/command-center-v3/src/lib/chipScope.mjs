// Defense v4 WS-BOARD — movement-chip scope logic, extracted pure so it's unit-testable
// (scripts/test_chip_scope.mjs runs this under plain node in the build).
//
// Rule: ranks are computed WITHIN THE RENDERED LIST SCOPE only — a truncated
// industries board (top/bottom 8) compares against the same 16 rows the user sees,
// never against phantom full-universe ranks. Callouts pick the biggest IMPROVEMENT
// among positive movers and the sharpest DETERIORATION among the bottom half —
// a −18% group climbing ranks is a breakdown decelerating, not "strongest rotation".

/** rows: [{name, value, prevValue}] — returns rows with rank, prevRank, delta (within scope). */
export function rankWithinScope(rows) {
  const withVal = rows.filter(r => r.value != null)
  const now = [...withVal].sort((a, b) => b.value - a.value)
  const prev = [...withVal].filter(r => r.prevValue != null).sort((a, b) => b.prevValue - a.prevValue)
  const prevRank = new Map(prev.map((r, i) => [r.name, i + 1]))
  return now.map((r, i) => {
    const pr = prevRank.get(r.name) ?? null
    return { ...r, rank: i + 1, prevRank: pr, delta: pr != null ? pr - (i + 1) : null, isNew: pr == null }
  })
}

/** The one-line callout under a board: improvement among gainers, breakdown among losers. */
export function boardCallout(ranked, tf, longerTf) {
  const gainers = ranked.filter(r => r.value > 0 && (r.delta ?? 0) > 0)
    .sort((a, b) => (b.delta ?? 0) - (a.delta ?? 0))
  const losers = ranked.filter(r => r.value < 0)
    .sort((a, b) => a.value - b.value)
  const parts = []
  if (gainers.length) {
    const g = gainers[0]
    parts.push(`${g.name}: #${g.rank} on ${tf}, was #${g.prevRank} on ${longerTf} ▲${g.delta} — the strongest rotation at this timeframe`)
  }
  if (losers.length) {
    const l = losers[0]
    const quartile = l.prevRank != null && l.prevRank <= Math.ceil(ranked.length / 4)
    const was = l.prevRank == null ? '' : quartile ? `, was top-quartile on ${longerTf}` : `, was #${l.prevRank} on ${longerTf}`
    parts.push(`${l.name}: ${l.value > 0 ? '+' : ''}${l.value}% on ${tf}${was} — the sharpest breakdown`)
  }
  return parts.length ? parts.join(' · ') : `ranks broadly match the ${longerTf} view — no big rotation at this timeframe`
}
