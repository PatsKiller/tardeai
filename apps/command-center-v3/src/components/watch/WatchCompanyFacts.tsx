import './WatchCompanyFacts.css'
import type { CompanyFacts, CompanyFact } from '../../lib/watchProspectsModel'

function sourceNote(f?: CompanyFact) {
  const at = f?.observed_at
  const clock = f?.clock_kind?.replace(/_/g, ' ') || 'source observation'
  return `${f?.source || 'No source on file'}${at ? ` · ${clock} ${at}` : ' · source time unavailable'}${f?.missing_reason ? ` · ${f.missing_reason.replace(/_/g, ' ')}` : ''}`
}
function dateLabel(value?: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().slice(0, 10) : 'Date unavailable'
}
export function WatchCompanyFacts({ facts, symbol }: { facts?: CompanyFacts | null; symbol: string }) {
  const cat = facts?.catalyst
  const headline = cat?.status === 'CURRENT' ? cat.headline : null
  // Only the CIO record projection supplies these values. No upstream fallback.
  const url = cat?.url && /^https?:\/\//i.test(cat.url) ? cat.url : null
  return <section className="watch-company-facts" data-testid="watch-company-facts" aria-label={`${symbol} CIO company facts`}>
    <div className="watch-company-heading">
      <strong title={sourceNote(facts?.company)}>{facts?.company?.value || 'Company name unavailable'}</strong>
      <span title={sourceNote(facts?.sector)}>{facts?.sector?.value || 'Sector unavailable'}</span>
      <span title={sourceNote(facts?.industry)}>{facts?.industry?.value || 'Industry unavailable'}</span>
    </div>
    <p className="watch-company-description" title={`${facts?.description?.value || 'No company description on file'} · ${sourceNote(facts?.description)}`}>
      {facts?.description?.value || 'No company description on file'}
    </p>
    <div className="watch-company-catalyst">
      <span className="watch-company-label">Catalyst</span>
      {headline ? <>
        {url ? <a href={url} target="_blank" rel="noopener noreferrer">{headline}</a> : <span>{headline}</span>}
        <span className="watch-company-source">{dateLabel(cat?.published_at || cat?.observed_at)} · {cat?.feed || cat?.source || 'Source unavailable'}{!cat?.published_at ? ' · observed date' : ''}</span>
        <span className="watch-company-source" title="A stored verification declaration is not independent factual verification.">Source claim · verification {cat?.factual_verification_status || 'not established'}</span>
      </> : <span title={cat?.missing_reason?.replace(/_/g, ' ') || facts?.missing_reason?.replace(/_/g, ' ')}>
        No catalyst on file{cat?.status === 'STALE' ? ' · prior evidence stale' : ''}
      </span>}
    </div>
    <small className="watch-company-provenance" title={['company', 'description', 'sector', 'industry'].map(k => `${k}: ${sourceNote(facts?.[k as 'company'])}`).join('\n')}>
      CIO record · {facts?.status === 'MISSING' || !facts ? (facts?.missing_reason || 'company facts not on CIO record').replace(/_/g, ' ') : 'stored source evidence'}
      {facts?.conflicts?.length ? ` · ${facts.conflicts.length} source conflict(s)` : ''}
    </small>
  </section>
}
