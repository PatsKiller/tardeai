import { useEffect, useMemo, useState } from 'react'
import FibChartsInline from './FibChartsInline'
import AnalystReviews, { useAnalystMap } from './AnalystReviews'
import InsiderActivity from './InsiderActivity'
import FinvizEnrichmentPanel from './FinvizEnrichmentPanel'
import OptionChainPanel from './OptionChainPanel'
import HoldingReportLinks from './HoldingReportLinks'
import SymbolJourneyPanel from './SymbolJourneyPanel'
import { useAnalystReportMap } from '../hooks/useAnalystReportMap'
import { EvidenceBlock } from './EvidenceBlock'

// finviz-derived recom fields are NOT analyst ratings (known correction): finviz 'recom' is a momentum
// number, and the holdings enrichment mislabels it as 'Strong Sell' (e.g. SCHD recom 1.34 → labeled
// Strong Sell, contradicting Yahoo's real consensus). Suppress them from the record so the drawer shows
// only the real Yahoo consensus (via the Analyst reviews section).
const SUPPRESS_KEYS = new Set(['analyst_rating', 'recom_score', 'recom_raw'])

export interface DrillContext {
  title: string
  subtitle?: string
  endpoint: string
  rows: Record<string, any>[]
  links?: { label: string; href: string; note?: string }[]
  subjectType?: string
  subjectKey?: string
  /** Option chain drill — show chain table instead of stock intel panels */
  chainMode?: boolean
  highlightStrike?: number
  highlightExpiration?: string
  chainSide?: 'call' | 'put'
}

interface Props { ctx: DrillContext | null; onClose: () => void }

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
const TEAL = '#2dd4bf'
const panel = { background: 'rgba(15,23,42,.72)', border: '1px solid rgba(148,163,184,.20)', borderRadius: 12, padding: 14 } as const
const metric = { background: 'rgba(2,6,23,.40)', border: '1px solid rgba(148,163,184,.18)', borderRadius: 10, padding: '10px 12px' } as const

const KEY_LABELS: Record<string, string> = {
  pnl: 'P&L', total_pnl: 'Total P&L', rsi: 'RSI', win_rate: 'Win Rate', avg_confidence: 'Avg Confidence',
  eval_overall_score: 'Overall Score', eval_verdict: 'Verdict', profit_factor: 'Profit Factor', r_multiple: 'R Multiple',
  proposed_entry: 'Entry', proposed_target1: 'Target', proposed_stop: 'Stop', strategy_id: 'Strategy', object_id: 'ID',
  last_enriched_at: 'Last AI Enriched', last_validated_at: 'Last Validated', latest_recommendation: 'CIO View',
  entry_limit: 'Entry Limit', entry_stop: 'Stop', entry_target: 'Target', entry_rr: 'R:R', operator_decision: 'Decision',
}
const ACRONYMS = /\b(Pnl|Rsi|Raci|Id|Url|Llm|Atr|Mfe|Mae|Vwap|Macd|Adx|Pf|Wr|Rr|Cio|Tca|Pct|Bb|Rvol)\b/gi
const SECTION_RE = /^[—\-]{1,2}\s*(.+?)\s*[—\-]{1,2}$/
const LLM_META: Record<string, { label: string; color: string }> = { grok: { label: 'Grok', color: '#1d9bf0' }, chatgpt: { label: 'ChatGPT', color: '#10a37f' }, claude: { label: 'Claude', color: '#d97757' }, local: { label: 'Local', color: '#2dd4bf' } }

