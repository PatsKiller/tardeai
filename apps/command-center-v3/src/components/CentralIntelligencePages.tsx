import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from './DetailDrawer'

const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'
const CYAN = '#06b6d4'
const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 15 }
const metric: React.CSSProperties = { background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.18)', borderRadius: 10, padding: '10px 12px' }
const btn = (active = false, color = BLUE): React.CSSProperties => ({ fontSize: 10, padding: '6px 11px', borderRadius: 7, border: `1px solid ${active ? color : 'var(--border)'}`, background: active ? color + '22' : 'var(--bg2)', color: active ? color : MUTED, fontWeight: active ? 850 : 600, cursor: 'pointer' })
const input: React.CSSProperties = { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 7, color: TEXT0, fontSize: 11, padding: '8px 10px' }

type Mode = 'command' | 'quality'
interface Props { mode: Mode; onDrill: (ctx: DrillContext) => void }
type IntelItem = { id: string; source: string; type: string; symbol?: string; title: string; summary?: string; severity: 'critical' | 'warning' | 'info' | 'positive'; confidence: number; freshnessH: number | null; model?: string; lane?: string; action?: string; raw: any }

function first(...xs: any[]) { return xs.find(x => x !== undefined && x !== null && x !== '') }
function n(v: any, d = 0) { const x = Number(v); return Number.isFinite(x) ? x.toFixed(d) : '—' }
function ago(v: any): { label: string; hours: number | null } { if (!v) return { label: 'unknown', hours: null }; const t = new Date(v).getTime(); if (!Number.isFinite(t)) return { label: 'unknown', hours: null }; const h = Math.max(0, (Date.now() - t) / 36e5); if (h < 1) return { label: 'just now', hours: h }; if (h < 48) return { label: `${Math.round(h)}h ago`, hours: h }; return { label: `${Math.round(h / 24)}d ago`, hours: h } }
function color(sev: string) { return sev === 'critical' ? RED : sev === 'warning' ? AMBER : sev === 'positive' ? GREEN : BLUE }
function confidenceFrom(x: any, fallback = 0.65) { const v = first(x.confidence, x.research_confidence, x.eval_confidence, x.score != null ? Number(x.score) / 100 : null); const y = Number(v); if (!Number.isFinite(y)) return fallback; return y > 1 ? Math.min(1, y / 100) : Math.min(1, Math.max(0, y)) }
function severityFrom(x: any): IntelItem['severity'] { const s = String(first(x.severity, x.priority, x.operator_priority, x.advisory_flag, x.status, x.decision, x.recommendation, '')).toLowerCase(); if (/critical|urgent|triggered|blocked|stop|risk|caution|avoid|sell|unprotected|stale|failed/.test(s)) return s.includes('caution') || s.includes('stale') ? 'warning' : 'critical'; if (/warn|wait|hold|pending|review|neutral|partial/.test(s)) return 'warning'; if (/positive|buy|go|bullish|fresh|protected|completed|ok|pass/.test(s)) return 'positive'; return 'info' }
function qscore(it: IntelItem) { const freshnessPenalty = it.freshnessH == null ? 0.18 : it.freshnessH > 72 ? 0.28 : it.freshnessH > 24 ? 0.15 : it.freshnessH > 8 ? 0.07 : 0; const sourcePenalty = /unknown|browser-local|fallback/i.test(it.source) ? 0.16 : 0; const modelPenalty = it.model || it.lane ? 0 : 0.08; return Math.max(0, Math.min(1, it.confidence - freshnessPenalty - sourcePenalty - modelPenalty)) }
function estError(it: IntelItem) { return Math.max(0.02, Math.min(0.75, 1 - qscore(it))) }
function extractText(v: any) { if (!v) return ''; if (typeof v === 'string') { try { const j = JSON.parse(v); return j.content ?? j.summary ?? j.text ?? v } catch { return v } } return v.content ?? v.summary ?? v.text ?? v.recommendation ?? v.title ?? v.message ?? JSON.stringify(v).slice(0, 240) }

