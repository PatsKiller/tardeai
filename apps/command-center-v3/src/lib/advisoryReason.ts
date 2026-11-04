/** Advisory wording only. Producer state, verdict, action and evidence remain unchanged. */
export type AdvisoryReentryPresentation = { stateLabel: string | null; reason: string | null }

type Fields = Record<string, unknown>

function fields(value: unknown): Fields {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Fields : {}
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

/** Translate only the two known implementation identifiers; retain all other source detail. */
function operatorReason(value: string | null): string | null {
  return value === null ? null : value
    .replace(/\bindicator_confluence_cache\b/gi, 'technical indicators')
    .replace(/\brun\s+indicator_cache_refresh\b/gi, 'refresh technical indicators')
    .replace(/\bindicator_cache_refresh\b/gi, 'technical indicator refresh')
}

const RECORDED_FIELD_STATES = new Set(['AVAILABLE', 'STALE', 'DERIVED', 'REFERENCE_ONLY'])

function recordedNumber(reentry: Fields, name: 'price' | 'rsi', legacy: unknown): number | null {
  let value = legacy
  if (Object.prototype.hasOwnProperty.call(reentry, name)) {
    const field = reentry[name]
    if (field !== null && typeof field === 'object' && !Array.isArray(field)) {
      const evidence = fields(field)
      const state = text(evidence.state)
      // Explicitly unavailable canonical evidence must not be replaced by an older scalar.
      if (state !== null && !RECORDED_FIELD_STATES.has(state.trim().toUpperCase())) return null
      value = evidence.value
    } else {
      value = field
    }
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return name === 'price' && value <= 0 ? null : value
}

export function advisoryReentryPresentation(row: unknown): AdvisoryReentryPresentation {
  const source = fields(row)
  const reentry = fields(source.reentry)
  const state = text(fields(reentry.state).value) ?? text(source.reentry_state)
  const signals = Array.isArray(source.rationale_signals) ? source.rationale_signals : []
  const reason = operatorReason(text(source.why_call) ?? text(signals[0]) ?? text(source.rationale)
    ?? text(reentry.why) ?? text(reentry.reason) ?? text(source.reentry_reason))

  if (state?.trim().toUpperCase() !== 'MISSING MARKET') return { stateLabel: state, reason }

  const price = recordedNumber(reentry, 'price', source.reentry_price)
  const rsi = recordedNumber(reentry, 'rsi', source.reentry_rsi)
  if (price !== null && rsi === null) {
    return {
      stateLabel: 'RSI unavailable',
      reason: 'A price is recorded, but RSI is unavailable. Waiting for refreshed technical evidence.',
    }
  }
  if (price === null && rsi !== null) {
    return {
      stateLabel: 'Quote unavailable',
      reason: 'RSI is recorded, but a quote is unavailable. Waiting for refreshed quote evidence.',
    }
  }
  if (price === null && rsi === null) {
    return {
      stateLabel: 'Quote and RSI unavailable',
      reason: 'A quote and RSI are unavailable. Waiting for refreshed market and technical evidence.',
    }
  }
  // A missing-evidence producer state still stands when its numeric fields disagree with it.
  return {
    stateLabel: 'Market evidence incomplete',
    reason: 'Market evidence is incomplete. Waiting for refreshed re-entry evidence.',
  }
}