function humanizeKey(k: string): string { if (KEY_LABELS[k]) return KEY_LABELS[k]; return k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(ACRONYMS, m => ({ pnl: 'P&L', rsi: 'RSI', raci: 'RACI', id: 'ID', url: 'URL', llm: 'LLM', atr: 'ATR', mfe: 'MFE', mae: 'MAE', vwap: 'VWAP', macd: 'MACD', adx: 'ADX', pf: 'PF', wr: 'WR', rr: 'R:R', cio: 'CIO', tca: 'TCA', pct: '%', bb: 'BB', rvol: 'RVOL' }[m.toLowerCase()] || m)) }
function parseMaybeJson(v: any): any { if (v && typeof v === 'object') return v; if (typeof v === 'string') { const t = v.trim(); if ((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))) { try { return JSON.parse(t) } catch {} } } return null }
function isEmptyVal(v: any): boolean { if (v == null) return true; if (typeof v === 'string') { const t = v.trim().toLowerCase(); if (t === '' || t === 'null' || t === 'none' || t === 'n/a' || t === 'undefined') return true } const obj = parseMaybeJson(v); if (Array.isArray(obj)) return obj.length === 0; if (obj && typeof obj === 'object') return Object.values(obj).every(isEmptyVal); return false }
function statusColor(v: any): string | undefined { const t = String(v ?? '').toLowerCase(); if (/\b(agree|allowed|operational|completed|promoted|approved|win|good|pass|active|on|buy|bullish|fresh|protected|yes)\b/.test(t)) return GREEN; if (/\b(disagree|disabled|error|rejected|failed|loss|blocked|critical|naked|off|avoid|sell|bearish|stale|unprotected|no)\b/.test(t)) return RED; if (/\b(wait|caution|shadow|staged|pending|review|warning|weak|hold|neutral|partial)\b/.test(t)) return AMBER; return undefined }
function fmtScalar(v: any): { text: string; color?: string } { if (v == null || v === '') return { text: '—', color: DIM }; if (typeof v === 'boolean') return { text: v ? 'yes' : 'no', color: v ? GREEN : DIM }; if (typeof v === 'number') return { text: Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(Number(v.toFixed(4))), color: v < 0 ? RED : undefined }; if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T[\d:.]/.test(v)) { const d = new Date(v); if (!isNaN(d.getTime())) return { text: d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } } const s = String(v); return { text: s, color: statusColor(s) } }
function ago(v: any) { if (!v) return ''; const t = new Date(v).getTime(); if (!Number.isFinite(t)) return ''; const h = Math.round((Date.now() - t) / 36e5); if (h < 1) return 'just now'; if (h < 48) return `${h}h ago`; return `${Math.round(h / 24)}d ago` }
function money(v: any) { const n = Number(v); return Number.isFinite(n) ? `$${n.toFixed(2)}` : '—' }
function pick(row: any, keys: string[]) { for (const k of keys) if (!isEmptyVal(row?.[k])) return row[k]; return null }
function chipColor(v: any) { return statusColor(v) || BLUE }
function fmtBlob(v: any): string[] { if (v == null) return []; let x = v; if (typeof x === 'string') { try { x = JSON.parse(x) } catch { return [x] } } if (Array.isArray(x)) return x.map((e: any) => typeof e === 'object' ? Object.values(e).filter(Boolean).join(' · ') : String(e)); if (typeof x === 'object') return Object.values(x).filter(Boolean).map(String); return [String(x)] }

function Metric({ label, value, color = TEXT0 }: any) { return <div style={metric}><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 850 }}>{label}</div><div style={{ fontSize: 14, fontWeight: 950, color, marginTop: 4, lineHeight: 1.15 }}>{value || '—'}</div></div> }
function Chip({ text, color = BLUE }: any) { return <span style={{ fontSize: 10, fontWeight: 850, padding: '3px 8px', borderRadius: 6, background: color + '22', color, border: `1px solid ${color}55`, whiteSpace: 'nowrap' }}>{text}</span> }
function Section({ title, subtitle, children, accent = BLUE }: any) { return <div style={{ ...panel, borderLeft: `4px solid ${accent}` }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 9 }}><div style={{ fontSize: 12, fontWeight: 950, color: TEXT0, textTransform: 'uppercase', letterSpacing: '.04em' }}>{title}</div>{subtitle && <div style={{ fontSize: 10, color: MUTED }}>{subtitle}</div>}</div>{children}</div> }

