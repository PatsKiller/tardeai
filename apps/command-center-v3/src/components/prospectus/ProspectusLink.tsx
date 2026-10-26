/** "Prospectus" entry point for ticker cards and the shared ticker modal (operator 2026-10-26). Opens
 *  /v3/prospectus/:symbol. Inside the router it navigates in-app; outside one (isolated fixtures) it is a plain link.
 *  Clicks never bubble into the card that hosts it. Height: 28px desktop, 44px on a phone (pages/Prospectus.css,
 *  loaded with the app bundle; not imported here so isolated esbuild harnesses without a CSS output still build). */
import { Link, useInRouterContext } from 'react-router-dom'
import { pageRoute, normSymbol } from '../../lib/prospectusModel'
import { RADIUS, TYPE } from '../../lib/designTokens'

const style: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: '0 8px', minWidth: 28,
  fontSize: TYPE.sm, fontWeight: 800, lineHeight: 1, whiteSpace: 'nowrap', textDecoration: 'none', cursor: 'pointer',
  color: 'var(--ai-color)', background: 'var(--ai-bg)', border: '1px solid var(--ai-border)', borderRadius: RADIUS.pill,
}

export default function ProspectusLink({ symbol, compact, testId = 'prospectus-link' }: { symbol: string; compact?: boolean; testId?: string }) {
  const sym = normSymbol(symbol)
  const inRouter = useInRouterContext()
  if (!sym) return null
  // Compact (table rows, card icon rows): icon only, so the host's columns do not widen; the name is in aria-label.
  const label = compact ? null : 'Prospectus'
  const common = {
    className: 'psp-entry-link', 'data-testid': testId, 'data-symbol': sym, style,
    'aria-label': `Open the ${sym} prospectus`, title: `Read the ${sym} prospectus (report, charts, PDF and Word)`,
    onClick: (e: React.MouseEvent) => e.stopPropagation(),
  }
  return inRouter
    ? <Link to={pageRoute(sym)} {...common}><span aria-hidden="true">▤</span>{label}</Link>
    : <a href={`/v3${pageRoute(sym)}`} {...common}><span aria-hidden="true">▤</span>{label}</a>
}
