import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from './DetailDrawer'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import ActionBriefCard from './intelligence/ActionBriefCard'
import { briefFromIntelItem, type IntelItem } from '../lib/intelBrief'
import { KPI } from './intelligence/dashboardKit'
import { intelligenceItemId as stableId } from '../lib/intelligenceItemId'

const TEXT0 = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const MUTED = 'var(--text3)'
const GREEN = 'var(--green)'
const RED = 'var(--red)'
const AMBER = 'var(--amber)'
const BLUE = 'var(--blue)'
const PURPLE = 'var(--purple)'
const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 15 }
const input: React.CSSProperties = { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 7, color: TEXT0, fontSize: 11, padding: '8px 10px' }

type Special = 'all' | 'actionable' | 'highError' | 'stale'
type ViewPreset = 'priority' | 'all'
interface Props { onDrill: (ctx: DrillContext) => void }
type EnsembleMeta = { score: number; decision: 'approve' | 'block'; consensus: boolean; lanes: string[] }

// Content-derived id imported from ../lib/intelligenceItemId (stableId alias).
function ago(v: any): { label: string; hours: number | null } { if (!v) return { label: 'unknown', hours: null }; const t = new Date(v).getTime(); if (!Number.isFinite(t)) return { label: 'unknown', hours: null }; const h = Math.max(0, (Date.now() - t) / 36e5); if (h < 1) return { label: 'just now', hours: h }; if (h < 48) return { label: `${Math.round(h)}h ago`, hours: h }; return { label: `${Math.round(h / 24)}d ago`, hours: h } }
function sevColor(sev: string) { return sev === 'critical' ? RED : sev === 'warning' ? AMBER : sev === 'positive' ? GREEN : BLUE }
function confidenceFrom(x: any, fallback = 0.65) { const v = first(x.confidence, x.research_confidence, x.eval_confidence, x.score != null ? Number(x.score) / 100 : null); const y = Number(v); if (!Number.isFinite(y)) return fallback; return y > 1 ? Math.min(1, y / 100) : Math.min(1, Math.max(0, y)) }
function severityFrom(x: any): IntelItem['severity'] { const s = String(first(x.severity, x.priority, x.operator_priority, x.advisory_flag, x.status, x.decision, x.recommendation, '')).toLowerCase(); if (/critical|urgent|triggered|blocked|stop|risk|avoid|sell|unprotected|failed/.test(s)) return 'critical'; if (/caution|stale|warn|wait|hold|pending|review|neutral|partial/.test(s)) return 'warning'; if (/positive|buy|go|bullish|fresh|protected|completed|ok|pass/.test(s)) return 'positive'; return 'info' }
// Structural signals are FACTS (price vs stop, position state) — their quality is data completeness +
// signal clarity (encoded in `confidence` at build time), NOT news-freshness or LM review. Opinion/research
// signals (news, research, external-LM) keep the freshness/source/LM penalties.
const STRUCTURAL = /^(risk|telegram\/action|open-trade|setup)$/
function isStructural(it: IntelItem) { return STRUCTURAL.test(it.type) }
// Base structural/opinion score, BEFORE any multi-LLM ensemble adjustment (kept separate so the
// ensemble delta below is a visible, bounded nudge rather than folded invisibly into one number).
function baseQscore(it: IntelItem) {
  if (isStructural(it)) { const stale = it.freshnessH != null && it.freshnessH > 96 ? 0.10 : 0; return Math.max(0, Math.min(1, it.confidence - stale)) }
  const freshnessPenalty = it.freshnessH == null ? 0.18 : it.freshnessH > 72 ? 0.28 : it.freshnessH > 24 ? 0.15 : it.freshnessH > 8 ? 0.07 : 0; const sourcePenalty = /unknown|browser-local|fallback/i.test(it.source) ? 0.16 : 0; const modelPenalty = it.model || it.lane ? 0 : 0.08; return Math.max(0, Math.min(1, it.confidence - freshnessPenalty - sourcePenalty - modelPenalty)) }
