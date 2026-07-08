import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AdvisorChangesPanel from '../components/AdvisorChangesPanel'

const PAGE_TABS = ['Review', 'Advisor Guide'] as const

// ── Types ──────────────────────────────────────────────────────────────────
type AmountRange = { low?: number; high?: number; basis?: string; action?: string }
type ShareRange = { low?: number; high?: number }
type RotationPair = {
  action_class?: string
  from_symbol?: string
  to_symbol?: string
  from_account?: string
  to_account?: string
  score?: number
  review_amount?: number
  review_amount_range?: AmountRange
  from_price?: number
  to_price?: number
  from_shares_held?: number
  sell_shares_range?: ShareRange
  buy_shares_range?: ShareRange
  from_degradation?: Degradation | null
  entry_plan?: any
  rationale?: string
}

type SectorOverweight = {
  theme?: string
  pct?: number
  target?: number
  excess_pct?: number
  excess_dollars?: number
  top_holdings?: string[]
}
type SectorUnderweight = { theme?: string; pct?: number; floor?: number; gap_pct?: number }
type Degradation = {
  thesis_status?: string
  severity?: number
  signal_source?: string
  deterministic?: boolean
  escalation_reason?: string
  technical_drift?: string
  what_changed?: string
  near_52wk_low_pct?: number
  analyst_recom?: number
  needs_review?: boolean
}
type DegradedHolding = Degradation & {
  symbol?: string
  sector?: string
  account_type?: string
  current_value?: number
  price?: number
  day_change_pct?: number
  est_shares?: number
}

type RotationData = {
  ok?: boolean
  advisory_only?: boolean
  error?: string
  cached_at?: string
  cache_age_sec?: number
  stale?: boolean
  portfolio_total?: number
  summary?: {
    trim_review?: number
    add_review?: number
    rotation_ideas?: number
    watch?: number
  }
  data_quality?: Record<string, any>
  missing_sector?: number
  missing_analyst_upside?: number
  sector_overweights?: SectorOverweight[]
  sector_underweights?: SectorUnderweight[]
  degraded_holdings?: DegradedHolding[]
  top_rotation_ideas?: RotationPair[]
  top_pairs?: RotationPair[]
  top_candidates?: any[]
  fee_swaps?: any[]
  total_annual_fee_usd?: number | null
  research_candidates?: any[]
  etf_candidates?: any[]
  research_rotation_ideas?: RotationPair[]
  generated_at?: string
}

type ValidationObj = { ok?: boolean; issues?: string[] }
type AskResult = {
  ok?: boolean
  error?: string
  stderr_tail?: string
  advisory_only?: boolean
  backend?: string
  answer_mode?: string
  answer?: string
  grounded_answer?: string
  local_answer_validation?: ValidationObj
  local_answer_raw?: string
  grok_oauth_prompt_path?: string
  grok_second_opinion?: { mode?: string;[k: string]: any }
  rotation_summary?: any
  grounding_report?: any
}

type GrokPromptResult = {
  ok?: boolean
  advisory_only?: boolean
  grok_available?: boolean
  grok_answer?: string
  prompt_text?: string
  prompt_path?: string
  note?: string
  error?: string
}

// ── Style helpers ───────────────────────────────────────────────────────────
const ACCENT = '#60a5fa'
const card: React.CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16,
}
const btn = (active: boolean): React.CSSProperties => ({
  padding: '6px 14px', fontSize: 12, borderRadius: 6, cursor: active ? 'not-allowed' : 'pointer',
  border: `1px solid ${ACCENT}55`, background: active ? 'var(--bg2)' : 'rgba(96,165,250,.15)',
  color: active ? 'var(--text3)' : ACCENT, fontWeight: 700,
})

const ACTION_BADGE: Record<string, { label: string; c: string }> = {
  WATCH: { label: 'WATCH', c: '#f59e0b' },
  ADD_REVIEW: { label: 'ADD REVIEW', c: '#22c55e' },
  TRIM_REVIEW: { label: 'TRIM REVIEW', c: '#ef4444' },
  ROTATE_REVIEW: { label: 'ROTATE REVIEW', c: '#60a5fa' },
  RESEARCH_MORE: { label: 'RESEARCH MORE', c: '#6b7280' },
}

const money = (v?: number) =>
  typeof v === 'number'
    ? v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : 'review range unavailable'

function ActionBadge({ cls }: { cls?: string }) {
  const m = ACTION_BADGE[(cls || '').toUpperCase()] ?? { label: cls || 'REVIEW', c: '#6b7280' }
  return (
    <span style={{
      fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, letterSpacing: 0.4,
      background: `${m.c}1f`, color: m.c, border: `1px solid ${m.c}44`,
    }}>{m.label}</span>
  )
}

const DEG_C: Record<string, string> = { triggered: '#ef4444', danger: '#ef4444', broken: '#ef4444', warning: '#f59e0b', weakening: '#f59e0b' }
function DegBadge({ d }: { d?: { thesis_status?: string; deterministic?: boolean; signal_source?: string } }) {
  if (!d?.thesis_status) return null
  const c = DEG_C[d.thesis_status] ?? '#f59e0b'
  const src = d.deterministic ? 'stop math' : 'LLM read'
  return (
    <span title={`Source: ${d.signal_source ?? 'aegis'} (${d.deterministic ? 'deterministic stop-distance' : 'gemma3 thesis read'})`}
      style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 7px', borderRadius: 4, letterSpacing: 0.3,
        background: `${c}1f`, color: c, border: `1px solid ${c}55`, whiteSpace: 'nowrap' }}>
      {d.thesis_status.toUpperCase()} · {src}
    </span>
  )
}

