import { useEffect, useState, useCallback, type CSSProperties, type ReactNode } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

/**
 * /v3/cio — the private investment office home (Phase 8).
 *
 * Decision-first, evidence-later. Six sections:
 *   CIO NOW · CAPITAL PLAN · PORTFOLIO POSTURE · OPPORTUNITIES · REPORT · EVIDENCE
 *
 * UX rules enforced here:
 *   - dollars before percentages when discussing action
 *   - plain-English labels (no snake_case in primary views)
 *   - no model/process telemetry above the fold (that lives in EVIDENCE)
 *   - stale/missing evidence is muted, never red (red = negative investment judgment)
 *   - render state never implies a model ran when it did not
 */

interface Props { onDrill?: (ctx: any) => void }

type DecisionFreshnessBoard = {
  name?: string
  detail?: string
  status?: string
  age_seconds?: number | null
}

type DecisionFreshness = {
  version?: string
  reasons?: string[]
  evidence_source_count?: number
  session?: string
  board?: DecisionFreshnessBoard[]
  financial_truth_quality?: string
  state?: string
  label?: string
}

type Decision = {
  kind: 'position' | 'action'
  symbol?: string | null
  account?: string | null
  stance?: string
  delta_usd?: number | null
  value_usd?: number | null
  weight_pct?: number | null
  why_now?: string
  risk?: string | null
  urgency?: 'high' | 'medium' | 'low'
  next_review?: string | null
  tax_note?: string | null
  counter_thesis?: string | null
  action_id?: string
  domain?: string
  // Phase 5 — institutional card fields (render only when present)
  decision_id?: string | null
  decision_input_digest?: string | null
  decision_evidence_digest?: string | null
  action?: string | null
  action_label?: string | null
  action_label_display?: string | null
  act_now?: boolean | null
  current_weight_pct?: number | null
  target_weight_pct?: number | null
  recommended_delta_usd?: number | null
  trim_to_clear_fire_usd?: number | null
  trim_to_policy_usd?: number | null
  scenario_trim_usd?: number | null
  target_status?: string | null
  sizing_method?: string | null
  sizing_objective?: string | null
  freshness?: DecisionFreshness | string | null
}

type CioAttention = {
  investment_decisions?: number
  workflow_actions?: number
  open_plans?: number
  material_today?: number
  material_today_ids?: string[]
  labels?: Record<string, string>
  note?: string
}

type CioNow = {
  decisions: Decision[]
  decision_count: number
  open_actions_count: number
  open_plans_count: number
  material_today_count?: number
  attention?: CioAttention
}

type Home = {
  ok?: boolean
  as_of?: string
  authority?: string
  version?: string
  cio_now: CioNow
  capital_plan: CapitalPlan
  posture: Posture
  opportunities: Opportunities
  report: ReportSummary
  evidence: Evidence
}

type CapitalPlan = {
  cash_total_usd: number | null
  cash_reserved_usd: number | null
  cash_investable_usd: number | null
  cash_band: { min_pct: number | null; max_pct: number | null }
  recommended_deploy_usd: number | null
  recommended_raise_usd: number | null
  sources: { label: string; usd: number }[]
  uses: { label: string; usd: number }[]
  post_plan_cash_usd: number | null
  post_plan_cash_pct: number | null
  cash_posture: string
}

type Posture = {
  thesis: { stance: string; summary: string | null; principles: string[] }
  concentration: { top_position: string | null; top_weight_pct: number | null; fire_pct: number | null }
  risk_heat: { max_drawdown_pct: number | null; sharpe: number | null; sortino: number | null }
  sector_tilts: { sector: string; state: string; exposure_pct: number | null; target_pct: number | null; recommendation: string }[]
  performance: { portfolio_cagr: number | null; benchmark_cagr: number | null; alpha_annualized: number | null; benchmark_label: string | null }
  income: { total_usd: number | null }
  tax_issues: string[]
  constraints: string[]
}

type Opportunities = {
  watch: { symbol: string; source: string; signal: string; label: string }[]
  reentry: { symbol: string; source: string; signal: string; label: string }[]
  rotation: { sector: string; state: string; recommendation: string }[]
  research_gaps: { symbol: string; sector: string }[]
}

type ReportSummary = {
  as_of: string | null
  report_version: string | null
  source_sha: string | null
  manifest_hash: string | null
  source_traceability_pct: number | null
  field_count: number | null
  fields_present: number | null
  fields_unavailable: string[]
  quality_flag_count: number | null
  pdf_pages: number | null
  render_errors: string[]
}

type Evidence = {
  as_of: string | null
  report_version: string | null
  authority: string | null
  source_sha: string | null
  source_refs: { name: string; sha256: string }[]
  validator_states: { reviewer: string; status: string; ts: string; contradictions?: number }[]
  run_ids: { id: string; state: string; ts: string }[]
  internal_codes: string[]
}

type DispositionRec = {
  disposition: string
  rating?: number | null
  identity_class?: string
  note?: string
  occurred_at?: string
}
type DispositionMap = Record<string, DispositionRec>

const TABS = ['cio-now', 'capital-plan', 'posture', 'opportunities', 'report', 'evidence'] as const
type Tab = typeof TABS[number]