// Curation is deterministic math (see baseQscore) — this is the one place a real independent multi-LLM
// verdict (Grok + ChatGPT + local gemma, from the SAME ensemble jobs the card's "Ask LM" button enqueues)
// is allowed to move the ranking: a consensus BLOCK pulls a card down (it should not look trustworthy just
// because its raw fields look complete); a consensus APPROVE with a strong score nudges it up. Bounded
// (+/-12pts) and only ever applied when a verdict actually exists — no LLM call happens on the render path.
function qscore(it: IntelItem) {
  const base = baseQscore(it)
  const en = it.ensemble
  if (!en || !en.consensus) return base
  const delta = en.decision === 'block' ? -0.12 : en.score >= 8 ? 0.12 : en.score >= 6 ? 0.05 : 0
  return Math.max(0, Math.min(1, base + delta))
}
function estError(it: IntelItem) { return Math.max(0.02, Math.min(0.75, 1 - qscore(it))) }
function money(v: any) { const n = Number(v); return Number.isFinite(n) ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—' }
function btn(active = false, color = BLUE): React.CSSProperties { return { fontSize: 10, padding: '6px 11px', borderRadius: 7, border: `1px solid ${active ? color : 'var(--border)'}`, background: active ? color + '22' : 'var(--bg2)', color: active ? color : MUTED, fontWeight: active ? 850 : 600, cursor: 'pointer' } }

function qualityReasons(it: IntelItem) {
  const out: string[] = []
  if (isStructural(it)) {
    // a price-vs-stop fact: grade it on its own data, not on "LM review"/news-timestamp
    if (it.confidence < .55) out.push('incomplete price/stop data')
    else if (it.confidence < .72) out.push('marginal signal (small breach / thin evidence)')
    if (it.freshnessH != null && it.freshnessH > 96) out.push('quote >96h old')
    if (/risk|telegram|open-trade/.test(it.type)) out.push('confirm via broker/account readback')
    return out.length ? out : ['data-complete structural signal; confirm broker readback before action']
  }
  if (it.confidence < .6) out.push(`low source/model confidence (${Math.round(it.confidence * 100)}%)`)
  if (it.freshnessH == null) out.push('missing timestamp')
  else if (it.freshnessH > 72) out.push('stale >72h')
  else if (it.freshnessH > 24) out.push('stale >24h')
  if (it.ensemble?.consensus && it.ensemble.decision === 'block') out.push(`ensemble consensus BLOCK (${it.ensemble.lanes.join('+')}, ${it.ensemble.score.toFixed(1)}/10)`)
  else if (!it.model && !it.lane) out.push('not independently LM-reviewed')
  if (/research-gap/.test(it.type)) out.push('research gap not resolved')
  return out.length ? out : ['source looks usable; still verify before action']
}
function isLowValueSetup(it: IntelItem) {
  if (it.type !== 'setup') return false
  const decision = String((it.raw as any)?.decision ?? '').toUpperCase()
  const score = Number((it.raw as any)?.score ?? 0)
  return (decision === 'WAIT' && score < 10) || qscore(it) < 0.15
}
function isActNow(it: IntelItem) {
  if (it.type === 'risk' || it.type === 'telegram/action' || it.type === 'open-trade') return true
  if (it.type === 'external-lm-report' && it.severity === 'critical') return true
  return qscore(it) >= 0.55 && estError(it) <= 0.35 && !!it.action && it.severity !== 'info'
}
function priorityRank(it: IntelItem) {
  if (it.type === 'risk' || it.type === 'telegram/action') return 0
  if (it.type === 'open-trade' && it.severity === 'critical') return 1
  if (it.type === 'external-lm-report') return 2
  if (isActNow(it)) return 3
  if (it.severity === 'critical') return 4
  if (it.severity === 'warning') return 5
  return 6
}
function sortByPriority(a: IntelItem, b: IntelItem) {
  return priorityRank(a) - priorityRank(b) || estError(a) - estError(b) || qscore(b) - qscore(a)
}

function nextStep(it: IntelItem) {
  if (it.type === 'risk') return 'Open Risk/Open Trades and verify current price, stop status, and account protection.'
  if (it.type === 'telegram/action') return 'Compare Telegram/action alert to Schwab read-only activity and current position.'
  if (it.type === 'open-trade') return 'Open the position card; resolve cost basis/protection before any trade decision.'
  if (it.type === 'external-lm-report') return 'Read the counter-view and ask local LM to reconcile dissent against current holdings.'
  if (it.type === 'research-gap') return 'Assign research or run topic review before using this as a trading signal.'
  if (it.type === 'watchlist') return 'Check card freshness, analyst target, entry/stop/target and current price before setup.'
  if (it.type === 'setup') return 'Confirm the catalyst and entry price are current before proposal/manual setup.'
  return 'Open source record and verify freshness, source, and portfolio impact.'
}

function first(...xs: any[]) { return xs.find(x => x !== undefined && x !== null && x !== '') }

function ItemCard({ item, onDrill }: { item: IntelItem; onDrill: (ctx: DrillContext) => void }) {
  const brief = briefFromIntelItem(item)
  const weak = estError(item) > .35 || qscore(item) < .55
  const footer = weak ? (
    <div onClick={e => e.stopPropagation()}>
      <EnsembleValidationInline targetType="signal" targetId={item.id} subject={item.symbol || item.type} content={`${item.title}\n${item.summary ?? ''}`} />
    </div>
  ) : undefined
  return (
    <ActionBriefCard
      {...brief}
      footer={footer}
      onDrill={() => onDrill({ title: item.title, subtitle: brief.who, endpoint: item.source, rows: [item.raw] })}
    />
  )
}

export default function CentralIntelligencePages({ onDrill }: Props) {
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: command } = useApi<any>('/api/v2/command', 60_000)
  const { data: brief } = useApi<any>('/api/v2/morning-brief', 300_000)
  const { data: reportIntel } = useApi<any>('/api/v2/hermes/subject-intel-map?type=report', 300_000)
  const { data: market } = useApi<any>('/api/v2/market-intelligence', 120_000)
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/scanner', 60_000)
  const { data: watchlist } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: openTrades } = useApi<any>('/api/v2/open-trades/intelligence', 60_000)
  const { data: research } = useApi<any>('/api/v2/research-topics', 120_000)
  const { data: inference } = useApi<any>('/api/v2/inference/latest', 120_000)
  const { data: rotation } = useApi<any>('/api/v2/rotation/summary', 300_000)
  // Already-computed multi-LLM verdicts (Grok + ChatGPT + local gemma) for signals an operator has
  // previously asked to verify — joined back onto matching cards below so curation reflects LLM review
  // it actually has, instead of only showing it behind a click. No LLM call happens here; read-only join.
  const { data: ensembleFeed } = useApi<any>('/api/v2/inference/ensemble?limit=200', 120_000)
  const ensembleById = useMemo(() => {
    const m = new Map<string, EnsembleMeta>()
    // useApi already unwraps the {ok,data} envelope, so ensembleFeed IS the array — but stay defensive
    // in case the route ever nests it (matches the ?? fallback pattern used for /api/v2/command above).
    const rows: any[] = Array.isArray(ensembleFeed) ? ensembleFeed : (ensembleFeed?.data ?? [])
    rows.filter((r: any) => r.target_type === 'signal').forEach((r: any) => {
      if (!r.target_id || m.has(r.target_id)) return
      const votes = typeof r.votes === 'string' ? JSON.parse(r.votes || '[]') : (r.votes ?? [])
      const lanes = typeof r.lanes_used === 'string' ? JSON.parse(r.lanes_used || '[]') : (r.lanes_used ?? votes.map((v: any) => v.lane))
      m.set(r.target_id, { score: Number(r.final_score) || 0, decision: r.final_decision === 'approve' ? 'approve' : 'block', consensus: !!r.consensus_reached, lanes })
    })
    return m
  }, [ensembleFeed])
  const [source, setSource] = useState('all')
  const [sev, setSev] = useState('all')
  const [special, setSpecial] = useState<Special>('all')
  const [search, setSearch] = useState('')
  const [question, setQuestion] = useState('')
  const [feedback, setFeedback] = useState('')
  const [lmStatus, setLmStatus] = useState('')
  const [useGrok, setUseGrok] = useState(false)
  const [lmReview, setLmReview] = useState<{ local?: string; localErr?: string; grok?: string; grokErr?: string } | null>(null)
  const [lmBusy, setLmBusy] = useState(false)
  const [viewPreset, setViewPreset] = useState<ViewPreset>('priority')
  const [lmOpen, setLmOpen] = useState(false)
  const cmd = command?.data ?? command ?? {}

  const items = useMemo<IntelItem[]>(() => {
    const out: IntelItem[] = []
    const add = (x: Partial<IntelItem> & { raw?: any }) => { if (!x.title) return; const a = ago((x.raw as any)?.at ?? (x.raw as any)?.updated_at ?? (x.raw as any)?.last_enriched_at ?? (x.raw as any)?.created_at ?? (x.raw as any)?.generated_at); const type = x.type || 'intelligence'; const source = x.source || 'unknown'; const id = stableId(type, source, x.symbol, String(x.title)); out.push({ id, source, type, symbol: x.symbol, title: String(x.title), summary: x.summary, severity: x.severity || severityFrom(x.raw ?? x), confidence: x.confidence ?? confidenceFrom(x.raw ?? x), freshnessH: x.freshnessH ?? a.hours, model: x.model, lane: x.lane, action: x.action, raw: x.raw ?? x, ensemble: ensembleById.get(id) }) }
    // Current price by symbol from the risk feed — the /api/v2/command feed omits current price, so without
    // this the command items can't compute breach and all collapse to a flat 0.66. seenStop dedups the same
    // triggered stop showing as both a risk item AND a command item.
    const priceBy: Record<string, number> = {}
    ;(risk?.positions ?? []).forEach((p: any) => { const c = Number(p.current_price); if (p.symbol && Number.isFinite(c)) priceBy[String(p.symbol).toUpperCase()] = c })
    const seenStop = new Set<string>()
    const riskSymbols = new Set<string>()
    ;(risk?.positions ?? []).forEach((p: any) => { if (p.symbol && (p.triggered || p.triggered_stop)) seenStop.add(String(p.symbol).toUpperCase()) })
    ;(risk?.positions ?? []).filter((p: any) => p.triggered || p.near_stop || p.unprotected || p.triggered_stop).slice(0, 25).forEach((p: any) => { const sym = String(p.symbol ?? '').toUpperCase(); if (sym) riskSymbols.add(sym); const cp = Number(p.current_price), sp = Number(p.stop_price ?? p.stop); const ok = Number.isFinite(cp) && Number.isFinite(sp) && sp > 0; const breach = ok ? Math.abs(cp - sp) / sp : 0; const conf = ok ? Math.min(.96, .60 + Math.min(breach * 3, .36)) : .45; add({ source: '/api/v2/risk', type: 'risk', symbol: p.symbol, title: `${p.symbol} risk/stop review`, summary: `${p.account ?? ''} stop ${p.stop_price ?? p.stop ?? '—'} · current ${p.current_price ?? '—'}${ok ? ` · ${(breach * 100).toFixed(1)}% past stop` : ' · price missing'}`, severity: 'critical', confidence: conf, raw: p, action: 'verify stop / protection' }) })
    ;(cmd.triggered_detail ?? []).slice(0, 20).forEach((s: any) => { const sym = String(s.symbol ?? '').toUpperCase(); if (sym && seenStop.has(sym)) return; /* dedup: same stop already shown as a risk item */ const cp = Number(s.current_price) || priceBy[sym]; const sp = Number(s.stop_price ?? s.stop); const ok = Number.isFinite(cp) && Number.isFinite(sp) && sp > 0; const breach = ok ? Math.abs(cp - sp) / sp : 0; const conf = ok ? Math.min(.95, .64 + Math.min(breach * 3, .31)) : ((s.stop_price ?? s.stop) && s.symbol ? .6 : .48); add({ source: '/api/v2/command', type: 'telegram/action', symbol: s.symbol, title: `${s.symbol} triggered stop from command feed`, summary: `Stop ${s.stop_price ?? s.stop ?? '—'} · ${s.account ?? ''}${ok ? ` · current ${cp.toFixed(2)} · ${(breach * 100).toFixed(1)}% past` : ''}`, severity: 'critical', confidence: conf, raw: s, action: 'confirm broker state' }) })
    ;(brief?.action_items ?? []).forEach((a: any, i: number) => add({ source: '/api/v2/morning-brief', type: 'brief-action', title: typeof a === 'string' ? a : (a.message ?? a.title ?? a.action ?? `Action item ${i + 1}`), summary: typeof a === 'object' ? a.code ?? a.reason ?? '' : '', raw: a, action: 'review' }))
    // External-LM reports come as a daily SERIES (e.g. REPORT:aegis_morning_brief_<date>) repeating the
    // same advice with a different date — collapse each subject to its FRESHEST entry so stale repeats
    // don't flood the board. Strip a trailing date from the key to get the subject group.
    const lmGroups: Record<string, { e: any; key: string; ts: number }> = {}
    Object.entries(reportIntel?.map ?? {}).forEach(([key, arr]: any) => (arr ?? []).forEach((e: any) => {
      const subj = String(key).replace(/[_:-]?\d{4}-\d{2}-\d{2}.*$/, '').trim() || String(key)
      const ts = Date.parse(e.at ?? e.created_at ?? e.generated_at ?? e.updated_at ?? '') || 0
      const cur = lmGroups[subj]
      if (!cur || ts > cur.ts) lmGroups[subj] = { e, key, ts }
    }))
    Object.values(lmGroups).forEach(({ e, key }) => add({ source: '/api/v2/hermes/subject-intel-map?type=report', type: 'external-lm-report', title: e.recommendation ?? key, summary: [e.dissent, ...(Array.isArray(e.risk_flags) ? e.risk_flags : [])].filter(Boolean).join(' · '), model: e.model, lane: e.lane, confidence: confidenceFrom(e, .7), raw: { ...e, key }, action: e.dissent ? 'resolve counter-view' : 'review report' }))
    ;(cmd.top_news ?? []).slice(0, 30).forEach((n: any) => add({ source: '/api/v2/command', type: 'portfolio-news', symbol: n.symbol, title: n.title ?? n.headline, summary: n.why_it_matters ?? n.source, raw: n }))
    ;(market?.top_mentioned_symbols ?? []).slice(0, 20).forEach((s: any) => add({ source: '/api/v2/market-intelligence', type: 'market-signal', symbol: typeof s === 'string' ? s : s.symbol, title: `${typeof s === 'string' ? s : s.symbol} mentioned in market intelligence`, summary: typeof s === 'object' ? `${s.mentions ?? '—'} mentions` : '', raw: s, confidence: .58 }))
    ;(tradeAi?.tickers ?? []).filter((t: any) => { const d = String(t.decision ?? '').toUpperCase(); const sc = Number(t.score ?? 0); return d === 'GO' || (d === 'WAIT' && sc >= 10) || sc >= 30 }).slice(0, 40).forEach((t: any) => add({ source: '/api/v2/trade-ai', type: 'setup', symbol: t.symbol, title: `${t.symbol} ${t.decision ?? 'setup'} score ${t.score ?? '—'}`, summary: t.catalyst ?? t.reason ?? t.sector, raw: t, action: t.decision === 'GO' ? 'consider watchlist/manual setup' : 'monitor' }))
    ;(watchlist?.items ?? []).slice(0, 35).forEach((w: any) => add({ source: '/api/v2/watchlist/items', type: 'watchlist', symbol: w.symbol, title: `${w.symbol} watchlist ${w.latest_recommendation ?? w.entry_urgency ?? ''}`, summary: first(w.catalyst, w.reason, w.description, w.entry_setup, 'curated watchlist item'), raw: w, confidence: confidenceFrom(w, .68), action: w.entry_urgency === 'ready' ? 'entry review' : 'monitor' }))
    ;(openTrades?.positions ?? []).filter((p: any) => ['critical','high'].includes(String(p.operator_priority ?? '').toLowerCase()) || (p.risk_flags ?? []).length > 0).slice(0, 30).forEach((p: any) => { const rf = (p.risk_flags ?? []).length; const pr = String(p.operator_priority ?? '').toLowerCase(); const conf = Math.min(.95, .58 + 0.08 * Math.min(rf, 3) + (pr === 'critical' ? .14 : pr === 'high' ? .07 : 0) + ((p.decision_reason || p.strategy_rationale) ? .06 : 0)); add({ source: '/api/v2/open-trades/intelligence', type: 'open-trade', symbol: p.symbol, title: `${p.symbol} ${p.operator_decision ?? 'position review'}`, summary: p.decision_reason ?? p.strategy_rationale, severity: severityFrom(p), confidence: conf, raw: p, action: p.primary_next_review ?? 'review position' }) })
    ;(research?.research_gaps ?? []).slice(0, 20).forEach((g: any) => add({ source: '/api/v2/research-topics', type: 'research-gap', symbol: g.symbol, title: g.display_name ?? g.topic_id ?? g.topic ?? 'Research gap', summary: [g.reason, g.detail].filter(Boolean).join(' — '), severity: 'warning', raw: g, action: 'assign research' }))
    // Layer 4 / regime synthesis — sector rotation, opportunity, regional (deduped titles)
    const infSeen = new Set<string>()
    ;(inference?.results ?? []).slice(0, 24).forEach((r: any) => {
      const key = `${r.inference_type}:${(r.title || '').slice(0, 60)}`
      if (infSeen.has(key)) return
      infSeen.add(key)
      const t = String(r.inference_type || '')
      const infSym = String(r.subject ?? '').toUpperCase()
      if (t === 'aegis_thesis' && infSym && (riskSymbols.has(infSym) || seenStop.has(infSym))) return
      const sev: IntelItem['severity'] = r.severity === 'critical' ? 'critical' : r.severity === 'high' ? 'warning' : t === 'opportunity' || t === 'sector_rotation' ? 'positive' : 'info'
      add({
        source: '/api/v2/inference/latest', type: t || 'inference', symbol: /^[A-Z]{1,5}$/.test(r.subject || '') ? r.subject : undefined,
        title: r.title, summary: (r.body || '').slice(0, 400), severity: sev, confidence: Number(r.confidence) || 0.65,
        model: r.source_lane, raw: r,
        action: t === 'sector_rotation' ? 'review small-cap swing / rotation' : t === 'opportunity' ? 'watchlist review' : t === 'risk' ? 'verify protection' : 'review inference',
      })
    })
    // Index tape: IWM vs SPY relative strength banner when small caps lead
    const spy = overview?.index_tape?.spy
    const iwm = overview?.index_tape?.iwm
    const spyCh = Number(spy?.change_percent ?? spy?.change_pct ?? spy?.pct)
    const iwmCh = Number(iwm?.change_percent ?? iwm?.change_pct ?? iwm?.pct)
    if (Number.isFinite(spyCh) && Number.isFinite(iwmCh) && iwmCh - spyCh >= 0.35) {
      add({
        source: '/api/v2/overview', type: 'market-signal', symbol: 'IWM',
        title: `Small-cap tape: IWM ${iwmCh >= 0 ? '+' : ''}${iwmCh.toFixed(2)}% vs SPY ${spyCh >= 0 ? '+' : ''}${spyCh.toFixed(2)}%`,
        summary: `Russell 2000 outperforming large caps by ${(iwmCh - spyCh).toFixed(2)}% today — check Rotation + swing proposals.`,
        severity: 'positive', confidence: Math.min(0.9, 0.6 + (iwmCh - spyCh) / 3), raw: { spy, iwm }, action: 'review rotation / watchlist',
      })
    }
    const rotIdeas = (rotation?.top_rotation_ideas ?? rotation?.research_rotation_ideas ?? []).slice(0, 6)
    rotIdeas.forEach((p: any, i: number) => add({
      source: '/api/v2/rotation/summary', type: 'setup', symbol: p.into || p.to || p.symbol,
      title: p.label || p.idea || `Rotation idea ${i + 1}`,
      summary: [p.rationale, p.thesis, p.why].filter(Boolean).join(' · '),
      severity: 'info', confidence: 0.62, raw: p, action: 'rotation review',
    }))
    return out.sort(sortByPriority)
  }, [risk, cmd, brief, reportIntel, market, tradeAi, watchlist, openTrades, research, inference, overview, rotation, ensembleById])

  const applyKpi = (next: { source?: string; sev?: string; special?: Special; search?: string; view?: ViewPreset }) => { setSource(next.source ?? 'all'); setSev(next.sev ?? 'all'); setSpecial(next.special ?? 'all'); setSearch(next.search ?? ''); if (next.view) setViewPreset(next.view) }
  const filtered = items.filter(it => (source === 'all' || it.type === source || it.source.includes(source)) && (sev === 'all' || it.severity === sev) && (special === 'all' || (special === 'actionable' && !!it.action) || (special === 'highError' && estError(it) > .35) || (special === 'stale' && (it.freshnessH ?? 999) > 24)) && (!search || `${it.symbol ?? ''} ${it.title} ${it.summary ?? ''} ${it.action ?? ''}`.toLowerCase().includes(search.toLowerCase())))
  const displayFiltered = useMemo(() => {
    const list = viewPreset === 'priority' ? filtered.filter(it => !isLowValueSetup(it)) : filtered
    return [...list].sort(sortByPriority)
  }, [filtered, viewPreset])
  const actNowItems = useMemo(() => displayFiltered.filter(isActNow), [displayFiltered])
  const monitorItems = useMemo(() => displayFiltered.filter(it => !isActNow(it)), [displayFiltered])
  const actNowCount = useMemo(() => items.filter(isActNow).length, [items])
  const stopCount = useMemo(() => items.filter(it => it.type === 'risk').length, [items])
  const hiddenNoise = useMemo(() => items.filter(isLowValueSetup).length, [items])
  const linkStyle: React.CSSProperties = { fontSize: 10, fontWeight: 700, color: BLUE, textDecoration: 'none' }
  const sectionHead = (label: string, n: number, color = TEXT0) => (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '2px 0 8px' }}>
      <div style={{ color, fontWeight: 900, fontSize: 12 }}>{label}</div>
      <div style={{ color: MUTED, fontSize: 10 }}>{n} item{n === 1 ? '' : 's'}</div>
    </div>
  )
  const avgQ = filtered.length ? filtered.reduce((a, b) => a + qscore(b), 0) / filtered.length : 0
  const highErr = items.filter(x => estError(x) > .35).length
  const ensembleBlocked = items.filter(x => x.ensemble?.consensus && x.ensemble.decision === 'block').length
  const bySource = Object.entries(items.reduce((a: any, i) => { a[i.type] = (a[i.type] ?? 0) + 1; return a }, {})).map(([name, value]) => ({ name, value }))

  const askLm = async () => {
    const payload = { question, feedback, visible_items: filtered.slice(0, 12), page: 'command', requested_review: 'quality accuracy usefulness and actionability', use_grok: useGrok }
    setLmBusy(true); setLmReview(null)
    setLmStatus(useGrok ? 'Running local LLM + Grok review…' : 'Running local LLM review…')
    try {
      const r = await fetch('/api/v2/agents/intelligence-feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      if (!r.ok) throw new Error(String(r.status))
      const j = await r.json()
      setLmReview({ local: j.local_review, localErr: j.local_error, grok: j.grok_review, grokErr: j.grok_error })
      setLmStatus(`${j.message ?? 'Reviewed'} · ${j.latency_ms ?? '?'}ms · recorded to learning loop (#${j.id})`)
    } catch (e: any) {
      const local = JSON.parse(localStorage.getItem('tradeai.intelFeedback.v1') || '[]'); local.unshift({ at: new Date().toISOString(), payload }); localStorage.setItem('tradeai.intelFeedback.v1', JSON.stringify(local.slice(0, 50)))
      setLmStatus(`Review endpoint error (${e.message}); saved locally for agent handoff.`)
    } finally { setLmBusy(false) }
  }

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ ...panel, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
      <div>
        <div style={{ fontSize: 21, fontWeight: 950, color: TEXT0 }}>Consolidated Intelligence Command</div>
        <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>Priority view surfaces stops, open-trade reviews, and high-confidence actions first. Low-score WAIT setups stay collapsed unless you expand.</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
        <div style={{ display: 'flex', gap: 10 }}>
          <Link to="/risk" style={linkStyle}>Risk →</Link>
          <Link to="/portfolio" style={linkStyle}>Portfolio →</Link>
          <Link to="/trading?tab=Open+Trades" style={linkStyle}>Open Trades →</Link>
        </div>
        <div style={{ fontSize: 10, color: MUTED }}>{items.length} signals · avg quality <span style={{ color: avgQ > .7 ? GREEN : avgQ > .5 ? AMBER : RED, fontWeight: 800 }}>{(avgQ * 100).toFixed(0)}%</span> · {hiddenNoise} low-score setups {viewPreset === 'priority' ? 'hidden' : 'visible'}</div>
      </div>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}>
      <KPI label="Needs action" value={actNowCount} color={actNowCount ? RED : GREEN} sub="stops · open trades · verified" active={viewPreset === 'priority' && special === 'all' && sev === 'all'} onClick={() => applyKpi({ view: 'priority' })} />
      <KPI label="Stop breaches" value={stopCount} color={stopCount ? RED : GREEN} sub="risk feed" active={source === 'risk'} onClick={() => applyKpi({ source: 'risk', view: 'priority' })} />
      <KPI label="High error-rate" value={highErr} color={highErr ? RED : GREEN} sub="click to focus" active={special === 'highError'} onClick={() => applyKpi({ special: 'highError' })} />
      <KPI label="Ensemble BLOCK" value={ensembleBlocked} color={ensembleBlocked ? RED : GREEN} sub={ensembleBlocked ? 'LLM-flagged, resolve' : 'none flagged'} active={special === 'highError' && ensembleBlocked > 0} onClick={() => applyKpi({ special: 'highError', view: 'priority' })} />
      <KPI label="Portfolio" value={money(overview?.portfolio_value)} color={TEXT0} sub="open-trade focus" active={source === 'open-trade'} onClick={() => applyKpi({ source: 'open-trade', view: 'priority' })} />
    </div>
    <FilterRow source={source} setSource={setSource} sev={sev} setSev={setSev} special={special} setSpecial={setSpecial} search={search} setSearch={setSearch} types={[...new Set(items.map(i => i.type))]} viewPreset={viewPreset} setViewPreset={setViewPreset} />
    <div style={{ ...panel }}>
      <button onClick={() => setLmOpen(v => !v)} style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: 0, background: 'transparent', cursor: 'pointer', padding: 0 }}>
        <div style={{ color: TEXT0, fontWeight: 900 }}>Agent / Local LM Review & Feedback</div>
        <span style={{ color: MUTED, fontSize: 10 }}>{lmOpen ? 'collapse ▲' : 'expand ▼'}</span>
      </button>
      {lmOpen && <>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8, marginTop: 9 }}><textarea value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask the local model: What changed? Which signals conflict? What should agents verify?" style={{ ...input, minHeight: 58 }} /><textarea value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="Feedback to agents / LM critique: missing source, false positive, stale data, better decision wording..." style={{ ...input, minHeight: 58 }} /><div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 130 }}><label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: TEXT0, cursor: 'pointer' }}><input type="checkbox" checked={useGrok} onChange={e => setUseGrok(e.target.checked)} /> also ask Grok</label><button onClick={askLm} disabled={lmBusy} style={{ ...btn(true, PURPLE), flex: 1, opacity: lmBusy ? .6 : 1 }}>{lmBusy ? 'Reviewing…' : 'Run LM Review'}</button></div></div>
        {lmStatus && <div style={{ fontSize: 10, color: lmStatus.includes('Reviewed') || lmStatus.includes('recorded') ? GREEN : AMBER, marginTop: 7 }}>{lmStatus}</div>}
        {lmReview && <div style={{ display: 'grid', gridTemplateColumns: lmReview.grok || lmReview.grokErr ? '1fr 1fr' : '1fr', gap: 10, marginTop: 10 }}>
          <div style={{ background: 'rgba(96,165,250,.05)', border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}><div style={{ fontSize: 11, fontWeight: 800, color: BLUE, marginBottom: 5 }}>🖥 Local LLM (gemma)</div><div style={{ fontSize: 11.5, color: TEXT0, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{lmReview.local || <span style={{ color: AMBER }}>{lmReview.localErr || 'no response'}</span>}</div></div>
          {(lmReview.grok || lmReview.grokErr) && <div style={{ background: 'rgba(168,85,247,.05)', border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}><div style={{ fontSize: 11, fontWeight: 800, color: PURPLE, marginBottom: 5 }}>⚡ Grok</div><div style={{ fontSize: 11.5, color: TEXT0, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{lmReview.grok || <span style={{ color: AMBER }}>{lmReview.grokErr || 'no response'}</span>}</div></div>}
        </div>}
      </>}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '1.1fr .9fr', gap: 14 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {actNowItems.length > 0 && <div>
          {sectionHead('Act now', actNowItems.length, RED)}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 10 }}>{actNowItems.map(it => <ItemCard key={it.id} item={it} onDrill={onDrill} />)}</div>
        </div>}
        {monitorItems.length > 0 && <div>
          {sectionHead(viewPreset === 'priority' ? 'Monitor (top)' : 'Monitor', viewPreset === 'priority' ? Math.min(6, monitorItems.length) : monitorItems.length, AMBER)}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 10 }}>{(viewPreset === 'priority' ? monitorItems.slice(0, 6) : monitorItems).map(it => <ItemCard key={it.id} item={it} onDrill={onDrill} />)}</div>
          {viewPreset === 'priority' && monitorItems.length > 6 && <button onClick={() => setViewPreset('all')} style={{ ...btn(), marginTop: 4, alignSelf: 'flex-start' }}>Show {monitorItems.length - 6} more monitor items</button>}
        </div>}
        {displayFiltered.length === 0 && <div style={{ ...panel, color: MUTED, fontSize: 12 }}>No items match the current filters. Try clearing filters or showing all signals.</div>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={panel}>
          <div style={{ color: TEXT0, fontWeight: 900, marginBottom: 8 }}>Decision implications</div>
          {displayFiltered.slice(0, 8).map(it => <div key={it.id} style={{ borderBottom: '1px solid rgba(148,163,184,.13)', padding: '7px 0' }}><div style={{ color: sevColor(it.severity), fontSize: 10, fontWeight: 900 }}>{it.action ?? 'review'}</div><div style={{ color: TEXT2, fontSize: 11 }}>{it.symbol ? `${it.symbol}: ` : ''}{it.title}</div><div style={{ color: MUTED, fontSize: 9, marginTop: 2 }}>{nextStep(it)}</div></div>)}
        </div>
        <div style={panel}>
          <div style={{ color: TEXT0, fontWeight: 900, marginBottom: 8 }}>Source health</div>
          {bySource.map(s => <button key={s.name} onClick={() => applyKpi({ source: String(s.name) })} style={{ width: '100%', display: 'flex', justifyContent: 'space-between', padding: '6px 0', border: 0, borderBottom: '1px solid rgba(148,163,184,.12)', fontSize: 11, background: 'transparent', cursor: 'pointer' }}><span style={{ color: source === s.name ? BLUE : MUTED }}>{s.name}</span><span style={{ color: TEXT0, fontWeight: 850 }}>{String(s.value)}</span></button>)}
        </div>
      </div>
    </div>
  </div>
}

function FilterRow({ source, setSource, sev, setSev, special, setSpecial, search, setSearch, types, viewPreset, setViewPreset }: any) {
  return <div style={{ ...panel, display: 'grid', gridTemplateColumns: '130px 180px 160px 170px 1fr', gap: 9, alignItems: 'center' }}>
    <select value={viewPreset ?? 'priority'} onChange={e => setViewPreset?.(e.target.value)} style={input}><option value="priority">Priority view</option><option value="all">Show all signals</option></select>
    <select value={source} onChange={e => setSource(e.target.value)} style={input}><option value="all">All sources/types</option>{types.map((t: string) => <option key={t} value={t}>{t}</option>)}</select>
    <select value={sev} onChange={e => setSev(e.target.value)} style={input}><option value="all">All severities</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option><option value="positive">Positive</option></select>
    <select value={special} onChange={e => setSpecial(e.target.value)} style={input}><option value="all">All quality</option><option value="actionable">Actionable only</option><option value="highError">High error-rate</option><option value="stale">Stale / unknown</option></select>
    <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter by symbol, topic, source, decision, trend, implication…" style={input} />
  </div>
}
