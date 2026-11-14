/** Portfolio (classic) tab resolution for `?tab=` deep links — OBS-B2-4e (Sprint 8H-2).
 *  /v3/portfolio sends any legacy `?tab=` link to /v3/portfolio-classic unchanged; the classic page then resolved the
 *  tab by exact, case-sensitive match, so `?tab=returns`, `?tab=lookthrough` or `?tab=Stop_Management` silently opened
 *  Holdings — a link that names a view and shows a different one. Resolution here is case-, space-, hyphen- and
 *  underscore-insensitive, plus a short explicit alias list. Anything still unrecognised falls back to Holdings, and
 *  `known` says so, so a caller can tell "asked for Holdings" from "asked for something we do not have". */

export const PORTFOLIO_TABS = ['Holdings', 'Allocation', 'Look-through', 'Returns', 'Dividends', 'Forecast', 'Tax', 'Stop Management'] as const
export type PortfolioTab = typeof PORTFOLIO_TABS[number]

const norm = (s: string): string => s.toLowerCase().replace(/[\s_\-+.]+/g, '')

/** Extra spellings seen in links and notes. Keys are already normalised. */
const ALIASES: Record<string, PortfolioTab> = {
  lookthru: 'Look-through',
  stops: 'Stop Management',
  stop: 'Stop Management',
  stopmgmt: 'Stop Management',
  dividend: 'Dividends',
  return: 'Returns',
}

const BY_NORM: Record<string, PortfolioTab> = Object.fromEntries(PORTFOLIO_TABS.map(t => [norm(t), t]))

export interface TabResolution { tab: PortfolioTab; known: boolean }

export function resolvePortfolioTabParam(raw: string | null | undefined): TabResolution {
  if (raw == null || raw.trim() === '') return { tab: 'Holdings', known: true }
  const k = norm(raw)
  const hit = BY_NORM[k] ?? ALIASES[k]
  return hit ? { tab: hit, known: true } : { tab: 'Holdings', known: false }
}

export function resolvePortfolioTab(raw: string | null | undefined): PortfolioTab {
  return resolvePortfolioTabParam(raw).tab
}
