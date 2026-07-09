import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import type { DrillContext } from '../components/DetailDrawer'
import HermesSoulEditor, { PROFILE_LABELS } from '../components/HermesSoulEditor'
import { EvidenceBlock } from '../components/EvidenceBlock'
import HermesClosedLoopPanel from '../components/HermesClosedLoopPanel'
import HermesDiscoveryInbox from '../components/HermesDiscoveryInbox'
import PrivateProxyCard from '../components/PrivateProxyCard'

interface Props { onDrill: (ctx: DrillContext) => void }
const FLEETS = ['Research Fleet', 'Momentum Scalp Swarm'] as const
// Operator-first order: triage tabs before registry/debug tabs.
const TABS = ['Overview', 'Research', 'Closed Loop', 'Maturity', 'Discovery', 'Workflow', 'Sources', 'Provenance', 'Pipeline', 'Dual Opinion', 'Proxy Cards'] as const
const REGISTRY_TABS = new Set(['Sources', 'Provenance', 'Pipeline', 'Proxy Cards', 'Dual Opinion'])
const SCALP_TABS = ['Overview', 'Workflow', 'Getting Started'] as const

const MATURITY_COLOR: Record<string, string> = {
  full: '#22c55e', mostly: '#84cc16', semi: '#f59e0b', manual: '#ef4444',
}
const GAP_SEV_COLOR: Record<string, string> = { critical: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }

