import { useMemo } from 'react'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from './DetailDrawer'

// Interactive Intelligence pipeline workflow (2026-06-04) — mirrors the Agents/Hermes workflow
// tabs (React Flow, clickable nodes → drilldown). Live data from /api/v2/system/pipeline-health.
// Flow: ingestion (news/topics/Hermes) → curation/scoring → catalyst + LLM enhancement → RAG →
// agent jobs. Node colors = stage; border color = data freshness (green<6h, amber<24h, red older).

const STAGE = { ingestion: '#60a5fa', curation: '#f59e0b', enhance: '#a855f7', hermes: '#06b6d4', rag: '#22c55e', jobs: '#60a5fa' }

const hoursSince = (iso?: string | null) => iso ? (Date.now() - new Date(iso).getTime()) / 3600000 : null
const freshColor = (iso?: string | null, greenH = 6, amberH = 24) => {
  const h = hoursSince(iso)
  if (h === null) return '#6b7280'
  return h <= greenH ? '#22c55e' : h <= amberH ? '#f59e0b' : '#ef4444'
}

export default function IntelligenceWorkflow({ onDrill }: { onDrill: (ctx: DrillContext) => void }) {
  const { data: ph } = useApi<any>('/api/v2/system/pipeline-health', 60_000)
  const d = ph ?? {}
  const ing = d.ingestion ?? {}, cur = d.curation ?? {}, llm = d.llm ?? {}, rag = d.rag ?? {}, jobs = d.jobs ?? {}

  const { nodes, edges } = useMemo(() => {
    // id, label, sub (metric), x, y, stage color, freshness ts (optional), drill payload
    const defs = [
      { id: 'news', label: 'News Ingestion', sub: `${ing.news_today ?? 0} today · ${ing.news_7d ?? 0}/7d`, x: 0, y: 0, c: STAGE.ingestion, ts: ing.news_latest, rows: ing },
      { id: 'topics', label: 'Topics / Monitor', sub: `${ing.topics_active ?? 0} active`, x: 0, y: 95, c: STAGE.ingestion, ts: null, rows: ing },
      { id: 'hermes', label: 'Hermes Research', sub: `${cur.hermes_staged ?? 0} staged · ${cur.hermes_promoted ?? 0} promoted\nRAG ${rag.hermes_embedded ?? 0}/${rag.hermes_promoted ?? cur.hermes_promoted ?? 0} · q ${rag.hermes_queue_pending ?? 0}`, x: 0, y: 190, c: STAGE.hermes, ts: rag.latest, rows: { ...cur, rag_hermes: rag } },
      { id: 'curation', label: 'Curation / Scoring', sub: `${cur.iris_approved ?? 0} ok · ${cur.iris_pending ?? 0} pend`, x: 250, y: 95, c: STAGE.curation, ts: null, rows: cur },
      { id: 'catalyst', label: 'Catalyst Events', sub: `${cur.momentum_catalyst_today ?? 0} today`, x: 500, y: 25, c: STAGE.enhance, ts: null, rows: cur },
      { id: 'llm', label: 'LLM Enhancement', sub: `${llm.agent_results_today ?? 0} results today`, x: 500, y: 165, c: STAGE.enhance, ts: llm.holdings_llm_latest, rows: llm },
      { id: 'rag', label: 'RAG Corpus', sub: `${rag.corpus_total ?? 0} · +${rag.corpus_7d ?? 0}/7d`, x: 760, y: 95, c: STAGE.rag, ts: rag.latest, rows: rag },
      { id: 'jobs', label: 'Agent Jobs', sub: `${jobs.queued ?? 0} q · ${jobs.processing ?? 0} run · ${jobs.failed_today ?? 0} fail`, x: 1010, y: 95, c: STAGE.jobs, ts: null, rows: jobs },
    ]
    const nodes = defs.map(n => ({
      id: n.id, position: { x: n.x, y: n.y }, data: { label: n.label, sub: n.sub, c: n.c, ts: n.ts, rows: n.rows },
      style: {
        background: 'var(--bg1)', color: 'var(--text0)', fontSize: 10, fontWeight: 600,
        border: `2px solid ${n.ts ? freshColor(n.ts) : n.c}`, borderRadius: 8, width: 180, padding: 6,
        whiteSpace: 'pre-line' as const, textAlign: 'center' as const, lineHeight: 1.35,
      },
    }))
    const E = (s: string, t: string, label: string, dashed = false, color = '#475569') => ({
      id: `${s}-${t}`, source: s, target: t, label, animated: !dashed,
      style: { stroke: color, strokeWidth: 1.5, strokeDasharray: dashed ? '5 5' : undefined },
      labelStyle: { fontSize: 8, fill: 'var(--text3)' }, markerEnd: { type: MarkerType.ArrowClosed, color },
    })
    const edges = [
      E('news', 'curation', 'score'),
      E('topics', 'curation', 'ingest'),
      E('hermes', 'curation', 'bridge', true, '#06b6d4'),
      E('curation', 'catalyst', 'classify'),
      E('curation', 'llm', 'enrich'),
      E('catalyst', 'rag', 'fuse → embed'),
      E('llm', 'rag', 'embed'),
      E('rag', 'jobs', 'serve'),
    ]
    return { nodes, edges }
  }, [JSON.stringify(d)])

  // custom node renderer via data.sub — React Flow shows data.label; we append sub through a title.
  const nodesWithSub = nodes.map(n => ({ ...n, data: { ...n.data, label: `${n.data.label}\n${n.data.sub}` } }))

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
      <div style={{ display: 'flex', gap: 14, marginBottom: 8, fontSize: 9, color: 'var(--text3)', flexWrap: 'wrap' }}>
        <span><b style={{ color: STAGE.ingestion }}>■</b> ingestion</span>
        <span><b style={{ color: STAGE.hermes }}>■</b> Hermes</span>
        <span><b style={{ color: STAGE.curation }}>■</b> curation/scoring</span>
        <span><b style={{ color: STAGE.enhance }}>■</b> enhancement</span>
        <span><b style={{ color: STAGE.rag }}>■</b> RAG</span>
        <span>border = data freshness (green &lt;6h · amber &lt;24h · red older) · click a node to drill</span>
      </div>
      <div style={{ height: 420, background: 'var(--bg0)', borderRadius: 8 }}>
        <ReactFlow nodes={nodesWithSub} edges={edges} fitView nodesDraggable={false} nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_, node) => {
            const nd: any = node.data
            onDrill({
              title: String(nd.label).split('\n')[0],
              subtitle: nd.sub,
              endpoint: '/api/v2/system/pipeline-health',
              rows: [nd.rows && typeof nd.rows === 'object' ? nd.rows : { value: nd.sub }],
            })
          }}>
          <Background color="var(--border)" gap={16} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>
        Source: /api/v2/system/pipeline-health · as of {d.as_of?.slice(0, 19)?.replace('T', ' ') ?? '—'}
      </div>
    </div>
  )
}
