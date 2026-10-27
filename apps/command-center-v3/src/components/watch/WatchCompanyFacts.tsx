import './WatchCompanyFacts.css'
import type { CompanyFacts, CompanyFact } from '../../lib/watchProspectsModel'
import type { ReactNode } from 'react'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { fmtAsOf } from '../../lib/asOfDisplay'

function sourceNote(f?: CompanyFact) {
  const at = f?.observed_at
  const clock = f?.clock_kind?.replace(/_/g, ' ') || 'source observation'
  return `${f?.source || 'No source on file'}${at ? ` · ${clock} ${fmtAsOf(at) || 'time unknown'}` : ' · source time unavailable'}${f?.missing_reason ? ` · ${f.missing_reason.replace(/_/g, ' ')}` : ''}`
}
function dateLabel(value?: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().slice(0, 10) : null
}
/** Card name: the server's common display name; a registry ALL-CAPS string is never shown as-is. */
export function companyDisplayName(f?: CompanyFact | null) {
  if (f?.display_name) return f.display_name
  const v = f?.value
  if (!v) return null
  const letters = v.replace(/[^A-Za-z]/g, '')
  if (letters.length <= 4 || letters.replace(/[^A-Z]/g, '').length / letters.length <= 0.8) return v
  return v.toLowerCase().replace(/\b([a-z])/g, c => c.toUpperCase())
}
function catalystDate(cat?: CompanyFacts['catalyst']) {
  return cat?.date || dateLabel(cat?.published_at || cat?.observed_at) || 'Date unknown'
}
function catalystSource(cat?: { source_label?: string | null; feed?: string | null; source?: string | null }) {
  return cat?.source_label || cat?.feed || cat?.source || 'Source unavailable'
}
function noneReason(cat?: CompanyFacts['catalyst'], facts?: CompanyFacts | null) {
  return cat?.reason || (cat?.missing_reason || facts?.missing_reason || '').replace(/_/g, ' ') || null
}
export function WatchCompanyFacts({ facts, symbol, part = 'full', ticker, ownership }: { facts?: CompanyFacts | null; symbol: string;
  part?: 'company' | 'catalyst' | 'full'; ticker?: ReactNode; ownership?: ReactNode }) {
  const cat = facts?.catalyst
  const headline = cat?.status === 'CURRENT' ? cat.headline : null
  const name = companyDisplayName(facts?.company)
  const legal = facts?.company?.legal_name || facts?.company?.value || null
  const why = noneReason(cat, facts)
  const sourceClocks = [facts?.company, facts?.description, facts?.sector, facts?.industry].map(f => f?.observed_at ? Date.parse(f.observed_at) : NaN)
  const oldest = sourceClocks.every(Number.isFinite) ? Math.min(...sourceClocks) : null
  const ageHours = oldest == null ? null : Math.max(0, (Date.now() - oldest) / 3_600_000)
  const ageText = ageHours == null ? 'source time unknown' : ageHours >= 24 ? `oldest source ${Math.floor(ageHours / 24)} d ago` : `oldest source ${Math.floor(ageHours)} h ago`
  const news = part === 'full' ? (facts?.recent_news || []).filter(n => n?.headline).slice(0, 3) : []
  // Only the CIO record projection supplies these values. No upstream fallback.
  const url = cat?.url && /^https?:\/\//i.test(cat.url) ? cat.url : null
  return <section className={`watch-company-facts watch-company-${part}`} data-testid={part === 'catalyst' ? 'watch-company-catalyst' : 'watch-company-facts'} aria-label={`${symbol} CIO company facts`}>
    {part !== 'catalyst' && <>
    <div className="watch-company-heading">
      {ticker}<strong style={{ fontSize: TYPE.base + 1, color: TOKENS.text[1], fontWeight: 400 }} data-testid="watch-company-name"
        title={`${legal ? `Registered name: ${legal} · ` : ''}${sourceNote(facts?.company)}`}>{name || 'Company name unavailable'}</strong>
    </div>
    {part === 'full' && legal && legal !== name && <small className="watch-company-legal" data-testid="watch-company-legal" style={{ color: TOKENS.text[2] }}>Registered name: {legal}</small>}
    <p className="watch-company-description" title={`${facts?.description?.value || 'No company description on file'} · ${sourceNote(facts?.description)}`}>
      {facts?.description?.value || 'No company description on file'}
    </p>
    <div className="watch-company-chips" style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
      {[['sector', facts?.sector], ['industry', facts?.industry]].map(([key, field]) => <span key={String(key)} title={sourceNote(field as CompanyFact)}
        style={{ background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: '2px 8px' }}>{(field as CompanyFact)?.value || `${key === 'sector' ? 'Sector' : 'Industry'} unavailable`}</span>)}
    </div>
    {ownership && <div className="watch-card-ownership" data-testid="watch-card-ownership" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{ownership}</div>}
    </>}
    {part !== 'company' && <>
    <div className="watch-company-catalyst">
      <span className="watch-company-label" style={{ fontSize: TYPE.sm, textTransform: 'uppercase', color: TOKENS.text[2] }}>CATALYST</span>
      {headline ? <>
        {cat?.catalyst_class === 'UPCOMING_EVENT' && <span className="watch-company-upcoming" data-testid="watch-company-upcoming">Upcoming</span>}
        {url ? <a href={url} target="_blank" rel="noopener noreferrer">{headline}</a> : <span className="watch-company-headline">{headline}</span>}
        <span className="watch-company-source" data-testid="watch-company-catalyst-meta">
          <span data-testid="watch-company-catalyst-date">{catalystDate(cat)}</span> · {catalystSource(cat)}{cat?.date_kind === 'observed' || (!cat?.date && !cat?.published_at) ? ' · observed date' : ''}
        </span>
        {part === 'full' && <span className="watch-company-source">Source claim · verification {cat?.factual_verification_status || 'not established'} (a stored declaration, not independent verification)</span>}
      </> : <>
        <span data-testid="watch-company-none">None on file{cat?.status === 'STALE' ? ' · prior evidence stale' : ''}</span>
        {why && <span className="watch-company-source watch-company-none-reason" data-testid="watch-company-none-reason">{why}</span>}
      </>}
    </div>
    {news.length > 0 && <div className="watch-company-news" data-testid="watch-company-news">
      <span className="watch-company-label" style={{ fontSize: TYPE.sm, textTransform: 'uppercase', color: TOKENS.text[2] }}>Recent news · not catalysts</span>
      <ul>{news.map((n, i) => <li key={i}>
        {n.url && /^https?:\/\//i.test(n.url) ? <a href={n.url} target="_blank" rel="noopener noreferrer">{n.headline}</a> : <span>{n.headline}</span>}
        <span className="watch-company-source"> · {n.date || 'Date unknown'} · {catalystSource(n)}</span>
      </li>)}</ul>
    </div>}
    </>}
    {(part === 'full' || part === 'company') &&
    <small className="watch-company-provenance" title={['company', 'description', 'sector', 'industry'].map(k => `${k}: ${sourceNote(facts?.[k as 'company'])}`).join('\n')}>
      Company facts · {facts?.status === 'MISSING' || !facts ? (facts?.missing_reason === 'cio_record_missing' ? 'no company facts saved for this security GUID' : (facts?.missing_reason || 'company facts not on CIO record').replace(/_/g, ' ')) : 'stored source evidence'}
      {' · '}{ageText}
      {facts?.conflicts?.length ? ` · ${facts.conflicts.length} source conflict(s)` : ''}
    </small>}
  </section>
}