function SummaryCard({ label, value, color, onClick, active }: { label: string; value: React.ReactNode; color?: string; onClick?: () => void; active?: boolean }) {
  const clickable = !!onClick
  return (
    <div onClick={onClick} title={clickable ? `Show ${label}` : undefined}
      style={{ ...card, textAlign: 'center', padding: '14px 10px',
        cursor: clickable ? 'pointer' : 'default',
        borderColor: active ? (color ?? '#60a5fa') : 'var(--border)',
        boxShadow: active ? `0 0 0 1px ${color ?? '#60a5fa'}` : undefined,
        transition: 'border-color .15s' }}>
      <div style={{ fontSize: 24, fontWeight: 800, color: color ?? 'var(--text0)' }}>{value}</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>{label}{clickable && <span style={{ color: color ?? '#60a5fa' }}> ▾</span>}</div>
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────
export default function RotationIntelligence() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabSlug = searchParams.get('tab') ?? ''
  const [pageTab, setPageTab] = useState<typeof PAGE_TABS[number]>(
    tabSlug === 'changelog' || tabSlug === 'advisor-guide' ? 'Advisor Guide' : 'Review')
  const selectPageTab = (t: typeof PAGE_TABS[number]) => {
    setPageTab(t)
    const next = new URLSearchParams(searchParams)
    if (t === 'Advisor Guide') next.set('tab', 'advisor-guide')
    else next.delete('tab')
    setSearchParams(next, { replace: true })
  }
  const [data, setData] = useState<RotationData | null>(null)
  const [summaryWarn, setSummaryWarn] = useState<string>('')
  const [question, setQuestion] = useState('Should I trim XLB for SPCX? How much should I trim?')
  const [busy, setBusy] = useState<string>('')   // which action is running
  const [result, setResult] = useState<AskResult | null>(null)
  const [rebalReview, setRebalReview] = useState<{ grok_answer?: string; note?: string; error?: string } | null>(null)
  const [askError, setAskError] = useState<string>('')
  const [grokPrompt, setGrokPrompt] = useState<GrokPromptResult | null>(null)
  const [copied, setCopied] = useState(false)
  const [gapsResult, setGapsResult] = useState<{ ok?: boolean; created?: any[]; note?: string; error?: string } | null>(null)
  const [proposeState, setProposeState] = useState<Record<string, string>>({})  // etf symbol -> status
  const [feedbackState, setFeedbackState] = useState<Record<string, string>>({})  // ideaKey -> action label
  const [oversight, setOversight] = useState<{ lanes?: Record<string, any>; prompt?: string; note?: string; error?: string } | null>(null)
  const [oversightCopied, setOversightCopied] = useState(false)
  const [laneHealth, setLaneHealth] = useState<{ lanes?: any[]; ready_count?: number; total?: number } | null>(null)
  const [laneBusy, setLaneBusy] = useState(false)
  const [laneMsg, setLaneMsg] = useState('')
  const [drill, setDrill] = useState<string>('')   // active summary-card drill filter

  async function loadSummary() {
    setSummaryWarn('')
    try {
      const res = await fetch('/api/v2/rotation/summary')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      // ROUTES auto-wraps as { ok, data: {...} } — unwrap .data
      const inner: RotationData = json?.data ?? json
      if (inner && inner.ok === false) {
        setSummaryWarn(`Rotation summary unavailable: ${inner.error ?? 'review data not ready'}`)
      }
      setData(inner ?? null)
    } catch (err) {
      setSummaryWarn(`Rotation summary unavailable: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  async function ask(backend: 'grounded' | 'local' | 'dual_oauth') {
    setBusy(backend === 'grounded' ? 'Ask Local (grounded)' : backend === 'local' ? 'Validate with local model' : 'Run Dual Review')
    setAskError('')
    if (backend !== 'local') setResult(null)   // keep grounded result on screen while local validation runs
    try {
      const res = await fetch('/api/v2/rotation/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, backend }),
      })
      // RAW advisor JSON (not wrapped). Parse defensively — a slow local-model call can return an
      // empty/truncated body; never surface "Unexpected end of JSON input".
      const text = await res.text()
      let json: AskResult
      try {
        json = text ? JSON.parse(text) : { ok: false, error: 'Empty response — the local model likely timed out under GPU load. Try again, or use Build Grok OAuth Prompt (instant).' }
      } catch {
        json = { ok: false, error: 'Advisor returned a non-JSON / truncated response (local model busy). Use Build Grok OAuth Prompt for an instant result.' }
      }
      if (json && json.ok === false) {
        setAskError(`Advisor error: ${json.error ?? `HTTP ${res.status}`}`)
      }
      setResult(json)
      if (json?.grok_oauth_prompt_path) {
        setGrokPrompt(prev => ({ ...(prev ?? {}), prompt_path: json.grok_oauth_prompt_path }))
      }
    } catch (err) {
      setAskError(`Advisor request failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy('')
    }
  }

  // Inline free/OAuth Grok second opinion (runs via the local OAuth proxy — no API key, no paid API).
  // Falls back to the manual paste prompt if the proxy is not authenticated.
  async function runGrokReview() {
    setBusy('Run Grok Review')
    setAskError('')
    try {
      const res = await fetch('/api/v2/rotation/grok-review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const text = await res.text()   // RAW (not wrapped); parse defensively
      let json: GrokPromptResult
      try { json = text ? JSON.parse(text) : { ok: false, error: 'Empty response — Grok proxy may be busy. Try again.' } }
      catch { json = { ok: false, error: 'Non-JSON response — try again.' } }
      if (json && json.ok === false) setAskError(`Grok review error: ${json.error ?? `HTTP ${res.status}`}`)
      setGrokPrompt(json)
    } catch (err) {
      setAskError(`Grok review request failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy('')
    }
  }

  // Inline free/OAuth Grok review of the rebalance-from-research ideas.
  async function runGrokRebalanceReview() {
    setBusy('Grok Review Ideas'); setRebalReview(null)
    try {
      const res = await fetch('/api/v2/rotation/grok-rebalance-review', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
      })
      const text = await res.text()
      let json: any
      try { json = text ? JSON.parse(text) : { error: 'Empty response — Grok proxy may be busy. Try again.' } }
      catch { json = { error: 'Non-JSON response — try again.' } }
      setRebalReview(json)
    } catch (err) {
      setRebalReview({ error: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy('')
    }
  }

  // Create an advisory ETF/short proposal (PENDING, operator-confirmed) from a sleeve play.
  async function proposeEtf(c: any) {
    setProposeState(prev => ({ ...prev, [c.symbol]: '…' }))
    try {
      const res = await fetch('/api/v2/rotation/propose-etf', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: c.symbol, direction: c.direction, instrument_type: c.instrument_type, sleeve: c.sleeve, rationale: c.rationale }),
      })
      const j = await res.json()
      setProposeState(prev => ({ ...prev, [c.symbol]: j?.ok ? (j.already_exists ? 'exists' : 'proposed') : 'error' }))
    } catch {
      setProposeState(prev => ({ ...prev, [c.symbol]: 'error' }))
    }
  }

  // Seed TradeAI + Hermes research directives for the underweight sleeves + named rotate-in candidates.
  // Advisory wiring only — directives queue research; nothing is bought or sold.
  async function researchGaps() {
    setBusy('Research Gaps'); setGapsResult(null)
    try {
      const res = await fetch('/api/v2/rotation/research-gaps', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
      })
      const text = await res.text()
      let json: any
      try { json = text ? JSON.parse(text) : { ok: false, error: 'Empty response — try again.' } }
      catch { json = { ok: false, error: 'Non-JSON response — try again.' } }
      setGapsResult(json)
    } catch (err) {
      setGapsResult({ ok: false, error: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy('')
    }
  }

  // Record operator feedback on a rebalance idea into the learning loop (llm_feedback_observations).
  async function sendFeedback(idea: any, action: 'reviewed' | 'dismissed' | 'acted') {
    const key = `${idea.from_symbol}-${idea.to_symbol}`
    setFeedbackState(prev => ({ ...prev, [key]: '…' }))
    try {
      const res = await fetch('/api/v2/rotation/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, idea }),
      })
      const text = await res.text()
      let json: any = {}
      try { json = text ? JSON.parse(text) : {} } catch { /* noop */ }
      setFeedbackState(prev => ({ ...prev, [key]: json?.ok ? action : 'error' }))
    } catch {
      setFeedbackState(prev => ({ ...prev, [key]: 'error' }))
    }
  }

  // Free OAuth LLM lane health (Grok / ChatGPT / Hermes / local) — command-center monitoring.
  async function loadLaneHealth() {
    try {
      const res = await fetch('/api/v2/llm/oauth-lanes')
      const json = await res.json()
      setLaneHealth(json?.data ?? json ?? null)
    } catch { /* noop */ }
  }
  // Control: run keepalive now (rolls Grok/ChatGPT OAuth tokens, alerts on stale).
  async function runKeepalive() {
    setLaneBusy(true); setLaneMsg('')
    try {
      const res = await fetch('/api/v2/llm/oauth-lanes/keepalive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const text = await res.text()
      let j: any = {}
      try { j = text ? JSON.parse(text) : {} } catch { /* noop */ }
      setLaneMsg(j?.ok ? `Keepalive ran — ${j.ok_ ?? j.ok}/${j.checked ?? '?'} lanes ok, ${j.alerts_sent ?? 0} alert(s) sent.` : 'Keepalive failed — retry.')
      await loadLaneHealth()
    } catch {
      setLaneMsg('Keepalive request failed.')
    } finally {
      setLaneBusy(false)
    }
  }
  const sinceText = (ts?: number) => {
    if (!ts) return 'never'
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
    if (s < 90) return 'just now'
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    return `${Math.floor(s / 86400)}d ago`
  }

  // Independent oversight layers — free/OAuth Grok + ChatGPT (codex). Advisory only.
  async function runOversight() {
    setBusy('Run Oversight'); setOversight(null)
    try {
      const res = await fetch('/api/v2/rotation/oversight', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lanes: ['grok', 'chatgpt'] }),
      })
      const text = await res.text()
      let json: any
      try { json = text ? JSON.parse(text) : { error: 'Empty response — try again.' } }
      catch { json = { error: 'Non-JSON response — try again.' } }
      setOversight(json)
    } catch (err) {
      setOversight({ error: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy('')
    }
  }
  async function copyOversightPrompt() {
    if (!oversight?.prompt) return
    try { await navigator.clipboard.writeText(oversight.prompt); setOversightCopied(true); setTimeout(() => setOversightCopied(false), 2000) } catch { /* noop */ }
  }

  // prefill from ?question= on mount
  useEffect(() => {
    try {
      const q = new URLSearchParams(window.location.search).get('question')
      if (q) setQuestion(q)
    } catch { /* noop */ }
    loadSummary()
    loadLaneHealth()
  }, [])

  const s = data?.summary ?? {}
  const dq = data?.data_quality ?? {}
  const missingAnalyst = data?.missing_analyst_upside ?? dq.rows_missing_analyst_upside ?? dq.missing_analyst_upside ?? dq.rows_without_analyst_upside
  const ideas = data?.top_rotation_ideas ?? []
  const pairs = (data?.top_pairs ?? []).filter((p: any) => p?.from_symbol || p?.to_symbol)
  const noIdeas = ideas.length === 0 && pairs.length === 0
  const candidates = (data?.top_candidates ?? []) as any[]
  function clickDrill(key: string, sectionId: string) {
    const next = drill === key ? '' : key
    setDrill(next)
    setTimeout(() => document.getElementById(next ? sectionId : '')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
  }
  const drillLabel: Record<string, string> = {
    TRIM_REVIEW: 'Trim Review', ADD_REVIEW: 'Add Review', WATCH: 'Watch',
    missing_sector: 'Missing Sector', missing_analyst: 'Missing Analyst Upside',
  }
  const drillCands = (() => {
    if (!drill || drill === 'rotation_ideas') return candidates
    if (drill === 'missing_sector') return candidates.filter((c: any) => !c.sector)
    if (drill === 'missing_analyst') return candidates.filter((c: any) => c.evidence?.missing_or_neutral_analyst_upside === true || (c.evidence?.positive_upside_pct == null && c.evidence?.analyst_not_applicable !== true))
    return candidates.filter((c: any) => (c.recommendation || '').toUpperCase() === drill)
  })()
  const feeSwaps = (data?.fee_swaps ?? []) as any[]
  const totalAnnualFee = data?.total_annual_fee_usd
  const researchIdeas = (data?.research_rotation_ideas ?? []) as any[]
  const researchCands = (data?.research_candidates ?? []) as any[]
  const etfCands = (data?.etf_candidates ?? []) as any[]
  const instrLabel = (t?: string) => (t === 'inverse_etf' ? 'INVERSE ETF' : (t || 'stock').toUpperCase())
  const instrColor = (t?: string) => (t === 'etf' ? '#14b8a6' : t === 'inverse_etf' ? '#ef4444' : t === 'fund' ? '#a855f7' : '#6b7280')
  const InstrBadge = ({ t }: { t?: string }) => (t && t !== 'stock'
    ? <span style={{ fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 3, background: `${instrColor(t)}1f`, color: instrColor(t), border: `1px solid ${instrColor(t)}55`, letterSpacing: 0.3 }}>{instrLabel(t)}</span>
    : null)
  const overweights = (data?.sector_overweights ?? []) as SectorOverweight[]
  const underweights = (data?.sector_underweights ?? []) as SectorUnderweight[]
  const hasSleeveImbalance = overweights.length > 0 || underweights.length > 0
  const rangeText = (r?: AmountRange) =>
    r && r.low != null ? `${money(r.low)} – ${money(r.high)}` : 'review range unavailable'
  const px = (v?: number) =>
    typeof v === 'number' ? `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
  const sh = (r?: ShareRange) => (r && r.low != null ? `${r.low.toLocaleString()}–${r.high?.toLocaleString()} shares` : null)
  const dayColor = (v?: number) => (v == null ? 'var(--text3)' : v >= 0 ? '#22c55e' : '#ef4444')
  const dayText = (v?: number) => (v == null ? '' : `${v >= 0 ? '+' : ''}${v}%`)
  const degraded = (data?.degraded_holdings ?? []) as DegradedHolding[]
  // Plain-English, one-sentence recommendation for a rebalance idea card.
  function plainRec(idea: RotationPair): string {
    const from = idea.from_symbol ?? '—'
    const to = idea.to_symbol ?? '—'
    const deg = idea.from_degradation
    const posVal = (idea.from_price && idea.from_shares_held) ? idea.from_price * idea.from_shares_held : undefined
    const small = posVal != null && posVal < 2000
    const toUp = (data?.research_candidates ?? []).find((c: any) => c.symbol === to)?.analyst_upside_pct
    const toPart = `If you want to redeploy the proceeds, ${to} is a high-conviction research idea${toUp != null ? ` (analysts see ${toUp}% upside)` : ''} — but you confirm sizing, tax and account fit.`
    if (deg?.thesis_status) {
      const st = deg.thesis_status.toUpperCase()
      const why = deg.escalation_reason || deg.what_changed || 'its protective stop deteriorated'
      const action = small
        ? `Review reducing or closing this small ${posVal != null ? money(posVal) + ' ' : ''}position.`
        : `Review trimming this position toward your stop discipline.`
      return `${from} tripped its protective stop (${st} — ${why}). ${action} ${toPart}`
    }
    const r = idea.review_amount_range
    const amt = r?.low != null ? ` about ${money(r.low)}–${money(r.high)}` : ''
    return `${from} is flagged as a trim candidate (concentration/valuation). Review trimming${amt}. ${toPart}`
  }
  const DEG_COLOR: Record<string, string> = { triggered: '#ef4444', danger: '#ef4444', broken: '#ef4444', warning: '#f59e0b', weakening: '#f59e0b' }

  const grokAnswer = grokPrompt?.grok_answer
  const grokNote = grokPrompt?.note
  const promptText = grokPrompt?.prompt_text
  const promptPath = grokPrompt?.prompt_path || result?.grok_oauth_prompt_path
  const hasGrok = Boolean(grokAnswer || promptText || promptPath)

  async function copyPrompt() {
    if (!promptText) return
    try {
      await navigator.clipboard.writeText(promptText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard unavailable */ }
  }

  return (
    <div style={{ padding: 4 }}>
      {/* A. Header */}
      <header style={{ marginBottom: 18 }}>
        <div className="hub-title-row" style={{ marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Rotation Intelligence</div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 3 }}>
              Grounded local review + free/OAuth Grok second opinion
            </div>
          </div>
          <div className="hub-tabs">
            {PAGE_TABS.map(t => (
              <button key={t} onClick={() => selectPageTab(t)} style={{
                padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
                background: pageTab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
                color: pageTab === t ? '#60a5fa' : 'var(--text3)', fontWeight: pageTab === t ? 700 : 400,
              }}>{t}</button>
            ))}
          </div>
        </div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 5, fontWeight: 600 }}>
          Advisory only · human review required · no broker action
        </div>
        {pageTab === 'Review' && data?.cache_age_sec != null && (
          <div style={{ fontSize: 10, color: data?.stale ? '#f59e0b' : 'var(--text3)', marginTop: 4 }}>
            ⟳ refreshed {data.cache_age_sec < 60 ? `${data.cache_age_sec}s` : `${Math.round(data.cache_age_sec / 60)}m`} ago{data?.stale ? ' · stale, refreshing in background' : ''} · heavy engine pre-warmed every 8 min (no page wait)
          </div>
        )}
      </header>

      {pageTab === 'Advisor Guide' && <AdvisorChangesPanel />}

      {pageTab === 'Review' && (<>

      {/* B. Summary cards */}
      {summaryWarn && (
        <div style={{
          marginBottom: 14, padding: '8px 12px', borderRadius: 8, fontSize: 11,
          background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)', color: '#f59e0b',
        }}>
          {summaryWarn} — page remains usable; counts shown as “—”.
        </div>
      )}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 20 }}>
        <SummaryCard label="Trim Review" value={s.trim_review ?? '—'} color="#ef4444" active={drill === 'TRIM_REVIEW'} onClick={() => clickDrill('TRIM_REVIEW', 'review-candidates')} />
        <SummaryCard label="Add Review" value={s.add_review ?? '—'} color="#22c55e" active={drill === 'ADD_REVIEW'} onClick={() => clickDrill('ADD_REVIEW', 'review-candidates')} />
        <SummaryCard label="Rotation Ideas" value={s.rotation_ideas ?? '—'} color={ACCENT} active={drill === 'rotation_ideas'} onClick={() => clickDrill('rotation_ideas', 'rotation-ideas')} />
        <SummaryCard label="Watch" value={s.watch ?? '—'} color="#f59e0b" active={drill === 'WATCH'} onClick={() => clickDrill('WATCH', 'review-candidates')} />
        <SummaryCard label="Missing Sector" value={data?.missing_sector ?? '—'} color="#a855f7" active={drill === 'missing_sector'} onClick={() => clickDrill('missing_sector', 'review-candidates')} />
        <SummaryCard label="Missing Analyst Upside" value={missingAnalyst ?? '—'} color="#a855f7" active={drill === 'missing_analyst'} onClick={() => clickDrill('missing_analyst', 'review-candidates')} />
      </section>

      {/* Fee-driven swaps — autonomous cost-efficiency: rotate an expensive fund into a cheaper one held */}
      {(feeSwaps.length > 0 || totalAnnualFee != null) && (
        <section style={{ ...card, marginBottom: 20, borderColor: 'rgba(245,158,11,.3)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>
              Fee-Driven Swaps <span style={{ fontSize: 10, fontWeight: 400, color: '#f59e0b' }}>· advisory · cost vs return, not a price signal</span>
            </div>
            <span style={{ flex: 1 }} />
            {totalAnnualFee != null && <span style={{ fontSize: 11, color: 'var(--text2)' }}>portfolio fees <b style={{ color: '#f59e0b' }}>{money(totalAnnualFee)}/yr</b></span>}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
            Holdings where a cheaper fund you already own is matching or beating it. Annual fee = expense ratio × value.
            <b> Review only</b> — operator confirms tax/sizing; nothing is placed.
          </div>
          {feeSwaps.length === 0
            ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>No fee-inefficient holdings flagged.</div>
            : <div style={{ display: 'grid', gap: 8 }}>
                {feeSwaps.map((f: any, i: number) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '8px 10px', borderRadius: 8, background: 'var(--bg2)', border: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{f.out_symbol}</span>
                    {f.in_symbol && <><span style={{ color: 'var(--text3)' }}>→</span>
                      <span style={{ fontSize: 13, fontWeight: 800, color: '#22c55e', fontFamily: 'monospace' }}>{f.in_symbol}</span></>}
                    <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 3, background: f.severity === 'high' ? 'rgba(239,68,68,.15)' : 'rgba(245,158,11,.15)', color: f.severity === 'high' ? '#ef4444' : '#f59e0b' }}>{(f.severity || '').toUpperCase()}</span>
                    {f.tax_free_to_switch && <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 3, background: 'rgba(34,197,94,.15)', color: '#22c55e' }}>TAX-FREE (IRA)</span>}
                    <span style={{ flex: 1 }} />
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>
                      {f.expense_ratio_pct != null ? `${f.expense_ratio_pct}% ER` : 'ER unknown'}
                      {f.alt_expense_ratio_pct != null && f.in_symbol ? ` vs ${f.alt_expense_ratio_pct}%` : ''}
                      {f.ytd_return_pct != null ? ` · ${f.ytd_return_pct}% YTD` : ''}
                      {f.alt_ytd_return_pct != null && f.in_symbol ? ` vs ${f.alt_ytd_return_pct}%` : ''}
                    </span>
                    {f.excess_fee_vs_index_usd != null && <span style={{ fontSize: 13, fontWeight: 800, color: '#f59e0b' }}>{money(f.excess_fee_vs_index_usd)}/yr</span>}
                  </div>
                ))}
              </div>}
        </section>
      )}

      {/* B2. Sleeve Balance — sector/theme overweight & underweight detection */}
      {hasSleeveImbalance && (
        <section style={{ ...card, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>
              Sleeve Balance <span style={{ fontSize: 10, fontWeight: 400, color: '#f59e0b' }}>· advisory · comfort targets, not a model signal</span>
            </div>
            <span style={{ flex: 1 }} />
            {data?.portfolio_total != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>portfolio {money(data.portfolio_total)}</span>}
            {underweights.length > 0 && (
              <button disabled={!!busy} onClick={researchGaps} style={btn(!!busy)} title="Queue TradeAI + Hermes research directives for the underweight sleeves and rotate-in names">
                {busy === 'Research Gaps' ? 'Seeding…' : 'Have TradeAI + Hermes research these gaps'}
              </button>
            )}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
            Look-through theme weights vs your comfort targets (<span style={{ fontFamily: 'monospace' }}>config/rotation_sector_targets.json</span>).
            Excess $ and trim ranges are <b>review ranges only</b> — operator confirms sizing/tax; nothing is placed.
          </div>

          {gapsResult && (
            <div style={{ marginBottom: 12, padding: '8px 11px', borderRadius: 8, fontSize: 11,
              background: gapsResult.ok ? 'rgba(34,197,94,.08)' : 'rgba(239,68,68,.08)',
              border: `1px solid ${gapsResult.ok ? 'rgba(34,197,94,.3)' : 'rgba(239,68,68,.3)'}`,
              color: gapsResult.ok ? '#22c55e' : '#ef4444' }}>
              {gapsResult.ok
                ? `Seeded ${gapsResult.created?.length ?? 0} research directive(s) → TradeAI + Hermes will research these${(gapsResult.created?.length ?? 0) === 0 ? ' (already queued — deduped)' : ''}.`
                : `Could not seed research: ${gapsResult.error ?? gapsResult.note ?? 'unknown'}`}
              {(gapsResult.created?.length ?? 0) > 0 && (
                <span style={{ color: 'var(--text3)', fontWeight: 400 }}> {' · '}{gapsResult.created!.map((c: any) => `${c.kind}:${c.label}`).join(', ')}</span>
              )}
            </div>
          )}

          {overweights.length > 0 && (
            <>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 6 }}>Overweight — review trimming toward target</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10, marginBottom: underweights.length ? 16 : 0 }}>
                {overweights.map((o, idx) => (
                  <article key={`ow-${o.theme}-${idx}`} style={{ ...card, borderColor: 'rgba(239,68,68,.3)' }}>
                    <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>{o.theme}</div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', marginBottom: 6 }}>
                      <span style={{ fontSize: 20, fontWeight: 800, color: '#ef4444' }}>{o.pct}%</span>
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>vs {o.target}% target · +{o.excess_pct}%</span>
                    </div>
                    <div style={{ fontSize: 10.5, color: 'var(--text2)' }}>
                      Over target by <b style={{ color: '#ef4444' }}>{money(o.excess_dollars)}</b> <span style={{ color: 'var(--text3)' }}>(review range)</span>
                    </div>
                    {(o.top_holdings ?? []).length > 0 && (
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5, fontFamily: 'monospace' }}>{(o.top_holdings ?? []).join(' · ')}</div>
                    )}
                  </article>
                ))}
              </div>
            </>
          )}

          {underweights.length > 0 && (
            <>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#22c55e', marginBottom: 6 }}>Underweight — redeploy gap (being researched)</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
                {underweights.map((u, idx) => (
                  <article key={`uw-${u.theme}-${idx}`} style={{ ...card, borderColor: 'rgba(34,197,94,.3)' }}>
                    <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>{u.theme}</div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                      <span style={{ fontSize: 20, fontWeight: 800, color: '#22c55e' }}>{u.pct}%</span>
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>vs {u.floor}% floor · gap {u.gap_pct}%</span>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {/* B2b. ETF / Fund sleeve plays — long for underweight sleeves, inverse/short hedge for overweight */}
      {etfCands.length > 0 && (
        <section style={{ ...card, marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>
            ETF / Fund Sleeve Plays <span style={{ fontSize: 10, fontWeight: 400, color: '#14b8a6' }}>· baskets, not single stocks · long or short</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>Direct sleeve exposure via ETFs: a <b>long</b> ETF to fill an underweight sleeve, or an <b>inverse/short</b> ETF as an advisory hedge for an overweight sleeve. Review only — nothing is placed.</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
            {etfCands.map((c: any, idx: number) => {
              const isShort = c.direction === 'short'
              const dc = isShort ? '#ef4444' : '#22c55e'
              return (
                <article key={`${c.symbol}-${idx}`} style={{ ...card, borderColor: `${dc}33` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{c.symbol}</span>
                    <InstrBadge t={c.instrument_type} />
                    <span style={{ fontSize: 8.5, fontWeight: 800, padding: '1px 6px', borderRadius: 3, background: `${dc}1f`, color: dc, border: `1px solid ${dc}55` }}>{isShort ? 'SHORT / HEDGE' : 'LONG'}</span>
                    <span style={{ flex: 1 }} />
                    {c.held && <span style={{ fontSize: 8.5, color: 'var(--text3)' }}>held</span>}
                  </div>
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 4 }}>{c.name} · sleeve: {c.sleeve}</div>
                  <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text1)', marginBottom: 4 }}>
                    {c.price != null ? px(c.price) : '—'}
                    {c.day_change_pct != null && <span style={{ color: dayColor(c.day_change_pct), marginLeft: 6 }}>{dayText(c.day_change_pct)}</span>}
                    {c.leverage && <span style={{ color: '#ef4444', marginLeft: 6 }}>{c.leverage}×</span>}
                  </div>
                  <div style={{ fontSize: 10.5, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 8 }}>{c.rationale}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                    {proposeState[c.symbol] === 'proposed' ? (
                      <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 700 }}>✓ PENDING {isShort ? 'short' : 'long'} proposal created — review-only</span>
                    ) : proposeState[c.symbol] === 'exists' ? (
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>active proposal already exists</span>
                    ) : (
                      <>
                        <button disabled={proposeState[c.symbol] === '…'} onClick={() => proposeEtf(c)}
                          style={{ ...btn(proposeState[c.symbol] === '…'), padding: '4px 10px', fontSize: 10.5, borderColor: `${dc}55`, background: `${dc}1f`, color: dc }}>
                          {proposeState[c.symbol] === '…' ? 'Creating…' : `Propose ${isShort ? 'SHORT' : 'LONG'} (review)`}
                        </button>
                        {proposeState[c.symbol] === 'error' && <span style={{ fontSize: 9.5, color: '#ef4444' }}>failed — retry</span>}
                        <span style={{ fontSize: 8.5, color: 'var(--text3)' }}>PENDING · operator approval + gates required</span>
                      </>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      )}

      {/* B3. Deteriorating Holdings — Aegis thesis-health rotate-OUT review (real deterioration) */}
      {degraded.length > 0 && (
        <section style={{ ...card, marginBottom: 20, borderColor: 'rgba(239,68,68,.3)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>
              Deteriorating Holdings <span style={{ fontSize: 10, fontWeight: 400, color: '#ef4444' }}>· advisory rotate-out review · real deterioration</span>
            </div>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>{degraded.length} flagged · Aegis nightly briefs</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
            Held names Aegis flags as weakening/warning/danger/triggered. <b>TRIGGERED/DANGER/WARNING are deterministic stop-distance math</b> (high confidence, not LLM);
            WEAKENING is a local-LLM (gemma3) thesis read. These drive the "what to rotate out" side — review only, nothing is placed.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 10 }}>
            {degraded.slice(0, 18).map((h, idx) => {
              const c = DEG_COLOR[h.thesis_status ?? ''] ?? '#f59e0b'
              return (
                <article key={`${h.symbol}-${idx}`} style={{ ...card, borderColor: `${c}44` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{h.symbol}</span>
                    <span style={{ flex: 1 }} />
                    <DegBadge d={h} />
                  </div>
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>
                    {(h.sector ?? '—')} · {(h.account_type ?? '—').toString().replace(/_/g, ' ')}
                  </div>
                  {h.price != null && (
                    <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text1)', marginBottom: 4 }}>
                      {px(h.price)}{h.est_shares != null && <span style={{ color: 'var(--text3)' }}> × {h.est_shares.toLocaleString()} shares</span>}
                      {h.day_change_pct != null && <span style={{ color: dayColor(h.day_change_pct), marginLeft: 6 }}>{dayText(h.day_change_pct)}</span>}
                      {h.current_value != null && <span style={{ color: 'var(--text3)', marginLeft: 6 }}>· {money(h.current_value)}</span>}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.4 }}>
                    {h.escalation_reason || h.what_changed || h.technical_drift || '—'}
                    {h.near_52wk_low_pct != null && <span style={{ color: '#ef4444' }}> · {h.near_52wk_low_pct}% from 52wk high</span>}
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      )}

      {/* C. Ask Advisor */}
      <section style={{ ...card, marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Ask the Rotation Advisor</div>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', marginBottom: 12, padding: 10, fontSize: 12,
            background: 'var(--bg2)', color: 'var(--text0)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical',
          }}
        />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <button disabled={!!busy} onClick={() => ask('grounded')} style={btn(!!busy)}>Ask Local</button>
          <button disabled={!!busy} onClick={runGrokReview} style={btn(!!busy)}>Run Grok Review</button>
          <button disabled={!!busy || !result} onClick={() => ask('local')} style={btn(!!busy || !result)} title={!result ? 'Ask Local first, then optionally validate with the local model' : ''}>Validate with local model</button>
          <button disabled={!!busy} onClick={() => ask('dual_oauth')} style={btn(!!busy)}>Run Dual Review</button>
          <button disabled={!!busy} onClick={loadSummary} style={btn(!!busy)}>Refresh Summary</button>
          {busy && <span style={{ fontSize: 11, color: ACCENT }}>Running {busy}…{(busy.includes('local model') || busy === 'Run Dual Review') ? ' (local model — can take 1–3 min under GPU load)' : ''}</span>}
        </div>
        <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 8 }}>
          <b>Ask Local</b> returns the grounded review instantly. <b>Run Grok Review</b> gets a second opinion inline via the free Grok OAuth proxy. <b>Validate with local model</b> / <b>Run Dual Review</b> run the local model (1–3 min under GPU load).
          Grok runs on a free / OAuth session — <b>no API key, no paid API</b> (manual-paste fallback if the proxy is offline). The advisor reviews holdings and offers a second opinion; it never places, buys, or sells anything.
        </div>
        {askError && (
          <div style={{ marginTop: 10, fontSize: 11, color: '#ef4444' }}>
            {askError}
            {result?.stderr_tail && (
              <pre style={{ marginTop: 4, fontSize: 9, color: 'var(--text3)', whiteSpace: 'pre-wrap' }}>{result.stderr_tail}</pre>
            )}
          </div>
        )}
      </section>

      {/* C2. Independent Oversight — free/OAuth Grok + ChatGPT review the rotate-out reasoning */}
      <section style={{ ...card, marginBottom: 20, borderColor: 'rgba(168,85,247,.3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#a855f7' }}>Independent Oversight <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text3)' }}>· Grok + ChatGPT · free / OAuth · no API key</span></div>
          <span style={{ flex: 1 }} />
          <button disabled={!!busy} onClick={runOversight} style={btn(!!busy)}>{busy === 'Run Oversight' ? 'Reviewing… (ChatGPT can take ~1–4 min)' : 'Run Grok + ChatGPT Oversight'}</button>
        </div>
        <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 10 }}>
          Two independent models review the system's rotate-OUT flags, rebalance ideas, and sector overweights — a second + third opinion on the engine. Both run on free OAuth sessions (Grok via the local xAI-OAuth proxy, ChatGPT via the openai-codex OAuth proxy — <b>not the paid API</b>). Advisory only; oversight never places, buys, or sells.
        </div>
        {/* OAuth-lane monitor + control (Grok / ChatGPT / Hermes / local) — command-center commander */}
        {laneHealth?.lanes && (
          <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 10, marginBottom: oversight ? 12 : 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)' }}>Free OAuth LLM Lanes</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{laneHealth.ready_count}/{laneHealth.total} ready</span>
              <span style={{ flex: 1 }} />
              <button disabled={laneBusy} onClick={runKeepalive} style={{ ...btn(laneBusy), padding: '3px 10px', fontSize: 9.5 }} title="Run keepalive now — rolls the Grok/ChatGPT OAuth tokens forward and alerts on stale">{laneBusy ? 'Running…' : 'Run keepalive'}</button>
              <button disabled={laneBusy} onClick={loadLaneHealth} style={{ ...btn(laneBusy), padding: '3px 8px', fontSize: 9.5 }}>Re-check ↻</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 6 }}>
              {laneHealth.lanes.map((l: any) => {
                const ready = Boolean(l.ready ?? (l.status === 'ready' && l.authenticated && !l.token_expired))
                const offline = l.status === 'offline'
                const col = ready ? '#22c55e' : offline ? '#ef4444' : '#f59e0b'
                return (
                  <div key={l.lane} style={{ border: `1px solid ${col}44`, background: `${col}10`, borderRadius: 6, padding: '5px 8px' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: col }}>{ready ? '●' : offline ? '○' : '◐'} {l.label}</div>
                    <div style={{ fontSize: 9, color: 'var(--text2)' }}>{l.status}{l.last_ok ? ` · ok ${sinceText(l.last_ok)}` : ''}</div>
                    {!ready && l.hint && <div style={{ fontSize: 8.5, color: 'var(--text3)', fontFamily: 'monospace', marginTop: 2 }}>{l.hint}</div>}
                  </div>
                )
              })}
            </div>
            {laneMsg && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>{laneMsg}</div>}
            <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 6 }}>Keepalive runs daily (cron) to keep the rolling OAuth tokens warm; a stale lane pings Telegram. Monitoring only — no broker, no paid API.</div>
          </div>
        )}
        {oversight?.error && <div style={{ fontSize: 11, color: '#ef4444' }}>{oversight.error}</div>}
        {oversight?.lanes && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}>
            {(['grok', 'chatgpt'] as const).map((lane) => {
              const r = oversight.lanes?.[lane]
              if (!r) return null
              const label = lane === 'grok' ? 'Grok (xAI OAuth)' : 'ChatGPT (openai-codex OAuth)'
              return (
                <div key={lane} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: r.ok ? '#a855f7' : '#f59e0b', marginBottom: 6 }}>
                    {label} {r.ok ? <span style={{ fontSize: 9, color: 'var(--text3)' }}>· {r.model}</span> : <span style={{ fontSize: 9, color: '#f59e0b' }}>· unavailable</span>}
                  </div>
                  {r.ok ? (
                    <div style={{ fontSize: 12, color: 'var(--text0)', whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{r.answer}</div>
                  ) : (
                    <div style={{ fontSize: 10.5, color: 'var(--text2)' }}>
                      {r.error || 'Lane unavailable.'} {lane === 'chatgpt' ? 'Re-login to activate the ChatGPT OAuth proxy, or paste the prompt below into chatgpt.com (free).' : 'Or paste the prompt below into the model’s free web session.'}
                      {r.auth_hint && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4, fontFamily: 'monospace' }}>{r.auth_hint}</div>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {oversight?.prompt && (
          <details style={{ marginTop: 10 }}>
            <summary style={{ fontSize: 10, color: 'var(--text3)', cursor: 'pointer' }}>view / copy the oversight prompt (manual paste fallback for any unavailable lane)</summary>
            <button onClick={copyOversightPrompt} style={{ ...btn(false), margin: '8px 0', borderColor: '#a855f755', background: 'rgba(168,85,247,.15)', color: '#a855f7' }}>{oversightCopied ? 'Copied ✓' : 'Copy Oversight Prompt'}</button>
            <textarea readOnly value={oversight.prompt} rows={8} style={{ width: '100%', boxSizing: 'border-box', padding: 10, fontSize: 10, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical' }} />
          </details>
        )}
      </section>

      {/* D. Result panel */}
      {result && (result.answer || result.grounded_answer || result.answer_mode || result.local_answer_validation || result.rotation_summary) && (
        <section style={{ ...card, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Advisor Review</div>
            {result.answer_mode && (
              <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, background: 'rgba(96,165,250,.15)', color: ACCENT }}>
                mode: {result.answer_mode}
              </span>
            )}
            {result.backend && <span style={{ fontSize: 9, color: 'var(--text3)' }}>backend: {result.backend}</span>}
          </div>

          {result.answer && (
            <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap', marginBottom: 12 }}>{result.answer}</div>
          )}

          {result.grounded_answer && result.grounded_answer !== result.answer && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 3 }}>Grounded answer</div>
              <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{result.grounded_answer}</div>
            </div>
          )}

          {result.local_answer_validation && (
            <div style={{ marginBottom: 12, padding: '8px 11px', borderRadius: 8, background: 'var(--bg2)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: result.local_answer_validation.ok ? '#22c55e' : '#f59e0b' }}>
                Local answer validation: {result.local_answer_validation.ok ? 'OK' : 'issues flagged'}
              </div>
              {(result.local_answer_validation.issues ?? []).length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 10.5, color: 'var(--text2)' }}>
                  {(result.local_answer_validation.issues ?? []).map((iss, i) => <li key={i}>{iss}</li>)}
                </ul>
              )}
            </div>
          )}

          {result.grok_second_opinion?.mode && (
            <div style={{ marginBottom: 12, fontSize: 11, color: 'var(--text2)' }}>
              Grok second opinion mode: <b style={{ color: '#f59e0b' }}>{result.grok_second_opinion.mode}</b> (free / OAuth / manual-paste)
            </div>
          )}

          {result.rotation_summary && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 3 }}>Rotation summary</div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11, color: 'var(--text2)' }}>
                {typeof result.rotation_summary === 'object'
                  ? Object.entries(result.rotation_summary).filter(([, v]) => typeof v !== 'object').map(([k, v]) => (
                    <span key={k}>{k.replace(/_/g, ' ')}: <b style={{ color: 'var(--text1)' }}>{String(v)}</b></span>
                  ))
                  : <span>{String(result.rotation_summary)}</span>}
              </div>
            </div>
          )}

          {result.local_answer_raw && (
            <details style={{ marginBottom: 10 }}>
              <summary style={{ fontSize: 10.5, color: 'var(--text3)', cursor: 'pointer' }}>Local answer (raw)</summary>
              <pre style={{ marginTop: 6, fontSize: 10, color: 'var(--text2)', whiteSpace: 'pre-wrap', background: 'var(--bg2)', padding: 10, borderRadius: 8 }}>{result.local_answer_raw}</pre>
            </details>
          )}

          {result.grounding_report && (
            <details>
              <summary style={{ fontSize: 10.5, color: 'var(--text3)', cursor: 'pointer' }}>Grounding report (JSON)</summary>
              <pre style={{ marginTop: 6, fontSize: 9.5, color: 'var(--text2)', whiteSpace: 'pre-wrap', background: 'var(--bg2)', padding: 10, borderRadius: 8, maxHeight: 320, overflow: 'auto' }}>
                {JSON.stringify(result.grounding_report, null, 2)}
              </pre>
            </details>
          )}
        </section>
      )}

      {/* E. Grok second opinion (inline free/OAuth) — manual paste is the fallback */}
      {hasGrok && (
        <section style={{ ...card, marginBottom: 20, borderColor: 'rgba(245,158,11,.3)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#f59e0b', marginBottom: 6 }}>Grok Second Opinion <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text3)' }}>· free / OAuth · no API key</span></div>
          {grokAnswer ? (
            <>
              <div style={{ fontSize: 12.5, color: 'var(--text0)', whiteSpace: 'pre-wrap', lineHeight: 1.55, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>{grokAnswer}</div>
              <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 6 }}>{grokNote ?? 'Free/OAuth Grok via the local proxy. Grounding remains authoritative — this is advisory only.'}</div>
              <details style={{ marginTop: 8 }}>
                <summary style={{ fontSize: 10, color: 'var(--text3)', cursor: 'pointer' }}>view / copy the prompt that was sent</summary>
                {promptPath && <div style={{ fontSize: 9.5, color: 'var(--text3)', margin: '6px 0' }}>Prompt file: <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{promptPath}</span></div>}
                {promptText && <>
                  <button onClick={copyPrompt} style={{ ...btn(false), marginBottom: 8, borderColor: '#f59e0b55', background: 'rgba(245,158,11,.15)', color: '#f59e0b' }}>{copied ? 'Copied ✓' : 'Copy Grok Prompt'}</button>
                  <textarea readOnly value={promptText} rows={8} style={{ width: '100%', boxSizing: 'border-box', padding: 10, fontSize: 10, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical' }} />
                </>}
              </details>
            </>
          ) : (
            <>
              <div style={{ fontSize: 10.5, color: 'var(--text2)', marginBottom: 10 }}>{grokNote ?? 'Grok proxy offline — paste this into Grok using free/OAuth login. No API key is used.'}</div>
              {promptPath && <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Prompt file: <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{promptPath}</span></div>}
              {promptText ? (
                <>
                  <button onClick={copyPrompt} style={{ ...btn(false), marginBottom: 10, borderColor: '#f59e0b55', background: 'rgba(245,158,11,.15)', color: '#f59e0b' }}>{copied ? 'Copied ✓' : 'Copy Grok Prompt'}</button>
                  <textarea readOnly value={promptText} rows={10} style={{ width: '100%', boxSizing: 'border-box', padding: 10, fontSize: 10.5, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical' }} />
                </>
              ) : (
                <pre style={{ fontSize: 10.5, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', padding: 10, borderRadius: 8, whiteSpace: 'pre-wrap' }}>cat "{promptPath}"</pre>
              )}
            </>
          )}
        </section>
      )}

      {/* F. Rotation Ideas */}
      <section id="rotation-ideas" style={{ scrollMarginTop: 80 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Rotation Ideas</div>
        {noIdeas ? (
          <div style={{ ...card, fontSize: 11.5, color: 'var(--text2)' }}>
            No model-supported rotation ideas. Continue WATCH / RESEARCH_MORE.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
            {[...ideas, ...pairs].map((idea, idx) => (
              <article key={`${idea.from_symbol}-${idea.to_symbol}-${idx}`} style={card}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <ActionBadge cls={idea.action_class} />
                  <span style={{ flex: 1 }} />
                  {idea.score != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>score {idea.score}</span>}
                </div>
                <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace', marginBottom: 4 }}>
                  {idea.from_symbol ?? '—'} → {idea.to_symbol ?? '—'}
                </div>
                {idea.entry_plan?.limit_price != null && (
                  <div style={{ fontSize: 9.5, fontFamily: 'monospace', marginBottom: 6, padding: '3px 6px', borderRadius: 5, background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.25)', lineHeight: 1.5 }}>
                    <span style={{ fontWeight: 800, color: '#22c55e' }}>🎯 {idea.to_symbol} entry {px(idea.entry_plan.limit_price)}</span>
                    {idea.entry_plan.entry_zone_low != null && <span style={{ color: 'var(--text2)' }}> · zone {px(idea.entry_plan.entry_zone_low)}–{px(idea.entry_plan.entry_zone_high)}</span>}
                    {idea.entry_plan.stop_price != null && <span style={{ color: '#ef4444' }}> · stop {px(idea.entry_plan.stop_price)}</span>}
                    {idea.entry_plan.risk_reward != null && <span style={{ color: 'var(--text3)' }}> · R:R {idea.entry_plan.risk_reward}</span>}
                    {(idea.entry_plan.urgency || idea.entry_plan.proposal_tag) && <span style={{ marginLeft: 5, fontWeight: 800, color: idea.entry_plan.urgency === 'ready' ? '#22c55e' : idea.entry_plan.urgency === 'near_entry' ? '#f59e0b' : '#9ca3af' }}>{idea.entry_plan.urgency === 'ready' ? 'READY' : idea.entry_plan.urgency === 'near_entry' ? 'NEAR-ENTRY' : (idea.entry_plan.proposal_tag || 'WATCH')}</span>}
                  </div>
                )}
                {(idea.from_account || idea.to_account) && (
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>
                    {(idea.from_account ?? 'n/a').replace(/_/g, ' ')} → {(idea.to_account ?? 'n/a').replace(/_/g, ' ')}
                  </div>
                )}
                {idea.rationale && <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 6 }}>{idea.rationale}</div>}
                <div style={{ fontSize: 10.5, color: 'var(--text3)' }}>
                  Suggested review amount: <b style={{ color: 'var(--text1)' }}>{money(idea.review_amount)}</b>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Review candidates (per-symbol, not pairs) */}
      {candidates.length > 0 && (
        <section id="review-candidates" style={{ scrollMarginTop: 80 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Review Candidates</div>
            {drill && drill !== 'rotation_ideas' && (
              <span style={{ fontSize: 10, padding: '2px 9px', borderRadius: 12, background: 'rgba(96,165,250,.15)', color: ACCENT, border: `1px solid ${ACCENT}55`, fontWeight: 700 }}>
                filtered: {drillLabel[drill] ?? drill} ({drillCands.length}) · <span onClick={() => setDrill('')} style={{ cursor: 'pointer', textDecoration: 'underline' }}>clear</span>
              </span>
            )}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Per-symbol review candidates from the grounded scorer — not buy/sell instructions. Each is a WATCH / review item only. {drill ? 'Showing your selected filter (within the top scored candidates).' : 'Tip: click a summary card above to filter.'}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
            {(drill && drill !== 'rotation_ideas' ? drillCands : candidates).slice(0, 24).map((c: any, idx: number) => {
              const ev = c.evidence ?? {}
              return (
                <article key={`${c.symbol}-${c.account_key}-${idx}`} style={card}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{c.symbol ?? '—'}</span>
                    {c.degradation && <DegBadge d={c.degradation} />}
                    <span style={{ flex: 1 }} />
                    <ActionBadge cls={c.recommendation} />
                  </div>
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>
                    {(c.sector ?? '—')} · {(c.account_type ?? c.account_key ?? '—').toString().replace(/_/g, ' ')}
                  </div>
                  {c.price != null && (
                    <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text1)', marginBottom: 4 }}>
                      {px(c.price)}{c.est_shares != null && <span style={{ color: 'var(--text3)' }}> × {c.est_shares.toLocaleString()} shares</span>}
                      {c.day_change_pct != null && <span style={{ color: dayColor(c.day_change_pct), marginLeft: 6 }}>{dayText(c.day_change_pct)}</span>}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text2)', flexWrap: 'wrap' }}>
                    {c.current_value != null && <span>value {money(c.current_value)}</span>}
                    {c.trim_score ? <span>trim {c.trim_score}</span> : null}
                    {c.add_score ? <span style={{ color: '#22c55e' }}>add {c.add_score}</span> : null}
                    {!c.trim_score && c.degradation && <span style={{ color: '#ef4444' }} title="Valuation trim score is 0; the rotate-out signal is the stop/thesis status">stop-driven</span>}
                    {c.confidence != null && <span>conf {c.confidence}</span>}
                  </div>
                  {(ev.positive_upside_pct != null || ev.concentration_pct != null) && (
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
                      {ev.positive_upside_pct != null && <>upside {ev.positive_upside_pct}% </>}
                      {ev.concentration_pct != null && <>· conc {ev.concentration_pct}%</>}
                    </div>
                  )}
                </article>
              )
            })}
          </div>
          {candidates.length > 24 && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>+{candidates.length - 24} more</div>}
        </section>
      )}

      {/* G. Rebalance from research (rotate into non-held names) — advisory */}
      {(researchIdeas.length > 0 || researchCands.length > 0) && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Rebalance from Research <span style={{ fontSize: 10, fontWeight: 400, color: '#f59e0b' }}>· advisory · not a model-supported signal</span></div>
            <span style={{ flex: 1 }} />
            {researchIdeas.length > 0 && <button disabled={!!busy} onClick={runGrokRebalanceReview} style={btn(!!busy)}>{busy === 'Grok Review Ideas' ? 'Reviewing…' : 'Grok Review These Ideas'}</button>}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Ideas to rotate from a trim-worthy holding into a high-conviction <b>research name you don't hold</b>. Review only — confirm sizing, tax, and account fit yourself; nothing is placed.
            <div style={{ marginTop: 4, color: '#f59e0b' }}><b>"stop-driven"</b> = the rotate-out reason is the Aegis stop/thesis signal, not the valuation trim score. These names have <b>trim score 0</b> on purpose — they're small positions with positive analyst upside, so the valuation engine wouldn't trim them; the broken stop is what flags them. (The engine doesn't see stop state, so the two signals can disagree — that's the point of showing both.)</div>
          </div>

          {rebalReview && (
            <div style={{ ...card, marginBottom: 12, borderColor: 'rgba(245,158,11,.3)' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b', marginBottom: 6 }}>Grok review of these ideas <span style={{ fontSize: 9.5, fontWeight: 400, color: 'var(--text3)' }}>· free / OAuth · no API key</span></div>
              {rebalReview.grok_answer ? (
                <div style={{ fontSize: 12, color: 'var(--text0)', whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{rebalReview.grok_answer}</div>
              ) : (
                <div style={{ fontSize: 11, color: '#ef4444' }}>{rebalReview.error ?? rebalReview.note ?? 'No review returned.'}</div>
              )}
            </div>
          )}

          {researchIdeas.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12, marginBottom: 14 }}>
              {researchIdeas.map((idea: any, idx: number) => {
                const fk = `${idea.from_symbol}-${idea.to_symbol}`
                const fb = feedbackState[fk]
                return (
                <article key={`${fk}-${idx}`} style={{ ...card, borderColor: idea.from_degradation ? 'rgba(239,68,68,.4)' : 'rgba(96,165,250,.3)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
                    <ActionBadge cls={idea.action_class} />
                    {idea.from_degradation && <DegBadge d={idea.from_degradation} />}
                    <span style={{ flex: 1 }} />
                    {idea.from_degradation
                      ? <span style={{ fontSize: 10, color: '#ef4444', fontWeight: 700 }} title="Driven by the stop-risk signal, not the valuation trim score (which is 0 for this small/high-upside name)">stop-driven</span>
                      : (idea.score ? <span style={{ fontSize: 10, color: 'var(--text3)' }}>trim {idea.score}</span> : null)}
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace', marginBottom: 2 }}>{idea.from_symbol ?? '—'} → <span style={{ color: '#22c55e' }}>{idea.to_symbol ?? '—'}</span></div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'monospace', marginBottom: 6 }}>
                    {px(idea.from_price)}{idea.from_shares_held != null && <span> · {Math.round(idea.from_shares_held).toLocaleString()} shares held</span>} → {px(idea.to_price)}
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--text0)', lineHeight: 1.5, marginBottom: 8, padding: '7px 9px', background: 'rgba(96,165,250,.08)', borderLeft: '3px solid #60a5fa', borderRadius: 4 }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: 0.4 }}>In plain English</span>
                    <div style={{ marginTop: 2 }}>{plainRec(idea)}</div>
                  </div>
                  {idea.rationale && <details style={{ marginBottom: 8 }}><summary style={{ fontSize: 9.5, color: 'var(--text3)', cursor: 'pointer' }}>technical detail</summary><div style={{ fontSize: 10.5, color: 'var(--text2)', lineHeight: 1.5, marginTop: 4 }}>{idea.rationale}</div></details>}
                  {idea.review_amount_range && (
                    <div style={{ fontSize: 10.5, color: 'var(--text3)', marginBottom: 8 }}>
                      Review range: <b style={{ color: 'var(--text1)' }}>{rangeText(idea.review_amount_range)}</b>
                      {(sh(idea.sell_shares_range) || sh(idea.buy_shares_range)) && (
                        <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                          {sh(idea.sell_shares_range) && (
                            <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'rgba(239,68,68,.12)', color: '#ef4444', border: '1px solid #ef444433', fontWeight: 700 }}>
                              {idea.review_amount_range?.action === 'reduce_or_close' ? 'review reducing/closing' : idea.review_amount_range?.action === 'reduce' ? 'review reducing' : 'review trimming'} ~{sh(idea.sell_shares_range)} {idea.from_symbol}
                            </span>
                          )}
                          {sh(idea.buy_shares_range) && (
                            <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'rgba(34,197,94,.12)', color: '#22c55e', border: '1px solid #22c55e33', fontWeight: 700 }}>
                              ≈ {sh(idea.buy_shares_range)} {idea.to_symbol}
                            </span>
                          )}
                        </div>
                      )}
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>{idea.review_amount_range.basis ?? '5–15% of the position — advisory, operator-confirmed, not auto-placed'}</div>
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                    {fb && fb !== 'error' && fb !== '…' ? (
                      <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 700 }}>✓ {fb} — logged to learning loop</span>
                    ) : (
                      <>
                        <button disabled={fb === '…'} onClick={() => sendFeedback(idea, 'reviewed')} style={{ ...btn(fb === '…'), padding: '4px 10px', fontSize: 10.5 }}>Reviewed</button>
                        <button disabled={fb === '…'} onClick={() => sendFeedback(idea, 'dismissed')} style={{ ...btn(fb === '…'), padding: '4px 10px', fontSize: 10.5, borderColor: '#6b728055', background: 'rgba(107,114,128,.15)', color: '#9ca3af' }}>Dismiss</button>
                        {fb === '…' && <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>saving…</span>}
                        {fb === 'error' && <span style={{ fontSize: 9.5, color: '#ef4444' }}>save failed — retry</span>}
                      </>
                    )}
                  </div>
                </article>
              )})}
            </div>
          )}

          {researchCands.length > 0 && (
            <>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 2 }}>Research candidates to rotate into (not held)</div>
              <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 8 }}>Ranked by Hermes composite (momentum/setup/social) — but the <b>CIO view</b> + <b>analyst coverage depth</b> are now shown on each, and the rotate-into <i>ideas</i> above only target names the CIO would actually BUY. A high Hermes rank with <span style={{ color: '#ef4444' }}>CIO: AVOID</span> or <span style={{ color: '#f59e0b' }}>1 analyst ⚠ thin</span> means hype/coverage outran conviction — not a buy.</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                {researchCands.map((c: any, idx: number) => {
                  const hasAnalyst = c.analyst_upside_pct != null || c.analyst_rating
                  const enriched = !!(c.sector && hasAnalyst && c.description)
                  return (
                  <article key={`${c.symbol}-${idx}`} style={{ ...card, borderColor: c.cio_avoid ? 'rgba(239,68,68,.35)' : c.cio_endorsed ? 'rgba(34,197,94,.3)' : 'var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{c.symbol}</span>
                      <InstrBadge t={c.instrument_type} />
                      {c.cio_view && <span title="CIO holistic view (watchlist final synthesis)" style={{ fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 3, background: c.cio_avoid ? '#ef44441f' : c.cio_endorsed ? '#22c55e1f' : '#6b72801f', color: c.cio_avoid ? '#ef4444' : c.cio_endorsed ? '#22c55e' : '#9ca3af', border: `1px solid ${c.cio_avoid ? '#ef444455' : c.cio_endorsed ? '#22c55e55' : '#6b728055'}` }}>CIO: {c.cio_view}</span>}
                      {c.hermes_rank != null && <span style={{ fontSize: 9.5, color: '#a855f7' }}>★#{c.hermes_rank}</span>}
                      <span style={{ flex: 1 }} />
                      {c.analyst_rating
                        ? <ActionBadge cls={String(c.analyst_rating).includes('buy') ? 'ADD_REVIEW' : 'WATCH'} />
                        : <span style={{ fontSize: 8, color: 'var(--text3)', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 5px' }}>{enriched ? '' : 'enriching'}</span>}
                    </div>
                    {/* uniform rows so every card carries the same fields (placeholders when data is pending) */}
                    <div style={{ fontSize: 9.5, color: c.sector ? 'var(--text3)' : 'var(--text3)', opacity: c.sector ? 1 : 0.6, marginBottom: 6 }}>{c.sector ?? 'sector pending'}</div>
                    <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text1)', marginBottom: 4 }}>
                      <span style={{ color: 'var(--text3)', fontSize: 9 }}>live </span>{c.price != null ? px(c.price) : '—'}
                      {c.day_change_pct != null && <span style={{ color: dayColor(c.day_change_pct), marginLeft: 6 }}>{dayText(c.day_change_pct)}</span>}
                    </div>
                    {/* Disciplined target entry (operator: no blind market buys). Plan from watchlist_entry_planner. */}
                    {c.entry_plan?.limit_price != null ? (
                      <div style={{ fontSize: 9.5, fontFamily: 'monospace', marginBottom: 5, padding: '3px 6px', borderRadius: 5, background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.25)', lineHeight: 1.5 }}>
                        <span style={{ fontWeight: 800, color: '#22c55e' }}>🎯 entry {px(c.entry_plan.limit_price)}</span>
                        {c.entry_plan.entry_zone_low != null && <span style={{ color: 'var(--text2)' }}> · zone {px(c.entry_plan.entry_zone_low)}–{px(c.entry_plan.entry_zone_high)}</span>}
                        {c.entry_plan.stop_price != null && <span style={{ color: '#ef4444' }}> · stop {px(c.entry_plan.stop_price)}</span>}
                        {c.entry_plan.target_price != null && <span style={{ color: 'var(--text2)' }}> · tgt {px(c.entry_plan.target_price)}</span>}
                        {c.entry_plan.risk_reward != null && <span style={{ color: 'var(--text3)' }}> · R:R {c.entry_plan.risk_reward}</span>}
                        {(c.entry_plan.urgency || c.entry_plan.proposal_tag) && <span style={{ marginLeft: 5, fontWeight: 800, color: c.entry_plan.urgency === 'ready' ? '#22c55e' : c.entry_plan.urgency === 'near_entry' ? '#f59e0b' : '#9ca3af' }}>{c.entry_plan.urgency === 'ready' ? 'READY' : c.entry_plan.urgency === 'near_entry' ? 'NEAR-ENTRY' : (c.entry_plan.proposal_tag || 'WATCH')}</span>}
                      </div>
                    ) : (
                      <div style={{ fontSize: 9, color: '#f59e0b', marginBottom: 5, opacity: 0.85 }}>⏳ target entry pending — review before buying (no blind market buy)</div>
                    )}
                    <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text2)', flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ opacity: hasAnalyst ? 1 : 0.55 }}>{c.analyst_upside_pct != null ? `upside ${c.analyst_upside_pct}%` : 'analyst pending'}</span>
                      {c.analyst_opinions != null && <span style={{ color: c.thin_coverage ? '#f59e0b' : 'var(--text3)' }}>{c.analyst_opinions} analyst{c.analyst_opinions === 1 ? '' : 's'}{c.thin_coverage ? ' ⚠ thin' : ''}</span>}
                      {c.analyst_opinions == null && c.instrument_type === 'stock' && <span style={{ color: '#f59e0b' }}>no coverage ⚠</span>}
                      {c.score != null && <span>score {Math.round(c.score)}</span>}
                    </div>
                    <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 5, lineHeight: 1.4, opacity: c.description ? 1 : 0.55 }}>
                      {c.description || 'Company profile pending — Hermes research queued for this name.'}
                    </div>
                  </article>
                )})}
              </div>
            </>
          )}
        </section>
      )}

      {data?.generated_at && (
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
          Source: /api/v2/rotation/summary · generated {data.generated_at} · advisory only, no broker action
        </div>
      )}
      </>)}
    </div>
  )
}
