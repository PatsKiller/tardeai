import { useMemo, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { useIntelligenceItemState } from '../../hooks/useIntelligenceItemState'
import type { DrillContext } from '../DetailDrawer'
import SynthesizedReportCard from '../SynthesizedReportCard'
import type { ReportCardItem } from '../SynthesizedReportCard'
import IntelligenceCardActions from './IntelligenceCardActions'
import { KPI, DonutStat, SectionHeader, dashboardCard } from './dashboardKit'
import { intelligenceItemId } from '../../lib/intelligenceItemId'

interface Props { onDrill: (ctx: DrillContext) => void }

const SOURCE_LABEL: Record<string, string> = {
  news: 'News articles', youtube: 'YouTube transcripts', social_post: 'Social posts',
  sec_form4: 'SEC Form 4', fred_series: 'FRED economic', agent_result: 'Agent memory',
  agent_synthesis: 'Agent synthesis', cio_decision: 'CIO decisions', fused_signal: 'Fused signals',
  decision_outcome: 'Decision outcomes', hermes_research: 'Hermes research', research_finding: 'Research findings',
}

const SOURCE_ICON: Record<string, string> = {
  news: '📰', youtube: '▶', sec_form4: '📋', hermes_research: '🔬', agent_result: '🤖',
}

function pctColor(p: number) {
  if (p >= 70) return 'var(--green)'
  if (p >= 40) return 'var(--amber)'
  return 'var(--red)'
}

function libraryItemId(item: any) {
  return intelligenceItemId('library', item.source_type ?? 'library', item.symbol, item.title ?? String(item.id))
}

export default function IntelligenceSourcesTab({ onDrill }: Props) {
  const [libSearch, setLibSearch] = useState('')
  const [libSource, setLibSource] = useState('')
  const [libPage, setLibPage] = useState(0)
  const [embedFilter, setEmbedFilter] = useState<'all' | 'embedded' | 'pending'>('all')
  const [showDismissed, setShowDismissed] = useState(false)

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
  const { data: library, loading: libLoading, refetch } = useApi<any>(`/api/v2/intelligence/library?${libParams}`, 60_000)

  const bySource = rag?.by_source ?? {}
  const items = library?.items ?? []
  const total = library?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / 40))

  const cardIds = useMemo(() => items.map(libraryItemId), [items])
  const { byId: stateById, refresh: refreshState } = useIntelligenceItemState(cardIds, 'library')
  const onActionDone = () => { refreshState(); refetch() }

  const embedMix = useMemo(() => {
    let embedded = 0
    let pending = 0
    for (const it of items) {
      if (it.is_embedded) embedded++
      else pending++
    }
    return [
      { name: 'Embedded', value: embedded, color: 'var(--green)' },
      { name: 'Not embedded', value: pending, color: 'var(--amber)' },
    ]
  }, [items])

  const visibleItems = useMemo(() => items.filter((it: any) => {
    const st = stateById.get(libraryItemId(it)) ?? 'active'
    if (st === 'dismissed' && !showDismissed) return false
    if (embedFilter === 'embedded' && !it.is_embedded) return false
    if (embedFilter === 'pending' && it.is_embedded) return false
    return true
  }), [items, stateById, showDismissed, embedFilter])

  const dismissedCount = items.filter((it: any) => stateById.get(libraryItemId(it)) === 'dismissed').length

  const input: React.CSSProperties = {
    background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text0)', fontSize: 11, padding: '6px 10px',
  }

  const toCard = (item: any): ReportCardItem => ({
    id: libraryItemId(item),
    type: `${SOURCE_ICON[item.source_type] ?? '📄'} ${SOURCE_LABEL[item.source_type] ?? item.source_type}`,
    channel: item.source_label,
    title: item.title,
    summary: `Quality ${item.quality ?? '—'} · ${item.is_embedded ? 'embedded in RAG' : 'not yet embedded'}`,
    severity: item.is_embedded ? 'positive' : 'warning',
    symbol: item.symbol ?? undefined,
    created_at: item.created_at,
    quality_score: item.quality,
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <SectionHeader title="Pipeline Ops" subtitle="RAG coverage · Hermes coordinator · ingestion health" accent="var(--teal, #2dd4bf)" />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <KPI
          label="RAG coverage"
          value={ragLoading ? '…' : rag?.coverage_pct == null ? `${rag?.total_embedded?.toLocaleString() ?? '—'} emb` : `${rag?.coverage_pct}%`}
          sub={rag?.coverage_pct == null ? 'embeddings incl. pruned rows' : `${rag?.total_embedded?.toLocaleString() ?? '—'} embedded`}
          color={rag?.coverage_pct == null ? 'var(--text0)' : pctColor(rag?.coverage_pct ?? 0)}
        />
        <KPI
          label="Hermes coordinator"
          value={hermes?.coordinator_active ? 'LIVE' : 'CHECK'}
          sub={hermes?.coordinator_last_tick ? `last ${new Date(hermes.coordinator_last_tick).toLocaleTimeString()}` : '—'}
          color={hermes?.coordinator_active ? 'var(--green)' : 'var(--amber)'}
        />
        <KPI
          label="Hermes → RAG"
          value={`${hermes?.rag_pipeline?.embedded ?? 0}/${hermes?.rag_pipeline?.promoted ?? 0}`}
          sub={`queue ${hermes?.embedding_queue?.pending ?? 0} pending · ${hermes?.embedding_queue?.failed ?? 0} failed`}
          color="var(--blue)"
        />
        <KPI label="Finviz screeners" value={screeners?.sources?.length ?? 0} sub="active pipelines" />
      </div>

      <div style={{ ...dashboardCard, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Embedding coverage by source</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
          {Object.entries(bySource).map(([key, val]: any) => (
            <div key={key} style={{ background: 'var(--bg2)', borderRadius: 6, padding: '8px 10px' }}
              title={val.pct == null ? 'coverage % not computable' : undefined}>
              <div style={{ fontSize: 10, color: 'var(--text3)' }}>{SOURCE_LABEL[key] ?? key}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: val.pct == null ? 'var(--text3)' : pctColor(val.pct ?? 0), marginTop: 2 }}>{val.pct == null ? '—' : `${val.pct}%`}</div>
              <div style={{ fontSize: 10, color: 'var(--text3)' }}>{val.pct == null ? `${val.embedded} emb · ${val.total} rows` : `${val.embedded}/${val.total}`}</div>
            </div>
          ))}
        </div>
      </div>

      {searchSrc && (
        <div style={{ ...dashboardCard, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Ingestion pipelines</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(searchSrc).filter(([k]) => !k.startsWith('_')).map(([key, val]: any) => (
              <span key={key} style={{
                fontSize: 10, padding: '4px 10px', borderRadius: 5,
                background: val.active ? 'rgba(34,197,94,.12)' : 'var(--bg2)',
                color: val.active ? 'var(--green)' : 'var(--text3)', border: `1px solid ${val.active ? 'rgba(34,197,94,.25)' : 'var(--border)'}`,
              }}>
                {key.replace(/_/g, ' ')}{val.articles != null ? ` · ${val.articles}` : ''}{val.transcripts != null ? ` · ${val.transcripts}` : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      <div style={{ ...dashboardCard, padding: 14, borderLeft: '4px solid var(--blue)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Unified intelligence library</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>{total.toLocaleString()} items · page {libPage + 1}/{pages}</div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" style={{ ...input, cursor: 'pointer', fontWeight: embedFilter === 'all' ? 700 : 400 }} onClick={() => setEmbedFilter('all')}>All</button>
            <button type="button" style={{ ...input, cursor: 'pointer', fontWeight: embedFilter === 'embedded' ? 700 : 400 }} onClick={() => setEmbedFilter('embedded')}>Embedded</button>
            <button type="button" style={{ ...input, cursor: 'pointer', fontWeight: embedFilter === 'pending' ? 700 : 400 }} onClick={() => setEmbedFilter('pending')}>Pending</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 12, marginBottom: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 8 }}>
            <input value={libSearch} onChange={e => { setLibSearch(e.target.value); setLibPage(0) }} placeholder="Search title…" style={input} />
            <select value={libSource} onChange={e => { setLibSource(e.target.value); setLibPage(0) }} style={input}>
              <option value="">All types</option>
              {Object.keys(SOURCE_LABEL).map(k => <option key={k} value={k}>{SOURCE_LABEL[k]}</option>)}
            </select>
          </div>
          <DonutStat data={embedMix} height={90} onSliceClick={name => setEmbedFilter(name === 'Embedded' ? 'embedded' : name === 'Not embedded' ? 'pending' : 'all')} />
        </div>

        {dismissedCount > 0 && (
          <button type="button" onClick={() => setShowDismissed(v => !v)} style={{ ...input, cursor: 'pointer', marginBottom: 10 }}>
            {showDismissed ? 'Hide' : 'Show'} {dismissedCount} dismissed
          </button>
        )}

        {libLoading && !items.length ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>Loading library…</div>
        ) : visibleItems.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>No library items match.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {visibleItems.map((item: any, i: number) => {
              const card = toCard(item)
              return (
                <div
                  key={`${item.source_type}-${item.id}-${i}`}
                  onClick={() => onDrill({ title: item.title, subtitle: item.source_label ?? item.source_type, endpoint: '/api/v2/intelligence/library', rows: [item] })}
                  style={{ cursor: 'pointer' }}
                >
                  <SynthesizedReportCard
                    item={card}
                    compact={false}
                    footer={<IntelligenceCardActions itemId={card.id} itemType="library" symbol={item.symbol} onDone={onActionDone} />}
                  />
                </div>
              )
            })}
          </div>
        )}

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
