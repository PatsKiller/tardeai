import { useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { useToast } from '../components/ToastProvider'
import { timeAgo } from '../lib/format'
import PositionCard from '../components/ai-analyst/PositionCard'
import StrategyCard from '../components/ai-analyst/StrategyCard'
import { DoughnutChart, BarChartJS } from '../components/charts'

/*
  AI Analyst — Interactive Intelligence Dashboard (Grok visual + working data)
  - Prominent Ask AI bar with live Ollama query
  - Computed metrics from actual AI content (not hardcoded)
  - Tabbed navigation: Overview | Holdings | Strategy | Defense | Retirement
  - Extracted position cards + strategy cards from AI markdown
  - Right sidebar detail panel on position select
  - Parsed markdown with color-coded checklists for all tabs
*/

interface AISection { key: string; title: string; content: string }
interface AIData { has_data: boolean; sections: AISection[]; generated_at: string; run_type: string; model: string }
interface AIReport { id: number; report_type: string; title: string; content: string; provider: string; cost: number; generated_at: string }
interface AIReportsResp { reports: AIReport[] }
interface AlexAnalysis { symbol: string; trigger: string; severity: string; created_at: string; summary?: string }
interface AlexRecentResp { analyses: AlexAnalysis[] }
interface AgentSummaryItem { agent: string; last_run: string; status: string; actions_taken: number }
interface AgentsSummaryResp { agents: AgentSummaryItem[] }
type Tab = 'overview' | 'holdings' | 'strategy' | 'defense' | 'retirement' | 'reports'

const TAB_MAP: Record<Tab, string[]> = {
  overview: ['executive_summary'], holdings: ['deep_holdings'],
  strategy: ['dividend_strategy', 'bond_strategy', 'v_strategy'],
  defense: ['defense_analysis'], retirement: ['ira_opportunities'],
  reports: [],
}

// ── Extraction helpers ────────────────────────────────────────────────────

interface ExtractedPosition { symbol: string; name: string; allocation: string; recommendation: string; analysis: string }

function extractPositions(content: string): ExtractedPosition[] {
  const results: ExtractedPosition[] = []
  const regex = /###\s*\*\*(.+?)\s*\((.+?)\)\s*—\s*(.+?)\*\*\s*\n\*\*RECOMM(?:ENDATION)?:\s*(\w+)\*\*\s*—?\s*([\s\S]*?)(?=###\s*\*\*|\n##\s|$)/g
  let m
  while ((m = regex.exec(content)) !== null) {
    results.push({ symbol: m[1].trim(), name: m[2].trim(), allocation: m[3].trim(), recommendation: m[4].trim(), analysis: m[5].trim().slice(0, 500) })
  }
  return results
}

interface ExtractedStrategy { recommendation: string; detail: string; rotationTarget?: string; checklist: { text: string; status: 'good' | 'warning' | 'bad' }[] }

function extractStrategy(content: string, key: string): ExtractedStrategy | null {
  const checklist: ExtractedStrategy['checklist'] = []
  const checkRe = /[✅❌⚠️]\s*\*\*(.+?)\*\*/g
  let cm
  while ((cm = checkRe.exec(content)) !== null) {
    const line = content.slice(cm.index, content.indexOf('\n', cm.index))
    checklist.push({ text: cm[1].replace(/→.*$/, '').trim(), status: line.includes('✅') ? 'good' : line.includes('❌') ? 'bad' : 'warning' })
  }
  if (key === 'v_strategy') {
    const rec = content.match(/RECOMMENDATION:\s*\*\*(.+?)\*\*/i)?.[1]?.trim() || 'Review'
    const detail = content.match(/Visa remains.*?(?=\n##|\n---)/s)?.[0]?.trim().slice(0, 350) || content.slice(0, 300)
    const rot = content.match(/OPTIMAL ROTATION TARGET\s*\n([\s\S]*?)(?=\n##|$)/i)?.[1]?.trim().slice(0, 250)
    return { recommendation: rec, detail, rotationTarget: rot, checklist }
  }
  const firstPara = content.match(/^(?!#)(?!-)(?!\*).{40,}/m)?.[0]?.slice(0, 300) || content.slice(0, 200)
  return { recommendation: checklist.filter(c => c.status === 'bad').length > 2 ? 'Needs Action' : 'Review', detail: firstPara, checklist }
}

// ── Markdown parser ───────────────────────────────────────────────────────

interface Block { type: 'heading' | 'checklist' | 'paragraph' | 'divider'; level?: number; text?: string; items?: { status: string; label: string; action?: string }[] }

function parseContent(raw: string): Block[] {
  const blocks: Block[] = []
  const lines = raw.split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i].trim()
    if (!line || line === '---') { if (line === '---') blocks.push({ type: 'divider' }); i++; continue }
    if (line.startsWith('#')) { const m = line.match(/^(#{1,4})\s+(.+)/); if (m) { blocks.push({ type: 'heading', level: m[1].length, text: m[2].replace(/[#]/g, '').trim() }); i++; continue } }
    if (/^[-*]?\s*[✅❌⚠️]/.test(line)) {
      const items: Block['items'] = []
      while (i < lines.length && /^[-*]?\s*[✅❌⚠️]/.test(lines[i].trim())) {
        const cl = lines[i].trim()
        const status = cl.includes('✅') ? 'pass' : cl.includes('❌') ? 'fail' : 'warn'
        const cleaned = cl.replace(/^[-*]\s*/, '').replace(/[✅❌⚠️]\s*/, '').trim()
        const actionMatch = cleaned.match(/→\s*\[(.+?)\]/)
        items!.push({ status, label: cleaned.replace(/→\s*\[.+?\]/, '').replace(/\*\*/g, '').trim(), action: actionMatch?.[1] })
        i++
      }
      if (items!.length) blocks.push({ type: 'checklist', items }); continue
    }
    let para = ''
    while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith('#') && !/^[-*]?\s*[✅❌⚠️]/.test(lines[i].trim()) && lines[i].trim() !== '---') { para += (para ? ' ' : '') + lines[i].trim(); i++ }
    if (para) blocks.push({ type: 'paragraph', text: para })
  }
  return blocks
}

// ── Component ─────────────────────────────────────────────────────────────

export default function AIAnalyst() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const { data, loading } = useApi<AIData>('/api/v2/ai-analyst')
  const { data: reportsData } = useApi<AIReportsResp>('/api/v2/ai-reports')
  const { data: alexData } = useApi<AlexRecentResp>('/api/v2/alex/recent')
  const { data: agentsData } = useApi<AgentsSummaryResp>('/api/v2/agents/summary')
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [selectedPosition, setSelectedPosition] = useState<ExtractedPosition | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [aiResponse, setAiResponse] = useState('')

  const handleAsk = useCallback(async () => {
    if (!question.trim()) return
    setAsking(true); setAiResponse('')
    try {
      const res = await fetch('/api/v2/ai-ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: question.trim() }) })
      const json = await res.json()
      setAiResponse(json.ok ? json.answer : json.error || 'Failed')
      if (json.ok) showToast('AI responded', 'success')
      else showToast('AI query failed', 'error')
    } catch { setAiResponse('Network error — Ollama may be offline'); showToast('AI query failed', 'error') }
    setAsking(false)
  }, [question, showToast])

  // Computed metrics from actual content
  const metrics = useMemo(() => {
    if (!data?.sections) return { pass: 0, fail: 0, warn: 0 }
    let pass = 0, fail = 0, warn = 0
    for (const s of data.sections) for (const m of (s.content.match(/[✅❌⚠️]/g) || [])) { if (m === '✅') pass++; else if (m === '❌') fail++; else warn++ }
    return { pass, fail, warn }
  }, [data])

  const positions = useMemo(() => {
    const hs = data?.sections?.find(s => s.key === 'deep_holdings')
    return hs ? extractPositions(hs.content) : []
  }, [data])

  const strategies = useMemo(() => {
    if (!data?.sections) return []
    return ['dividend_strategy', 'bond_strategy', 'v_strategy'].map(key => {
      const section = data.sections.find(s => s.key === key)
      if (!section) return null
      const strat = extractStrategy(section.content, key)
      return strat ? { key, title: section.title, ...strat } : null
    }).filter(Boolean) as (ExtractedStrategy & { key: string; title: string })[]
  }, [data])

  const tabSections = useMemo(() => data?.sections?.filter(s => (TAB_MAP[activeTab] || []).includes(s.key)) || [], [data, activeTab])

  if (loading) return <div style={{ padding: 40, color: 'var(--text3)', fontFamily: 'var(--sans)' }}>Loading AI Analysis...</div>

  return (
    <>
      <PageHeader title="AI Analyst" subtitle={data?.generated_at ? `${data.run_type || 'daily'} · ${data.model || 'Claude'} · ${timeAgo(data.generated_at)} · Validated = confirmed OK · Monitor = watch · Action = decide today` : 'AI analysis — run daily pipeline via Actions page to generate'} />
      <div style={{ padding: '6px 12px', marginBottom: 10, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 10, color: 'var(--amber)' }}>
        Advisory only — all trades must be executed manually at your broker (Fidelity/Schwab). This app does not place or cancel orders.
      </div>

      {/* ── Ask AI ── */}
      <div style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(74,144,244,0.25)', borderRadius: 12, padding: '18px 20px', marginBottom: 24 }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>🤖 Ask AI About Your Portfolio</div>
        <div style={{ display: 'flex', gap: 12 }}>
          <input value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleAsk()}
            placeholder="E.g. Should I trim Visa? What about REITs in the IRA? Tax optimization ideas?"
            style={{ flex: 1, padding: '14px 18px', fontSize: 13, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text0)', fontFamily: 'var(--sans)', outline: 'none' }} />
          <button onClick={handleAsk} disabled={asking || !question.trim()}
            style={{ padding: '14px 32px', background: asking ? 'var(--bg3)' : 'var(--accent)', color: asking ? 'var(--text3)' : '#000', fontWeight: 700, border: 'none', borderRadius: 10, cursor: asking ? 'wait' : 'pointer', fontFamily: 'var(--sans)', minWidth: 140 }}>
            {asking ? 'Thinking...' : 'Ask AI →'}
          </button>
        </div>
        {aiResponse && (
          <div style={{ marginTop: 16, padding: 16, background: 'var(--bg2)', borderRadius: 10, fontSize: 13, lineHeight: 1.6, borderLeft: '4px solid var(--accent)', color: 'var(--text1)', whiteSpace: 'pre-wrap', maxHeight: 300, overflowY: 'auto' }}>
            {aiResponse}
          </div>
        )}
      </div>

      {/* ── Metrics ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
        <MetricTile label="AI Sections" value={String(data?.sections?.length || 0)} />
        <MetricTile label="Action Items" value={String(metrics.fail)} deltaColor="var(--red)" delta={`${metrics.fail} need action`} />
        <MetricTile label="Validated" value={String(metrics.pass)} deltaColor="var(--green)" delta="confirmed OK" />
        <MetricTile label="Monitor" value={String(metrics.warn)} deltaColor="var(--amber)" delta="watch items" />
        {(metrics.pass + metrics.fail + metrics.warn) > 0 && (
          <div style={{ background: 'rgba(16,20,28,0.92)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <DoughnutChart labels={['Pass', 'Fail', 'Warn']} data={[metrics.pass, metrics.fail, metrics.warn]} colors={['#0ecb81', '#f6465d', '#f0b90b']} height={100} />
          </div>
        )}
      </div>

      {/* ── Tabs ── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap' }}>
        {(Object.keys(TAB_MAP) as Tab[]).map(tab => {
          const active = activeTab === tab
          const icons: Record<Tab, string> = { overview: '📋', holdings: '📊', strategy: '💰', defense: '🛡️', retirement: '🎯', reports: '📄' }
          const labels: Record<Tab, string> = { overview: 'Overview', holdings: 'Holdings', strategy: 'Strategy', defense: 'Defense', retirement: 'Retirement', reports: `Reports (${(reportsData?.reports || []).length})` }
          return (
            <button key={tab} onClick={() => { setActiveTab(tab); setSelectedPosition(null) }} style={{
              padding: '9px 22px', borderRadius: 9999,
              background: active ? 'rgba(74,144,244,0.15)' : 'transparent',
              border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
              color: active ? 'var(--accent)' : 'var(--text2)',
              fontWeight: active ? 700 : 500, fontSize: 13, cursor: 'pointer', fontFamily: 'var(--sans)',
            }}>
              {icons[tab]} {labels[tab]}
            </button>
          )
        })}
      </div>

      {/* ── Main content ── */}
      {!data?.has_data ? (
        <div style={{ background: 'rgba(16,20,28,0.92)', borderRadius: 12, padding: 40, textAlign: 'center', color: 'var(--text3)', border: '1px solid rgba(255,255,255,0.07)' }}>No AI analysis available. Run the daily pipeline to generate.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: selectedPosition ? '1fr 380px' : '1fr', gap: 24 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* Holdings → Position cards */}
            {activeTab === 'holdings' && positions.length > 0 && (
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 14, color: 'var(--text1)', fontFamily: 'var(--sans)' }}>Position Analysis ({positions.length})</div>
                {/* Position allocation bar chart */}
                <div style={{ background: 'rgba(16,20,28,0.92)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: 16, marginBottom: 20 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginBottom: 10, fontFamily: 'var(--sans)' }}>Allocation Distribution</div>
                  <BarChartJS
                    labels={positions.map(p => p.symbol)}
                    data={positions.map(p => parseFloat(p.allocation) || 0)}
                    colors={positions.map(p => p.recommendation.match(/TRIM|SELL/i) ? '#f6465d' : p.recommendation.match(/HOLD/i) ? '#0ecb81' : '#4a90f4')}
                    height={120}
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
                  {positions.map(pos => (
                    <PositionCard key={pos.symbol} symbol={pos.symbol} name={pos.name} allocation={pos.allocation}
                      recommendation={pos.recommendation} rationale={pos.analysis}
                      selected={selectedPosition?.symbol === pos.symbol}
                      onSelect={() => setSelectedPosition(selectedPosition?.symbol === pos.symbol ? null : pos)} />
                  ))}
                </div>
              </div>
            )}

            {/* Strategy → Strategy cards with extracted checklists */}
            {activeTab === 'strategy' && strategies.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 20 }}>
                {strategies.map(strat => (
                  <StrategyCard key={strat.key} title={strat.title} recommendation={strat.recommendation}
                    detail={strat.detail} checklist={strat.checklist} rotationTarget={strat.rotationTarget}
                    actionLabel={strat.key === 'v_strategy' ? 'Review V Holdings' : strat.key === 'dividend_strategy' ? 'Review Dividends' : 'Review Rebalance'}
                    actionRoute={strat.key === 'v_strategy' ? '/portfolio?symbol=V' : strat.key === 'dividend_strategy' ? '/dividends' : '/rebalance'} />
                ))}
              </div>
            )}

            {/* Reports tab */}
            {activeTab === 'reports' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {(reportsData?.reports || []).length === 0 ? (
                  <div style={{ background: 'rgba(16,20,28,0.92)', borderRadius: 12, padding: 40, textAlign: 'center', color: 'var(--text3)', border: '1px solid rgba(255,255,255,0.07)' }}>
                    No reports generated yet. Weekly and monthly reports are created by the Alex automation pipeline.
                  </div>
                ) : (
                  (reportsData?.reports || []).map(report => (
                    <div key={report.id} style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '20px 24px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <div>
                          <span style={{
                            fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 700, textTransform: 'uppercase', marginRight: 8,
                            background: report.report_type === 'monthly' ? 'rgba(74,144,244,0.15)' : 'rgba(14,203,129,0.1)',
                            color: report.report_type === 'monthly' ? 'var(--accent)' : 'var(--green)',
                          }}>{report.report_type}</span>
                          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{report.title}</span>
                        </div>
                        <div style={{ fontSize: 10, color: 'var(--text3)' }}>
                          {report.provider && <span>{report.provider} · </span>}
                          {report.generated_at ? timeAgo(report.generated_at) : ''}
                          {report.generated_at && (Date.now() - new Date(report.generated_at).getTime()) > 86400000 && (
                            <span style={{ marginLeft: 6, fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(239,68,68,0.15)', color: '#EF4444', fontWeight: 600 }}>STALE</span>
                          )}
                        </div>
                      </div>
                      <div style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--text1)', whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto', fontFamily: 'var(--sans)' }}>
                        {report.content}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Overview: Agent collaboration activity */}
            {activeTab === 'overview' && (agentsData?.agents || []).length > 0 && (
              <div style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '20px 24px' }}>
                <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 14, color: 'var(--text1)', fontFamily: 'var(--sans)' }}>Agent Collaboration</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
                  {(agentsData?.agents || []).map(agent => (
                    <div key={agent.agent} onClick={() => navigate(`/agent-dashboard/${agent.agent}`)}
                      style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', cursor: 'pointer', transition: 'border-color 0.15s' }}
                      onMouseEnter={e => (e.currentTarget.style.borderColor = 'rgba(99,102,241,0.5)')}
                      onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{agent.agent}</span>
                        <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 9999, fontWeight: 700, background: agent.status === 'active' ? 'rgba(14,203,129,0.12)' : 'rgba(255,255,255,0.06)', color: agent.status === 'active' ? 'var(--green)' : 'var(--text3)' }}>{agent.status}</span>
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--text2)', fontFamily: 'var(--sans)' }}>{agent.actions_taken} actions</div>
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Last run: {agent.last_run ? timeAgo(agent.last_run) : '—'}</div>
                      <div style={{ fontSize: 8, color: 'rgba(99,102,241,0.5)', marginTop: 4 }}>Click for details</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Alex Recent Activity */}
            {(alexData?.analyses || []).length > 0 && (
              <div style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '20px 24px' }}>
                <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 14, color: 'var(--text1)', fontFamily: 'var(--sans)' }}>Alex Recent Activity</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                  {(alexData?.analyses || []).slice(0, 5).map((a, i) => (
                    <div key={i} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{a.symbol}</span>
                        <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 9999, fontWeight: 700,
                          background: a.severity === 'high' ? 'rgba(246,70,93,0.12)' : a.severity === 'medium' ? 'rgba(240,185,11,0.12)' : 'rgba(14,203,129,0.12)',
                          color: a.severity === 'high' ? 'var(--red)' : a.severity === 'medium' ? 'var(--amber)' : 'var(--green)',
                        }}>{a.severity}</span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text1)', fontWeight: 600, fontFamily: 'var(--sans)', marginBottom: 4 }}>{a.trigger}</div>
                      <div style={{ fontSize: 9, color: 'var(--text3)' }}>{a.created_at ? timeAgo(a.created_at) : '—'}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Parsed markdown for all tabs */}
            {tabSections.map(section => {
              const blocks = parseContent(section.content)
              const genAt = data?.generated_at ? new Date(data.generated_at) : null
              const ageHrs = genAt ? (Date.now() - genAt.getTime()) / 3600000 : 999
              const isStale = ageHrs > 24
              const hasOldDate = section.content?.includes('April 5, 2025') || section.content?.includes('April 2025')
              return (
                <div key={section.key} style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '20px 24px' }}>
                  {(isStale || hasOldDate) && (
                    <div style={{ marginBottom: 10, padding: '6px 10px', borderRadius: 6, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3, background: 'rgba(239,68,68,0.2)', color: '#EF4444', fontWeight: 700 }}>STALE</span>
                      <span style={{ fontSize: 10, color: '#EF4444' }}>
                        {isStale ? `Generated ${Math.floor(ageHrs)}h ago` : 'Content references old dates'}
                        {hasOldDate ? ' — content references April 2025' : ''}
                        . Regenerate with current context.
                      </span>
                    </div>
                  )}
                  {blocks.map((block, idx) => <RenderBlock key={idx} block={block} />)}
                </div>
              )
            })}
          </div>

          {/* ── Right sidebar ── */}
          {selectedPosition && (
            <div style={{ background: 'rgba(16,20,28,0.95)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: 24, alignSelf: 'start', position: 'sticky', top: 90 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
                <div>
                  <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{selectedPosition.symbol}</div>
                  <div style={{ color: 'var(--text3)', fontSize: 11 }}>{selectedPosition.name}</div>
                </div>
                <button onClick={() => setSelectedPosition(null)} style={{ fontSize: 24, color: 'var(--text3)', cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
              </div>

              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>Recommendation</div>
                <span style={{ padding: '6px 16px', borderRadius: 9999, fontSize: 12, fontWeight: 700, display: 'inline-block',
                  background: selectedPosition.recommendation.match(/TRIM|SELL/i) ? 'rgba(246,70,93,0.15)' : 'rgba(74,144,244,0.15)',
                  color: selectedPosition.recommendation.match(/TRIM|SELL/i) ? 'var(--red)' : 'var(--accent)',
                }}>{selectedPosition.recommendation}</span>
              </div>

              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>Allocation</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{selectedPosition.allocation}</div>
              </div>

              <div style={{ fontSize: 11, lineHeight: 1.65, color: 'var(--text1)', marginBottom: 24, maxHeight: 300, overflowY: 'auto' }}>
                {selectedPosition.analysis}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[['View Full Holdings', `/portfolio?symbol=${selectedPosition.symbol}`], ['Risk Analysis', `/risk?symbol=${selectedPosition.symbol}`], ['Open Research', `/research?symbol=${selectedPosition.symbol}`], ['Rebalance', '/rebalance']].map(([label, route]) => (
                  <button key={route} onClick={() => navigate(route)} style={{ padding: 12, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: 'var(--text0)', cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 11, textAlign: 'left', fontWeight: 600 }}>{label} →</button>
                ))}
                <button onClick={() => showToast('Added to Journal', 'success')} style={{ padding: 12, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 600 }}>Log to Journal ✓</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Quick nav ── */}
      <div style={{ display: 'flex', gap: 6, marginTop: 20, flexWrap: 'wrap' }}>
        {[['Portfolio', '/portfolio'], ['Risk', '/risk'], ['Rebalance', '/rebalance'], ['Retirement', '/retirement'], ['Forecast', '/forecast'], ['Dividends', '/dividends']].map(([l, r]) => (
          <button key={r} onClick={() => navigate(r)} style={{ fontSize: 10, padding: '5px 12px', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 9999, background: 'rgba(255,255,255,0.04)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)' }}>{l}</button>
        ))}
      </div>
    </>
  )
}

// ── Block renderer ────────────────────────────────────────────────────────

function RenderBlock({ block }: { block: Block }) {
  if (block.type === 'divider') return <div style={{ height: 1, background: 'rgba(255,255,255,0.06)', margin: '12px 0' }} />
  if (block.type === 'heading') {
    const s = [0, 20, 15, 13, 12]
    return <div style={{ fontSize: s[block.level || 2], fontWeight: 800, color: block.level === 1 ? '#fff' : 'var(--text0)', fontFamily: 'var(--sans)', margin: `${block.level === 1 ? 4 : 12}px 0 8px` }}>{block.text}</div>
  }
  if (block.type === 'checklist' && block.items) {
    const colors: Record<string, string> = { pass: 'var(--green)', fail: 'var(--red)', warn: 'var(--amber)', info: 'var(--text2)' }
    const bgs: Record<string, string> = { pass: 'rgba(14,203,129,0.06)', fail: 'rgba(246,70,93,0.06)', warn: 'rgba(240,185,11,0.06)', info: 'rgba(255,255,255,0.03)' }
    const icons: Record<string, string> = { pass: '✅', fail: '❌', warn: '⚠️', info: '•' }
    return (
      <div style={{ display: 'grid', gap: 6, margin: '10px 0' }}>
        {block.items.map((item, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, padding: '10px 12px', borderRadius: 8, background: bgs[item.status], borderLeft: `3px solid ${colors[item.status]}`, alignItems: 'flex-start' }}>
            <span style={{ fontSize: 13, flexShrink: 0 }}>{icons[item.status]}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: 'var(--text0)', lineHeight: 1.5, fontFamily: 'var(--sans)' }}>{item.label}</div>
              {item.action && <div style={{ fontSize: 11, color: colors[item.status], fontWeight: 600, marginTop: 3 }}>→ {item.action}</div>}
            </div>
          </div>
        ))}
      </div>
    )
  }
  if (block.type === 'paragraph' && block.text) {
    const html = block.text.replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--text0)">$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>')
    return <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.7, margin: '6px 0', fontFamily: 'var(--sans)' }} dangerouslySetInnerHTML={{ __html: html }} />
  }
  return null
}