function ObjBlock({ obj }: { obj: any }) {
  if (Array.isArray(obj)) return <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{obj.filter(x => !isEmptyVal(x)).map((x, i) => { const inner = parseMaybeJson(x); return <div key={i} style={{ padding: '8px 10px', background: 'rgba(2,6,23,.32)', borderRadius: 8, border: '1px solid rgba(148,163,184,.12)' }}>{inner && typeof inner === 'object' ? <ObjBlock obj={inner} /> : <div style={{ fontSize: 11, color: TEXT2, lineHeight: 1.5 }}>• {String(x)}</div>}</div> })}</div>
  if (obj && typeof obj === 'object' && (obj.title || obj.why_it_matters || obj.url)) return <div>{obj.title && <div style={{ fontSize: 12, fontWeight: 850, color: TEXT0, lineHeight: 1.45 }}>{String(obj.title)}</div>}<div style={{ fontSize: 10, color: MUTED, marginTop: 2 }}>{[obj.source, obj.age_hours != null ? `${Math.round(Number(obj.age_hours))}h ago` : (obj.published_at ? new Date(obj.published_at).toLocaleString() : null), obj.severity, obj.sentiment].filter(Boolean).join(' · ')}</div>{obj.why_it_matters && <div style={{ fontSize: 11, color: TEXT2, marginTop: 5, lineHeight: 1.5 }}><b style={{ color: TEXT1 }}>Why it matters:</b> {String(obj.why_it_matters)}</div>}{obj.url && <a href={obj.url} target="_blank" rel="noreferrer" style={{ fontSize: 10, color: '#bfdbfe', fontWeight: 800 }}>open source →</a>}</div>
  const entries = Object.entries(obj || {}).filter(([, vv]) => !isEmptyVal(vv))
  if (entries.length === 0) return <span style={{ fontSize: 10, color: MUTED }}>(nothing notable)</span>
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px,1fr))', gap: 6 }}>{entries.map(([kk, vv]) => { const inner = parseMaybeJson(vv); if (inner && typeof inner === 'object') return <div key={kk} style={{ gridColumn: '1 / -1', padding: '4px 0' }}><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', fontWeight: 850 }}>{humanizeKey(kk)}</div><div style={{ marginTop: 4 }}><ObjBlock obj={inner} /></div></div>; const f = fmtScalar(vv); return <div key={kk} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, borderBottom: '1px solid rgba(148,163,184,.12)', padding: '4px 0' }}><span style={{ fontSize: 10, color: MUTED }}>{humanizeKey(kk)}</span><span style={{ fontSize: 11, color: f.color || TEXT1, fontWeight: f.color ? 850 : 650, textAlign: 'right', wordBreak: 'break-word' }}>{f.text}</span></div> })}</div>
}
function Field({ k, v }: { k: string; v: any }) { const sec = k.match(SECTION_RE); if (sec) return <div style={{ gridColumn: '1 / -1', fontSize: 10, fontWeight: 900, letterSpacing: '.06em', textTransform: 'uppercase', color: TEXT2, margin: '10px 0 4px', paddingBottom: 4, borderBottom: '1px solid rgba(148,163,184,.18)' }}>{sec[1]}</div>; const obj = parseMaybeJson(v); if (obj && typeof obj === 'object') return <div style={{ gridColumn: '1 / -1', padding: '8px 0', borderBottom: '1px solid rgba(148,163,184,.12)' }}><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', marginBottom: 5, fontWeight: 850 }}>{humanizeKey(k)}</div><ObjBlock obj={obj} /></div>; const f = fmtScalar(v); return <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '5px 0', borderBottom: '1px solid rgba(148,163,184,.12)' }}><span style={{ color: MUTED, fontSize: 10 }}>{humanizeKey(k)}</span><span style={{ color: f.color || TEXT0, fontSize: 11.5, fontWeight: f.color ? 850 : 600, textAlign: 'right', wordBreak: 'break-word' }}>{f.text}</span></div> }

export default function DetailDrawer({ ctx, onClose }: Props) {
  const [intel, setIntel] = useState<any>(null)
  useEffect(() => {
    setIntel(null)
    if (!ctx) return
    let cancelled = false
    const row = ctx.rows?.[0] ?? {}
    const symCand = String(row.symbol || ctx.subjectKey || (ctx.title || '').match(/^[A-Z]{1,5}\b/)?.[0] || '').toUpperCase().trim()
    const stockSym = /^[A-Z]{1,5}$/.test(symCand) ? symCand : ''
    const chain = ctx.chainMode || (ctx.endpoint || '').includes('option-chain')
    const journey = (ctx.endpoint || '').includes('symbol-journey')
    const url = ctx.endpoint?.startsWith('/api/v2/hermes/intel/')
      ? ctx.endpoint
      : stockSym && !chain && !journey
        ? `/api/v2/hermes/intel/${stockSym}`
        : (ctx.subjectType && ctx.subjectKey)
          ? `/api/v2/hermes/subject-intel?type=${encodeURIComponent(ctx.subjectType)}&key=${encodeURIComponent(ctx.subjectKey)}`
          : null
    if (!url) return
    fetch(url).then(r => r.ok ? r.json() : null).then(j => { if (!cancelled && j?.data) setIntel(j.data); else if (!cancelled && j && !j.data) setIntel(j) }).catch(() => {})
    return () => { cancelled = true }
  }, [ctx])

  const primary = ctx?.rows?.[0] ?? {}
  // symbol for the inline charts: prefer the record's symbol, else the subjectKey, else parse the title.
  const drawerSymbol = useMemo(() => {
    const cand = String(primary.symbol || ctx?.subjectKey || (ctx?.title || '').match(/^[A-Z]{1,5}\b/)?.[0] || '').toUpperCase().trim()
    return /^[A-Z]{1,5}$/.test(cand) ? cand : ''
  }, [primary, ctx])
  const aMap = useAnalystMap()
  const reportMap = useAnalystReportMap()
  const actionMetrics = useMemo(() => {
    if (!ctx) return []
    return [
      ['CIO view', pick(primary, ['latest_recommendation', 'operator_decision', 'recommendation', 'signal'])],
      ['Score', pick(primary, ['score', 'hermes_composite_score', 'eval_overall_score', 'pi_score'])],
      ['Entry', pick(primary, ['entry_limit', 'proposed_entry', 'entry_price', 'limit_price'])],
      ['Stop', pick(primary, ['entry_stop', 'proposed_stop', 'stop_price'])],
      ['Target', pick(primary, ['entry_target', 'proposed_target1', 'target_price'])],
      ['R:R', pick(primary, ['entry_rr', 'rr', 'risk_reward'])],
      ['RSI', pick(primary, ['rsi', 'current_rsi'])],
      ['Freshness', pick(primary, ['last_enriched_at', 'updated_at', 'last_validated_at'])],
    ].filter(([, v]) => !isEmptyVal(v))
  }, [ctx, primary])

  const chainMode = ctx?.chainMode || (ctx?.endpoint || '').includes('option-chain')
  const journeyMode = (ctx?.endpoint || '').includes('symbol-journey')
  const showStockIntel = !chainMode && !journeyMode && !!drawerSymbol

  if (!ctx) return null
  return <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end', background: 'rgba(2,6,23,.22)' }} onClick={onClose}>
    <div onClick={e => e.stopPropagation()} style={{ width: 'min(1320px, 96vw)', height: '100vh', background: 'linear-gradient(180deg, #111827, #0f172a)', borderLeft: '1px solid rgba(148,163,184,.22)', display: 'flex', flexDirection: 'column', boxShadow: '-10px 0 40px rgba(0,0,0,.55)' }}>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(148,163,184,.18)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexShrink: 0 }}>
        <div><div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}><div style={{ fontSize: 20, fontWeight: 950, color: TEXT0 }}>{ctx.title}</div>
          {/* rotation review lives here (not on the card) — rotatable holdings only: not cash, not a mutual fund */}
          {drawerSymbol && !primary.is_cash && (
            <HoldingReportLinks
              symbol={drawerSymbol}
              entry={reportMap[drawerSymbol]}
              reportType={reportMap[drawerSymbol]?.report_type}
            />
          )}
          {drawerSymbol && !primary.is_cash && !/^[A-Z]{4,5}X$/.test(drawerSymbol) && <a href={`/v3/rotation?question=${encodeURIComponent(`Review whether ${drawerSymbol} exposure should be reduced`)}`} title="Review this exposure in the Rotation Advisor (advisory · no broker action)" style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 6, textDecoration: 'none', background: 'rgba(96,165,250,.13)', color: '#60a5fa', border: '1px solid rgba(96,165,250,.32)' }}>⤢ Rotation review →</a>}</div>{ctx.subtitle && <div style={{ fontSize: 12, color: MUTED, marginTop: 3 }}>{ctx.subtitle}</div>}<div style={{ fontSize: 10, color: DIM, fontFamily: 'monospace', marginTop: 8 }}>Source: {ctx.endpoint}</div></div>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 22, padding: '0 4px' }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {ctx.links && ctx.links.length > 0 && <Section title="Where to act" accent={BLUE}><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{ctx.links.map((l, i) => <a key={i} href={l.href} title={l.note} style={{ fontSize: 12, fontWeight: 850, color: '#bfdbfe', textDecoration: 'none', padding: '6px 12px', borderRadius: 7, background: 'rgba(96,165,250,.13)', border: '1px solid rgba(96,165,250,.32)' }}>{l.label} →</a>)}</div></Section>}
        {actionMetrics.length > 0 && <Section title="Action board" subtitle="key fields surfaced from the record" accent={GREEN}><div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(150px,1fr))', gap: 10 }}>{actionMetrics.map(([k, v]) => { const f = fmtScalar(v); return <Metric key={k} label={k} value={k === 'Freshness' ? (ago(v) || f.text) : (String(k).match(/Entry|Stop|Target/) ? money(v) : f.text)} color={f.color || (k === 'Stop' ? RED : k === 'Entry' || k === 'Target' ? TEXT0 : TEXT1)} /> })}</div></Section>}
        {chainMode && ctx.endpoint && (
          <Section title="Option chain" subtitle="Schwab live quotes · bid/ask/mid · read-only" accent={BLUE}>
            <OptionChainPanel
              endpoint={ctx.endpoint}
              highlightStrike={ctx.highlightStrike}
              highlightExp={ctx.highlightExpiration}
              defaultSide={ctx.chainSide || 'call'}
            />
          </Section>
        )}
        {journeyMode && ctx.endpoint && <SymbolJourneyPanel endpoint={ctx.endpoint} />}
        {showStockIntel && drawerSymbol && aMap[drawerSymbol] && <Section title="Analyst reviews & targets" subtitle="Yahoo consensus + finnhub distribution · aggregated (no firm names in feed)" accent={GREEN}><AnalystReviews symbol={drawerSymbol} map={aMap} /></Section>}
        {showStockIntel && drawerSymbol && <Section title="Charts · daily & monthly" subtitle="swing · Fibonacci · confluence as price lines · advisory" accent={BLUE}><FibChartsInline symbol={drawerSymbol} /></Section>}
        {showStockIntel && drawerSymbol && !primary.is_cash && /^[A-Z]{1,5}$/.test(drawerSymbol) && !/^[A-Z]{4,5}X$/.test(drawerSymbol) && (
          <Section title="Finviz technical chart" subtitle="daily candles · SMA 20/50/200 · RSI/volume overlays (Finviz)" accent={BLUE}>
            <img src={`https://charts2.finviz.com/chart.ashx?t=${drawerSymbol}&ty=c&ta=1&p=d&s=l`}
                 alt={`Finviz chart for ${drawerSymbol}`} loading="lazy"
                 style={{ width: '100%', maxWidth: 760, borderRadius: 8, border: '1px solid var(--border)', background: '#fff' }}
                 onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }} />
            <div style={{ fontSize: 9, color: DIM, marginTop: 4 }}>Source: Finviz charts2.finviz.com · technical overlay · advisory</div>
          </Section>
        )}
        {showStockIntel && drawerSymbol && !primary.is_cash && /^[A-Z]{1,5}$/.test(drawerSymbol) && (
          <Section title="Finviz metrics" subtitle="technicals · performance · valuation · fundamentals · ownership (Finviz daily)" accent={BLUE}><FinvizEnrichmentPanel symbol={drawerSymbol} /></Section>
        )}
        {showStockIntel && drawerSymbol && !primary.is_cash && /^[A-Z]{1,5}$/.test(drawerSymbol) && (
          <Section title="Insider activity · SEC Form 4" subtitle="recent insider filings (authoritative · advisory)" accent={AMBER}><InsiderActivity symbol={drawerSymbol} /></Section>
        )}
        {(primary.llm_evidence?.length > 0 || (primary.llm_data_i_doubt && primary.llm_data_i_doubt !== 'none') || primary.llm_health) && (
          <Section title="Holdings LLM health" subtitle={primary.llm_health ? `${primary.llm_health} · ${primary.llm_action || '—'}` : 'structured evidence from holdings refresh'} accent={TEAL}>
            {primary.llm_summary && <div style={{ fontSize: 11, color: TEXT2, marginBottom: 6, lineHeight: 1.45 }}>{typeof primary.llm_summary === 'string' ? primary.llm_summary.slice(0, 280) : ''}</div>}
            <EvidenceBlock evidence={primary.llm_evidence} dataIDoubt={primary.llm_data_i_doubt} />
          </Section>
        )}
        {primary.protection_advisory && (primary.protection_advisory.evidence?.length > 0 || (primary.protection_advisory.data_i_doubt && primary.protection_advisory.data_i_doubt !== 'none')) && (
          <Section title="Stop advisory evidence" subtitle={primary.protection_advisory.model ? `${primary.protection_advisory.model} · stop $${primary.protection_advisory.stop_price ?? '—'}` : 'protection advisor'} accent={AMBER}>
            {primary.protection_advisory.rationale && <div style={{ fontSize: 11, color: TEXT2, marginBottom: 6, lineHeight: 1.45 }}>{String(primary.protection_advisory.rationale).slice(0, 320)}</div>}
            <EvidenceBlock evidence={primary.protection_advisory.evidence} dataIDoubt={primary.protection_advisory.data_i_doubt} />
          </Section>
        )}
        {primary.stop_curation && (primary.stop_curation.evidence?.length > 0 || (primary.stop_curation.data_i_doubt && primary.stop_curation.data_i_doubt !== 'none') || primary.stop_curation.grade) && (
          <Section title="Grok stop curation" subtitle={primary.stop_curation.grade ? `grade ${primary.stop_curation.grade}` : 'external LLM R:R review'} accent={PURPLE}>
            {primary.stop_curation.rr_assessment && <div style={{ fontSize: 11, color: TEXT2, marginBottom: 6, lineHeight: 1.45 }}>{primary.stop_curation.rr_assessment}</div>}
            <EvidenceBlock evidence={primary.stop_curation.evidence} dataIDoubt={primary.stop_curation.data_i_doubt} />
          </Section>
        )}
        {intel?.cio_synthesis && (intel.cio_synthesis.evidence?.length > 0 || intel.cio_synthesis.narrative_snip || (intel.cio_synthesis.data_i_doubt && intel.cio_synthesis.data_i_doubt !== 'none')) && (
          <Section title="CIO synthesis evidence" subtitle={intel.cio_synthesis.recommendation ? `recommendation: ${intel.cio_synthesis.recommendation}` : 'watchlist committee synthesis'} accent={PURPLE}>
            {intel.cio_synthesis.narrative_snip && <div style={{ fontSize: 11, color: TEXT2, marginBottom: 6, lineHeight: 1.45, fontStyle: 'italic' }}>{intel.cio_synthesis.narrative_snip}</div>}
            <EvidenceBlock evidence={intel.cio_synthesis.evidence} dataIDoubt={intel.cio_synthesis.data_i_doubt} />
          </Section>
        )}
        {intel?.setup && <Section title={`Hermes setup · ${intel.setup.conviction || 'unknown'} conviction`} accent={PURPLE}><div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 12 }}><div><div style={{ fontSize: 16, color: '#d8b4fe', fontWeight: 950 }}>{intel.setup.type}</div><div style={{ fontSize: 12, color: TEXT2, marginTop: 7, lineHeight: 1.5 }}><b style={{ color: TEXT1 }}>Entry:</b> {intel.setup.entry}</div><div style={{ fontSize: 12, color: TEXT2, lineHeight: 1.5 }}><b style={{ color: TEXT1 }}>Invalidation:</b> {intel.setup.invalidation}</div><div style={{ fontSize: 11, color: MUTED, marginTop: 5 }}>{intel.setup.why}</div></div>{intel.competition && <div style={{ ...metric }}><div style={{ fontSize: 9, color: MUTED, fontWeight: 850, textTransform: 'uppercase' }}>Competition / peer context</div><ObjBlock obj={intel.competition} /></div>}</div></Section>}
        {intel?.external_intel?.length > 0 && <Section title={`External LLM intelligence (${intel.external_intel.length})`} subtitle="recommendation, structured evidence, counter-view, risk flags" accent={BLUE}><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(420px,1fr))', gap: 12 }}>{intel.external_intel.map((e: any, i: number) => { const m = LLM_META[e.lane] || { label: e.lane || 'LLM', color: TEXT2 }; const rf = fmtBlob(e.risk_flags); return <div key={i} style={{ background: 'rgba(2,6,23,.38)', border: `1px solid ${m.color}55`, borderLeft: `5px solid ${m.color}`, borderRadius: 11, padding: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 7 }}><span style={{ fontSize: 13, fontWeight: 950, color: m.color }}>{m.label}<span style={{ color: MUTED, fontWeight: 500, fontSize: 10, marginLeft: 6 }}>{e.model}</span></span><span style={{ fontSize: 10, color: MUTED }}>{e.at ? new Date(e.at).toLocaleString() : ''}</span></div>{e.recommendation && <div style={{ fontSize: 12.5, color: TEXT0, fontWeight: 850, lineHeight: 1.45, marginBottom: 6 }}>{e.recommendation}</div>}<EvidenceBlock evidence={e.evidence} dataIDoubt={e.data_i_doubt} compact />{e.dissent && <div style={{ fontSize: 11, color: AMBER, marginTop: 5, lineHeight: 1.45 }}><b>Counter-view:</b> {e.dissent}</div>}{rf.length > 0 && <div style={{ fontSize: 11, color: RED, marginTop: 5, lineHeight: 1.45 }}><b>Risks:</b> {rf.join('; ')}</div>}{e.confidence != null && <div style={{ marginTop: 7 }}><Chip text={`confidence ${e.confidence}`} color={chipColor(e.confidence)} /></div>}</div> })}</div></Section>}
        {ctx.rows.length === 0 && !chainMode && !journeyMode && <Section title="No data" accent={DIM}><div style={{ color: MUTED, fontSize: 12 }}>No data rows.</div></Section>}
        {ctx.rows.map((row, i) => { const entries = Object.entries(row).filter(([k, v]) => !SUPPRESS_KEYS.has(k) && (k.match(SECTION_RE) || !isEmptyVal(v))); const hidden = Object.keys(row).length - entries.length; return <Section key={i} title={ctx.rows.length > 1 ? `Source record ${i + 1}` : 'Source record'} subtitle={hidden > 0 ? `${hidden} empty fields hidden` : undefined} accent={DIM}><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', columnGap: 28, rowGap: 2 }}>{entries.map(([k, v]) => <Field key={k} k={k} v={v} />)}</div></Section> })}
      </div>
      <div style={{ padding: '10px 16px', borderTop: '1px solid rgba(148,163,184,.18)', fontSize: 9, color: MUTED, textAlign: 'center' }}>Read-only intelligence drawer. No order controls, no broker writes, advisory review only.</div>
    </div>
  </div>
}

export function DrawerStat({ label, value, color }: { label: string; value: string; color?: string }) { return <div style={{ padding: '8px 0', borderBottom: '1px solid rgba(148,163,184,.12)' }}><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase' }}>{label}</div><div style={{ fontSize: 13, fontWeight: 850, color: color || TEXT0 }}>{value}</div></div> }