function KPI({ label, value, sub, color = TEXT0 }: any) { return <div style={metric}><div style={{ fontSize: 22, fontWeight: 950, color }}>{value}</div><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', letterSpacing: '.05em', marginTop: 3 }}>{label}</div>{sub && <div style={{ fontSize: 10, color: DIM, marginTop: 4 }}>{sub}</div>}</div> }
function ItemCard({ item, onDrill }: { item: IntelItem; onDrill: (ctx: DrillContext) => void }) { const qs = qscore(item), er = estError(item); return <div onClick={() => onDrill({ title: item.title, subtitle: `${item.source} · ${item.type}`, endpoint: item.source, rows: [item.raw] })} style={{ border: `1px solid ${color(item.severity)}55`, borderLeft: `4px solid ${color(item.severity)}`, borderRadius: 11, background: 'rgba(15,23,42,.58)', padding: 12, cursor: 'pointer' }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline' }}><div style={{ display: 'flex', gap: 7, alignItems: 'center', flexWrap: 'wrap' }}>{item.symbol && <span style={{ color: TEXT0, fontSize: 14, fontWeight: 950, fontFamily: 'monospace' }}>{item.symbol}</span>}<span style={{ color: color(item.severity), fontSize: 9, fontWeight: 900, textTransform: 'uppercase' }}>{item.severity}</span><span style={{ color: MUTED, fontSize: 9 }}>{item.type}</span></div><span style={{ color: qs >= .72 ? GREEN : qs >= .5 ? AMBER : RED, fontSize: 10, fontWeight: 900 }}>quality {Math.round(qs * 100)}%</span></div><div style={{ color: TEXT0, fontSize: 12, fontWeight: 800, marginTop: 7, lineHeight: 1.35 }}>{item.title}</div>{item.summary && <div style={{ color: TEXT2, fontSize: 11, lineHeight: 1.45, marginTop: 5 }}>{String(item.summary).slice(0, 280)}</div>}<div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8, fontSize: 9 }}><span style={{ color: MUTED }}>{item.source}</span>{item.model && <span style={{ color: BLUE }}>{item.model}</span>}<span style={{ color: er > .45 ? RED : er > .25 ? AMBER : GREEN }}>est error {(er * 100).toFixed(0)}%</span>{item.action && <span style={{ color: AMBER }}>action: {item.action}</span>}</div></div> }

export default function CentralIntelligencePages({ mode, onDrill }: Props) {
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: command } = useApi<any>('/api/v2/command', 60_000)
  const { data: brief } = useApi<any>('/api/v2/morning-brief', 300_000)
  const { data: reportIntel } = useApi<any>('/api/v2/hermes/subject-intel-map?type=report', 300_000)
  const { data: market } = useApi<any>('/api/v2/market-intelligence', 120_000)
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: watchlist } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: openTrades } = useApi<any>('/api/v2/open-trades/intelligence', 60_000)
  const { data: research } = useApi<any>('/api/v2/research-topics', 120_000)
  const { data: hermes } = useApi<any>('/api/v2/hermes/health', 120_000)
  const [source, setSource] = useState('all')
  const [sev, setSev] = useState('all')
  const [search, setSearch] = useState('')
  const [question, setQuestion] = useState('')
  const [feedback, setFeedback] = useState('')
  const [lmStatus, setLmStatus] = useState('')

  const cmd = command?.data ?? command ?? {}
  const items = useMemo<IntelItem[]>(() => {
    const out: IntelItem[] = []
    const add = (x: Partial<IntelItem> & { raw?: any }) => { if (!x.title) return; const a = ago((x.raw as any)?.at ?? (x.raw as any)?.updated_at ?? (x.raw as any)?.last_enriched_at ?? (x.raw as any)?.created_at ?? (x.raw as any)?.generated_at); out.push({ id: `${x.source}-${out.length}`, source: x.source || 'unknown', type: x.type || 'intelligence', symbol: x.symbol, title: String(x.title), summary: x.summary, severity: x.severity || severityFrom(x.raw ?? x), confidence: x.confidence ?? confidenceFrom(x.raw ?? x), freshnessH: x.freshnessH ?? a.hours, model: x.model, lane: x.lane, action: x.action, raw: x.raw ?? x }) }

    ;(risk?.positions ?? []).filter((p: any) => p.triggered || p.near_stop || p.unprotected || p.triggered_stop).slice(0, 25).forEach((p: any) => add({ source: '/api/v2/risk', type: 'risk', symbol: p.symbol, title: `${p.symbol} risk/stop review`, summary: `${p.account ?? ''} stop ${p.stop_price ?? p.stop ?? '—'} · current ${p.current_price ?? '—'}`, severity: 'critical', raw: p, action: 'verify stop / protection' }))
    ;(cmd.triggered_detail ?? []).slice(0, 20).forEach((s: any) => add({ source: '/api/v2/command', type: 'telegram/action', symbol: s.symbol, title: `${s.symbol} triggered stop from command feed`, summary: `Stop ${s.stop_price ?? s.stop ?? '—'} · ${s.account ?? ''}`, severity: 'critical', raw: s, action: 'confirm broker state' }))
    ;(brief?.action_items ?? []).forEach((a: any, i: number) => add({ source: '/api/v2/morning-brief', type: 'brief-action', title: typeof a === 'string' ? a : (a.message ?? a.title ?? a.action ?? `Action item ${i + 1}`), summary: typeof a === 'object' ? a.code ?? a.reason ?? '' : '', raw: a, action: 'review' }))
    Object.entries(reportIntel?.map ?? {}).forEach(([key, arr]: any) => (arr ?? []).forEach((e: any) => add({ source: '/api/v2/hermes/subject-intel-map?type=report', type: 'external-lm-report', title: e.recommendation ?? key, summary: [e.dissent, ...(Array.isArray(e.risk_flags) ? e.risk_flags : [])].filter(Boolean).join(' · '), model: e.model, lane: e.lane, confidence: confidenceFrom(e, .7), raw: { ...e, key }, action: e.dissent ? 'resolve counter-view' : 'review report' })))
    ;(cmd.top_news ?? []).slice(0, 30).forEach((n: any) => add({ source: '/api/v2/command', type: 'portfolio-news', symbol: n.symbol, title: n.title ?? n.headline, summary: n.why_it_matters ?? n.source, raw: n }))
    ;(market?.top_mentioned_symbols ?? []).slice(0, 20).forEach((s: any) => add({ source: '/api/v2/market-intelligence', type: 'market-signal', symbol: typeof s === 'string' ? s : s.symbol, title: `${typeof s === 'string' ? s : s.symbol} mentioned in market intelligence`, summary: typeof s === 'object' ? `${s.mentions ?? '—'} mentions` : '', raw: s, confidence: .58 }))
    ;(tradeAi?.tickers ?? []).filter((t: any) => ['GO','WAIT'].includes(String(t.decision ?? '').toUpperCase()) || Number(t.score ?? 0) >= 30).slice(0, 40).forEach((t: any) => add({ source: '/api/v2/trade-ai', type: 'setup', symbol: t.symbol, title: `${t.symbol} ${t.decision ?? 'setup'} score ${t.score ?? '—'}`, summary: t.catalyst ?? t.reason ?? t.sector, raw: t, action: t.decision === 'GO' ? 'consider watchlist/manual setup' : 'monitor' }))
    ;(watchlist?.items ?? []).slice(0, 35).forEach((w: any) => add({ source: '/api/v2/watchlist/items', type: 'watchlist', symbol: w.symbol, title: `${w.symbol} watchlist ${w.latest_recommendation ?? w.entry_urgency ?? ''}`, summary: first(w.catalyst, w.reason, w.description, w.entry_setup, 'curated watchlist item'), raw: w, confidence: confidenceFrom(w, .68), action: w.entry_urgency === 'ready' ? 'entry review' : 'monitor' }))
    ;(openTrades?.positions ?? []).filter((p: any) => ['critical','high'].includes(String(p.operator_priority ?? '').toLowerCase()) || (p.risk_flags ?? []).length > 0).slice(0, 30).forEach((p: any) => add({ source: '/api/v2/open-trades/intelligence', type: 'open-trade', symbol: p.symbol, title: `${p.symbol} ${p.operator_decision ?? 'position review'}`, summary: p.decision_reason ?? p.strategy_rationale, severity: severityFrom(p), raw: p, action: p.primary_next_review ?? 'review position' }))
    ;(research?.research_gaps ?? []).slice(0, 20).forEach((g: any) => add({ source: '/api/v2/research-topics', type: 'research-gap', symbol: g.symbol, title: g.topic ?? g.symbol ?? 'Research gap', summary: g.source ?? g.reason, severity: 'warning', raw: g, action: 'assign research' }))
    return out.sort((a, b) => (color(b.severity) === RED ? 1 : 0) - (color(a.severity) === RED ? 1 : 0) || estError(b) - estError(a))
  }, [risk, cmd, brief, reportIntel, market, tradeAi, watchlist, openTrades, research])

  const filtered = items.filter(it => (source === 'all' || it.type === source || it.source.includes(source)) && (sev === 'all' || it.severity === sev) && (!search || `${it.symbol ?? ''} ${it.title} ${it.summary ?? ''}`.toLowerCase().includes(search.toLowerCase())))
  const quality = filtered.map(it => ({ ...it, q: qscore(it), e: estError(it) }))
  const avgQ = quality.length ? quality.reduce((a, b) => a + b.q, 0) / quality.length : 0
  const highErr = quality.filter(x => x.e > .35).length
  const stale = quality.filter(x => (x.freshnessH ?? 999) > 24).length
  const bySeverity = ['critical', 'warning', 'info', 'positive'].map(s => ({ name: s, value: items.filter(i => i.severity === s).length, color: color(s) }))
  const bySource = Object.entries(items.reduce((a: any, i) => { a[i.type] = (a[i.type] ?? 0) + 1; return a }, {})).map(([name, value]) => ({ name, value }))

  const askLm = async () => {
    const payload = { question, feedback, visible_items: filtered.slice(0, 12), page: mode, requested_review: 'quality accuracy usefulness and actionability' }
    setLmStatus('Submitting to local review endpoint…')
    try {
      const r = await fetch('/api/v2/agents/intelligence-feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      if (!r.ok) throw new Error(String(r.status))
      const j = await r.json(); setLmStatus(`Submitted: ${j.status ?? 'ok'}`)
    } catch (e: any) {
      const local = JSON.parse(localStorage.getItem('tradeai.intelFeedback.v1') || '[]')
      local.unshift({ at: new Date().toISOString(), payload })
      localStorage.setItem('tradeai.intelFeedback.v1', JSON.stringify(local.slice(0, 50)))
      setLmStatus(`No backend feedback endpoint yet (${e.message}); saved locally for agent handoff.`)
    }
  }

  if (mode === 'quality') return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ ...panel, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}><div><div style={{ fontSize: 21, fontWeight: 950, color: TEXT0 }}>Signal Quality & Error-Rate Board</div><div style={{ fontSize: 11, color: MUTED }}>Reliability scoring across briefs, reports, Telegram/action feeds, watchlist, trade AI and risk signals. Polls source APIs daily/continuously from the UI.</div></div><div style={{ color: avgQ > .7 ? GREEN : avgQ > .5 ? AMBER : RED, fontWeight: 950 }}>avg quality {(avgQ * 100).toFixed(0)}%</div></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}><KPI label="Signals reviewed" value={items.length} /><KPI label="High error-rate" value={highErr} color={highErr ? RED : GREEN} sub="est error >35%" /><KPI label="Stale items" value={stale} color={stale ? AMBER : GREEN} sub=">24h old or unknown" /><KPI label="LM/Hermes" value={hermes?.autonomous_loop_active ? 'ON' : 'review'} color={hermes?.autonomous_loop_active ? GREEN : AMBER} sub={hermes?.gateway_status ?? 'gateway'} /></div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}><div style={panel}><div style={{ color: TEXT0, fontWeight: 900, marginBottom: 8 }}>Severity mix</div><ResponsiveContainer width="100%" height={220}><PieChart><Pie data={bySeverity} dataKey="value" nameKey="name" outerRadius={78}>{bySeverity.map((x, i) => <Cell key={i} fill={x.color} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></div><div style={panel}><div style={{ color: TEXT0, fontWeight: 900, marginBottom: 8 }}>Source volume</div><ResponsiveContainer width="100%" height={220}><BarChart data={bySource}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.12)" /><XAxis dataKey="name" tick={{ fill: MUTED, fontSize: 9 }} /><YAxis tick={{ fill: MUTED, fontSize: 9 }} /><Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} /><Bar dataKey="value" fill={BLUE} /></BarChart></ResponsiveContainer></div></div>
    <FilterRow source={source} setSource={setSource} sev={sev} setSev={setSev} search={search} setSearch={setSearch} types={[...new Set(items.map(i => i.type))]} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(420px,1fr))', gap: 12 }}>{quality.slice(0, 60).map(it => <ItemCard key={it.id} item={it} onDrill={onDrill} />)}</div>
  </div>

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ ...panel, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}><div><div style={{ fontSize: 21, fontWeight: 950, color: TEXT0 }}>Consolidated Intelligence Command</div><div style={{ fontSize: 11, color: MUTED }}>One-page synthesis of page intelligence, briefs, Hermes/LM reports, Telegram/action items, watchlist, trade AI and portfolio risk.</div></div><div style={{ fontSize: 10, color: MUTED }}>Daily source: /morning-brief · live poll: risk/trade/watchlist</div></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}><KPI label="Total intelligence" value={items.length} /><KPI label="Critical" value={items.filter(i => i.severity === 'critical').length} color={RED} /><KPI label="Warnings" value={items.filter(i => i.severity === 'warning').length} color={AMBER} /><KPI label="Actionable" value={items.filter(i => i.action).length} color={BLUE} /><KPI label="Portfolio" value={`$${Number(overview?.portfolio_value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`} color={TEXT0} /></div>
    <FilterRow source={source} setSource={setSource} sev={sev} setSev={setSev} search={search} setSearch={setSearch} types={[...new Set(items.map(i => i.type))]} />
    <div style={{ ...panel }}><div style={{ color: TEXT0, fontWeight: 900, marginBottom: 9 }}>Agent / Local LM Review & Feedback</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8 }}><textarea value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask the local model: What changed? Which signals conflict? What should agents verify?" style={{ ...input, minHeight: 58 }} /><textarea value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="Feedback to agents / LM critique: missing source, false positive, stale data, better decision wording..." style={{ ...input, minHeight: 58 }} /><button onClick={askLm} style={{ ...btn(true, PURPLE), alignSelf: 'stretch', minWidth: 130 }}>Send / Save Review</button></div>{lmStatus && <div style={{ fontSize: 10, color: lmStatus.startsWith('Submitted') ? GREEN : AMBER, marginTop: 7 }}>{lmStatus}</div>}</div>
    <div style={{ display: 'grid', gridTemplateColumns: '1.1fr .9fr', gap: 14 }}><div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 10 }}>{filtered.slice(0, 18).map(it => <ItemCard key={it.id} item={it} onDrill={onDrill} />)}</div><div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}><div style={panel}><div style={{ color: TEXT0, fontWeight: 900, marginBottom: 8 }}>Decision implications</div>{filtered.slice(0, 8).map(it => <div key={it.id} style={{ borderBottom: '1px solid rgba(148,163,184,.13)', padding: '7px 0' }}><div style={{ color: color(it.severity), fontSize: 10, fontWeight: 900 }}>{it.action ?? 'review'}</div><div style={{ color: TEXT2, fontSize: 11 }}>{it.symbol ? `${it.symbol}: ` : ''}{it.title}</div></div>)}</div><div style={panel}><div style={{ color: TEXT0, fontWeight: 900, marginBottom: 8 }}>Source health</div>{bySource.map(s => <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid rgba(148,163,184,.12)', fontSize: 11 }}><span style={{ color: MUTED }}>{s.name}</span><span style={{ color: TEXT0, fontWeight: 850 }}>{String(s.value)}</span></div>)}</div></div></div>
  </div>
}

function FilterRow({ source, setSource, sev, setSev, search, setSearch, types }: any) { return <div style={{ ...panel, display: 'grid', gridTemplateColumns: '180px 180px 1fr', gap: 9, alignItems: 'center' }}><select value={source} onChange={e => setSource(e.target.value)} style={input}><option value="all">All sources/types</option>{types.map((t: string) => <option key={t} value={t}>{t}</option>)}</select><select value={sev} onChange={e => setSev(e.target.value)} style={input}><option value="all">All severities</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option><option value="positive">Positive</option></select><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter by symbol, topic, source, decision, trend, implication…" style={input} /></div> }
