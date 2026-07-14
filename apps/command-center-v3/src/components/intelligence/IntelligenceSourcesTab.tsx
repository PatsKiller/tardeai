import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import type { DrillContext } from '../DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }

function pctColor(p: number) {
  if (p >= 70) return '#22c55e'
  if (p >= 40) return '#f59e0b'
  return '#ef4444'
}

const SOURCE_LABEL: Record<string, string> = {
  news: 'News articles', youtube: 'YouTube transcripts', social_post: 'Social posts',
  sec_form4: 'SEC Form 4', fred_series: 'FRED economic', agent_result: 'Agent memory',
  agent_synthesis: 'Agent synthesis', cio_decision: 'CIO decisions', fused_signal: 'Fused signals',
  decision_outcome: 'Decision outcomes', hermes_research: 'Hermes research', research_finding: 'Research findings',
}

export default function IntelligenceSourcesTab({ onDrill }: Props) {
  const [libSearch, setLibSearch] = useState('')
  const [libSource, setLibSource] = useState('')
  const [libPage, setLibPage] = useState(0)
  const { data: rag, loading: ragLoading } = useApi<any>('/api/v2/rag/status', 120_000)
  const { data: searchSrc } = useApi<any>('/api/v2/search-sources', 120_000)
  const { data: hermes } = useApi<any>('/api/v2/hermes/health', 120_000)
  const { data: screeners } = useApi<any>('/api/v2/intelligence-sources', 300_000)

  const libParams = [
    'limit=40',
    `offset=${libPage * 40}`,
    libSearch && `q=${encodeURIComponent(libSearch)}`,
    libSource && `source_type=${encodeURIComponent(libSource)}`,
  ].filter(Boolean).join('&')
  const { data: library, loading: libLoading } = useApi<any>(`/api/v2/intelligence/library?${libParams}`, 60_000)

  const bySource = rag?.by_source ?? {}
  const items = library?.items ?? []
  const total = library?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / 40))

  const input: React.CSSProperties = {
    background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text0)', fontSize: 11, padding: '6px 10px',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <div style={{ ...card, padding: 12, textAlign: 'center' }}>
          {/* pct is null when embeddings outnumber current rows (orphans of pruned rows) —
              show the two raw counts as facts instead of a bogus >100% figure. */}
          <div style={{ fontSize: rag?.coverage_pct == null && !ragLoading ? 14 : 22, fontWeight: 800, color: rag?.coverage_pct == null ? 'var(--text0)' : pctColor(rag?.coverage_pct ?? 0) }}>
            {ragLoading ? '…' : rag?.coverage_pct == null
              ? `${rag?.total_embedded?.toLocaleString() ?? '—'} embeddings · ${rag?.total_rows?.toLocaleString() ?? '—'} rows`
              : `${rag?.coverage_pct}%`}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>RAG coverage</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
            {rag?.coverage_pct == null && !ragLoading
              ? 'embeddings incl. since-pruned rows — % n/a'
              : `${rag?.total_embedded?.toLocaleString() ?? '—'} embedded`}
          </div>
        </div>
        <div style={{ ...card, padding: 12, textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: hermes?.coordinator_active ? '#22c55e' : '#f59e0b' }}>
            {hermes?.coordinator_active ? 'LIVE' : 'CHECK'}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>Hermes coordinator</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>last {hermes?.coordinator_last_tick ? new Date(hermes.coordinator_last_tick).toLocaleString() : '—'}</div>
        </div>
        <div style={{ ...card, padding: 12, textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: '#60a5fa' }}>
            {hermes?.rag_pipeline?.embedded ?? 0}/{hermes?.rag_pipeline?.promoted ?? 0}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>Hermes → RAG</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
            queue: {hermes?.embedding_queue?.pending ?? 0} pending · {hermes?.embedding_queue?.failed ?? 0} failed
          </div>
        </div>
        <div style={{ ...card, padding: 12, textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text0)' }}>{screeners?.sources?.length ?? 0}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>Finviz screeners</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>active ingestion pipelines</div>
        </div>
      </div>

      <div style={{ ...card, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Embedding coverage by source</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
          {Object.entries(bySource).map(([key, val]: any) => (
            <div key={key} style={{ background: 'var(--bg2)', borderRadius: 6, padding: '8px 10px' }}
              title={val.pct == null ? 'embeddings include rows since pruned from the source table — coverage % not computable' : undefined}>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>{SOURCE_LABEL[key] ?? key}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: val.pct == null ? 'var(--text3)' : pctColor(val.pct ?? 0), marginTop: 2 }}>{val.pct == null ? '—' : `${val.pct}%`}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>{val.pct == null ? `${val.embedded} embeddings · ${val.total} rows` : `${val.embedded}/${val.total}`}</div>
            </div>
          ))}
        </div>
      </div>

      {searchSrc && (
        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Ingestion pipelines</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(searchSrc).filter(([k]) => !k.startsWith('_')).map(([key, val]: any) => (
              <span key={key} style={{
                fontSize: 9, padding: '4px 10px', borderRadius: 5,
                background: val.active ? 'rgba(34,197,94,.12)' : 'var(--bg2)',
                color: val.active ? '#22c55e' : 'var(--text3)', border: `1px solid ${val.active ? 'rgba(34,197,94,.25)' : 'var(--border)'}`,
              }}>
                {key.replace(/_/g, ' ')}{val.articles != null ? ` · ${val.articles}` : ''}{val.transcripts != null ? ` · ${val.transcripts}` : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      <div style={{ ...card, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Unified intelligence library</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px auto', gap: 8, marginBottom: 10 }}>
          <input value={libSearch} onChange={e => { setLibSearch(e.target.value); setLibPage(0) }} placeholder="Search title…" style={input} />
          <select value={libSource} onChange={e => { setLibSource(e.target.value); setLibPage(0) }} style={input}>
            <option value="">All types</option>
            {Object.keys(SOURCE_LABEL).map(k => <option key={k} value={k}>{SOURCE_LABEL[k]}</option>)}
          </select>
          <span style={{ fontSize: 10, color: 'var(--text3)', alignSelf: 'center' }}>{total} items · p{libPage + 1}/{pages}</span>
        </div>
        {libLoading && !items.length ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>Loading library…</div>
        ) : items.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>No library items match.</div>
        ) : items.map((item: any, i: number) => (
          <div key={`${item.source_type}-${item.id}-${i}`}
            onClick={() => onDrill({ title: item.title, subtitle: item.source_label ?? item.source_type, endpoint: '/api/v2/intelligence/library', rows: [item] })}
            style={{
              padding: '8px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer',
              display: 'grid', gridTemplateColumns: '1fr auto', gap: 8,
            }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{item.title}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                {item.source_label} · {item.symbol ?? '—'} · quality {item.quality ?? '—'}
                {item.is_embedded ? ' · embedded' : ' · not embedded'}
              </div>
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>
              {item.created_at ? new Date(item.created_at).toLocaleDateString() : '—'}
            </div>
          </div>
        ))}
        {pages > 1 && (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 10 }}>
            <button disabled={libPage === 0} onClick={() => setLibPage(p => p - 1)} style={{ ...input, cursor: libPage === 0 ? 'default' : 'pointer' }}>Prev</button>
            <button disabled={libPage >= pages - 1} onClick={() => setLibPage(p => p + 1)} style={{ ...input, cursor: libPage >= pages - 1 ? 'default' : 'pointer' }}>Next</button>
          </div>
        )}
      </div>
    </div>
  )
}