const TAB_LABEL: Record<Tab, string> = {
  'cio-now': 'CIO NOW',
  'capital-plan': 'CAPITAL PLAN',
  posture: 'PORTFOLIO POSTURE',
  opportunities: 'OPPORTUNITIES',
  report: 'REPORT',
  evidence: 'EVIDENCE / AUDIT',
}

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return '—'
  const sign = n < 0 ? '−' : ''
  const abs = Math.abs(n)
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}K`
  return `${sign}$${abs.toFixed(0)}`
}

function fmtPct(n: number | null | undefined, signed = false): string {
  if (n == null) return '—'
  return `${signed && n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

function fmtSignedUsd(n: number | null | undefined): string {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : '−'}${fmtUsd(Math.abs(n))}`
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—'
  return n.toFixed(digits)
}

const CODE_LABEL: Record<string, string> = {
  ACT_NOW: 'ACT NOW',
  REVIEW: 'REVIEW',
  WATCH: 'WATCH',
  REVALIDATE: 'REVALIDATE',
  DATA_CONFLICT: 'DATA CONFLICT',
  STALE_REFRESH_REQUIRED: 'STALE — REFRESH REQUIRED',
  clear_fire_staged: 'Clear fire, staged',
  policy_normalize_staged: 'Policy normalize, staged',
  scenario_only: 'Scenario only',
  full_exit: 'Full exit',
  headroom_bounded_default: 'Headroom-bounded default',
}

function proseCode(s: string | null | undefined): string {
  if (!s) return ''
  return CODE_LABEL[s] || s.replace(/_/g, ' ')
}

function shortDecisionId(id: string): string {
  if (id.startsWith('dec_') && id.length > 16) return `dec_${id.slice(4, 16)}`
  return id.length > 16 ? `${id.slice(0, 16)}…` : id
}

function freshnessLine(f: Decision['freshness']): string | null {
  if (f == null || f === '') return null
  if (typeof f === 'string') return f
  if (f.label) return String(f.label)
  if (f.state) return proseCode(f.state)
  const board = Array.isArray(f.board) ? f.board : []
  const notable = board.filter(b => {
    const d = String(b.detail || b.status || '').toLowerCase()
    return d && d !== 'ok' && d !== 'pass'
  })
  if (notable.length) {
    return notable.slice(0, 2).map(b => {
      const name = b.name ? proseCode(b.name) : 'Source'
      const det = proseCode(String(b.detail || b.status || ''))
      return det ? `${name}: ${det}` : name
    }).join(' · ')
  }
  if (f.financial_truth_quality) return `Truth ${proseCode(f.financial_truth_quality)}`
  if (board.length) return 'Fresh'
  return null
}

// Canonical actionability (fail-closed): stale / conflict / revalidate override
// ACT_NOW. Risk text never renders ACT NOW. Only a fresh decision that is
// explicitly actionable (act_now or ACT_NOW label) may render ACT NOW.
function freshnessFlag(f: Decision['freshness']): string {
  if (f == null || f === '') return ''
  if (typeof f === 'string') return f.toUpperCase()
  const obj = f as any
  return String(obj.state || obj.label || obj.status || '').toUpperCase()
}

function actionability(d: Decision): { label: string; color: string } {
  const al = (d.action_label || '').toUpperCase()
  const ff = freshnessFlag(d.freshness)
  // Blocking states override ACT_NOW (fail-closed).
  if (al === 'DATA_CONFLICT' || ff === 'DATA_CONFLICT') return { label: 'DATA CONFLICT', color: 'var(--amber)' }
  if (al === 'STALE_REFRESH_REQUIRED' || al === 'REVALIDATE' || ff === 'STALE_REFRESH_REQUIRED' || ff === 'REVALIDATE' || ff === 'STALE' || ff === 'EXPIRED') {
    return { label: 'REVALIDATE', color: 'var(--amber)' }
  }
  if (d.act_now || al === 'ACT_NOW') return { label: 'ACT NOW', color: 'var(--red)' }
  if (al === 'REVIEW') return { label: 'REVIEW', color: 'var(--amber)' }
  return { label: 'WATCH', color: 'var(--text3)' }
}

// ── Shared style tokens ────────────────────────────────────────────────────────
const card: CSSProperties = {
  background: 'var(--bg2)', borderRadius: 8, padding: 16,
  border: '1px solid var(--border)', marginBottom: 16,
}
const kLabel: CSSProperties = {
  fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase',
  letterSpacing: '.4px', fontWeight: 700,
}
const muted: CSSProperties = { fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }
const faint: CSSProperties = { fontSize: 12, color: 'var(--text3)', lineHeight: 1.45 }

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 10, letterSpacing: '.2px' }}>
      {children}
    </div>
  )
}

function Stat({ label, value, sub, help }: { label: string; value: ReactNode; sub?: ReactNode; help?: string }) {
  return (
    <div title={help} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '12px 16px', border: '1px solid var(--border)', minWidth: 0 }}>
      <div style={kLabel}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)', marginTop: 2, whiteSpace: 'nowrap' }}>{value}</div>
      {sub != null && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div style={{ ...faint, padding: '8px 0' }}>{text}</div>
}

// ── Decision card with operator actions ───────────────────────────────────────

function decisionKey(d: Decision): string {
  // Canonical key is decision_id. Never POST position:symbol:account.
  return (d.decision_id || '').trim()
}

function legacyDispositionKey(d: Decision): string {
  if (d.kind === 'action') return `action:${d.action_id || 'unknown'}`
  return `position:${d.symbol || '?'}:${d.account || 'any'}`
}

function DecisionActions({ d, dispositions, legacyUnversioned, onAct }: {
  d: Decision
  dispositions: DispositionMap
  legacyUnversioned: DispositionMap
  onAct: (d: Decision, disposition: string, rating?: number) => void
}) {
  const key = decisionKey(d)
  const cur = key ? dispositions[key]?.disposition : undefined
  const legacy = legacyUnversioned[legacyDispositionKey(d)]
  const [rating, setRating] = useState<number>(0)
  const [showRate, setShowRate] = useState(false)

  const btn: CSSProperties = {
    padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)',
    background: 'var(--bg0)', color: 'var(--text1)', cursor: 'pointer',
    fontSize: 11, fontWeight: 600,
  }
  const active: CSSProperties = { ...btn, background: 'var(--accent-dim)', borderColor: 'var(--accent)', color: 'var(--accent)' }

  const canAct = Boolean(key)
  const act = (disp: string) => { if (canAct) onAct(d, disp, rating || undefined) }
  const rate = (n: number) => { setRating(n); setShowRate(false); if (canAct) onAct(d, cur || 'ack', n) }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 10 }}>
      <button type="button" disabled={!canAct} style={cur === 'ack' ? active : btn} onClick={() => act('ack')} aria-label={`Acknowledge ${d.symbol || d.action_id}`}>ACK</button>
      <button type="button" disabled={!canAct} style={cur === 'defer' ? active : btn} onClick={() => act('defer')} aria-label={`Defer ${d.symbol || d.action_id}`}>DEFER</button>
      <button type="button" disabled={!canAct} style={cur === 'done' ? active : btn} onClick={() => act('done')} aria-label={`Mark done ${d.symbol || d.action_id}`}>DONE</button>
      <button type="button" disabled={!canAct} style={cur === 'reject' ? { ...active, borderColor: 'var(--red)', color: 'var(--red)', background: 'var(--red-dim)' } : btn} onClick={() => act('reject')} aria-label={`Reject ${d.symbol || d.action_id}`}>REJECT</button>
      <button type="button" disabled={!canAct} style={showRate ? active : btn} onClick={() => setShowRate(v => !v)} aria-label={`Rate ${d.symbol || d.action_id}`}>RATE</button>
      {showRate && (
        <span style={{ display: 'inline-flex', gap: 4 }} role="radiogroup" aria-label="Usefulness rating">
          {[1, 2, 3, 4, 5].map(n => (
            <button key={n} type="button" style={n <= rating ? { ...btn, color: 'var(--amber)', borderColor: 'var(--amber)' } : btn}
              onClick={() => rate(n)} aria-label={`Rate ${n}`}>{n}</button>
          ))}
        </span>
      )}
      {rating > 0 && <span style={{ ...faint, fontSize: 11 }}>rated {rating}/5</span>}
      {!canAct && <span style={{ ...faint, fontSize: 11 }}>No decision id — disposition not recorded</span>}
      {legacy && (
        <span style={{ ...faint, fontSize: 11 }} title="Legacy position:symbol:account record is not applied to this decision">
          Legacy unversioned: {legacy.disposition} — not applied
        </span>
      )}
    </div>
  )
}

function DecisionCard({ d, dispositions, legacyUnversioned, onAct }: {
  d: Decision
  dispositions: DispositionMap
  legacyUnversioned: DispositionMap
  onAct: (d: Decision, disposition: string, rating?: number) => void
}) {
  const [open, setOpen] = useState(false)
  const act = actionability(d)
  const delta = d.recommended_delta_usd ?? d.delta_usd
  const weight = d.current_weight_pct ?? d.weight_pct
  const deltaColor = delta == null ? 'var(--text3)' : delta >= 0 ? 'var(--green)' : 'var(--red)'
  const title = d.kind === 'action' ? (d.why_now || d.action_id || 'Action') : `${d.symbol} · ${d.stance || 'Hold'}`
  const actionText = d.action_label_display || (d.action_label ? proseCode(d.action_label) : '')
  const sizingMethod = d.sizing_method ? proseCode(d.sizing_method) : ''
  const fresh = freshnessLine(d.freshness)
  const hasSizing = d.trim_to_clear_fire_usd != null || d.trim_to_policy_usd != null || !!sizingMethod || !!d.sizing_objective

  return (
    <div style={{ ...card, borderLeft: `3px solid ${act.color}` }} data-testid="cio-decision-card">
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'baseline' }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{title}</span>
        {d.account && d.kind === 'position' && <span style={faint}>{d.account.replace(/_/g, ' ')}</span>}
        <span style={{ fontSize: 11, fontWeight: 700, color: act.color, letterSpacing: '.3px', textTransform: 'uppercase' }}>
          {act.label}
        </span>
        {actionText && (
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)', letterSpacing: '.3px', textTransform: 'uppercase' }}>
            {actionText}
          </span>
        )}
        {d.decision_id && (
          <span style={faint} title={d.decision_id}>ID {shortDecisionId(d.decision_id)}</span>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, marginTop: 8 }}>
        <div>
          <div style={kLabel}>Dollar change</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: deltaColor }}>{fmtSignedUsd(delta)}</div>
        </div>
        <div>
          <div style={kLabel}>Position value</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmtUsd(d.value_usd)}</div>
        </div>
        <div>
          <div style={kLabel}>Current weight</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmtPct(weight)}</div>
        </div>
        {d.target_weight_pct != null && (
          <div>
            <div style={kLabel}>Target weight</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmtPct(d.target_weight_pct)}</div>
          </div>
        )}
        {d.next_review && (
          <div>
            <div style={kLabel}>Next review</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text2)' }}>{String(d.next_review).slice(0, 10)}</div>
          </div>
        )}
      </div>

      {hasSizing && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, marginTop: 8 }}>
          {d.trim_to_clear_fire_usd != null && (
            <div>
              <div style={kLabel}>Trim to clear fire</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{fmtUsd(d.trim_to_clear_fire_usd)}</div>
            </div>
          )}
          {d.trim_to_policy_usd != null && (
            <div>
              <div style={kLabel}>Trim to policy</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{fmtUsd(d.trim_to_policy_usd)}</div>
            </div>
          )}
          {sizingMethod && (
            <div>
              <div style={kLabel}>Sizing method</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text2)' }}>{sizingMethod}</div>
            </div>
          )}
          {d.scenario_trim_usd != null && (
            <div>
              <div style={kLabel}>Scenario trim (hypothetical)</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text2)' }}>{fmtUsd(d.scenario_trim_usd)}</div>
            </div>
          )}
        </div>
      )}

      {d.target_status === 'UNAVAILABLE' && (
        <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text2)' }}>
          Target weight unavailable — sizing did not produce a verified target.
        </div>
      )}

      {d.sizing_objective && (
        <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text1)' }}>
          <span style={{ color: 'var(--text3)' }}>Sizing: </span>{d.sizing_objective}
        </div>
      )}

      <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text1)' }}>
        <span style={{ color: 'var(--text3)' }}>Why now: </span>{d.why_now || '—'}
      </div>
      {fresh && (
        <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text2)' }}>
          <span style={{ color: 'var(--text3)' }}>Freshness: </span>{fresh}
        </div>
      )}

      <button type="button" onClick={() => setOpen(v => !v)} aria-expanded={open}
        style={{ background: 'transparent', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, fontWeight: 600, padding: '4px 0' }}>
        {open ? 'Hide evidence' : 'Why? · evidence'}
      </button>
      {open && (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 4 }} data-testid="cio-decision-evidence">
          {d.risk && <div style={faint}><span style={{ color: 'var(--text2)' }}>Risk: </span>{d.risk}</div>}
          {d.tax_note && <div style={faint}><span style={{ color: 'var(--text2)' }}>Tax: </span>{d.tax_note}</div>}
          {d.counter_thesis && <div style={faint}><span style={{ color: 'var(--text2)' }}>Counter-thesis: </span>{d.counter_thesis}</div>}
          {!d.risk && !d.tax_note && !d.counter_thesis && <div style={faint}>No additional evidence attached.</div>}
        </div>
      )}

      <DecisionActions d={d} dispositions={dispositions} legacyUnversioned={legacyUnversioned} onAct={onAct} />
    </div>
  )
}

// ── Section renderers ─────────────────────────────────────────────────────────

function CioNowSection({ home, dispositions, legacyUnversioned, onAct }: {
  home: Home
  dispositions: DispositionMap
  legacyUnversioned: DispositionMap
  onAct: (d: Decision, disp: string, r?: number) => void
}) {
  const now = home.cio_now
  const att = now.attention
  const investmentDecisions = att?.investment_decisions ?? now.decision_count
  const workflowActions = att?.workflow_actions ?? now.open_actions_count
  const openPlans = att?.open_plans ?? now.open_plans_count
  const materialToday = att?.material_today ?? now.material_today_count
  const { decisions } = now
  return (
    <div data-testid="cio-now-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Investment decisions" value={investmentDecisions} help="True investment decisions needing attention. Disjoint from workflow actions and plans." />
        <Stat label="Workflow actions" value={workflowActions} help="Open items in the CIO action ledger only — not mixed into decision cards." />
        <Stat label="Open plans" value={openPlans} help="Open advisory plans awaiting disposition." />
        <Stat label="Material Today" value={materialToday ?? '—'} help="Deduped priority set (not the sum of the other three). Cards show at most 5." />
      </div>
      {decisions.length === 0 ? (
        <Empty text="Nothing needs a decision right now. Portfolio is stable." />
      ) : (
        decisions.map((d, i) => <DecisionCard key={(decisionKey(d) || legacyDispositionKey(d)) + i} d={d} dispositions={dispositions} legacyUnversioned={legacyUnversioned} onAct={onAct} />)
      )}
    </div>
  )
}

function CapitalPlanSection({ cp }: { cp: CapitalPlan }) {
  return (
    <div data-testid="capital-plan-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Total cash" value={fmtUsd(cp.cash_total_usd)} help="All cash across accounts (audit-corrected sum of cash rows)." />
        <Stat label="Reserved cash" value={fmtUsd(cp.cash_reserved_usd)} help="Cash held back to the policy floor / reserve." />
        <Stat label="Investable cash" value={fmtUsd(cp.cash_investable_usd)} help="Cash above the reserve available to deploy." />
        <Stat label="Target band" value={cp.cash_band.min_pct != null && cp.cash_band.max_pct != null ? `${cp.cash_band.min_pct}–${cp.cash_band.max_pct}%` : '—'} help="Policy cash floor-to-ceiling as a share of portfolio." />
        <Stat label="Recommended deploy" value={fmtUsd(cp.recommended_deploy_usd)} help="Net dollars the desk recommends putting to work." />
        <Stat label="Recommended raise" value={fmtUsd(cp.recommended_raise_usd)} help="Prospective raise = future trims/exits not yet cash. Earmarked redeploy already in cash is not new capital." />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={card}>
          <SectionTitle>Sources of funds</SectionTitle>
          {cp.sources.length === 0 ? <Empty text="No sources projected." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="capital-sources">
              <tbody>
                {cp.sources.map((s, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 4px', fontSize: 12, color: 'var(--text1)' }}>{s.label}</td>
                    <td style={{ padding: '6px 4px', fontSize: 12, color: 'var(--text0)', textAlign: 'right', fontWeight: 600 }}>{fmtUsd(s.usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div style={card}>
          <SectionTitle>Uses of funds</SectionTitle>
          {cp.uses.length === 0 ? <Empty text="No uses projected." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="capital-uses">
              <tbody>
                {cp.uses.map((u, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 4px', fontSize: 12, color: 'var(--text1)' }}>{u.label}</td>
                    <td style={{ padding: '6px 4px', fontSize: 12, color: 'var(--text0)', textAlign: 'right', fontWeight: 600 }}>{fmtUsd(u.usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div style={{ ...card, marginTop: 16, display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'baseline' }}>
        <div>
          <div style={kLabel}>Resulting cash</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmtUsd(cp.post_plan_cash_usd)}</div>
        </div>
        <div>
          <div style={kLabel}>Post-plan cash %</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmtPct(cp.post_plan_cash_pct)}</div>
        </div>
        <div>
          <div style={kLabel}>Cash posture</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--accent)' }}>{cp.cash_posture}</div>
        </div>
      </div>
    </div>
  )
}

function PostureSection({ posture }: { posture: Posture }) {
  const { thesis, concentration, risk_heat, sector_tilts, performance, income, tax_issues, constraints } = posture
  return (
    <div data-testid="posture-section">
      <div style={card}>
        <SectionTitle>Thesis</SectionTitle>
        <div style={{ fontSize: 13, color: 'var(--text0)', fontWeight: 600 }}>{thesis.stance || 'No desk thesis published'}</div>
        {thesis.summary && <div style={{ ...muted, marginTop: 6 }}>{thesis.summary}</div>}
        {thesis.principles.length > 0 && (
          <div style={{ marginTop: 6 }}>
            {thesis.principles.map((p, i) => <div key={i} style={muted}>• {p}</div>)}
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Top position" value={concentration.top_position || '—'} sub={concentration.top_weight_pct != null ? `${fmtPct(concentration.top_weight_pct)} of portfolio` : undefined} help="Largest single position by weight." />
        <Stat label="Concentration cap" value={concentration.fire_pct != null ? `${fmtPct(concentration.fire_pct)}` : '—'} help="Single-name weight that trips a concentration fire." />
        <Stat label="Max drawdown" value={risk_heat.max_drawdown_pct != null ? fmtPct(risk_heat.max_drawdown_pct) : '—'} help="Largest peak-to-trough decline on record." />
        <Stat label="Sharpe" value={fmtNum(risk_heat.sharpe)} help="Risk-adjusted return vs volatility (higher is better)." />
        <Stat label="Sortino" value={fmtNum(risk_heat.sortino)} help="Risk-adjusted return vs downside volatility only." />
        <Stat label="Income (trailing)" value={fmtUsd(income.total_usd)} help="Total distributions recorded in the income ledger." />
      </div>

      <div style={card}>
        <SectionTitle>Performance vs benchmark</SectionTitle>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18 }}>
          <div>
            <div style={kLabel}>Portfolio CAGR</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{fmtPct(performance.portfolio_cagr)}</div>
          </div>
          <div>
            <div style={kLabel}>Benchmark</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text2)' }}>{performance.benchmark_label || '—'}</div>
          </div>
          <div>
            <div style={kLabel}>Benchmark CAGR</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{fmtPct(performance.benchmark_cagr)}</div>
          </div>
          <div>
            <div style={kLabel}>Alpha (annualized)</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: performance.alpha_annualized != null && performance.alpha_annualized >= 0 ? 'var(--green)' : 'var(--red)' }}>
              {fmtPct(performance.alpha_annualized, true)}
            </div>
          </div>
        </div>
      </div>

      {sector_tilts.length > 0 && (
        <div style={card}>
          <SectionTitle>Sector tilts</SectionTitle>
          <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="sector-tilts">
            <thead>
              <tr>
                <th style={{ textAlign: 'left', fontSize: 11, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>Sector</th>
                <th style={{ textAlign: 'left', fontSize: 11, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>State</th>
                <th style={{ textAlign: 'right', fontSize: 11, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>Exposure</th>
                <th style={{ textAlign: 'right', fontSize: 11, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>Target</th>
              </tr>
            </thead>
            <tbody>
              {sector_tilts.map((s, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '5px 6px', fontSize: 12, color: 'var(--text0)' }}>{s.sector}</td>
                  <td style={{ padding: '5px 6px', fontSize: 12, color: 'var(--text2)' }}>{s.state}</td>
                  <td style={{ padding: '5px 6px', fontSize: 12, color: 'var(--text0)', textAlign: 'right' }}>{fmtPct(s.exposure_pct)}</td>
                  <td style={{ padding: '5px 6px', fontSize: 12, color: 'var(--text2)', textAlign: 'right' }}>{fmtPct(s.target_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(tax_issues.length > 0 || constraints.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          {tax_issues.length > 0 && (
            <div style={card}>
              <SectionTitle>Tax issues</SectionTitle>
              {tax_issues.map((t, i) => <div key={i} style={{ ...muted, marginBottom: 4 }}>• {t}</div>)}
            </div>
          )}
          {constraints.length > 0 && (
            <div style={card}>
              <SectionTitle>Active constraints</SectionTitle>
              {constraints.map((c, i) => <div key={i} style={{ ...muted, marginBottom: 4 }}>• {c.replace(/_/g, ' ')}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function OpportunitiesSection({ opp }: { opp: Opportunities }) {
  const list = (items: { symbol: string; signal: string; source: string }[]) =>
    items.length === 0 ? <Empty text="None." /> : (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {items.map((it, i) => (
          <span key={i} title={`${it.signal} · source: ${it.source}`} style={{
            padding: '6px 12px', borderRadius: 6, background: 'var(--bg0)', border: '1px solid var(--border)', fontSize: 12,
          }}>
            <strong style={{ color: 'var(--text0)' }}>{it.symbol}</strong>
            <span style={{ color: 'var(--text2)', marginLeft: 6 }}>{it.signal}</span>
          </span>
        ))}
      </div>
    )

  return (
    <div data-testid="opportunities-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={card}>
          <SectionTitle>Watch candidates</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>Sourced from the advisory, defense, and CIO desks.</div>
          {list(opp.watch)}
        </div>
        <div style={card}>
          <SectionTitle>Re-entry</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>Names flagged to re-enter after an exit.</div>
          {list(opp.reentry)}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={card}>
          <SectionTitle>Rotation ideas</SectionTitle>
          {opp.rotation.length === 0 ? <Empty text="None." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {opp.rotation.map((r, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--text0)' }}>{r.sector}</td>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--text2)' }}>{r.state}</td>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--accent)' }}>{r.recommendation?.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div style={card}>
          <SectionTitle>Research gaps</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>Candidates that need research before a decision.</div>
          {opp.research_gaps.length === 0 ? <Empty text="None." /> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {opp.research_gaps.map((g, i) => (
                <span key={i} style={{ padding: '5px 10px', borderRadius: 6, background: 'var(--amber-dim)', border: '1px solid var(--amber)', fontSize: 12, color: 'var(--amber)' }}>
                  {g.symbol} <span style={{ color: 'var(--text3)' }}>· {g.sector}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ReportSection({ report }: { report: ReportSummary }) {
  const [html, setHtml] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [generatedAt, setGeneratedAt] = useState<string | null>(null)

  const generate = useCallback(() => {
    setBusy(true); setErr(null)
    fetch(`/api/v2/cio/report-v2?_=${Date.now()}`, { cache: 'no-store' })
      .then(async r => {
        const j = await r.json()
        if (!r.ok || !j?.ok) throw new Error(j?.error || `HTTP ${r.status}`)
        setHtml(j.html || null)
        setGeneratedAt(j.as_of || null)
      })
      .catch(e => setErr(String(e?.message || e)))
      .finally(() => setBusy(false))
  }, [])

  return (
    <div data-testid="report-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Source traceability" value={report.source_traceability_pct != null ? `${report.source_traceability_pct}%` : '—'} help="Share of reported numerical fields carrying a source." />
        <Stat label="Fields covered" value={`${report.fields_present ?? 0}/${report.field_count ?? '—'}`} help="Fields with source proof vs total required fields." />
        <Stat label="Unavailable fields" value={report.fields_unavailable.length} help="Fields explicitly unavailable (never estimated)." />
        <Stat label="Quality flags" value={report.quality_flag_count ?? 0} help="Fields using a documented methodology substitute." />
      </div>

      <div style={card}>
        <SectionTitle>Latest institutional report</SectionTitle>
        <div style={{ ...muted, marginBottom: 10 }}>
          {report.as_of ? `As of ${String(report.as_of).slice(0, 19).replace('T', ' ')}` : 'No report generated yet.'}
          {report.source_sha ? ` · source ${String(report.source_sha).slice(0, 12)}` : ''}
        </div>
        {report.render_errors.length > 0 && (
          <div style={{ ...faint, color: 'var(--amber)', marginBottom: 8 }}>
            PDF not rendered in this environment: {report.render_errors.join('; ')}
          </div>
        )}
        {report.fields_unavailable.length > 0 && (
          <div style={{ ...faint, marginBottom: 8 }}>
            Unavailable: {report.fields_unavailable.map(f => f.replace(/_/g, ' ')).join(' · ')}
          </div>
        )}
        <button type="button" onClick={generate} disabled={busy}
          style={{ padding: '8px 16px', borderRadius: 6, border: '1px solid var(--accent)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer', fontSize: 13, fontWeight: 700 }}>
          {busy ? 'Generating…' : 'Generate now'}
        </button>
        {err && <div style={{ ...faint, color: 'var(--red)', marginTop: 8 }}>{err}</div>}
      </div>

      {html && (
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', fontSize: 12, color: 'var(--text2)' }}>
            Full report{generatedAt ? ` · generated ${String(generatedAt).slice(0, 19).replace('T', ' ')}` : ''}
          </div>
          <iframe title="Institutional report" srcDoc={html} style={{ width: '100%', height: 720, border: 'none', background: 'var(--text0)' }} data-testid="report-iframe" />
        </div>
      )}
    </div>
  )
}

function EvidenceSection({ evidence }: { evidence: Evidence }) {
  return (
    <div data-testid="evidence-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Authority" value="Read-only advisory" help="This office composes advice; it cannot trade or move stops." />
        <Stat label="Report version" value={evidence.report_version || '—'} help="Version of the report generator." />
        <Stat label="Source SHA" value={evidence.source_sha ? String(evidence.source_sha).slice(0, 12) : '—'} help="Git commit the data was read from." />
        <Stat label="As of" value={evidence.as_of ? String(evidence.as_of).slice(0, 19).replace('T', ' ') : '—'} help="When the data snapshot was taken." />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={card}>
          <SectionTitle>Source references</SectionTitle>
          {evidence.source_refs.length === 0 ? <Empty text="None." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {evidence.source_refs.map((s, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--text1)' }}>{s.name}</td>
                    <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text3)', textAlign: 'right', fontFamily: 'monospace' }}>{String(s.sha256).slice(0, 12)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={card}>
          <SectionTitle>Validator states</SectionTitle>
          {evidence.validator_states.length === 0 ? <Empty text="None recorded." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {evidence.validator_states.map((v, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--text1)' }}>{v.reviewer}</td>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: v.status === 'PASS' ? 'var(--green)' : 'var(--text2)' }}>{v.status}</td>
                    <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text3)', textAlign: 'right' }}>{String(v.ts || '').slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={card}>
          <SectionTitle>Run / handoff IDs</SectionTitle>
          {evidence.run_ids.length === 0 ? <Empty text="None." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {evidence.run_ids.map((r, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--text1)' }}>{String(r.id || '').slice(0, 40)}</td>
                    <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text3)', textAlign: 'right' }}>{r.state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={card}>
          <SectionTitle>Internal codes</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>Fields the report explicitly marks unavailable (never estimated).</div>
          {evidence.internal_codes.length === 0 ? <Empty text="None." /> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {evidence.internal_codes.map((c, i) => (
                <code key={i} style={{ padding: '3px 8px', borderRadius: 4, background: 'var(--bg0)', border: '1px solid var(--border)', fontSize: 11, color: 'var(--text2)' }}>{c}</code>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ ...card, fontSize: 11, color: 'var(--text3)', marginTop: 16 }}>
        Model/process provenance lives here, below the fold. The office is READ_ONLY_ADVISORY — no broker, order, stop, or 2FA authority.
        {' · '}
        <Link to="/system" style={{ color: 'var(--accent)' }}>System</Link>
        {' · '}
        <Link to="/advisory" style={{ color: 'var(--accent)' }}>Advisory desk</Link>
        {' · '}
        <Link to="/agents" style={{ color: 'var(--accent)' }}>Agent runtime</Link>
      </div>
    </div>
  )
}

// ── Main hub ──────────────────────────────────────────────────────────────────

export default function CioHub({ onDrill }: Props) {
  const [sp, setSp] = useSearchParams()
  const planId = (sp.get('plan') || '').trim()
  const tabParam = (sp.get('tab') || '').trim() as Tab
  const initialTab: Tab = TABS.includes(tabParam) ? tabParam : 'cio-now'
  const [tab, setTab] = useState<Tab>(initialTab)
  const [dispositions, setDispositions] = useState<DispositionMap>({})
  const [legacyUnversioned, setLegacyUnversioned] = useState<DispositionMap>({})
  const { data, loading, error } = useApi<Home>('/api/v3/cio/home')

  useEffect(() => {
    if (TABS.includes(tabParam)) setTab(tabParam)
  }, [tabParam])

  useEffect(() => {
    fetch('/api/v3/cio/dispositions', { cache: 'no-store' })
      .then(r => r.json())
      .then(j => {
        if (j?.ok) {
          setDispositions(j.dispositions || {})
          setLegacyUnversioned(j.legacy_unversioned || {})
        }
      })
      .catch(() => { /* advisory-only; dispositions just won't pre-fill */ })
  }, [])

  const onAct = useCallback((d: Decision, disposition: string, rating?: number) => {
    const decisionId = (d.decision_id || '').trim()
    if (!decisionId) return
    const body: Record<string, unknown> = {
      disposition,
      rating,
      decision_id: decisionId,
      symbol: d.symbol ?? null,
      account: d.account ?? null,
      action: d.action || d.stance || null,
    }
    if (d.decision_input_digest) body.decision_input_digest = d.decision_input_digest
    if (d.decision_evidence_digest) body.decision_evidence_digest = d.decision_evidence_digest
    fetch(`/api/v3/cio/decision/${encodeURIComponent(decisionId)}/disposition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(j => {
        if (j?.ok) {
          setDispositions(prev => ({ ...prev, [decisionId]: { disposition: j.disposition.disposition, rating: j.disposition.rating, identity_class: j.disposition.identity_class } }))
        }
      })
      .catch(() => { /* keep last state; no fake success */ })
  }, [])

  const selectTab = (t: Tab) => {
    setTab(t)
    const next = new URLSearchParams(sp)
    next.set('tab', t)
    setSp(next, { replace: true })
  }

  const home = data

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1240 }} data-testid="cio-hub">
      <div style={hubTitle()}>CIO — Private Investment Office</div>
      <div style={hubSubtitle()}>
        Alex · Chief Investment Officer · READ_ONLY_ADVISORY
        {home?.as_of && <span style={{ color: 'var(--text3)', marginLeft: 12 }}>As of {new Date(home.as_of).toLocaleString()}</span>}
      </div>

      {/* Tab nav */}
      <nav style={{ display: 'flex', gap: 6, margin: '14px 0 20px', flexWrap: 'wrap' }} aria-label="Office sections" role="tablist">
        {TABS.map(t => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => selectTab(t)}
            style={{
              padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)',
              background: tab === t ? 'var(--accent-dim)' : 'var(--bg2)',
              color: tab === t ? 'var(--accent)' : 'var(--text2)', cursor: 'pointer',
              fontSize: 12, fontWeight: tab === t ? 700 : 500, letterSpacing: '.4px',
            }}
          >
            {TAB_LABEL[t]}
          </button>
        ))}
      </nav>

      {loading && !home && (
        <div style={{ padding: '12px 0', color: 'var(--text2)', fontSize: 13 }} data-testid="cio-home-loading">
          Loading office home…
        </div>
      )}
      {error && !home && (
        <div style={{ padding: '12px 0', color: 'var(--amber)', fontSize: 13 }} data-testid="cio-home-error">
          Office home unavailable: {String(error)}
        </div>
      )}

      {home && (
        <div role="tabpanel" aria-label={TAB_LABEL[tab]}>
          {tab === 'cio-now' && <CioNowSection home={home} dispositions={dispositions} legacyUnversioned={legacyUnversioned} onAct={onAct} />}
          {tab === 'capital-plan' && <CapitalPlanSection cp={home.capital_plan} />}
          {tab === 'posture' && <PostureSection posture={home.posture} />}
          {tab === 'opportunities' && <OpportunitiesSection opp={home.opportunities} />}
          {tab === 'report' && <ReportSection report={home.report} />}
          {tab === 'evidence' && <EvidenceSection evidence={home.evidence} />}
        </div>
      )}

      {/* Deep-linked plan detail (specialist/evidence workspace) */}
      {planId && (
        <div style={{ marginTop: 24 }}>
          <PlanDetailPanel planId={planId} />
        </div>
      )}
    </div>
  )
}