// Ground truth: HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md (Drive 2026-05-31).
// state is run-state, the most important honest encoding: operational vs designed vs disabled vs live_data(doc-mismatch).
type HState = 'operational' | 'designed' | 'disabled' | 'live_data' | 'running_unapproved' | 'idle' | 'dormant'
interface HAgent {
  id: string; label: string; state: HState; phase: string; mission: string;
  reads: string; writes: string; forbidden: string; caps: string;
  targets: string[]; pos: { x: number; y: number }; orchestrator?: boolean; readsTradeAI?: boolean;
}
const HERMES_AGENTS: HAgent[] = [
  { id: 'coordinator', label: 'Chief Hermes Coordinator', state: 'operational', phase: 'BUILT + OPERATIONAL — 24/7 cron */15 (conscious research + fleet live)', orchestrator: true,
    mission: 'Orchestrate continuous research curation, enforce caps, route tasks', reads: 'All hermes_* tables, Trade AI safe views, SearXNG health',
    writes: 'hermes_memory_events (coordination logs only)', forbidden: 'Trade, promote, embed, mutate proposals/trades/journal/holdings, broker',
    caps: 'Bounded per tick; kill switch halts next tick', targets: ['research_curator', 'source_discovery', 'librarian', 'backlog', 'promotion'], pos: { x: 430, y: 0 }, readsTradeAI: true },
  { id: 'research_curator', label: '24/7 Research Curator', state: 'operational', phase: 'OPERATIONAL — every coordinator tick (*/15, 24/7)',
    mission: 'Sector+industry universe, signals, prospects → watchlist; momentum scalp leads beyond Finviz → incubator', reads: 'finviz_group_performance, scalp_scan_results, trade_ai_scans, market_quotes, intelligence_entities, incubator_universe, hermes_research, news, enrichment, SearXNG',
    writes: 'watch_directives, topic_monitor, incubator_universe (momentum_scalp), research_critique_latest.json, hermes_consciousness_latest.json', forbidden: 'Trade, broker, operator approval gates',
    caps: '12 universe/tick · 8 scalp leads/tick · librarian+taxonomy score each batch · tagger hourly', targets: ['source_discovery', 'librarian'], pos: { x: 250, y: 70 }, readsTradeAI: true },
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
  { id: 'backlog', label: 'Research Backlog Manager', state: 'operational', phase: 'AUTONOMOUS — backlog_drain_agent (Coordinator */15)',
    mission: 'File backlog findings + drain staged items into LLM research (archives parent)', reads: 'hermes_research_intelligence, hermes_validation_findings, hermes_alerts, alert_events',
    writes: 'hermes_research_intelligence (research_backlog + backlog_resolution)', forbidden: 'Embed, promote, mutate core, broker, send messages',
    caps: '2 drains/tick · 10 backlog files/day', targets: ['source_discovery', 'librarian'], pos: { x: 660, y: 250 } },
  { id: 'autonomous', label: 'Autonomous Research Manager', state: 'operational', phase: 'ENABLED — directive B 2026-06-02 (live under caps + kill switch)',
    mission: 'Schedule autonomous source discovery (when approved)', reads: 'hermes_research_intelligence, SearXNG, Trade AI safe views',
    writes: 'hermes_research_intelligence (staged, when approved)', forbidden: 'Embed, promote, mutate core, broker',
    caps: '2 rows/run (when approved)', targets: ['librarian'], pos: { x: 110, y: 280 } },
]
// Multi-Hermes Momentum Scalp swarm — docs/hermes/momentum_scalp_swarm/
const SCALP_HERMES_AGENTS: HAgent[] = [
  { id: 'scalp_orchestrator', label: 'Hermes Orchestrator', state: 'designed', phase: 'PHASE 1 — Orchestrator + Live Monitor (paper 4.4→4.5)', orchestrator: true,
    mission: 'Central state manager, policy gatekeeper, routes tasks, Telegram HITL via OpenClaw', reads: 'state/momentum_scalp/*, scalp_stop_monitor, portfolio heat, regime_state',
    writes: 'orchestrator_audit.json, pending_approvals.json', forbidden: 'Broker writes, auto-entries without approval, violate L2 breakeven',
    caps: 'All material actions require Telegram approval', targets: ['signal_scout', 'entry_validation', 'live_monitor', 'stop_adjustment', 'exit_intelligence', 'post_trade_review'], pos: { x: 400, y: 0 }, readsTradeAI: true },
  { id: 'signal_scout', label: 'Signal Scout Agent', state: 'designed', phase: 'PHASE 2 — hermes_scalp_signal_scout.py (45s)',
    mission: 'Detect/qualify momentum + social signals; freshness SLA; conviction score', reads: 'scalp_scan_results, social_route signals, finviz, incubator_universe',
    writes: 'qualified_signals queue (via orchestrator)', forbidden: 'Direct entries, broker, bypass orchestrator',
    caps: 'Freshness SLA ≥45s for pure scalp', targets: ['scalp_orchestrator'], pos: { x: 80, y: 90 }, readsTradeAI: true },
  { id: 'entry_validation', label: 'Entry Validation Agent', state: 'designed', phase: 'PHASE 2 — hermes_scalp_entry_validation.py (60s)',
    mission: 'Final validation before scalp acceptance; Layer 1 structure+ATR hybrid; max 1.2R', reads: 'open_scalps.json, portfolio_heat.json, momentum_scalp.yaml',
    writes: 'journal entry + planned stop record (via approval)', forbidden: 'Entries when heat kill active, risk >1.2R, stale freshness',
    caps: 'Reject if portfolio heat >3.5%', targets: ['scalp_orchestrator'], pos: { x: 200, y: 200 }, readsTradeAI: true },
  { id: 'live_monitor', label: 'Live Monitor Agent', state: 'designed', phase: 'PHASE 1 — persistent daemon (hermes_scalp_live_monitor.py)',
    mission: 'Always-on open scalp monitoring; regime detection; dynamic stoplight Y/A/R', reads: 'paper_trades, scalp_stop_monitor, symbol_regime_state, pro_analyst_pills',
    writes: 'open_scalps.json, stoplight_status.json, regime_state.json, portfolio_heat.json', forbidden: 'Broker writes, unapproved stop mutations',
    caps: '30s scan interval', targets: ['scalp_orchestrator', 'stop_adjustment'], pos: { x: 400, y: 160 }, readsTradeAI: true },
  { id: 'stop_adjustment', label: 'Stop Adjustment Agent', state: 'designed', phase: 'PHASE 1 — with Live Monitor',
    mission: 'Layer 4 stop adjustments: regime shift, heat, freshness decay; full audit history', reads: 'stoplight_status.json, regime_state.json, stop policy',
    writes: 'stop_adjustment_history.json, paper_trades.current_stop (approval-gated)', forbidden: 'Trail before breakeven secured, broker orders',
    caps: 'Every change cites policy §section', targets: ['scalp_orchestrator'], pos: { x: 580, y: 200 } },
  { id: 'exit_intelligence', label: 'Exit Intelligence Agent', state: 'designed', phase: 'PHASE 3 — hermes_scalp_exit_intelligence.py (60s)',
    mission: 'Profit extension vs Street consensus; partial take + trail tighten suggestions', reads: 'pro_analyst_pills_latest.json, stoplight_status, open_scalps',
    writes: 'exit suggestions (via orchestrator)', forbidden: 'Auto-exits without approval',
    caps: 'Works with Stop Adjustment Agent', targets: ['stop_adjustment', 'scalp_orchestrator'], pos: { x: 720, y: 90 }, readsTradeAI: true },
  { id: 'post_trade_review', label: 'Post-Trade Review Agent', state: 'designed', phase: 'PHASE 3 — hermes_scalp_post_trade_review.py (300s)',
    mission: 'AI Trade Critique on closed scalps; 4 stop-quality questions; validation tracker', reads: 'paper_trades closed, replay, validation_tracker.json',
    writes: 'validation_tracker.json, critique feedback loop', forbidden: 'Mutate open trades',
    caps: 'Every closed scalp gets critique', targets: ['scalp_orchestrator'], pos: { x: 400, y: 320 }, readsTradeAI: true },
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
const HSTATE_COLOR: Record<HState, string> = { operational: '#22c55e', live_data: '#06b6d4', running_unapproved: '#f59e0b', designed: '#64748b', disabled: '#ef4444', idle: '#f59e0b', dormant: '#ef4444' }
const HSTATE_LABEL: Record<HState, string> = { operational: 'operational (live)', live_data: 'live data', running_unapproved: 'running — NOT approved', designed: 'designed — no footprint', disabled: 'disabled — not approved', idle: 'idle — ran recently', dormant: 'DORMANT — no recent output' }

export default function HermesHub({ onDrill }: Props) {
  const [fleet, setFleet] = useState<typeof FLEETS[number]>('Research Fleet')
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const [scalpTab, setScalpTab] = useState<typeof SCALP_TABS[number]>('Overview')
  const { data: health } = useApi<any>('/api/v2/hermes/health', 120_000)
  const { data: scalpSwarm } = useApi<any>('/api/v2/hermes/scalp-swarm/status', 60_000)
  const { data: selfLearn } = useApi<any>('/api/v2/hermes/self-learning-overview', 120_000)
  const { data: choices } = useApi<any>('/api/v2/hermes/advisory-choices', 120_000)
  const { data: backlog } = useApi<any>('/api/v2/hermes/research-backlog', 120_000)
  const { data: dualOp } = useApi<any>('/api/v2/hermes/dual-opinion', 120_000)
  const { data: pipeQual } = useApi<any>('/api/v2/hermes/pipeline-quality', 120_000)
  const { data: maturity } = useApi<any>('/api/v2/hermes/maturity-dashboard', 120_000)
  const { data: promo } = useApi<any>('/api/v2/hermes/promotion-review', 120_000)
  const { data: footprint } = useApi<any>('/api/v2/hermes/agent-footprint', 120_000)
  const { data: runstate } = useApi<any>('/api/v2/hermes/agent-runstate', 60_000)
  const { data: infra } = useApi<any>('/api/v2/hermes/infra', 60_000)
  const { data: provData } = useApi<any>('/api/v2/hermes/provenance', 60_000)
  const { data: sourcesData } = useApi<any>('/api/v2/hermes/sources', 120_000)
  const { data: profStatus } = useApi<any>('/api/v2/hermes/profiles-status', 120_000)
  const [editProfile, setEditProfile] = useState<string | null>(null)
  const [profilesOpen, setProfilesOpen] = useState(false)
  const [sourcesView, setSourcesView] = useState<'ops' | 'full'>('ops')
  const linkStyle: React.CSSProperties = { fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }
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
  // live run-state (real evidence) WINS over the static contract label — a dormant agent must not show 'operational'
  const liveById: Record<string, { live_state: string; last_active_h: number | null }> =
    Object.fromEntries(((runstate?.agents) || []).map((r: any) => [r.id, r]))
  const effState = (a: HAgent): HState => {
    const live = liveById[a.id]?.live_state
    if (live) {
      if (live === 'live') return 'operational'
      if (live === 'idle') return 'idle'
      if (live === 'dormant' || live === 'fleet_down') return 'dormant'
    }
    const f = fp[a.id]
    if (a.state === 'disabled') return 'disabled'
    if (a.state === 'operational') return 'operational'
    if (f && f.rows > 0 && f.mode !== 'smoke-test only') return 'running_unapproved'
    return 'designed'
  }
  const lastActiveLabel = (a: HAgent): string => {
    const h = liveById[a.id]?.last_active_h
    if (h == null) return ''
    return h < 1 ? `${Math.round(h * 60)}m ago` : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`
  }
  const scalpLiveById: Record<string, { live_state: string }> =
    Object.fromEntries((scalpSwarm?.agents || []).map((r: any) => [r.id, r]))
  const scalpEffState = (a: HAgent): HState => {
    const live = scalpLiveById[a.id]?.live_state
    if (live === 'live') return 'operational'
    if (live === 'idle') return 'idle'
    if (live === 'dormant') return 'dormant'
    return a.state
  }
  const { scalpWfNodes, scalpWfEdges } = useMemo(() => {
    const TRADE_AI = 'trade_ai_safe'
    const STATE_LAYER = 'swarm_state'
    const nodes: any[] = SCALP_HERMES_AGENTS.map(a => {
      const es = scalpEffState(a)
      const col = HSTATE_COLOR[es]
      const dim = es === 'designed' || es === 'disabled'
      return {
        id: a.id, position: a.pos,
        data: { label: `${a.orchestrator ? '★ ' : ''}${a.label}\n${HSTATE_LABEL[es]}` },
        style: {
          background: `${col}${dim ? '0d' : '1f'}`, color: 'var(--text0)', width: 182,
          border: `${a.orchestrator ? 2.5 : 1.5}px ${dim ? 'dashed' : 'solid'} ${col}`,
          borderRadius: 8, fontSize: 10, fontWeight: a.orchestrator ? 800 : 600, padding: '8px 10px',
          opacity: es === 'disabled' ? 0.5 : es === 'designed' ? 0.75 : 1, whiteSpace: 'pre-line', textAlign: 'center',
        },
      }
    })
    nodes.push({
      id: TRADE_AI, position: { x: 400, y: 420 },
      data: { label: 'Trade AI v12\n(paper_trades, journal, replay)' },
      style: { background: 'var(--bg2)', color: 'var(--text2)', border: '1.5px dotted var(--text3)', borderRadius: 8, fontSize: 10, padding: '8px 10px', width: 190, whiteSpace: 'pre-line', textAlign: 'center' },
    })
    nodes.push({
      id: STATE_LAYER, position: { x: 120, y: 420 },
      data: { label: 'state/momentum_scalp/\n(JSON shared state)' },
      style: { background: 'rgba(168,85,247,.1)', color: 'var(--text1)', border: '1.5px solid #a855f7', borderRadius: 8, fontSize: 10, padding: '8px 10px', width: 170, whiteSpace: 'pre-line', textAlign: 'center' },
    })
    nodes.push({
      id: 'telegram_hitl', position: { x: 680, y: 420 },
      data: { label: 'Telegram / OpenClaw\n(human-in-the-loop)' },
      style: { background: 'rgba(6,182,212,.1)', color: 'var(--text1)', border: '1.5px solid #06b6d4', borderRadius: 8, fontSize: 10, padding: '8px 10px', width: 170, whiteSpace: 'pre-line', textAlign: 'center' },
    })
    const ids = new Set(SCALP_HERMES_AGENTS.map(a => a.id))
    const edges: any[] = []
    SCALP_HERMES_AGENTS.forEach(a => a.targets.forEach(t => {
      if (!ids.has(t)) return
      edges.push({
        id: `scalp_${a.id}_${t}`, source: a.id, target: t, animated: scalpEffState(a) === 'operational',
        label: a.orchestrator ? 'orchestrates' : 'routes',
        labelStyle: { fontSize: 8, fill: 'var(--text3)' }, labelBgStyle: { fill: 'var(--bg1)' },
        style: { stroke: a.orchestrator ? '#a855f7' : 'var(--text3)', strokeWidth: 1, strokeDasharray: a.orchestrator ? '2 3' : '5 4', opacity: 0.65 },
        markerEnd: { type: MarkerType.ArrowClosed, color: a.orchestrator ? '#a855f7' : 'var(--text3)' },
      })
    }))
    SCALP_HERMES_AGENTS.filter(a => a.readsTradeAI).forEach(a => edges.push({
      id: `scalp_read_${a.id}`, source: TRADE_AI, target: a.id, animated: false,
      label: 'reads', labelStyle: { fontSize: 8, fill: '#06b6d4' }, labelBgStyle: { fill: 'var(--bg1)' },
      style: { stroke: '#06b6d4', strokeWidth: 1, strokeDasharray: '1 4', opacity: 0.6 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#06b6d4' },
    }))
    ;['live_monitor', 'stop_adjustment', 'scalp_orchestrator'].forEach(aid => edges.push({
      id: `scalp_state_${aid}`, source: STATE_LAYER, target: aid, animated: false,
      label: 'state R/W', labelStyle: { fontSize: 8, fill: '#a855f7' }, labelBgStyle: { fill: 'var(--bg1)' },
      style: { stroke: '#a855f7', strokeWidth: 1, strokeDasharray: '3 3', opacity: 0.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#a855f7' },
    }))
    edges.push({
      id: 'scalp_tg_orch', source: 'telegram_hitl', target: 'scalp_orchestrator', animated: false,
      label: 'approvals', labelStyle: { fontSize: 8, fill: '#06b6d4' }, labelBgStyle: { fill: 'var(--bg1)' },
      style: { stroke: '#06b6d4', strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#06b6d4' },
    })
    return { scalpWfNodes: nodes, scalpWfEdges: edges }
  }, [scalpSwarm])

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
        data: { label: `${a.orchestrator ? '★ ' : ''}${a.label}${act ? `\n${act}` : ''}\n${HSTATE_LABEL[es]}${lastActiveLabel(a) ? ` · ${lastActiveLabel(a)}` : ''}` },
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
  }, [staging, promo, backlog, footprint, searxUp, runstate])

  const isScalp = fleet === 'Momentum Scalp Swarm'
  const activeTabs = isScalp ? SCALP_TABS : TABS
  const activeTab = isScalp ? scalpTab : tab
  const setActiveTab = isScalp ? setScalpTab : setTab

  return (
    <div>
      {editProfile && <HermesSoulEditor profile={editProfile} onClose={() => setEditProfile(null)} />}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {FLEETS.map(f => (
          <button key={f} onClick={() => { setFleet(f); setActiveTab('Overview' as any) }} style={{
            padding: '6px 14px', fontSize: 12, borderRadius: 6, cursor: 'pointer', fontWeight: fleet === f ? 700 : 500,
            background: fleet === f ? (f.includes('Scalp') ? 'rgba(168,85,247,.15)' : 'rgba(96,165,250,.15)') : 'var(--bg2)',
            color: fleet === f ? (f.includes('Scalp') ? '#a855f7' : '#60a5fa') : 'var(--text3)',
            border: `1px solid ${fleet === f ? (f.includes('Scalp') ? 'rgba(168,85,247,.4)' : 'rgba(96,165,250,.4)') : 'var(--border)'}`,
          }}>{f}</button>
        ))}
      </div>
      <div className="hub-title-row">
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>
            {isScalp ? 'Hermes Momentum Scalp Swarm' : 'Hermes Research Agent Graph'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {isScalp ? (
              <>Paper phase 4.4→4.5 · policy-enforcing stop lifecycle · {scalpSwarm?.pending_approvals ?? 0} pending approvals
                · heat {scalpSwarm?.portfolio_heat?.aggregate_open_risk_pct ?? '—'}%</>
            ) : (
              <>Staging → promote → RAG pipeline · {health?.rag_pipeline?.coverage_pct ?? 0}% RAG coverage
                · {staging.hermes_research_intelligence ?? 0} intelligence rows
                {killSwitch && <span style={{ color: '#ef4444', marginLeft: 8 }}>KILL SWITCH ACTIVE</span>}</>
            )}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4, maxWidth: 760 }}>
            {isScalp ? (
              <>7-agent hierarchical swarm enforcing <code>MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md</code> (4-layer stops).
                Phase 1: Orchestrator + Live Monitor + Stop Adjustment. All material actions → Telegram approval.
                Docs: <code>docs/hermes/momentum_scalp_swarm/</code></>
            ) : (
              <>Daily ROI: <b>Research</b> backlog + <b>Closed Loop</b> + <b>Maturity</b> gaps. <b>Sources</b> is registry audit (595 labels) — use ops view, not raw scroll.
                Chat profiles live under <Link to="/system?tab=hermes" style={linkStyle}>System → Hermes</Link>.</>
            )}
          </div>
          {!isScalp && (
            <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
              <Link to="/intelligence?tab=command" style={linkStyle}>Intelligence triage →</Link>
              <Link to="/trading?tab=Open+Trades" style={linkStyle}>Open Trades →</Link>
              <Link to="/system?tab=hermes" style={linkStyle}>System → Hermes profiles →</Link>
            </div>
          )}
        </div>
        <div className="hub-tabs">
          {activeTabs.map(t => (
            <button key={t} onClick={() => setActiveTab(t as any)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: activeTab === t ? (isScalp ? 'rgba(168,85,247,.15)' : 'rgba(96,165,250,.15)') : 'var(--bg2)',
              color: activeTab === t ? (isScalp ? '#a855f7' : '#60a5fa') : 'var(--text3)', fontWeight: activeTab === t ? 700 : 400,
              opacity: !isScalp && REGISTRY_TABS.has(t) && activeTab !== t ? 0.72 : 1,
            }}>{t}{!isScalp && REGISTRY_TABS.has(t) ? ' ◦' : ''}</button>
          ))}
        </div>
      </div>

      {/* Global Hermes Profiles — identity/SOUL editor (shared with System → Hermes) */}
      {(profStatus?.profiles?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 14 }}>
          <button onClick={() => setProfilesOpen(v => !v)} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 6, cursor: 'pointer',
            background: 'var(--bg1)', border: '1px solid var(--border)', color: 'var(--text2)', fontSize: 10,
          }}>
            <span style={{ fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>Global Hermes profiles</span>
            <span>{profStatus.profiles.length} configured · edit identity in-page or System → Hermes</span>
            <span style={{ color: 'var(--text3)' }}>{profilesOpen ? '▲' : '▼'}</span>
          </button>
          {profilesOpen && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              {profStatus.profiles.map((p: any) => (
                <button key={p.profile} onClick={() => setEditProfile(p.profile)}
                  title={`${PROFILE_LABELS[p.profile] || p.profile} · ${p.model} · tools: ${p.tools}${p.soul_hash ? ' · SOUL ' + p.soul_hash : ''}`}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                    background: 'var(--bg1)', border: '1px solid var(--border)', color: 'var(--text1)', fontSize: 11 }}>
                  <span style={{ fontWeight: 600 }}>{p.profile}</span>
                  <span style={{ fontSize: 9, color: /enabled:/.test(p.tools) ? '#f59e0b' : p.tools === 'disabled' ? '#22c55e' : 'var(--text3)' }}>{p.tools}</span>
                  <span style={{ fontSize: 9, color: '#60a5fa' }}>✎ Identity</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

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

      {isScalp && scalpTab === 'Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={{ background: 'var(--bg1)', border: '1px solid rgba(168,85,247,.3)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Swarm Status</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8 }}>
              Phase: <b>{scalpSwarm?.phase ?? '4.4_paper_validation'}</b> · Policy: 4-layer stop methodology
            </div>
            {[
              ['Portfolio heat', `${scalpSwarm?.portfolio_heat?.aggregate_open_risk_pct ?? '—'}% (${scalpSwarm?.portfolio_heat?.heat_tier ?? '—'})`],
              ['Open scalps', String(scalpSwarm?.portfolio_heat?.open_scalp_count ?? 0)],
              ['Pending approvals', String(scalpSwarm?.pending_approvals ?? 0)],
              ['Qualified signals', String(scalpSwarm?.qualified_signals ?? 0)],
              ['Validated (awaiting TG)', String(scalpSwarm?.validated_pending_approval ?? 0)],
              ['Exit suggestions', String(scalpSwarm?.exit_suggestions ?? 0)],
              ['Post-trade reviews', String(scalpSwarm?.post_trade_reviews ?? 0)],
              ['Validation gate', scalpSwarm?.validation_overall ?? '—'],
              ['Pause new entries', scalpSwarm?.portfolio_heat?.pause_new_entries ? 'YES' : 'no'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 6px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                <span style={{ color: 'var(--text2)' }}>{k}</span><span style={{ fontWeight: 600, color: 'var(--text0)' }}>{v}</span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/scalp-swarm/status</div>
          </div>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Agent Roster (7)</div>
            {SCALP_HERMES_AGENTS.map(a => {
              const es = scalpEffState(a)
              return (
                <div key={a.id} onClick={() => onDrill({
                  title: a.label, subtitle: a.phase,
                  endpoint: `docs/hermes/momentum_scalp_swarm/agents/${a.id}.md`,
                  rows: [{ mission: a.mission, reads: a.reads, writes: a.writes, forbidden: a.forbidden, caps: a.caps, state: HSTATE_LABEL[es] }],
                })} style={{ display: 'flex', gap: 8, padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: HSTATE_COLOR[es], flexShrink: 0 }} />
                  <span style={{ fontWeight: 600, color: 'var(--text0)', flex: 1 }}>{a.label}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 9 }}>{HSTATE_LABEL[es]}</span>
                </div>
              )
            })}
          </div>
          <div style={{ gridColumn: '1 / -1', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Shared State Files</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 8 }}>
              {Object.entries(scalpSwarm?.state?.files ?? {}).map(([name, meta]: [string, any]) => (
                <div key={name} style={{ padding: '8px 10px', background: 'var(--bg2)', borderRadius: 6, fontSize: 10 }}>
                  <div style={{ fontFamily: 'monospace', color: meta.exists ? '#a855f7' : 'var(--text3)' }}>{name}</div>
                  <div style={{ color: 'var(--text3)', fontSize: 9, marginTop: 2 }}>
                    {meta.exists ? `${meta.age_hours}h ago · ${meta.size_bytes}B` : 'not initialized'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {isScalp && scalpTab === 'Workflow' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 10, color: '#a855f7', padding: '6px 10px', background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.3)', borderRadius: 6, fontWeight: 600 }}>
            Paper phase 4.4→4.5: Layer 2 breakeven is mandatory. Layer 3 trailing is advisory-only (config-OFF). All entries, stop adjustments, and exits require Telegram approval via OpenClaw.
          </div>
          <div style={{ height: 520, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
            <ReactFlow nodes={scalpWfNodes} edges={scalpWfEdges} fitView proOptions={{ hideAttribution: true }}
              nodesDraggable={false} nodesConnectable={false} elementsSelectable={true}
              onNodeClick={(_e, node) => {
                const a = SCALP_HERMES_AGENTS.find(x => x.id === node.id)
                if (!a) {
                  onDrill({ title: node.data?.label?.split('\n')[0] || node.id, subtitle: 'swarm infrastructure',
                    endpoint: 'docs/hermes/momentum_scalp_swarm/MULTI_HERMES_MOMENTUM_SCALP_ARCHITECTURE.md', rows: [{ note: node.data?.label }] })
                  return
                }
                onDrill({
                  title: a.label, subtitle: a.phase,
                  endpoint: `docs/hermes/momentum_scalp_swarm/agents/${a.id}.md`,
                  rows: [{ mission: a.mission, reads: a.reads, writes: a.writes, forbidden: a.forbidden, caps: a.caps, targets: a.targets.join(', ') }],
                })
              }}>
              <Background color="var(--border)" gap={20} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </div>
      )}

      {isScalp && scalpTab === 'Getting Started' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid rgba(168,85,247,.3)', borderRadius: 10, padding: 20, maxWidth: 820 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>Phase 1 — Spin up Orchestrator + Live Monitor</div>
          <ol style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.7, paddingLeft: 20 }}>
            <li>Enable Hermes <code>tradeai12b</code> profile with file read/write tools (System → Hermes).</li>
            <li>Start tmux session: <code>./linux_launchers/hermes_scalp_swarm_tmux.sh start</code></li>
            <li>Verify API: <code>curl http://127.0.0.1:7777/api/v2/hermes/scalp-swarm/status</code></li>
            <li>Confirm shared state updates in <code>state/momentum_scalp/</code> every 30s.</li>
            <li>Open Portfolio → Stop Management — regime + stoplight columns powered by Live Monitor.</li>
            <li>Material actions queue to <code>pending_approvals.json</code> → Telegram via OpenClaw.</li>
          </ol>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 16 }}>
            Full guide: <code>docs/hermes/momentum_scalp_swarm/GETTING_STARTED.md</code> ·
            Deployment: <code>DEPLOYMENT_OPERATIONS.md</code> ·
            Validation: <code>VALIDATION_CHECKLIST.md</code>
          </div>
        </div>
      )}

      {!isScalp && tab === 'Overview' && (
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

          {/* Autonomous closure loops */}
          <div style={{ background: 'var(--bg1)', border: '1px solid rgba(34,197,94,.25)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Autonomous closure loops</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11 }}>
              {[
                ['Backlog staged', String((backlog?.items ?? []).filter((i: any) => i.status === 'staged').length || staging.hermes_research_backlog || 0), 'hermes_backlog_drain.py drains → backlog_resolution'],
                ['Embed queue', `${health?.embedding_queue?.pending ?? 0} pending · ${health?.embedding_queue?.failed ?? 0} failed (auto-retry)`, 'Coordinator resets failed → pending each tick'],
                ['RAG coverage', `${health?.rag_pipeline?.embedded ?? 0}/${health?.rag_pipeline?.promoted ?? 0} (${health?.rag_pipeline?.coverage_pct ?? 0}%)`, 'backfill_promoted + embedding worker'],
                ['Source auto-approval', `${sourcesData?.stats?.news_active ?? 0}/${sourcesData?.stats?.news_total ?? 0} news active · ${sourcesData?.stats?.vetting_pending ?? 0} queued`, 'hermes_source_auto_approval.py — no operator step'],
                ['24/7 Research Curator', 'Shared critique snapshot + API', 'research_critique_latest.json + /api/v2/hermes/research-critique consumed by Trade AI processes'],
              ].map(([k, v, hint]) => (
                <div key={k} style={{ padding: '5px 6px', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text2)' }}>{k}</span>
                    <span style={{ fontWeight: 600, color: '#22c55e' }}>{v}</span>
                  </div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>{hint}</div>
                </div>
              ))}
            </div>
            {(sourcesData?.auto_approval?.activated?.length ?? 0) > 0 && (
              <div style={{ marginTop: 10, fontSize: 9, color: 'var(--text3)' }}>
                Last auto-activation tick: {sourcesData.auto_approval.updated_at?.slice(0, 19) ?? '—'} · {sourcesData.auto_approval.activated.length} activated
              </div>
            )}
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

      {!isScalp && tab === 'Discovery' && (
        <HermesDiscoveryInbox />
      )}

      {!isScalp && tab === 'Proxy Cards' && (
        <PrivateProxyCard />
      )}

      {!isScalp && tab === 'Closed Loop' && (
        <HermesClosedLoopPanel onDrill={onDrill} />
      )}

      {!isScalp && tab === 'Workflow' && (
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
            ⚠ WALL OPENED (operator directive B, 2026-06-02): the Coordinator runs the fleet LIVE every 15 min — auto-promote + RAG embeddings now flow into the core intelligence the trading agents read. Kill switch is {killSwitch ? 'ON (halted)' : 'OFF'} (halt: <code>touch data/runtime/HERMES_DISABLED</code> · resume: <code>rm data/runtime/HERMES_DISABLED</code>). Every promote/embed is audited + reversible.
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
            Directive B (2026-06-02): all 7 agents now live. Coordinator (cron */15) orchestrates the full fleet with auto-promote + RAG embedding writing into core intelligence; Autonomous Research Manager enabled; kill switch checked each tick (touch data/runtime/HERMES_DISABLED to halt; rm to resume). Every promote/embed audited + reversible. Footprint from /api/v2/hermes/agent-footprint.
          </div>
        </div>
      )}

      {!isScalp && tab === 'Provenance' && (
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

      {!isScalp && tab === 'Sources' && (() => {
        const stats = sourcesData?.stats ?? {}
        const connectors: any[] = sourcesData?.connectors ?? []
        const newsMaturity: any[] = sourcesData?.news_maturity ?? []
        const web: any[] = sourcesData?.web ?? []
        const vettingActions: any[] = sourcesData?.vetting_actions ?? []
        const autoApproval = sourcesData?.auto_approval ?? {}
        const credColor = (c: number) => c >= 50 ? '#22c55e' : c >= 25 ? '#f59e0b' : '#ef4444'
        const tierColor = (t: string) => t === 'core' ? '#a855f7' : t === 'trusted' ? '#22c55e' : t === 'probationary' ? '#f59e0b' : t === 'demoted' ? '#ef4444' : 'var(--text3)'
        const liveConnectors = connectors.filter(c => c.active)
        const offConnectors = connectors.filter(c => !c.active)
        const candidateNews = newsMaturity.filter(n => (n.maturity_tier || 'candidate') === 'candidate')
        const opsNewsTiers = ['core', 'trusted', 'probationary', 'demoted']
        const newsByTier = (sourcesView === 'ops' ? opsNewsTiers : ['core', 'trusted', 'probationary', 'candidate', 'demoted']).map(tier => ({
          tier,
          items: newsMaturity.filter(n => (n.maturity_tier || 'candidate') === tier),
        })).filter(g => g.items.length > 0)
        const webSorted = [...web].sort((a, b) => Number(b.credibility) - Number(a.credibility))
        const webDisplay = sourcesView === 'ops'
          ? webSorted.filter(w => w.active).slice(0, 48)
          : webSorted
        const yieldBar = (c: number) => `${Math.min(100, Math.max(2, Number(c)))}%`
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
              <div style={{ fontSize: 11, color: 'var(--text3)', lineHeight: 1.45, maxWidth: 720 }}>
                Registry audit — not a trading triage board. <b>Ops view</b> shows live pipes + activated tiers + preferred web paths only.
                Full registry = 595 news labels + {offConnectors.length} OFF challenger connectors.
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {(['ops', 'full'] as const).map(v => (
                  <button key={v} onClick={() => setSourcesView(v)} style={{
                    padding: '5px 12px', fontSize: 10, borderRadius: 6, cursor: 'pointer', fontWeight: v === sourcesView ? 800 : 600,
                    background: v === sourcesView ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
                    color: v === sourcesView ? '#60a5fa' : 'var(--text3)',
                    border: `1px solid ${v === sourcesView ? 'rgba(96,165,250,.35)' : 'var(--border)'}`,
                  }}>{v === 'ops' ? 'Ops view' : 'Full registry'}</button>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 10 }}>
              {[
                [`Live connectors`, `${stats.connectors_active ?? 0}/${stats.connectors_total ?? 0}`],
                [`Activated news`, `${stats.news_active ?? 0}/${stats.news_total ?? 0}`],
                [`Preferred web`, `${stats.web_preferred ?? 0}/${stats.web_total ?? 0}`],
                [`Linked news→web`, String(stats.news_linked_to_preferred_web ?? 0)],
                [`Auto-pending`, String(stats.vetting_pending ?? vettingActions.length)],
                [`Auto-activated`, String(stats.auto_activated_total ?? 0)],
              ].map(([k, v]) => (
                <span key={k} style={{ padding: '4px 10px', borderRadius: 6, background: 'var(--bg2)', border: '1px solid var(--border)', color: 'var(--text2)' }}>
                  <b style={{ color: 'var(--text0)' }}>{k}</b> · {v}
                </span>
              ))}
            </div>
            {/* Autonomous source activation audit */}
            <div style={{ background: 'var(--bg1)', border: '1px solid rgba(34,197,94,.25)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Autonomous source activation</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
                <code>hermes_source_auto_approval.py</code> activates core/trusted news sources when maturity thresholds pass (LLM for borderline trusted). Pending queue: {vettingActions.length}.
              </div>
              {(autoApproval.activated?.length ?? 0) > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 140, overflow: 'auto' }}>
                  {autoApproval.activated.slice(0, 12).map((a: any, i: number) => (
                    <div key={`${a.source}-${i}`} style={{ display: 'flex', gap: 8, fontSize: 10, padding: '4px 6px', background: 'var(--bg2)', borderRadius: 5 }}>
                      <span style={{ flex: 1, color: 'var(--text0)', fontWeight: 600 }}>{a.source?.replace(/^google_news:/, 'GN:')}</span>
                      <span style={{ color: '#22c55e' }}>{a.approval_reason || a.action}</span>
                      <span style={{ color: 'var(--text3)' }}>{a.score}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 10, color: 'var(--text3)' }}>No auto-activation audit yet — runs on Coordinator tick + daily 05:45 maturity chain.</div>
              )}
              {vettingActions.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 9, color: '#f59e0b' }}>
                  {vettingActions.length} sources awaiting next auto-approval pass (below threshold or LLM deferred).
                </div>
              )}
            </div>
            {/* Ingestion connectors */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Ingestion connectors ({liveConnectors.length} live / {connectors.length})</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>Real pipes: RSS, SEC, social, YouTube, AI APIs. ACTIVE = ingest path running today.{sourcesView === 'ops' && offConnectors.length > 0 ? ` Hiding ${offConnectors.length} OFF challenger candidates — switch to Full registry to browse.` : ''}</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 10 }}>
                {(sourcesView === 'ops' ? liveConnectors : connectors).map(s => (
                  <div key={`${s.type}-${s.name}`} onClick={() => onDrill({ title: s.name, subtitle: s.type, endpoint: '/api/v2/hermes/sources', rows: [s] })}
                    style={{ padding: '10px 12px', borderRadius: 8, cursor: 'pointer', background: 'var(--bg2)', border: `1px solid ${s.active ? 'rgba(34,197,94,.3)' : 'rgba(100,116,139,.3)'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{s.name}</span>
                      <span style={{ fontSize: 8, padding: '1px 6px', borderRadius: 3, fontWeight: 700, background: s.active ? 'rgba(34,197,94,.15)' : 'rgba(100,116,139,.15)', color: s.active ? '#22c55e' : 'var(--text3)' }}>{s.active ? 'LIVE' : 'OFF'}</span>
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>{typeof s.notes === 'string' && s.notes.startsWith('{') ? `maturity · ${s.maturity_tier || '—'}` : s.notes}</div>
                  </div>
                ))}
              </div>
            </div>
            {/* News maturity candidates */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>News maturity — attribution labels ({newsMaturity.filter(n => n.active).length} activated / {newsMaturity.length})</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
                Scored by <code>source_maturity.py</code> from signal precision + outcomes.
                {sourcesView === 'ops' && candidateNews.length > 0 && (
                  <> Ops view hides <b>{candidateNews.length}</b> low-priority candidate labels — they still ingest via RSS/linked web.</>
                )}
              </div>
              <div style={{ maxHeight: sourcesView === 'ops' ? 280 : 340, overflow: 'auto' }}>
                {newsByTier.map(({ tier, items }) => (
                  <div key={tier} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 10, fontWeight: 800, color: tierColor(tier), marginBottom: 4, textTransform: 'uppercase' }}>{tier} ({items.length})</div>
                    {items.slice(0, tier === 'candidate' ? 25 : sourcesView === 'ops' ? 8 : 12).map(n => (
                      <div key={n.name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, flexWrap: 'wrap' }}>
                        <span style={{ width: 200, fontFamily: 'monospace', color: 'var(--text1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={n.name}>
                          {n.name.replace(/^google_news:/, 'GN:')}
                        </span>
                        <span style={{ width: 36, fontWeight: 700, color: tierColor(n.maturity_tier) }}>{Math.round(n.maturity_score || 0)}</span>
                        <span style={{ width: 48, color: 'var(--text3)' }}>{n.go_rate != null ? `${Math.round(n.go_rate * 100)}% go` : '—'}</span>
                        <span style={{ width: 56, fontSize: 8, color: n.active ? '#22c55e' : 'var(--text3)' }}>{n.active ? 'activated' : 'candidate'}</span>
                        <span style={{ width: 72, fontSize: 8, color: n.ingest_allowed === false ? '#ef4444' : '#60a5fa' }} title={n.policy?.reason}>
                          {n.ingest_allowed === false ? 'ingest⛔' : `promo ${n.promotion_tier || n.policy?.promotion_tier || '—'}`}
                        </span>
                        {n.linked_web && (
                          <span style={{ fontSize: 8, color: n.web_preferred ? '#22c55e' : '#60a5fa' }} title="Linked web domain from SearXNG yield">
                            ↔ {n.linked_web}{n.web_preferred ? ' ✓preferred' : ''}
                          </span>
                        )}
                        {n.vetting_action && !n.active && (
                          <span style={{ fontSize: 8, color: '#f59e0b' }}>auto-pending</span>
                        )}
                      </div>
                    ))}
                    {tier === 'candidate' && items.length > 25 && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>+{items.length - 25} candidate rows (low priority noise)</div>}
                  </div>
                ))}
                {sourcesView === 'ops' && candidateNews.length > 0 && (
                  <button onClick={() => setSourcesView('full')} style={{ marginTop: 6, fontSize: 10, padding: '6px 10px', borderRadius: 6, cursor: 'pointer', background: 'var(--bg2)', border: '1px solid var(--border)', color: 'var(--text2)' }}>
                    Show {candidateNews.length} candidate news labels in full registry →
                  </button>
                )}
              </div>
            </div>
            {/* Web domains scored by yield (Track A) */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Web domains — SearXNG yield ({web.filter(w => w.active).length} preferred / {web.length})</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
                Yield = (promoted+embedded) ÷ research produced. Bar caps at 100% when yield &gt;100% (small-sample spikes).
                {sourcesView === 'ops' ? ` Showing top ${webDisplay.length} preferred domains.` : ''}
              </div>
              {webDisplay.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No web sources scored yet.</div> :
                <div style={{ maxHeight: sourcesView === 'ops' ? 420 : undefined, overflowY: sourcesView === 'ops' ? 'auto' : undefined }}>
                {webDisplay.map(s => (
                  <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 4px', borderBottom: '1px solid var(--border-subtle)' }}>
                    <span style={{ width: 170, fontSize: 11, color: 'var(--text1)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                    <div style={{ flex: 1, height: 10, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: yieldBar(Number(s.credibility)), background: credColor(Math.min(100, Number(s.credibility))) }} />
                    </div>
                    <span style={{ width: 42, fontSize: 10, color: credColor(Math.min(100, Number(s.credibility))), textAlign: 'right', fontWeight: 600 }}>{Number(s.credibility)}%</span>
                    <span style={{ width: 70, fontSize: 8, color: s.active ? '#22c55e' : 'var(--text3)', textAlign: 'right' }}>{s.active ? 'preferred' : 'candidate'}</span>
                  </div>
                ))}
                </div>}
              {sourcesView === 'ops' && web.length > webDisplay.length && (
                <button onClick={() => setSourcesView('full')} style={{ marginTop: 8, fontSize: 10, padding: '6px 10px', borderRadius: 6, cursor: 'pointer', background: 'var(--bg2)', border: '1px solid var(--border)', color: 'var(--text2)' }}>
                  Show all {web.length} web domains ({web.length - web.filter(w => w.active).length} candidate) →
                </button>
              )}
            </div>
          </div>
        )
      })()}

      {!isScalp && tab === 'Research' && backlog && (() => {
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
                    <EvidenceBlock evidence={it.evidence} dataIDoubt={it.data_i_doubt} compact maxItems={3} />
                    {(() => { const dom = domainsOf(it.source_urls_json); return dom.length ? <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>🔎 sources: {dom.slice(0, 4).join(', ')}{dom.length > 4 ? ` +${dom.length - 4}` : ''}</div> : null })()}
                  </div>
                </div>
              ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/research-backlog · {raw.length - described.length} duplicate(s) collapsed · sorted by severity</div>
          </div>
        )
      })()}

      {!isScalp && tab === 'Dual Opinion' && dualOp && (
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

      {!isScalp && tab === 'Maturity' && maturity && (() => {
        const layers = maturity.layer_scores ?? {}
        const areas: any[] = maturity.areas ?? []
        const gaps: any[] = maturity.gaps ?? []
        const lm = maturity.live_metrics ?? {}
        const caps = maturity.coordinator_caps ?? {}
        const sk = maturity.scalp_kpis ?? {}
        const skHealth = sk.health ?? {}
        const skTargets = sk.targets ?? {}
        const kpiColor = (ok: boolean | undefined) => (ok ? '#22c55e' : '#ef4444')
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* Layer scores */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              {[
                { l: 'Overall autonomous', v: layers.overall_autonomous, c: '#60a5fa' },
                { l: 'Research mind', v: layers.research_mind, c: '#22c55e' },
                { l: 'Portfolio attention', v: layers.portfolio_attention, c: '#84cc16' },
                { l: 'Trade execution', v: layers.trade_execution, c: '#ef4444' },
              ].map(k => (
                <div key={k.l} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', textAlign: 'center' }}>
                  <div style={{ fontSize: 26, fontWeight: 800, color: k.c }}>{k.v ?? '—'}%</div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{k.l}</div>
                </div>
              ))}
            </div>

            {sk.watchlist_active != null && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
                {[
                  { l: 'Active watchlist', v: sk.watchlist_active, t: `≤${skTargets.watchlist_active_max ?? 800}`, ok: skHealth.watchlist_active_ok },
                  { l: 'Rank >200', v: sk.watchlist_rank_gt_200, t: 'tail noise', ok: (sk.watchlist_rank_gt_200 ?? 0) < 100 },
                  { l: 'Score inserts/24h', v: sk.score_inserts_24h, t: `≤${skTargets.score_inserts_24h_max ?? 5000}`, ok: skHealth.score_volume_ok },
                  { l: 'Strategy tags', v: sk.strategy_tags_populated_pct != null ? `${sk.strategy_tags_populated_pct}%` : '—', t: `≥${skTargets.strategy_tags_pct_min ?? 95}%`, ok: skHealth.strategy_tags_ok },
                  { l: 'Stale jobs (>2h)', v: sk.watchlist_jobs_stale_2h, t: `≤${skTargets.stale_jobs_max ?? 20}`, ok: skHealth.stale_jobs_ok },
                ].map(k => (
                  <div key={k.l} style={{ background: 'var(--bg1)', border: `1px solid ${kpiColor(k.ok)}33`, borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 800, color: kpiColor(k.ok) }}>{k.v ?? '—'}</div>
                    <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 2 }}>{k.l}</div>
                    <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>target {k.t}</div>
                  </div>
                ))}
              </div>
            )}
            {sk.weights_profile && (
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                Scorer profile: <b style={{ color: sk.weights_profile === 'scalp' ? '#22c55e' : 'var(--text2)' }}>{sk.weights_profile}</b>
                {sk.scorer_always_cap ? ' · top-200 cap ON' : ' · top-200 cap OFF'}
                {sk.watchlist_archived != null && ` · ${sk.watchlist_archived} archived`}
              </div>
            )}

            <div style={{ fontSize: 10, color: 'var(--text3)', padding: '6px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
              Live from DB + coordinator caps · kill switch: <b style={{ color: maturity.kill_switch_active ? '#ef4444' : '#22c55e' }}>{maturity.kill_switch_active ? 'ON' : 'off'}</b>
              {' · '}embed {lm.embed_pending ?? 0} pending / {lm.embed_failed ?? 0} failed
              {' · '}watchlist jobs {lm.watchlist_jobs_queued ?? 0} queued
              {' · '}held {lm.held_count ?? 0}
              {caps.embed != null && <span> · caps promote {caps.promote}/tick embed {caps.embed}/tick</span>}
            </div>

            {/* Areas grid */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Autonomy by area ({areas.length})</div>
              {areas.map((a: any) => (
                <div key={a.id} onClick={() => onDrill({ title: a.label, subtitle: a.level_label, endpoint: '/api/v2/hermes/maturity-dashboard', rows: [a] })}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 100px 72px 90px', gap: 8, alignItems: 'center',
                    padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{a.label}</span>
                    {a.policy_manual && <span style={{ marginLeft: 6, fontSize: 8, color: '#f59e0b', padding: '1px 5px', borderRadius: 3, background: 'rgba(245,158,11,.12)' }}>POLICY</span>}
                    {a.cadence && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{a.cadence}</div>}
                  </div>
                  <span style={{ fontSize: 9, color: MATURITY_COLOR[a.level] ?? 'var(--text3)' }}>{a.level_label}</span>
                  <span style={{ fontWeight: 700, color: MATURITY_COLOR[a.level] ?? 'var(--text2)', textAlign: 'right' }}>{a.autonomy_pct}%</span>
                  <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${a.autonomy_pct}%`, background: MATURITY_COLOR[a.level] ?? '#64748b' }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Gaps — policy vs automatable */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Autonomy gaps — what&apos;s blocking full automation</div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
                {maturity.gap_summary?.automatable_now ?? 0} fixable without policy change · {maturity.gap_summary?.needs_operator_policy_change ?? 0} require operator policy change
              </div>
              {gaps.map((g: any) => (
                <div key={g.id} style={{ marginBottom: 14, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8,
                  borderLeft: `3px solid ${GAP_SEV_COLOR[g.severity] ?? 'var(--text3)'}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{g.title}</span>
                    <span style={{ fontSize: 9, display: 'flex', gap: 6 }}>
                      <span style={{ color: GAP_SEV_COLOR[g.severity] }}>{g.severity}</span>
                      {g.policy_manual
                        ? <span style={{ color: '#f59e0b' }}>manual by policy</span>
                        : <span style={{ color: '#22c55e' }}>automatable</span>}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6 }}>{g.why_not_autonomous_yet}</div>
                  {g.policy_reason && (
                    <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 6, padding: '6px 8px', background: 'rgba(245,158,11,.08)', borderRadius: 4 }}>
                      Policy: {g.policy_reason}
                    </div>
                  )}
                  {g.blockers?.length > 0 && (
                    <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
                      <b style={{ color: 'var(--text2)' }}>Blockers:</b>{' '}
                      {(g.blockers as string[]).join(' · ')}
                    </div>
                  )}
                  {g.recommended_fixes?.length > 0 && (
                    <div style={{ fontSize: 10, color: '#60a5fa', marginTop: 6 }}>
                      <b>Fixes:</b>{' '}
                      {(g.recommended_fixes as string[]).slice(0, 2).join(' · ')}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {maturity.consciousness?.attention?.length > 0 && (
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Curator attention (latest)</div>
                {(maturity.consciousness.attention as string[]).slice(0, 6).map((line: string, i: number) => (
                  <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 0' }}>· {line}</div>
                ))}
              </div>
            )}
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/hermes/maturity-dashboard · refreshed every 2 min</div>
          </div>
        )
      })()}

      {!isScalp && tab === 'Pipeline' && pipeQual && (
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
