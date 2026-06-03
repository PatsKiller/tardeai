import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Overview', 'Workflow', 'Provenance', 'Sources', 'Research', 'Dual Opinion', 'Pipeline'] as const

// Ground truth: HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md (Drive 2026-05-31).
// state is run-state, the most important honest encoding: operational vs designed vs disabled vs live_data(doc-mismatch).
type HState = 'operational' | 'designed' | 'disabled' | 'live_data' | 'running_unapproved'
interface HAgent {
  id: string; label: string; state: HState; phase: string; mission: string;
  reads: string; writes: string; forbidden: string; caps: string;
  targets: string[]; pos: { x: number; y: number }; orchestrator?: boolean; readsTradeAI?: boolean;
}
const HERMES_AGENTS: HAgent[] = [
  { id: 'coordinator', label: 'Chief Hermes Coordinator', state: 'operational', phase: 'BUILT + OPERATIONAL — directive B 2026-06-02 (cron */15, orchestrates full fleet live)', orchestrator: true,
    mission: 'Orchestrate daily/weekly agent plan, enforce caps, route tasks', reads: 'All hermes_* tables, Trade AI safe views, SearXNG health',
    writes: 'hermes_memory_events (coordination logs only)', forbidden: 'Trade, promote, embed, mutate proposals/trades/journal/holdings, broker',
    caps: '1 plan/day; defers to operator', targets: ['source_discovery', 'librarian', 'backlog', 'promotion'], pos: { x: 430, y: 0 }, readsTradeAI: true },
  { id: 'source_discovery', label: 'Source Discovery', state: 'operational', phase: 'OPERATIONAL (Phase 17–19)',
    mission: 'Discover research sources via SearXNG, stage candidates', reads: 'SearXNG (localhost), hermes_research_intelligence, Trade AI safe views',
    writes: "hermes_research_intelligence (source_discovery, staged)", forbidden: 'Embed, promote, mutate core, broker, public SearXNG',
    caps: '5 queries / 25 candidates / 5 staged per batch', targets: ['librarian'], pos: { x: 110, y: 150 }, readsTradeAI: true },
  { id: 'librarian', label: 'Hermes Librarian', state: 'operational', phase: 'APPROVED — operator-authorized 2026-06-02 (staging-only)',
    mission: 'Review staged findings; route to embed / promote / backlog', reads: 'hermes_research_intelligence, hermes_validation_findings, embeddings metadata',
    writes: 'hermes_research_intelligence (status updates only)', forbidden: 'Embed/promote directly, mutate core, broker',
    caps: '20 reviews/batch', targets: ['embedding', 'promotion', 'backlog'], pos: { x: 380, y: 150 } },
  { id: 'embedding', label: 'Embedding Curator', state: 'operational', phase: 'APPROVED — operator-authorized 2026-06-02 (staging-only; RAG worker still gated)',
    mission: 'Select records for embedding pilots; prevent RAG pollution', reads: 'hermes_research_intelligence, hermes_embedding_queue, embeddings metadata',
    writes: 'hermes_embedding_queue (candidates, requires --apply)', forbidden: 'Embed w/o phase approval, promote, mutate core, broker',
    caps: '2 embeddings / pilot batch', targets: [], pos: { x: 660, y: 70 } },
  { id: 'promotion', label: 'Promotion Review', state: 'operational', phase: 'OPERATIONAL — recommendations feed Coordinator AUTO-PROMOTE (live, directive B; reversible via audit)',
    mission: 'Review staged rows for promotion (advisory only)', reads: 'hermes_research_intelligence, hermes_promotion_audit, llm_intelligence_cache',
    writes: 'NONE (advisory output only)', forbidden: 'Promote directly, embed, mutate core, broker',
    caps: 'Review all staged rows', targets: ['operator'], pos: { x: 660, y: 160 } },
  { id: 'backlog', label: 'Research Backlog Manager', state: 'operational', phase: 'APPROVED — operator-authorized 2026-06-02 (staging-only; dedicated table optional)',
    mission: 'Maintain structured research backlog (priority/owner/status)', reads: 'hermes_research_intelligence, hermes_validation_findings, hermes_alerts, alert_events',
    writes: 'hermes_research_backlog — NOT YET CREATED (the /research-backlog endpoint surfaces backlog-tagged hermes_research_intelligence rows, not this agent\'s output)', forbidden: 'Embed, promote, mutate core, broker, send messages',
    caps: '10 backlog items/batch', targets: ['source_discovery', 'librarian'], pos: { x: 660, y: 250 } },
  { id: 'autonomous', label: 'Autonomous Research Manager', state: 'operational', phase: 'ENABLED — directive B 2026-06-02 (live under caps + kill switch)',
    mission: 'Schedule autonomous source discovery (when approved)', reads: 'hermes_research_intelligence, SearXNG, Trade AI safe views',
    writes: 'hermes_research_intelligence (staged, when approved)', forbidden: 'Embed, promote, mutate core, broker',
    caps: '2 rows/run (when approved)', targets: ['librarian'], pos: { x: 110, y: 280 } },
]
// Map raw finding types/topics → human-readable title + plain-English meaning + where to resolve.
function describeFinding(item: any): { title: string; meaning: string; resolve: string; severity: 'critical' | 'warning' | 'info'; where?: string } {
  const topic: string = item.topic || item.symbol || ''
  const t = topic.toLowerCase()
  const m = topic.match(/WR=([\d.]+)%.*?PF=([\d.]+).*?n=(\d+)/i)
  if (t.startsWith('backtest_weak_strategy') || (m && t.includes('backtest'))) {
    const wr = m ? +m[1] : null, pf = m ? +m[2] : null, n = m ? +m[3] : null
    const sev = (pf != null && pf < 1) ? 'critical' : 'warning'
    return { title: 'Weak strategy in backtest', meaning: `Win rate ${wr ?? '?'}% · profit factor ${pf ?? '?'} over ${n ?? '?'} trades — ${pf != null && pf < 1 ? 'loses money (PF<1)' : 'thin edge'}.`, resolve: 'Review this strategy in Strategy → Backtest; tighten entry rules or retire it.', severity: sev as any, where: 'Strategy → Backtest' }
  }
  if (t.startsWith('screener_underfilled')) return { title: 'Screener underfilled', meaning: topic.replace(/^screener_underfilled:\s*/i, ''), resolve: 'Loosen screener thresholds or check the data feed for the affected runs.', severity: 'warning', where: 'Strategy → Incubator' }
  if (t.startsWith('catalyst_quality_gap') || t.includes('catalyst')) return { title: 'Low-quality catalysts', meaning: topic.replace(/^catalyst_quality_gap:\s*/i, ''), resolve: 'Improve catalyst classification / raise the confidence floor before they reach proposals.', severity: 'warning', where: 'Intelligence' }
  if (t.includes('insufficient backtest') || t.includes('n≤2') || t.includes('insufficient')) return { title: 'Insufficient backtest sample', meaning: topic, resolve: 'Accumulate more closed trades before trusting these strategies; treat as unproven.', severity: 'info', where: 'Strategy → Backtest' }
  if (t.includes('journal learning') || t.includes('thesis review')) return { title: 'Journal learning empty', meaning: topic, resolve: 'Thesis reviews are not being generated — check the LLM review cron.', severity: 'warning', where: 'Journal' }
  if (t.includes('aggregate') && t.includes('win rate')) return { title: 'Aggregate win-rate weak', meaning: topic, resolve: 'Portfolio-wide hit rate is low — review strategy mix in Strategy → Analytics.', severity: 'warning', where: 'Strategy' }
  // fallback — still humanize
  return { title: (item.research_type || 'Research finding').replace(/_/g, ' '), meaning: topic || '(no detail)', resolve: 'Advisory finding — review and decide.', severity: 'info' }
}
const SEV_COLOR = { critical: '#ef4444', warning: '#f59e0b', info: '#60a5fa' } as const
// extract source domains from a research row's source_urls_json (idea B)
function domainsOf(srcJson: any): string[] {
  let urls = srcJson
  try { if (typeof urls === 'string') urls = JSON.parse(urls) } catch { return [] }
  if (urls && typeof urls === 'object' && !Array.isArray(urls)) urls = Object.values(urls)
  if (!Array.isArray(urls)) return []
  const out: string[] = []
  for (const u of urls) { if (typeof u === 'string' && u.startsWith('http')) { try { out.push(new URL(u).hostname.replace('www.', '')) } catch { /* skip */ } } }
  return [...new Set(out)]
}
const HSTATE_COLOR: Record<HState, string> = { operational: '#22c55e', live_data: '#06b6d4', running_unapproved: '#f59e0b', designed: '#64748b', disabled: '#ef4444' }
const HSTATE_LABEL: Record<HState, string> = { operational: 'operational (approved)', live_data: 'live data', running_unapproved: 'running — NOT approved', designed: 'designed — no footprint', disabled: 'disabled — not approved' }

