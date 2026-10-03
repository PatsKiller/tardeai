export const CIO_LINEAGE_STATES = [
  'LIVE', 'PARTIAL', 'UNWIRED', 'NOT_RUN', 'NOT_APPLICABLE', 'PENDING', 'UNAVAILABLE', 'UNKNOWN',
] as const

export type CioLineageState = typeof CIO_LINEAGE_STATES[number]

export function decisionLineageHref(decisionId: string): string {
  // BrowserRouter owns basename="/v3". Internal links must be basename-relative.
  return `/cio?tab=evidence-comms&sub=decision-lineage&decision=${encodeURIComponent(decisionId)}`
}

/** Decisions tab focused on one exact decision; the hub opens its lineage. */
export function decisionFocusHref(decisionId: string): string {
  return `/cio?tab=decisions&decision=${encodeURIComponent(decisionId)}`
}

/** Research tab filtered to one exact decision (and optionally one artifact). */
export function researchFocusHref(decisionId: string, artifactId?: string | null): string {
  const artifact = artifactId ? `&artifact=${encodeURIComponent(artifactId)}` : ''
  return `/cio?tab=research&decision=${encodeURIComponent(decisionId)}${artifact}`
}

export type CioDeepLinkFocus = { decision: string | null; artifact: string | null; research: string | null }

/** Exact-id focus carried by a CIO deep link; blank params are no focus. */
export function cioDeepLinkFocus(params: { get(name: string): string | null }): CioDeepLinkFocus {
  const read = (name: string) => (params.get(name) || '').trim() || null
  return { decision: read('decision'), artifact: read('artifact'), research: read('research') }
}

export function isCioLineageState(value: unknown): value is CioLineageState {
  return typeof value === 'string' && (CIO_LINEAGE_STATES as readonly string[]).includes(value)
}

const VALUE_MAX = 180

function scalarText(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'string') return value.trim() || null
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return null
}

/** One stage's backend value as readable text; null when there is nothing to show. */
export function stageValueText(value: unknown): string | null {
  let text = scalarText(value)
  if (text === null && Array.isArray(value)) {
    const items = value.map(item => scalarText(item)).filter((item): item is string => item !== null)
    text = items.length ? items.slice(0, 3).join(' · ') + (items.length > 3 ? ` (+${items.length - 3} more)` : '') : null
  } else if (text === null && value && typeof value === 'object') {
    const pairs = Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => [key, scalarText(item)] as const)
      .filter(([, item]) => item !== null)
    text = pairs.length ? pairs.slice(0, 5).map(([key, item]) => `${key}: ${item}`).join(' · ') : null
  }
  if (text === null) return null
  return text.length > VALUE_MAX ? `${text.slice(0, VALUE_MAX - 1)}…` : text
}
