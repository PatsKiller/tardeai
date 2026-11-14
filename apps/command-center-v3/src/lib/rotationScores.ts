/**
 * Rotation candidate scores — typed, labelled, never hidden when zero (RR-004).
 *
 * Why (2026-11-14, sprint 8H-2): the page rendered `{c.trim_score ? … : null}` and
 * `{c.add_score ? … : null}`, so a genuine score of 0 disappeared and the reader could not tell
 * "scored zero" vs "not returned". A zero is a real engine result (`rotation_intelligence_engine`
 * clamps both scores to 0–100) and it is the *most common* trim result for a small position with
 * positive upside, so hiding it replaced evidence with a blank. Labels also said `trim`/`add`
 * rather than "score", and confidence had no stated scale.
 *
 * Scale (read from the producer, `scripts/rotation_intelligence_engine.py:317-330`):
 *   trim_score / add_score — 0–100, rounded to 2dp, clamped.
 *   confidence             — 0–1, `round(min(0.95, 0.45 + score/100), 3)`.
 *
 * A score is an engine ranking signal, not shares, dollars or a target weight.
 */

export type ScoreState = 'value' | 'zero' | 'unavailable'

export type ScorePart = {
  key: 'trim' | 'add' | 'confidence'
  label: string
  state: ScoreState
  value: number | null
  text: string
  scale: string
  reason: string | null
}

export type ScoreView = {
  parts: ScorePart[]
  /** True when the valuation trim score is zero but Aegis degradation flagged the name. */
  stopDriven: boolean
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

function part(
  key: ScorePart['key'],
  label: string,
  raw: unknown,
  opts: { min: number; max: number; scale: string; nullReason?: unknown },
): ScorePart {
  const value = num(raw)
  if (value == null) {
    const reason = typeof opts.nullReason === 'string' && opts.nullReason.trim()
      ? opts.nullReason
      : `${key}_score was not returned as a number by the engine`
    return {
      key,
      label,
      state: 'unavailable',
      value: null,
      text: `${label} unavailable`,
      scale: opts.scale,
      reason: key === 'confidence' ? `${key} was not returned as a number by the engine` : reason,
    }
  }
  const inRange = value >= opts.min && value <= opts.max
  if (!inRange) {
    return {
      key,
      label,
      state: 'unavailable',
      value: null,
      text: `${label} unavailable`,
      scale: opts.scale,
      reason: `returned ${value}, outside the engine's ${opts.min}–${opts.max} scale`,
    }
  }
  return {
    key,
    label,
    state: value === 0 ? 'zero' : 'value',
    value,
    text: `${label} ${value}`,
    scale: opts.scale,
    reason: null,
  }
}

/** Build the renderable parts for one candidate. Order: trim, add, confidence. */
export function scoreView(candidate: unknown): ScoreView {
  const c = (candidate ?? {}) as Record<string, unknown>
  const trim = part('trim', 'Trim score', c.trim_score, {
    min: 0, max: 100, scale: '0–100 engine score', nullReason: c.trim_score_null_reason ?? c.score_unavailable_reason,
  })
  const add = part('add', 'Add score', c.add_score, {
    min: 0, max: 100, scale: '0–100 engine score', nullReason: c.add_score_null_reason ?? c.score_unavailable_reason,
  })
  const confidence = part('confidence', 'Confidence', c.confidence, {
    min: 0, max: 1, scale: '0–1 engine confidence',
  })
  return {
    parts: [trim, add, confidence],
    // The page's existing note, kept accurate: the rotate-out reason is the stop/thesis status,
    // not a positive valuation trim. Shown beside a real, visible zero rather than replacing it.
    stopDriven: trim.state === 'zero' && !!c.degradation,
  }
}

/** Tooltip text for one part: scale, provenance, and the reason it is unavailable. */
export function scoreTitle(p: ScorePart): string {
  if (p.state === 'unavailable') return `${p.label} unavailable — ${p.reason}`
  return `${p.label} — ${p.scale}. An engine ranking signal, not a share quantity, weight or order.`
}
