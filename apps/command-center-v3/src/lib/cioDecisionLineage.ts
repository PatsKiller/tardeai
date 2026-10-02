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

/**
 * Router-relative path for an href produced by the backend. The app runs under
 * BrowserRouter basename="/v3", so a backend href that already starts with
 * "/v3/" must drop it or the router renders "/v3/v3/...".
 */
export function routerPath(href: string): string {
  return href.replace(/^\/v3(?=\/|$)/, '') || '/'
}
