import IntelligenceCardActions from './intelligence/IntelligenceCardActions'
import { intelligenceItemId } from '../lib/intelligenceItemId'

const TEXT0 = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const MUTED = 'var(--text3)'
const BLUE = 'var(--blue)'
const AMBER = 'var(--amber)'
const GREEN = 'var(--green)'

const cta: React.CSSProperties = {
  fontSize: 12, fontWeight: 850, color: BLUE, textDecoration: 'none',
  padding: '8px 14px', borderRadius: 7, background: 'rgba(96,165,250,.13)',
  border: '1px solid rgba(96,165,250,.32)', display: 'inline-block',
}

function Badge({ label, color }: { label: string; color?: string }) {
  return (
    <span style={{ fontSize: 10, fontWeight: 800, padding: '3px 8px', borderRadius: 6, background: `${color ?? BLUE}22`, color: color ?? BLUE, border: `1px solid ${color ?? BLUE}55` }}>
      {label}
    </span>
  )
}

function StatGrid({ rows }: { rows: [string, string][] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '10px 12px' }}>
          <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase' }}>{k}</div>
          <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0, marginTop: 4 }}>{v}</div>
        </div>
      ))}
    </div>
  )
}

export function NewsArticleCurated({ row }: { row: Record<string, any> }) {
  const itemId = intelligenceItemId('news', row.source || 'news', row.symbol ?? undefined, row.title ?? '')
  const relColor = row.retirement_relevance === 'high' ? AMBER : row.retirement_relevance === 'medium' ? BLUE : MUTED
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Badge label={`${row.retirement_relevance ?? '—'} relevance`} color={relColor} />
        {row.strategy_type && <Badge label={String(row.strategy_type).replace(/_/g, ' ')} />}
        {row.symbol && <Badge label={row.symbol} color={BLUE} />}
      </div>
      <StatGrid rows={[
        ['Source', row.source ?? '—'],
        ['Relevance score', row.relevance_score != null ? String(row.relevance_score) : '—'],
        ['Published', row.created_at ? new Date(row.created_at).toLocaleString() : '—'],
      ]} />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {row.source_url && (
          <a href={row.source_url} target="_blank" rel="noreferrer" style={cta}>Open original article ↗</a>
        )}
        {row.symbol && /^[A-Z]{1,5}$/.test(row.symbol) && (
          <a href={`/v3/portfolio`} style={cta}>View in Portfolio →</a>
        )}
      </div>
      <IntelligenceCardActions itemId={itemId} itemType="news" symbol={row.symbol ?? undefined} />
    </div>
  )
}

const GAP_REASON: Record<string, string> = {
  zero_articles_and_transcripts: 'No articles or transcripts',
  zero_articles: 'No articles',
  zero_transcripts: 'No transcripts',
  stale_search: 'Stale search (>14d)',
}

export function ResearchGapCurated({ row }: { row: Record<string, any> }) {
  const isGap = row.reason != null || row.topic_id != null
  const isBrief = row.findings != null || row.latest_findings != null || row.summary_line != null
  const itemType = isBrief ? 'research_brief' as const : 'research_gap' as const
  const itemId = isBrief
    ? intelligenceItemId('research_brief', 'auto_research', row.symbol, row.topic ?? row.symbol ?? String(row.summary_line ?? ''))
    : intelligenceItemId('research_gap', row.reason ?? 'gap', undefined, row.display_name ?? row.topic_id ?? '')

  if (isBrief) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ fontSize: 10, color: AMBER, padding: '8px 10px', background: 'rgba(245,158,11,.08)', borderRadius: 8 }}>
          LLM narrative — verify figures against live Portfolio/Risk before acting.
        </div>
        {row.summary_line && <div style={{ fontSize: 14, fontWeight: 800, color: TEXT0, lineHeight: 1.4 }}>{row.summary_line}</div>}
        {(row.findings ?? row.latest_findings) && (
          <div style={{ fontSize: 12, color: TEXT2, lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{String(row.findings ?? row.latest_findings)}</div>
        )}
        <StatGrid rows={[
          ['Trigger', row.trigger ?? row.original_message ?? '—'],
          ['Updated', row.latest_finding_at ?? row.updated_at ? new Date(row.latest_finding_at ?? row.updated_at).toLocaleString() : '—'],
        ]} />
        <IntelligenceCardActions itemId={itemId} itemType="research_brief" symbol={row.symbol} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Badge label="Research gap" color={AMBER} />
        {isGap && <Badge label={GAP_REASON[row.reason] ?? row.reason ?? 'gap'} color={AMBER} />}
      </div>
      <StatGrid rows={[
        ['Topic', row.display_name ?? row.topic_id ?? row.topic ?? '—'],
        ['Reason', GAP_REASON[row.reason] ?? row.reason ?? '—'],
        ['Detail', row.detail ?? '—'],
        ['Coverage', (row.articles != null || row.transcripts != null) ? `${row.articles ?? 0} articles · ${row.transcripts ?? 0} transcripts` : '—'],
        ['Last searched', row.last_searched ? new Date(row.last_searched).toLocaleDateString() : 'never'],
      ]} />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <a href="/v3/research-intelligence" style={cta}>Open Research Intel desk →</a>
      </div>
      <IntelligenceCardActions itemId={itemId} itemType="research_gap" />
    </div>
  )
}

export function LibraryItemCurated({ row }: { row: Record<string, any> }) {
  const itemId = intelligenceItemId('library', row.source_type ?? 'library', row.symbol, row.title ?? String(row.id))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Badge label={row.source_label ?? row.source_type ?? 'library'} />
        <Badge label={row.is_embedded ? 'Embedded in RAG' : 'Not embedded'} color={row.is_embedded ? GREEN : AMBER} />
        {row.symbol && <Badge label={row.symbol} color={BLUE} />}
      </div>
      <StatGrid rows={[
        ['Quality score', row.quality != null ? String(row.quality) : '—'],
        ['Created', row.created_at ? new Date(row.created_at).toLocaleString() : '—'],
        ['Source type', row.source_type ?? '—'],
      ]} />
      {row.url && (
        <a href={row.url} target="_blank" rel="noreferrer" style={cta}>Open source ↗</a>
      )}
      <IntelligenceCardActions itemId={itemId} itemType="library" symbol={row.symbol} />
    </div>
  )
}

export function isCuratedIntelligenceEndpoint(endpoint?: string) {
  const ep = endpoint ?? ''
  return ep.includes('/news/articles') || ep.includes('/research-topics') || ep.includes('/intelligence/library')
}