// ── Deep-linked advisory plan (specialist/evidence workspace) ─────────────────

type Plan = {
  plan_id?: string
  situation_type?: string
  situation_label?: string
  symbols?: string[]
  status?: string
  summary?: string
  summary_clean?: string
  recommendation?: string
  recommendation_clean?: string
  options?: { id?: string; label?: string; pros?: string; cons?: string }[]
  risks?: string[]
  evidence_refs?: any[]
  fire_reasons?: string[]
  fire_reasons_human?: string[]
  thesis_version?: string
  owner_agent?: string
  revisit_at?: string
}

function PlanDetailPanel({ planId }: { planId: string }) {
  const [payload, setPayload] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true); setErr(null)
    fetch(`/api/v3/cio/plans/${encodeURIComponent(planId)}`, { cache: 'no-store' })
      .then(async r => {
        const j = await r.json()
        if (!r.ok || !j?.ok) throw new Error(j?.error || `HTTP ${r.status}`)
        setPayload(j)
      })
      .catch(e => setErr(String(e?.message || e)))
      .finally(() => setLoading(false))
  }, [planId])

  useEffect(() => { load() }, [load])

  const disposition = async (d: string) => {
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`/api/v3/cio/plans/${encodeURIComponent(planId)}/disposition`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ disposition: d }),
      })
      const j = await r.json()
      if (!r.ok || !j?.ok) throw new Error(j?.error || `HTTP ${r.status}`)
      setMsg(`${d} recorded (read-only advisory)`)
      setPayload((prev: any) => ({ ...prev, plan: j.plan }))
    } catch (e: any) {
      setMsg(`Failed: ${e?.message || e}`)
    } finally { setBusy(false) }
  }

  const plan: Plan = payload?.plan || {}
  const thesis = payload?.thesis
  const opts = Array.isArray(plan.options) ? plan.options : []
  const risks = Array.isArray(plan.risks) ? plan.risks : []
  const refs = Array.isArray(plan.evidence_refs) ? plan.evidence_refs : []
  const fire = Array.isArray(plan.fire_reasons_human) ? plan.fire_reasons_human : []
  const pin = plan.thesis_version || thesis?.thesis_version || '—'

  if (loading) return <div style={{ ...card, color: 'var(--text2)' }} data-testid="cio-plan-loading">Loading plan…</div>
  if (err) return <div style={{ ...card, borderColor: 'var(--red)', color: 'var(--red)' }} data-testid="cio-plan-error">Plan unavailable: {err}</div>

  return (
    <div style={{ ...card, borderColor: 'var(--accent)' }} data-testid="cio-plan-detail">
      <SectionTitle>{plan.situation_label || (plan.situation_type || 'Situation').replace(/_/g, ' ')}</SectionTitle>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        {plan.symbols?.length ? <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)' }}>{plan.symbols.join(', ')}</span> : null}
        <span style={{ fontSize: 12, color: 'var(--text2)' }}>thesis {pin}</span>
        {plan.owner_agent ? <span style={{ fontSize: 12, color: 'var(--text2)' }}>owner {plan.owner_agent}</span> : null}
        {plan.revisit_at ? <span style={{ fontSize: 12, color: 'var(--text2)' }}>revisit {String(plan.revisit_at).slice(0, 16)}</span> : null}
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>READ_ONLY_ADVISORY</span>
      </div>

      <div style={{ ...muted, marginBottom: 12 }}>{plan.summary_clean || plan.summary || '—'}</div>
      {plan.recommendation && <div style={{ fontSize: 13, color: 'var(--accent)', marginBottom: 12 }}>{plan.recommendation_clean || plan.recommendation}</div>}

      {opts.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {opts.map((o, i) => (
            <div key={i} style={{ padding: '8px 12px', marginBottom: 8, borderRadius: 6, background: 'var(--bg0)', border: '1px solid var(--border)' }}>
              <div style={{ color: 'var(--text0)', fontWeight: 700, fontSize: 13 }}>{i + 1}. {o.label || o.id || 'Option'}</div>
              {o.pros && <div style={{ color: 'var(--green)', marginTop: 4, fontSize: 12 }}>+ {o.pros}</div>}
              {o.cons && <div style={{ color: 'var(--red)', marginTop: 3, fontSize: 12 }}>− {o.cons}</div>}
            </div>
          ))}
        </div>
      )}

      {risks.length > 0 && (
        <ul style={{ margin: '0 0 12px', paddingLeft: 18, fontSize: 12, color: 'var(--text2)' }}>
          {risks.map((r, i) => <li key={i}>{String(r)}</li>)}
        </ul>
      )}
      {fire.length > 0 && <div style={{ fontSize: 12, color: 'var(--amber)', marginBottom: 12 }}>{fire.join(' · ')}</div>}

      {refs.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 12 }}>
          {refs.slice(0, 10).map((r: any, i: number) => (
            <div key={i}>• {r?.domain || '?'} · {String(r?.as_of || '').slice(0, 19)}</div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <button type="button" onClick={() => disposition('ack')} disabled={busy} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid var(--accent)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>Ack</button>
        <button type="button" onClick={() => disposition('defer')} disabled={busy} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg0)', color: 'var(--text1)', cursor: 'pointer', fontSize: 12 }}>Defer</button>
        <button type="button" onClick={() => disposition('done')} disabled={busy} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg0)', color: 'var(--text1)', cursor: 'pointer', fontSize: 12 }}>Done</button>
        <button type="button" onClick={() => disposition('reject')} disabled={busy} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid var(--red)', background: 'var(--bg0)', color: 'var(--red)', cursor: 'pointer', fontSize: 12 }}>Reject</button>
      </div>
      {msg && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 8 }}>{msg}</div>}
    </div>
  )
}
