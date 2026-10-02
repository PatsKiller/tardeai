/**
 * CIO Desk hub tab IA — 5 primary tabs + aliases from the former 13-tab strip.
 */

export const CIO_HUB_TABS = [
  'overview',
  'decisions',
  'research',
  'capital-policy',
  'evidence-comms',
] as const

export type CioHubTab = (typeof CIO_HUB_TABS)[number]

export const CIO_HUB_TAB_LABEL: Record<CioHubTab, string> = {
  overview: 'Overview',
  decisions: 'Decisions',
  research: 'Research',
  'capital-policy': 'Capital & Policy',
  'evidence-comms': 'Evidence & Comms',
}

/** Old query-param values → new primary tab (bookmarks / deep links). */
export const CIO_HUB_TAB_ALIASES: Record<string, CioHubTab> = {
  overview: 'overview',
  decisions: 'decisions',
  research: 'research',
  'capital-policy': 'capital-policy',
  'evidence-comms': 'evidence-comms',
  // Legacy 13-tab strip
  'cio-brain': 'evidence-comms',
  'cio-now': 'decisions',
  opportunities: 'decisions',
  'universe-theses': 'research',
  'investment-books': 'research',
  'capital-plan': 'capital-policy',
  posture: 'capital-policy',
  'operator-policy': 'capital-policy',
  report: 'evidence-comms',
  evidence: 'evidence-comms',
  'notification-gate': 'evidence-comms',
  'telegram-receipts': 'evidence-comms',
  'senses-evidence': 'evidence-comms',
  // Evidence subsection deep links (still land on Evidence & Comms)
  brain: 'evidence-comms',
  'full-brain': 'evidence-comms',
}

export const CIO_HUB_DEFAULT_TAB: CioHubTab = 'overview'

export function resolveCioHubTab(raw: string | null | undefined): CioHubTab {
  const key = String(raw || '').trim()
  if (!key) return CIO_HUB_DEFAULT_TAB
  return CIO_HUB_TAB_ALIASES[key] || CIO_HUB_DEFAULT_TAB
}

/** Optional evidence subsection when aliasing into Evidence & Comms. */
export function resolveEvidenceSubtab(raw: string | null | undefined): string | null {
  const key = String(raw || '').trim()
  const map: Record<string, string> = {
    report: 'report',
    evidence: 'audit',
    'notification-gate': 'notification-gate',
    'telegram-receipts': 'telegram-receipts',
    'senses-evidence': 'senses-evidence',
    brain: 'full-brain',
    'full-brain': 'full-brain',
    'cio-brain': 'full-brain',
  }
  return map[key] || null
}