export default function HermesHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const { data: health } = useApi<any>('/api/v2/hermes/health', 120_000)
  const { data: selfLearn } = useApi<any>('/api/v2/hermes/self-learning-overview', 120_000)
  const { data: choices } = useApi<any>('/api/v2/hermes/advisory-choices', 120_000)
  const { data: backlog } = useApi<any>('/api/v2/hermes/research-backlog', 120_000)
  const { data: dualOp } = useApi<any>('/api/v2/hermes/dual-opinion', 120_000)
  const { data: pipeQual } = useApi<any>('/api/v2/hermes/pipeline-quality', 120_000)
  const { data: promo } = useApi<any>('/api/v2/hermes/promotion-review', 120_000)
  const { data: footprint } = useApi<any>('/api/v2/hermes/agent-footprint', 120_000)
  const { data: infra } = useApi<any>('/api/v2/hermes/infra', 60_000)
  const { data: provData } = useApi<any>('/api/v2/hermes/provenance', 60_000)
  const { data: sourcesData } = useApi<any>('/api/v2/hermes/sources', 120_000)
  const credByDomain: Record<string, number> = {}
  for (const s of (sourcesData?.sources ?? [])) if (s.type === 'web') credByDomain[s.name] = Number(s.credibility ?? 0)
  const infraSvc: any[] = infra?.services ?? []
  const searxUp = infraSvc.find((s: any) => s.name === 'SearXNG')?.status === 'up'

  // Provenance node-graph lane: SearXNG/Internal → domain → producing AGENT → research item → RAG
  const { provNodes, provEdges } = useMemo(() => {
    const items: any[] = (provData?.items ?? []).slice(0, 28)
    if (items.length === 0) return { provNodes: [], provEdges: [] }
    const N: any[] = [], E: any[] = []
    const SX = 'sx', INT = 'internal', RAG = 'rag'
    const shortAgent = (a: string) => (a || 'unknown').replace(/_/g, ' ').replace(/ agent| loop/g, '').trim()
    N.push({ id: SX, position: { x: 0, y: 60 }, data: { label: `🔎 SearXNG\n${searxUp ? 'up' : 'down'}` }, style: { background: 'rgba(34,197,94,.12)', border: '1.5px solid #22c55e', borderRadius: 8, fontSize: 10, fontWeight: 700, width: 116, padding: 6, whiteSpace: 'pre-line', textAlign: 'center', color: 'var(--text0)' } })
    N.push({ id: INT, position: { x: 0, y: 220 }, data: { label: 'Internal\nfindings' }, style: { background: 'var(--bg2)', border: '1.5px dashed var(--text3)', borderRadius: 8, fontSize: 10, width: 116, padding: 6, whiteSpace: 'pre-line', textAlign: 'center', color: 'var(--text2)' } })
    N.push({ id: RAG, position: { x: 1180, y: 150 }, data: { label: '🧠 Core RAG\n(content_embeddings)' }, style: { background: 'rgba(168,85,247,.12)', border: '1.5px solid #a855f7', borderRadius: 8, fontSize: 10, fontWeight: 700, width: 140, padding: 6, whiteSpace: 'pre-line', textAlign: 'center', color: 'var(--text0)' } })
    // domain column
    const domains = [...new Set(items.map(i => i.domain).filter(Boolean))].slice(0, 8)
    domains.forEach((d: any, i: number) => {
      const cred = credByDomain[d]                       // self-learning yield score colors the source
      const dc = cred == null ? '#60a5fa' : cred >= 50 ? '#22c55e' : cred >= 25 ? '#f59e0b' : '#ef4444'
      N.push({ id: 'dom_' + d, position: { x: 180, y: i * 56 + 20 }, data: { label: `${d}${cred != null ? `\n${cred}% yield` : ''}` }, style: { background: `${dc}14`, border: `1px solid ${dc}`, borderRadius: 6, fontSize: 9, width: 140, padding: 5, textAlign: 'center', color: 'var(--text1)', whiteSpace: 'pre-line' } })
      E.push({ id: 'e_sx_' + d, source: SX, target: 'dom_' + d, animated: searxUp, style: { stroke: '#22c55e', strokeWidth: 1 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#22c55e' } })
    })
    // AGENT column — the producing agent (hermes_agent_name) that moved each item between stages
    const agents = [...new Set(items.map(i => i.agent).filter(Boolean))]
    const agentSeen = new Set<string>()
    agents.forEach((a: any, i: number) => N.push({ id: 'ag_' + a, position: { x: 400, y: i * 64 + 20 }, data: { label: `🤖 ${shortAgent(a)}` }, style: { background: 'rgba(6,182,212,.12)', border: '1.5px solid #06b6d4', borderRadius: 7, fontSize: 9, fontWeight: 600, width: 150, padding: 5, textAlign: 'center', color: 'var(--text0)' } }))
    // item column (color = status)
    items.forEach((it, idx) => {
      const col = it.status === 'promoted' ? '#22c55e' : '#f59e0b'
      const nid = 'it_' + it.id
      N.push({ id: nid, position: { x: 700, y: idx * 38 + 10 }, data: { label: `${it.label}` }, style: { background: `${col}1a`, border: `1px solid ${col}`, borderRadius: 6, fontSize: 9, width: 170, padding: 4, color: 'var(--text0)', overflow: 'hidden' } })
      const origin = it.domain ? 'dom_' + it.domain : INT
      const ag = it.agent ? 'ag_' + it.agent : null
      if (ag) {
        // origin → agent (dedup), agent → item
        if (!agentSeen.has(origin + '>' + ag)) { agentSeen.add(origin + '>' + ag); E.push({ id: 'e_oa_' + idx, source: origin, target: ag, style: { stroke: 'var(--text3)', strokeWidth: 0.8, opacity: 0.45 }, markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--text3)' } }) }
        E.push({ id: 'e_ai_' + it.id, source: ag, target: nid, style: { stroke: '#06b6d4', strokeWidth: 0.9, opacity: 0.6 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#06b6d4' } })
      } else {
        E.push({ id: 'e_o_' + it.id, source: origin, target: nid, style: { stroke: 'var(--text3)', strokeWidth: 0.8, opacity: 0.45 }, markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--text3)' } })
      }
      if (it.embedded) E.push({ id: 'e_rag_' + it.id, source: nid, target: RAG, animated: true, style: { stroke: '#a855f7', strokeWidth: 1 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#a855f7' } })
    })
    return { provNodes: N, provEdges: E }
  }, [provData, searxUp, sourcesData])

  const staging = health?.staging_counts ?? {}
  const killSwitch = health?.kill_switch_active ?? false
  const autonomous = health?.autonomous_loop_active ?? false
  const slData = selfLearn ?? {}

  // VALIDATED execution footprint per contract agent (real DB rows, not the design-doc label).
  // Maps the messy real hermes_agent_name values onto the 7 contract agents.
  const byName: Record<string, any> = {}
  for (const a of (footprint?.by_agent ?? [])) byName[a.agent] = a
  const sumRows = (...names: string[]) => names.reduce((s, n) => s + (byName[n]?.rows ?? 0), 0)
  const lastOf = (...names: string[]) => names.map(n => byName[n]?.last_active).filter(Boolean).sort().slice(-1)[0] || null
  // merge active job classifications (research_type breakdown) across alias agent-names
  const clsOf = (...names: string[]) => {
    const m: Record<string, number> = {}
    for (const n of names) for (const c of (byName[n]?.classifications ?? [])) m[c.type] = (m[c.type] || 0) + c.n
    return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([type, n]) => ({ type, n }))
  }
  // Directive B (2026-06-02): the Coordinator runs these LIVE (--apply) every ~15 min — no longer dry-run.
  const LIVE = 'live (--apply via Coordinator, every ~15 min)'
  const fp: Record<string, { rows: number; last: string | null; mode: string; cls: { type: string; n: number }[] }> = {
    coordinator: { rows: footprint?.memory_events?.total ?? 0, last: footprint?.memory_events?.last_active ?? null, mode: 'orchestrates fleet every ~15 min (cron */15)', cls: [{ type: 'coordination ticks', n: footprint?.memory_events?.total ?? 0 }] },
    source_discovery: { rows: sumRows('source_discovery_agent'), last: lastOf('source_discovery_agent'), mode: LIVE, cls: clsOf('source_discovery_agent') },
    librarian: { rows: sumRows('autonomous_librarian_loop', 'expanded_librarian_agent'), last: lastOf('autonomous_librarian_loop', 'expanded_librarian_agent'), mode: LIVE, cls: clsOf('autonomous_librarian_loop', 'expanded_librarian_agent') },
    backlog: { rows: sumRows('research_backlog_manager', 'siem_backlog_generator', 'ops_alert_integration'), last: lastOf('research_backlog_manager', 'siem_backlog_generator', 'ops_alert_integration'), mode: LIVE, cls: clsOf('research_backlog_manager', 'siem_backlog_generator', 'ops_alert_integration') },
    embedding: { rows: footprint?.embedding_queue?.total ?? 0, last: footprint?.embedding_queue?.last_active ?? null, mode: `live (--apply) · ${footprint?.embedding_queue?.completed ?? 0} embedded`, cls: [{ type: 'embedding candidates', n: footprint?.embedding_queue?.total ?? 0 }] },
    promotion: { rows: footprint?.promotion_audit?.total ?? 0, last: footprint?.promotion_audit?.last_active ?? null, mode: `live · ${footprint?.promotion_audit?.approved ?? 0} promoted (auto, reversible)`, cls: [{ type: 'promotions', n: footprint?.promotion_audit?.total ?? 0 }] },
    autonomous: { rows: sumRows('ticker_research_agent', 'trade_reflection_agent'), last: lastOf('ticker_research_agent', 'trade_reflection_agent'), mode: LIVE, cls: clsOf('ticker_research_agent', 'trade_reflection_agent') },
  }
  // Effective run-state = approval-state crossed with real footprint (the honest two-axis truth).
  const effState = (a: HAgent): HState => {
    const f = fp[a.id]
    if (a.state === 'disabled') return 'disabled'
    if (a.state === 'operational') return 'operational'
    // contract says design/not-approved — but did it actually run?
    if (f && f.rows > 0 && f.mode !== 'smoke-test only') return 'running_unapproved'
    return 'designed'
  }
  const { wfNodes, wfEdges } = useMemo(() => {
    const TRADE_AI = 'trade_ai_safe'
    const nodes: any[] = HERMES_AGENTS.map(a => {
      const es = effState(a)
      const col = HSTATE_COLOR[es]
      const dim = es === 'designed' || es === 'disabled'
      const f = fp[a.id]
      const topCls = f?.cls?.[0] ? `${f.cls[0].n} ${f.cls[0].type}` : null
      const act = f && f.rows > 0 ? `${f.rows} rows${topCls ? ` · ${topCls}` : ''}` : null
      return {
        id: a.id, position: a.pos,
        data: { label: `${a.orchestrator ? '★ ' : ''}${a.label}${act ? `\n${act}` : ''}\n${HSTATE_LABEL[es]}` },
        style: {
          background: `${col}${dim ? '0d' : '1f'}`, color: 'var(--text0)', width: 182,
          border: `${a.orchestrator ? 2.5 : 1.5}px ${dim ? 'dashed' : 'solid'} ${col}`,
          borderRadius: 8, fontSize: 10, fontWeight: a.orchestrator ? 800 : 600, padding: '8px 10px',
          opacity: es === 'disabled' ? 0.5 : es === 'designed' ? 0.7 : 1, whiteSpace: 'pre-line', textAlign: 'center',
        },
      }
    })
    // External core node — the WALL: Hermes reads Trade AI safe views, never controls the core fleet.
    nodes.push({
      id: TRADE_AI, position: { x: 430, y: 410 },
      data: { label: 'Trade AI safe views\n(core fleet — read-only)' },
      style: { background: 'var(--bg2)', color: 'var(--text2)', border: '1.5px dotted var(--text3)', borderRadius: 8, fontSize: 10, padding: '8px 10px', width: 190, whiteSpace: 'pre-line', textAlign: 'center' },
    })
    // SearXNG infra node (idea A) — the Docker web-search service feeding Source Discovery
    const SEARX = 'searxng'
    const sxCol = searxUp ? '#22c55e' : '#ef4444'
    nodes.push({
      id: SEARX, position: { x: -150, y: 150 },
      data: { label: `🔎 SearXNG (Docker :18888)\n${searxUp ? 'up' : 'DOWN'}` },
      style: { background: `${sxCol}1a`, color: 'var(--text0)', border: `1.5px solid ${sxCol}`, borderRadius: 8, fontSize: 10, fontWeight: 600, padding: '8px 10px', width: 160, whiteSpace: 'pre-line', textAlign: 'center' },
    })
    const ids = new Set(HERMES_AGENTS.map(a => a.id))
    const edges: any[] = []
    // SearXNG → Source Discovery (web search feed)
    edges.push({ id: 'searx_sd', source: SEARX, target: 'source_discovery', animated: searxUp,
      label: 'web search', labelStyle: { fontSize: 8, fill: sxCol }, labelBgStyle: { fill: 'var(--bg1)' },
      style: { stroke: sxCol, strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: sxCol } })
    // configured handoffs (dashed, NOT animated — most agents aren't live)
    HERMES_AGENTS.forEach(a => a.targets.forEach(t => {
      if (!ids.has(t)) return
      const orch = !!a.orchestrator
      edges.push({
        id: `cfg_${a.id}_${t}`, source: a.id, target: t, animated: false,
        label: orch ? 'orchestrates' : 'configured handoff',
        labelStyle: { fontSize: 8, fill: 'var(--text3)' }, labelBgStyle: { fill: 'var(--bg1)' },
        style: { stroke: 'var(--text3)', strokeWidth: 1, strokeDasharray: orch ? '2 3' : '5 4', opacity: 0.55 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--text3)' },
      })
    }))
    // THE WALL: one-way READ arrow from core → hermes (data flows out of core, read-only). Never a control edge.
    HERMES_AGENTS.filter(a => a.readsTradeAI).forEach(a => edges.push({
      id: `read_${a.id}`, source: TRADE_AI, target: a.id, animated: false,
      label: 'reads (read-only)', labelStyle: { fontSize: 8, fill: '#06b6d4' }, labelBgStyle: { fill: 'var(--bg1)' },
      style: { stroke: '#06b6d4', strokeWidth: 1, strokeDasharray: '1 4', opacity: 0.6 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#06b6d4' },
    }))
    return { wfNodes: nodes, wfEdges: edges }
  }, [staging, promo, backlog, footprint, searxUp])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Hermes</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            Sidecar research desk · {staging.hermes_research_intelligence ?? 0} intelligence rows
            {killSwitch && <span style={{ color: '#ef4444', marginLeft: 8 }}>KILL SWITCH ACTIVE</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {/* Infra health strip (idea C) — services the whole fleet depends on */}
      {infraSvc.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          {infraSvc.map((s: any) => (
            <div key={s.name} title={s.detail}
              onClick={() => onDrill({ title: s.name, subtitle: s.kind, endpoint: '/api/v2/hermes/infra', rows: [s] })}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
                background: 'var(--bg1)', border: `1px solid ${s.status === 'up' ? 'rgba(34,197,94,.3)' : 'rgba(239,68,68,.4)'}` }}>
              <span style={{ width: 7, height: 7, borderRadius: 4, background: s.status === 'up' ? '#22c55e' : '#ef4444' }} />
              <span style={{ fontSize: 11, color: 'var(--text1)', fontWeight: 600 }}>{s.name}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{s.detail}</span>
            </div>
          ))}
        </div>
      )}

      {tab === 'Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Staging counts */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Staging Counts</div>
            {Object.entries(staging).map(([k, v]: [string, any]) => (
              <div key={k} onClick={() => onDrill({ title: k.replace(/_/g, ' '), subtitle: `${v} rows`, endpoint: '/api/v2/hermes/health', rows: [{ table: k, count: v }] })}
                style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <span style={{ color: 'var(--text2)', fontFamily: 'monospace' }}>{k.replace('hermes_', '')}</span>
                <span style={{ fontWeight: 600, color: v > 0 ? '#60a5fa' : 'var(--text3)' }}>{v}</span>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 12, marginTop: 10, fontSize: 10 }}>
              <span style={{ color: autonomous ? '#22c55e' : 'var(--text3)' }}>Autonomous: {autonomous ? 'ON' : 'OFF'}</span>
              <span style={{ color: killSwitch ? '#ef4444' : 'var(--text3)' }}>Kill switch: {killSwitch ? 'ACTIVE' : 'OFF'}</span>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/hermes/health</div>
          </div>

          {/* Advisory choices */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Advisory Choices</div>
            {choices ? (
              <>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>{choices.total ?? 0} total</div>
                {Object.entries(choices.counts ?? {}).map(([choice, cnt]: [string, any]) => (
                  <div key={choice} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                    <span style={{ color: 'var(--text2)' }}>{choice.replace(/_/g, ' ')}</span>
                    <span style={{ color: 'var(--text0)' }}>{cnt}</span>
                  </div>
                ))}
                {(choices.total ?? 0) === 0 && <div style={{ color: 'var(--text3)', fontSize: 11 }}>Insufficient data — no operator choices recorded yet</div>}
              </>
            ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading...</div>}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/hermes/advisory-choices</div>
          </div>

          {/* Discovery engines — research producers beyond the 7 core contract agents */}
          {(() => {
            const DISCOVERY: Record<string, string> = {
              hermes_youtube_discovery: 'YouTube — SearXNG video search → transcripts',
              catalyst_momentum_engine: 'Catalyst momentum — SearXNG news on movers',
              source_discovery_agent: 'Source discovery — new research sources',
              ticker_research_agent: 'Ticker thesis challenger',
              news_research_agent: 'News research',
            }
            const engines = (footprint?.by_agent ?? []).filter((a: any) => DISCOVERY[a.agent])
            if (engines.length === 0) return null
            return (
              <div style={{ gridColumn: '1 / -1', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Discovery Engines</div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>Active research producers (SearXNG / YouTube → staged → curation → RAG), beyond the 7 core contract agents.</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 2fr 0.6fr 0.8fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
                  <span>Engine</span><span>What it does · working on</span><span>Rows</span><span>Last run</span>
                </div>
                {engines.map((e: any) => {
                  const cls = (e.classifications ?? []).map((c: any) => `${c.type.replace(/_/g, ' ')} ${c.n}`).join(' · ')
                  return (
                    <div key={e.agent} onClick={() => onDrill({ title: e.agent, subtitle: DISCOVERY[e.agent], endpoint: '/api/v2/hermes/agent-footprint', rows: [{ ...e, classifications: cls }] })}
                      style={{ display: 'grid', gridTemplateColumns: '1.4fr 2fr 0.6fr 0.8fr', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                      <span style={{ fontFamily: 'monospace', color: 'var(--text0)', fontWeight: 600 }}>{e.agent.replace('hermes_', '').replace('_agent', '').replace('_engine', '')}</span>
                      <span style={{ color: 'var(--text3)', fontSize: 9 }}>{DISCOVERY[e.agent]}{cls && <span style={{ color: 'var(--text2)' }}> · {cls}</span>}</span>
                      <span style={{ color: '#60a5fa', fontWeight: 700 }}>{e.rows}</span>
                      <span style={{ color: 'var(--text3)', fontSize: 9 }}>{e.last_active ?? '—'}</span>
                    </div>
                  )
                })}
                <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/agent-footprint (hermes_agent_name → research_type). YouTube discovery + catalyst momentum surfaced here.</div>
              </div>
            )
          })()}
        </div>
      )}

      {tab === 'Workflow' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 10, color: 'var(--text3)', flexWrap: 'wrap' }}>
            <span>★ = Hermes Coordinator</span>
            <span><span style={{ color: '#22c55e' }}>■</span> operational (approved)</span>
            <span><span style={{ color: '#f59e0b' }}>■</span> running — NOT approved</span>
            <span><span style={{ color: '#64748b' }}>▢</span> designed — no footprint</span>
            <span><span style={{ color: '#ef4444' }}>▢</span> disabled</span>
            <span style={{ marginLeft: 'auto', color: killSwitch ? '#ef4444' : '#22c55e', fontWeight: 700 }}>
              Kill switch: {killSwitch ? 'ACTIVE' : 'OFF'} · Autonomous: {autonomous ? 'ON' : 'OFF'}
            </span>
          </div>
          <div style={{ fontSize: 10, color: '#ef4444', padding: '6px 10px', background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.3)', borderRadius: 6, fontWeight: 600 }}>
            ⚠ WALL OPENED (operator directive B, 2026-06-02): the Coordinator runs the fleet LIVE every 15 min — auto-promote + RAG embeddings now flow into the core intelligence the trading agents read. Kill switch is OFF (re-arm: <code>touch hermes_sidecar/.hermes/DISABLED</code>). Every promote/embed is audited + reversible.
          </div>
          <div style={{ fontSize: 10, color: '#f59e0b', padding: '6px 10px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)', borderRadius: 6 }}>
            Each node shows <b>approval</b> (governance) and <b>execution footprint</b> (validated DB rows) separately, plus the <b>active job classifications</b> (what it's working on) and <b>next scheduled run</b>. Post directive-B all agents run live via the Coordinator every ~15 min. Click a node for the full breakdown.
          </div>
          <div style={{ height: 540, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
            <ReactFlow
              nodes={wfNodes} edges={wfEdges} fitView proOptions={{ hideAttribution: true }}
              nodesDraggable={false} nodesConnectable={false} elementsSelectable={true}
              onNodeClick={(_e, node) => {
                const a = HERMES_AGENTS.find(x => x.id === node.id)
                if (!a) { onDrill({ title: 'Trade AI safe views', subtitle: 'core fleet — Hermes reads only', endpoint: 'architecture', rows: [{ note: 'Hermes reads Trade AI safe views (read-only). No control/write edge into the core fleet.' }] }); return }
                const f = fp[a.id]; const es = effState(a)
                onDrill({
                  title: a.label, subtitle: `${HSTATE_LABEL[es]}`,
                  endpoint: 'HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md + /api/v2/hermes/agent-footprint',
                  rows: [{
                    '— APPROVAL (governance) —': '',
                    approval_state: a.phase,
                    '— EXECUTION (validated from DB) —': '',
                    rows_written: f?.rows ?? 0,
                    active_job_classifications: (f?.cls && f.cls.length) ? f.cls.map(x => `${x.type}: ${x.n}`).join(' · ') : 'none yet',
                    last_active: f?.last ?? 'never',
                    run_mode: f?.rows ? f.mode : 'no runtime rows',
                    schedule: 'Coordinator cron */15 (continuous)',
                    next_run: killSwitch ? 'HALTED (kill switch active)' : '≤15 min (next Coordinator tick)',
                    effective_state: HSTATE_LABEL[es],
                    '— CONTRACT (architecture for approval) —': '',
                    mission: a.mission, allowed_reads: a.reads, allowed_writes: a.writes,
                    forbidden: a.forbidden, caps: a.caps, handoff_targets: a.targets.join(', ') || '—',
                  }],
                })
              }}
            >
              <Background color="var(--border)" gap={20} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>
            Directive B (2026-06-02): all 7 agents now live. Coordinator (cron */15) orchestrates the full fleet with auto-promote + RAG embedding writing into core intelligence; Autonomous Research Manager enabled; kill switch off but checked each tick (touch hermes_sidecar/.hermes/DISABLED to halt). Every promote/embed audited + reversible. Footprint from /api/v2/hermes/agent-footprint.
          </div>
        </div>
      )}

      {tab === 'Provenance' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Research provenance: where web research comes from (SearXNG) and how it flows into the core RAG.</div>
          {/* Funnel: SearXNG → staged → promoted → embedded */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>Research flow</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {[
                { label: 'SearXNG', sub: searxUp ? 'Docker · up' : 'DOWN', color: searxUp ? '#22c55e' : '#ef4444' },
                { label: `${infra?.funnel?.staged ?? 0}`, sub: 'staged', color: '#60a5fa' },
                { label: `${infra?.funnel?.promoted ?? 0}`, sub: 'promoted → core intel', color: '#22c55e' },
                { label: `${infra?.funnel?.embedded ?? 0}`, sub: 'embedded → RAG', color: '#a855f7' },
              ].map((s, i, arr) => (
                <div key={s.sub} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ textAlign: 'center', padding: '10px 16px', borderRadius: 8, background: `${s.color}1a`, border: `1px solid ${s.color}` }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: s.color }}>{s.label}</div>
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{s.sub}</div>
                  </div>
                  {i < arr.length - 1 && <span style={{ color: 'var(--text3)', fontSize: 16 }}>→</span>}
                </div>
              ))}
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 10 }}>SearXNG web search → staged research → auto-promote (directive B) into core intelligence → RAG embeddings the core agents read. Source: /api/v2/hermes/infra</div>
          </div>
          {/* Full node-graph provenance lane — trace each research item from source → RAG */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Provenance lane — each research item traced source → RAG</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>🔎 source → <span style={{ color: '#06b6d4' }}>🤖 agent</span> → item (<span style={{ color: '#f59e0b' }}>■</span>staged <span style={{ color: '#22c55e' }}>■</span>promoted) → <span style={{ color: '#a855f7' }}>🧠 RAG</span> · recent {provNodes.filter((n: any) => n.id.startsWith('it_')).length}</div>
            </div>
            <div style={{ height: 560, border: '1px solid var(--border)', borderRadius: 8 }}>
              {provNodes.length === 0 ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text3)', fontSize: 12 }}>No research items to trace yet.</div>
              ) : (
                <ReactFlow nodes={provNodes} edges={provEdges} fitView proOptions={{ hideAttribution: true }}
                  nodesDraggable={false} nodesConnectable={false} elementsSelectable={true}
                  onNodeClick={(_e, node) => {
                    const it = (provData?.items ?? []).find((x: any) => 'it_' + x.id === node.id)
                    if (it) onDrill({ title: it.label, subtitle: `${it.status} · ${it.type ?? ''}`, endpoint: '/api/v2/hermes/provenance',
                      rows: [{ research_id: it.id, status: it.status, type: it.type, produced_by: it.agent, web_source: it.domain ?? 'internal (self-generated)', embedded_to_rag: it.embedded }] })
                  }}>
                  <Background color="var(--border)" gap={20} />
                  <Controls showInteractive={false} />
                </ReactFlow>
              )}
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Lane: SearXNG/Internal → source domain → research item (color=status) → Core RAG (purple edge if embedded). Click an item for full provenance. Source: /api/v2/hermes/provenance</div>
          </div>
          {/* Top web-source domains */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Top web sources (what SearXNG is pulling)</div>
            {(infra?.source_domains ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No source URLs captured yet.</div> :
              (infra?.source_domains ?? []).map((d: any) => {
                const max = Math.max(...(infra?.source_domains ?? []).map((x: any) => x.n), 1)
                return (
                  <div key={d.domain} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                    <div style={{ width: 160, fontSize: 11, color: 'var(--text1)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.domain}</div>
                    <div style={{ flex: 1, height: 12, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${d.n / max * 100}%`, background: '#60a5fa' }} />
                    </div>
                    <div style={{ width: 28, fontSize: 10, color: 'var(--text3)', textAlign: 'right' }}>{d.n}</div>
                  </div>
                )
              })}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Domains parsed from hermes_research_intelligence.source_urls_json. Click a finding in Research to see its specific sources.</div>
          </div>
        </div>
      )}

      {tab === 'Sources' && (() => {
        const srcs: any[] = sourcesData?.sources ?? []
        const connectors = srcs.filter(s => s.type !== 'web')
        const web = srcs.filter(s => s.type === 'web').sort((a, b) => Number(b.credibility) - Number(a.credibility))
        const credColor = (c: number) => c >= 50 ? '#22c55e' : c >= 25 ? '#f59e0b' : '#ef4444'
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>Self-learning source registry — connectors (where research can come from) + web domains scored by yield. Curated nightly by <code>hermes_source_curation.py</code>.</div>
            {/* Connectors */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Connectors ({connectors.filter(c => c.active).length} active / {connectors.length})</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 10 }}>
                {connectors.map(s => (
                  <div key={s.type} onClick={() => onDrill({ title: s.name, subtitle: s.type, endpoint: '/api/v2/hermes/sources', rows: [s] })}
                    style={{ padding: '10px 12px', borderRadius: 8, cursor: 'pointer', background: 'var(--bg2)', border: `1px solid ${s.active ? 'rgba(34,197,94,.3)' : 'rgba(100,116,139,.3)'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{s.name}</span>
                      <span style={{ fontSize: 8, padding: '1px 6px', borderRadius: 3, fontWeight: 700, background: s.active ? 'rgba(34,197,94,.15)' : 'rgba(100,116,139,.15)', color: s.active ? '#22c55e' : 'var(--text3)' }}>{s.active ? 'ACTIVE' : 'DORMANT'}</span>
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>{s.notes}</div>
                  </div>
                ))}
              </div>
            </div>
            {/* Web domains scored by yield (Track A) */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Web sources — learned yield ({web.filter(w => w.active).length} preferred / {web.length})</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>Yield = (promoted+embedded) ÷ research produced. Preferred ≥30% (boosted in future queries); low-yield = candidate/noise.</div>
              {web.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No web sources scored yet.</div> :
                web.map(s => (
                  <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 4px', borderBottom: '1px solid var(--border-subtle)' }}>
                    <span style={{ width: 170, fontSize: 11, color: 'var(--text1)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                    <div style={{ flex: 1, height: 10, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.max(2, Number(s.credibility))}%`, background: credColor(Number(s.credibility)) }} />
                    </div>
                    <span style={{ width: 42, fontSize: 10, color: credColor(Number(s.credibility)), textAlign: 'right', fontWeight: 600 }}>{Number(s.credibility)}%</span>
                    <span style={{ width: 70, fontSize: 8, color: s.active ? '#22c55e' : 'var(--text3)', textAlign: 'right' }}>{s.active ? 'preferred' : 'candidate'}</span>
                  </div>
                ))}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/sources · scored by hermes_source_curation.py (Tracks A + B). New domains auto-discovered as candidates.</div>
            </div>
          </div>
        )
      })()}

      {tab === 'Research' && backlog && (() => {
        const raw = backlog.items ?? []
        // de-dupe identical findings (the raw feed repeats them) + sort by severity
        const seen = new Set<string>(); const items: any[] = []
        for (const it of raw) { const key = (it.topic || it.symbol || '') + '|' + (it.status || ''); if (seen.has(key)) continue; seen.add(key); items.push(it) }
        const sevRank = { critical: 0, warning: 1, info: 2 } as any
        const described = items.map(it => ({ it, d: describeFinding(it) })).sort((a, b) => sevRank[a.d.severity] - sevRank[b.d.severity])
        const counts = described.reduce((m: any, x) => { m[x.d.severity] = (m[x.d.severity] || 0) + 1; return m }, {})
        return (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Research Backlog — what Hermes wants fixed ({described.length})</div>
              <div style={{ fontSize: 10, display: 'flex', gap: 10 }}>
                {counts.critical ? <span style={{ color: SEV_COLOR.critical }}>● {counts.critical} critical</span> : null}
                {counts.warning ? <span style={{ color: SEV_COLOR.warning }}>● {counts.warning} warning</span> : null}
                {counts.info ? <span style={{ color: SEV_COLOR.info }}>● {counts.info} info</span> : null}
              </div>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
              Advisory only — Hermes flags issues, it does not run or fix them autonomously (no auto-research, by design). Each card says what's wrong and where you'd resolve it. Status <b>staged</b> = recorded for review; not yet acted on.
            </div>
            {described.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No backlog items</div> :
              described.map(({ it, d }, i: number) => (
                <div key={i} onClick={() => onDrill({ title: d.title, subtitle: d.where ? `Resolve in ${d.where}` : 'advisory finding', endpoint: '/api/v2/hermes/research-backlog', rows: [{ finding: d.title, severity: d.severity, detail: d.meaning, suggested_resolution: d.resolve, where_to_resolve: d.where ?? '—', status: it.status, raw_topic: it.topic }] })}
                  style={{ display: 'flex', gap: 10, padding: '10px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer', alignItems: 'flex-start' }}>
                  <span style={{ width: 7, height: 7, borderRadius: 4, background: SEV_COLOR[d.severity], marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{d.title}
                      <span style={{ marginLeft: 8, fontSize: 8, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: 'var(--text3)', textTransform: 'uppercase' }}>{it.status}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 2 }}>{d.meaning}</div>
                    <div style={{ fontSize: 10, color: SEV_COLOR[d.severity], marginTop: 3 }}>→ {d.resolve}{d.where ? <span style={{ color: 'var(--text3)' }}>  ·  {d.where}</span> : null}</div>
                    {(() => { const dom = domainsOf(it.source_urls_json); return dom.length ? <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>🔎 sources: {dom.slice(0, 4).join(', ')}{dom.length > 4 ? ` +${dom.length - 4}` : ''}</div> : null })()}
                  </div>
                </div>
              ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/research-backlog · {raw.length - described.length} duplicate(s) collapsed · sorted by severity</div>
          </div>
        )
      })()}

      {tab === 'Dual Opinion' && dualOp && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Dual Opinion Advisory ({dualOp.total ?? 0})</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 12 }}>
            {[{l:'Agrees',v:dualOp.agrees,c:'#22c55e'},{l:'Caution',v:dualOp.agrees_with_caution,c:'#f59e0b'},{l:'Needs Evidence',v:dualOp.needs_more_evidence,c:'#60a5fa'},{l:'Disagrees',v:dualOp.disagrees,c:'#ef4444'}].map(k => (
              <div key={k.l} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: k.c }}>{k.v ?? 0}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.l}</div>
              </div>
            ))}
          </div>
          {(dualOp.opinions ?? []).slice(0, 8).map((op: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: op.symbol ?? `Opinion ${i}`, subtitle: op.verdict ?? '', endpoint: '/api/v2/hermes/dual-opinion', rows: [op] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{op.symbol ?? ''}</span>
              <span style={{ marginLeft: 8, color: op.verdict === 'AGREE' ? '#22c55e' : op.verdict === 'DISAGREE' ? '#ef4444' : '#f59e0b' }}>{op.verdict ?? '—'}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/dual-opinion</div>
        </div>
      )}

      {tab === 'Pipeline' && pipeQual && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Pipeline Quality ({pipeQual.total ?? 0} findings)</div>
          {pipeQual.advisory_notice && <div style={{ fontSize: 9, color: '#f59e0b', marginBottom: 8 }}>{pipeQual.advisory_notice}</div>}
          {(pipeQual.findings ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No quality findings</div> :
          (pipeQual.findings ?? []).slice(0, 10).map((f: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: f.finding_type ?? `Finding ${i}`, subtitle: f.severity ?? '', endpoint: '/api/v2/hermes/pipeline-quality', rows: [f] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ color: f.severity === 'critical' ? '#ef4444' : f.severity === 'warning' ? '#f59e0b' : 'var(--text2)' }}>{f.severity ?? '—'}</span>
              <span style={{ marginLeft: 8, color: 'var(--text0)' }}>{f.finding_type ?? ''}</span>
              <span style={{ marginLeft: 8, color: 'var(--text3)', fontSize: 9 }}>{f.symbol ?? ''}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/pipeline-quality</div>
        </div>
      )}
    </div>
  )
}
