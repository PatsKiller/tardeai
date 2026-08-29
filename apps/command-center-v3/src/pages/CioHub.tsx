import { useEffect, useState, useCallback, type CSSProperties, type ReactNode } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { SymbolThesisCard, type SymbolThesisCardPayload } from '../components/cio/SymbolThesisCard'
import CioBrainPanel from '../components/cio/CioBrainPanel'
import { NotificationGatePanel, SensesEvidencePanel, TelegramReceiptsPanel } from './MaturityPanels'
import { cioLabel, formatAsOfET } from '../lib/cioLabels'

/**
 * /v3/cio — the private investment office home (Phase 8).
 *
 * Decision-first, evidence-later. Six sections:
 *   CIO NOW · UNIVERSE & THESES · CAPITAL PLAN · PORTFOLIO POSTURE · OPPORTUNITIES · REPORT · EVIDENCE
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
  sizing_suppressed?: boolean
  sizing_suppression_reason?: string | null
  symbol_thesis_id?: string | null
  symbol_thesis_version?: string | null
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

type OperatorTrust = {
  aegis_last_run?: {
    available?: boolean
    generated_at?: string | null
    session_target?: string
    product_id?: string
    packet_chars?: number
    overflow?: boolean
    note?: string
  }
  holdings?: {
    available?: boolean
    ok?: boolean
    reason_code?: string
    reason?: string
    total?: number
  }
  notification?: {
    available?: boolean
    notification_class?: string | null
    suppression_reason?: string | null
    decision_id?: string
  }
}

type OfficeCoverage = {
  held?: number
  held_n?: number
  with_plan?: number
  with_thesis?: number
  thesis_count?: number
  with_research?: number
  with_case_summary?: number
  watch_ready?: number
  watch_block?: number
  reentry_near?: number
  class?: string
  note?: string
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
  operator_trust?: OperatorTrust
  coverage?: OfficeCoverage
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
  deploy_funding?: {
    recommended_deploy_usd?: number | null
    investable_cash_usd?: number | null
    prospective_raise_usd?: number | null
    deployable_usd?: number | null
    deploy_exceeds_investable_cash?: boolean
    gap_vs_investable_cash_usd?: number | null
    note?: string | null
  }
  deploy_request_notes?: string[]
}

type Posture = {
  thesis: { stance: string; summary: string | null; principles: string[] }
  concentration: { top_position: string | null; top_weight_pct: number | null; fire_pct: number | null }
  risk_heat: { max_drawdown_pct: number | null; sharpe: number | null; sortino: number | null }
  sector_tilts: {
    sector: string
    state: string
    exposure_pct: number | null
    target_pct: number | null
    target_source?: string | null
    target_label?: string | null
    target_is_placeholder?: boolean
    recommendation: string
  }[]
  sector_target_honesty?: {
    all_targets_placeholder?: boolean
    all_targets_identical?: boolean
    note?: string | null
  }
  performance: {
    portfolio_cagr: number | null
    benchmark_cagr: number | null
    alpha_annualized: number | null
    benchmark_label: string | null
    benchmark_source?: string | null
  }
  income: { total_usd: number | null }
  tax_issues: string[]
  constraints: string[]
}

type Opportunities = {
  watch: { symbol: string; source: string; signal: string; label: string }[]
  reentry: { symbol: string; source: string; signal: string; label: string }[]
  watch_total?: number
  reentry_total?: number
  queue_reentry_total?: number
  surface_a_reentry_count?: number
  surface_a_reentry_near?: number
  surface_a_reentry_reenter?: number
  reentry_pipes?: {
    queue?: string
    surface_a?: string
    merged?: boolean
    note?: string
  }
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

const TABS = ['cio-brain', 'cio-now', 'operator-policy', 'universe-theses', 'investment-books', 'capital-plan', 'posture', 'opportunities', 'report', 'evidence', 'notification-gate', 'telegram-receipts', 'senses-evidence'] as const
type Tab = typeof TABS[number]

const TAB_LABEL: Record<Tab, string> = {
  'cio-brain': 'CIO BRAIN',
  'cio-now': 'CIO NOW',
  'operator-policy': 'OPERATOR POLICY',
  'universe-theses': 'UNIVERSE & THESES',
  'investment-books': 'INVESTMENT BOOKS',
  'capital-plan': 'CAPITAL PLAN',
  posture: 'PORTFOLIO POSTURE',
  opportunities: 'OPPORTUNITIES',
  report: 'REPORT',
  evidence: 'EVIDENCE / AUDIT',
  'notification-gate': 'NOTIFICATION GATE',
  'telegram-receipts': 'TELEGRAM RECEIPTS',
  'senses-evidence': 'SENSES EVIDENCE',
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
  // Operator chrome: no dec_ / prod_ / plan_ / trace_ prefixes.
  const stripped = id.replace(/^(dec_|prod_|plan_|trace_)/, '')
  return stripped.length > 12 ? `${stripped.slice(0, 12)}…` : stripped
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

  const btn: CSSProperties = {
    padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)',
    background: 'var(--bg0)', color: 'var(--text1)', cursor: 'pointer',
    fontSize: 11, fontWeight: 600,
  }
  const active: CSSProperties = { ...btn, background: 'var(--accent-dim)', borderColor: 'var(--accent)', color: 'var(--accent)' }

  const canAct = Boolean(key)
  const act = (disp: string) => { if (canAct) onAct(d, disp) }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 10 }}>
      <button type="button" disabled={!canAct} style={cur === 'agree' ? active : btn} onClick={() => act('agree')} aria-label={`Agree ${d.symbol || d.action_id}`}>AGREE</button>
      <button type="button" disabled={!canAct} style={cur === 'disagree' ? { ...active, borderColor: 'var(--red)', color: 'var(--red)', background: 'var(--red-dim)' } : btn} onClick={() => act('disagree')} aria-label={`Disagree ${d.symbol || d.action_id}`}>DISAGREE</button>
      <button type="button" disabled={!canAct} style={cur === 'defer' ? active : btn} onClick={() => act('defer')} aria-label={`Defer ${d.symbol || d.action_id}`}>DEFER</button>
      <button type="button" disabled={!canAct} style={cur === 'need_data' ? active : btn} onClick={() => act('need_data')} aria-label={`Request data for ${d.symbol || d.action_id}`}>NEED DATA</button>
      <button type="button" disabled={!canAct} style={cur === 'no_longer_relevant' ? active : btn} onClick={() => act('no_longer_relevant')} aria-label={`No longer relevant ${d.symbol || d.action_id}`}>NO LONGER RELEVANT</button>
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

      {d.sizing_suppressed && (
        <div style={{ marginTop: 8, fontSize: 13, color: 'var(--amber)' }} data-testid="cio-sizing-suppressed">
          Sizing withheld until current financial truth clears {proseCode(d.sizing_suppression_reason || 'quality gate')}.
        </div>
      )}

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

function TrustStrip({ trust }: { trust?: OperatorTrust }) {
  const aegis = trust?.aegis_last_run
  const hold = trust?.holdings
  const ntf = trust?.notification
  const aegisLabel = !aegis?.available
    ? (aegis?.note || 'no packet yet')
    : `${aegis.session_target || 'isolated'}${aegis.generated_at ? ` · ${String(aegis.generated_at).slice(0, 16).replace('T', ' ')}` : ''}`
  const holdLabel = hold?.reason_code || 'DATA_UNAVAILABLE'
  const ntfClass = ntf?.notification_class || 'none on record'
  const ntfSuppress = ntf?.suppression_reason || (ntf?.available === false ? 'DATA_UNAVAILABLE' : 'none')
  return (
    <div data-testid="cio-trust-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
      <Stat label="Aegis last run" value={aegisLabel} help="Isolated evening packet. Overflow must stay false." />
      <Stat label="Holdings reason" value={holdLabel} help="Completeness / last-good guard. Incomplete $722k stays blocked." />
      <Stat label="Notification" value={ntfClass} help="Latest operator_trust.notification class. Live delivery is a separate gate." />
      <Stat label="Suppression" value={ntfSuppress} help="operator_trust.notification.suppression_reason when the lineage did not page." />
    </div>
  )
}

function CoverageCard({ coverage }: { coverage?: OfficeCoverage }) {
  const c = coverage || {}
  const heldN = c.held_n ?? c.held ?? 0
  const thesisCount = c.thesis_count ?? c.with_thesis ?? 0
  const n = (v: number | undefined) => (v == null ? 0 : v)
  return (
    <div
      data-testid="cio-coverage-card"
      style={{ ...card, marginBottom: 16 }}
    >
      <SectionTitle>Office coverage</SectionTitle>
      <div style={{ ...faint, marginBottom: 10 }}>
        Class D · from holdings thesis, plans, case summaries, watch block, Surface A reentry. No Telegram.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
        <Stat
          label="Thesis / held"
          value={`${thesisCount}/${heldN}`}
          help="thesis_count / held_n from holdings_thesis_coverage.current_n / held_n. SCHG dust may still count in held_n."
        />
        <Stat label="With plan" value={n(c.with_plan)} help="Held symbols on injected open plans." />
        <Stat label="With research" value={n(c.with_research)} help="Held symbols on open plans with hermes_result_id." />
        <Stat label="Case summaries" value={n(c.with_case_summary)} help="Active CASE_SUMMARY count (A-context)." />
        <Stat label="Watch READY" value={n(c.watch_ready)} help="Named READY/GO symbols. Live often 0 — honest." />
        <Stat label="Watch BLOCK" value={n(c.watch_block)} help="Honest BLOCK count; never remapped to READY." />
        <Stat label="Reentry NEAR" value={n(c.reentry_near)} help="Surface A NEAR count (former holdings book)." />
      </div>
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
      <TrustStrip trust={home.operator_trust} />
      <CoverageCard coverage={home.coverage} />
      {decisions.length === 0 ? (
        <Empty text="Nothing needs a decision right now. Portfolio is stable." />
      ) : (
        <>
          {decisions.map((d, i) => <DecisionCard key={(decisionKey(d) || legacyDispositionKey(d)) + i} d={d} dispositions={dispositions} legacyUnversioned={legacyUnversioned} onAct={onAct} />)}
          {investmentDecisions > decisions.length && (
            <div style={{ fontSize: 12, color: 'var(--text3)', margin: '4px 0 16px' }}>
              Showing {decisions.length} of {investmentDecisions} decisions — the rest rank below this attention threshold.
            </div>
          )}
        </>
      )}
    </div>
  )
}

function CapitalPlanSection({ cp }: { cp: CapitalPlan }) {
  const funding = cp.deploy_funding
  return (
    <div data-testid="capital-plan-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Total cash" value={fmtUsd(cp.cash_total_usd)} help="All cash across accounts (audit-corrected sum of cash rows)." />
        <Stat label="Reserved cash" value={fmtUsd(cp.cash_reserved_usd)} help="Cash held back to the policy floor / reserve." />
        <Stat label="Investable cash" value={fmtUsd(cp.cash_investable_usd)} help="Cash above the reserve available to deploy." />
        <Stat label="Target band" value={cp.cash_band.min_pct != null && cp.cash_band.max_pct != null ? `${cp.cash_band.min_pct}–${cp.cash_band.max_pct}%` : '—'} help="Policy cash floor-to-ceiling as a share of portfolio." />
        <Stat label="Recommended deploy" value={fmtUsd(cp.recommended_deploy_usd)} help="Net dollars the desk recommends putting to work (capped by investable cash + prospective raise)." />
        <Stat label="Recommended raise" value={fmtUsd(cp.recommended_raise_usd)} help="Prospective raise = future trims/exits not yet cash. Earmarked redeploy already in cash is not new capital." />
      </div>

      {funding?.deploy_exceeds_investable_cash && (
        <div data-testid="deploy-vs-investable-gap" style={{ ...card, marginBottom: 12, borderLeft: '3px solid var(--amber)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--amber)', marginBottom: 4 }}>Deploy exceeds investable cash</div>
          <div style={{ fontSize: 12, color: 'var(--text1)' }}>
            {funding.note || `Recommended deploy ${fmtUsd(funding.recommended_deploy_usd)} exceeds investable cash ${fmtUsd(funding.investable_cash_usd)} by ${fmtUsd(funding.gap_vs_investable_cash_usd)}.`}
          </div>
        </div>
      )}

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
          {(cp.deploy_request_notes || []).length > 0 && (
            <div style={{ marginTop: 8 }}>
              {(cp.deploy_request_notes || []).map((n, i) => (
                <div key={i} style={{ ...muted, marginBottom: 2 }}>• {n}</div>
              ))}
            </div>
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
            {performance.benchmark_source && (
              <div style={{ ...muted, marginTop: 4, maxWidth: 360 }} data-testid="benchmark-source">
                {performance.benchmark_source}
              </div>
            )}
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
          {posture.sector_target_honesty?.all_targets_placeholder && (
            <div style={{ ...muted, marginBottom: 8 }} data-testid="sector-target-placeholder-note">
              {posture.sector_target_honesty.note || 'Sector targets shown are placeholder / model defaults — not researched IPS targets.'}
            </div>
          )}
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
                  <td style={{ padding: '5px 6px', fontSize: 12, color: 'var(--text2)', textAlign: 'right' }}>
                    {fmtPct(s.target_pct)}
                    {s.target_is_placeholder && (
                      <div style={{ fontSize: 11, color: 'var(--text3)' }}>placeholder / model default</div>
                    )}
                    {!s.target_is_placeholder && s.target_label && (
                      <div style={{ fontSize: 11, color: 'var(--text3)' }}>{s.target_label}</div>
                    )}
                  </td>
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
              {constraints.map((c, i) => <div key={i} style={{ ...muted, marginBottom: 4 }}>• {cioLabel(c)}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

type UniverseThesesPayload = {
  ok?: boolean
  error?: string
  detail?: string
  metrics?: Record<string, unknown>
  symbols?: Array<{
    symbol?: string
    portfolio_role?: string
    thesis_state?: string
    thesis_version?: string | number
    memberships?: string[]
    bucket?: string
  }>
  note?: string
}

function AgentResearchOpsStrip() {
  const { data, loading, error } = useApi<any>('/api/v3/cio/agent-research-ops', 60_000)
  const q = data?.queue || {}
  const mix = data?.provider_mix_today || {}
  const flash = data?.flash_first || {}
  const failClasses = data?.failure_classes_today || {}
  const capTone = data?.global_cap_status === 'CONFIGURED' ? undefined : 'var(--amber)'
  return (
    <div data-testid="cio-agent-research-ops" style={{ display: 'grid', gap: 10, marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: 'var(--text3)' }}>
        Intelligence engine ops. Advisory only. Automatic queued work is DeepSeek Flash first.
        Failed jobs are not silently re-queued.
      </div>
      {loading && <div style={muted}>Loading research ops…</div>}
      {error && <div style={{ color: 'var(--amber)', fontSize: 13 }}>Research ops unavailable: {String(error)}</div>}
      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
          <Stat label="Queued" value={String(q.queued ?? '—')} />
          <Stat label="Created today" value={String(q.created_today ?? '—')} />
          <Stat label="Completed today" value={String(q.completed_today ?? '—')} />
          <Stat label="Failed today" value={String(q.failed_today ?? '—')} />
          <Stat label="Oldest queued" value={q.oldest_queued ? String(q.oldest_queued).slice(0, 16) : '—'} />
          <Stat label="Global cap" value={String(data.global_cap_status ?? '—')} />
          <Stat label="Maria queued" value={String((q.by_agent && q.by_agent.maria) ?? '—')} />
          <Stat label="Stale/superseded" value={String(q.stale_or_superseded ?? '—')} />
        </div>
      )}
      {data?.dominant_failure_class && (
        <div style={{ fontSize: 12, color: 'var(--amber)' }} data-testid="cio-research-failure-class">
          Dominant failure: {String(data.dominant_failure_class)}
          {Object.keys(failClasses).length > 0
            ? ` · ${Object.entries(failClasses).map(([k, v]) => `${k}=${v}`).join(' · ')}`
            : ''}
        </div>
      )}
      {data?.operator_finding && (
        <div style={{ fontSize: 12, color: 'var(--text2)' }}>{String(data.operator_finding)}</div>
      )}
      {mix && Object.keys(mix).length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--text2)' }}>
          Provider mix today:{' '}
          {Object.entries(mix).map(([k, v]) => `${k}=${v}`).join(' · ')}
        </div>
      )}
      {(flash.provider_attempted_today || flash.provider_actual_today) && (
        <div style={{ fontSize: 12, color: 'var(--text2)' }} data-testid="cio-research-flash-first">
          Flash-first attempted:{' '}
          {Object.entries(flash.provider_attempted_today || {}).map(([k, v]) => `${k}=${v}`).join(' · ') || '—'}
          {' · '}actual:{' '}
          {Object.entries(flash.provider_actual_today || {}).map(([k, v]) => `${k}=${v}`).join(' · ') || '—'}
          {flash.fallback_reason_today && Object.keys(flash.fallback_reason_today).length > 0
            ? ` · fallback: ${Object.entries(flash.fallback_reason_today).map(([k, v]) => `${k}=${v}`).join(' · ')}`
            : ''}
        </div>
      )}
      {capTone && data?.global_cap_status === 'MISSING' && (
        <div style={{ fontSize: 12, color: capTone }}>
          Cap env missing in this process — Flash path fail-closes until LLM_GLOBAL_DAILY_USD_CAP is set on the agent-jobs worker.
        </div>
      )}
    </div>
  )
}

/** Fail-soft map of GET /api/v3/cio/intelligence/{SYM} → card extras. */
function extrasFromIntelligence(body: any): Partial<SymbolThesisCardPayload> {
  if (!body || typeof body !== 'object') return {}
  const intel = (body.intelligence && typeof body.intelligence === 'object') ? body.intelligence : body
  const latest = body.latest_feedback || intel.latest_feedback || null
  const journal = Array.isArray(body.journal) ? body.journal : []
  const journalLatest = journal.length ? journal[journal.length - 1] : null
  const stance = body.operator_stance || body.stance
    || latest?.stance || journalLatest?.stance
    || intel.operator_stance || intel.stance
  const prov = body.provenance || intel.provenance
  const tech = body.technical_summary ?? intel.technical_summary ?? intel.technical
  const cau = body.causality ?? intel.causality
  const what = body.what_changed_detail
    ?? intel.what_changed_detail
    ?? (Array.isArray(intel.why_now) ? intel.why_now.filter(Boolean).join(' · ') : undefined)

  let technical_summary: string | undefined
  if (typeof tech === 'string') {
    technical_summary = tech
  } else if (tech && typeof tech === 'object') {
    const parts = [
      tech.price != null ? `Price ${tech.price}` : '',
      (tech.support_or_zone_low != null || tech.resistance_or_zone_high != null)
        ? `Zone ${tech.support_or_zone_low ?? '—'} → ${tech.resistance_or_zone_high ?? '—'}`
        : '',
      tech.stop_invalidation != null ? `Stop ${tech.stop_invalidation}` : '',
      tech.target != null ? `Target ${tech.target}` : '',
      tech.status ? `Status ${tech.status}` : '',
    ].filter(Boolean)
    technical_summary = parts.length ? parts.join(' · ') : undefined
  }

  let causality: string | undefined
  if (typeof cau === 'string') causality = cau
  else if (cau && typeof cau === 'object') {
    causality = String(cau.narrative || cau.effect || '') || undefined
  }

  const hist = Array.isArray(body.thesis_history)
    ? body.thesis_history
    : (Array.isArray(intel.thesis_history) ? intel.thesis_history : undefined)

  const out: Partial<SymbolThesisCardPayload> = {}
  if (stance != null && String(stance)) out.operator_stance = String(stance)
  if (latest && typeof latest === 'object' && latest.intent) {
    out.latest_feedback = {
      intent: String(latest.intent),
      ts: latest.ts != null ? String(latest.ts) : undefined,
      free_text: latest.free_text != null ? String(latest.free_text) : undefined,
    }
  }
  if (prov && typeof prov === 'object' && prov.decision_origin != null) {
    out.provenance = { decision_origin: String(prov.decision_origin) }
  }
  if (what != null && String(what)) out.what_changed_detail = String(what)
  if (technical_summary) out.technical_summary = technical_summary
  if (causality) out.causality = causality
  if (hist) out.thesis_history = hist

  // Phase D — research queue summary (fail-soft; prefer API summary fields).
  const rq = (body.research_queue && typeof body.research_queue === 'object')
    ? body.research_queue
    : ((intel.research_queue && typeof intel.research_queue === 'object') ? intel.research_queue : null)
  if (rq && rq.open_count != null && Number.isFinite(Number(rq.open_count))) {
    out.research_queue_open_count = Math.max(0, Math.floor(Number(rq.open_count)))
    if (rq.oldest_wait_human != null && String(rq.oldest_wait_human).trim()) {
      out.research_queue_oldest_wait_human = String(rq.oldest_wait_human).trim()
    }
  } else if (body.research_queue_open_count != null && Number.isFinite(Number(body.research_queue_open_count))) {
    out.research_queue_open_count = Math.max(0, Math.floor(Number(body.research_queue_open_count)))
    if (body.research_queue_oldest_wait_human != null) {
      out.research_queue_oldest_wait_human = String(body.research_queue_oldest_wait_human)
    }
  }

  return out
}

function UniverseThesesPanel() {
  const { data, loading, error } = useApi<UniverseThesesPayload>('/api/v3/cio/universe-theses', 60_000)
  const [sym, setSym] = useState('')
  const [intelExtras, setIntelExtras] = useState<Partial<SymbolThesisCardPayload>>({})
  const cardPath = sym ? `/api/v3/cio/symbol-thesis/${encodeURIComponent(sym)}` : ''
  const { data: card, loading: cardLoading, error: cardError } = useApi<any>(
    cardPath || '/api/v3/cio/symbol-thesis/_idle',
    0,
    { enabled: Boolean(sym) },
  )

  // Shared intelligence / journal — fail-soft on 404 or network errors (Phase B API).
  useEffect(() => {
    setIntelExtras({})
    if (!sym) return
    let cancelled = false
    fetch(`/api/v3/cio/intelligence/${encodeURIComponent(sym)}`, { cache: 'no-store' })
      .then(r => {
        if (!r.ok) return null
        return r.json()
      })
      .then(j => {
        if (cancelled || !j) return
        const body = j.ok !== undefined ? (j.data ?? j) : j
        if (j.ok === false && !body?.latest_feedback && !body?.intelligence) return
        setIntelExtras(extrasFromIntelligence(body))
      })
      .catch(() => {
        if (!cancelled) setIntelExtras({})
      })
    return () => { cancelled = true }
  }, [sym])

  const mergedCard: SymbolThesisCardPayload | null = (() => {
    if (!card) return null
    const base = card as SymbolThesisCardPayload
    const hist = (Array.isArray(base.thesis_history) && base.thesis_history.length)
      ? base.thesis_history
      : intelExtras.thesis_history
    return {
      ...base,
      ...intelExtras,
      // Prefer living-thesis history when present; fill from intelligence otherwise.
      thesis_history: hist,
      // Keep symbol-thesis what_changed unless intel provides richer detail only.
      what_changed: base.what_changed,
    }
  })()

  const missingApi = Boolean(error && String(error).includes('HTTP 404'))
  const payloadError = data && data.ok === false
  const rows = Array.isArray(data?.symbols) ? data!.symbols! : []
  const metricDefs = (data?.metrics?.percentage_definitions || {}) as Record<string, any>
  const heldSub = metricDefs.held_substantive || {}
  const materialCov = metricDefs.material_coverage || {}
  const materialSub = metricDefs.material_substantive || {}
  return (
    <div data-testid="cio-universe-theses" style={{ display: 'grid', gap: 14 }}>
      <div style={{ fontSize: 12, color: 'var(--text3)' }}>
        Living theses for the material universe. Advisory only. Merged on protected main (PR 397).
      </div>
      {loading && <div style={muted}>Loading universe &amp; theses…</div>}
      {(error || payloadError) && (
        <div data-testid="cio-universe-theses-error" style={{ color: 'var(--amber)', fontSize: 13 }}>
          {missingApi
            ? 'Universe theses API is not on this host yet (empty until /api/v3/cio/universe-theses exists).'
            : `Universe theses unavailable: ${payloadError ? (data?.error || data?.detail || 'ok=false') : String(error)}`}
        </div>
      )}
      {data?.metrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          <Stat label="Held CURRENT / THIN" value={`${data.metrics.held_current ?? '—'} / ${data.metrics.held_thin ?? '—'} of ${data.metrics.held ?? '—'}`} help="Living theses on current holdings. CURRENT is PASS-grade. THIN cleared the 40-char floor but failed substantiveness." />
          <Stat label="Held substantive" value={heldSub.denominator != null ? `${heldSub.pct}% (${heldSub.numerator}/${heldSub.denominator})` : '—'} help="CURRENT over held equity tickers; cash and unresolved identifiers excluded." />
          <Stat label="Material coverage" value={materialCov.denominator != null ? `${materialCov.pct}% (${materialCov.numerator}/${materialCov.denominator})` : '—'} help="CURRENT + THIN over the declared material-union denominator." />
          <Stat label="Material substantive" value={materialSub.denominator != null ? `${materialSub.pct}% (${materialSub.numerator}/${materialSub.denominator})` : '—'} help="CURRENT only over the declared material-union denominator." />
          <Stat label="Research required" value={String(data.metrics.research_required ?? '—')} />
          {data.metrics.bonds_unresolved != null && (
            <Stat label="Bonds & unresolved" value={String(data.metrics.bonds_unresolved)} help="CUSIP/unresolved identifiers sorted out of the main list." />
          )}
        </div>
      )}
      {Boolean((data as any)?.daily_thesis_changes?.counts) && (
        <div data-testid="cio-daily-thesis-changes" style={{ ...card, marginTop: 8 }}>
          <SectionTitle>Thesis changes (24h)</SectionTitle>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            {Object.entries(((data as any).daily_thesis_changes.counts || {}) as Record<string, number>)
              .filter(([, n]) => Number(n) > 0)
              .map(([k, n]) => `${k.replace(/_/g, ' ')} ${n}`)
              .join(' · ') || 'none'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>
            Cards live in data/cio/thesis_change_cards.jsonl. This strip is the operator-visible 24h counts — not a second store.
          </div>
        </div>
      )}
      {!loading && !error && !payloadError && rows.length === 0 && (
        <Empty text="No material universe theses to show." />
      )}
      {rows.length > 0 && (
        <div style={card}>
          <SectionTitle>Symbols</SectionTitle>
          {rows.slice(0, 80).map((r, i) => {
            const isUnresolved = r.bucket === 'BONDS_UNRESOLVED'
            return (
            <button
              key={(r.symbol || 'x') + i}
              type="button"
              onClick={() => setSym(String(r.symbol || ''))}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '8px 4px', border: 'none', borderBottom: '1px solid var(--border)',
                background: r.symbol === sym ? 'var(--accent-dim)' : 'transparent',
                color: isUnresolved ? 'var(--text3)' : 'var(--text1)', cursor: 'pointer', fontSize: 13,
              }}
            >
              <strong>{r.symbol}</strong>
              {r.bucket ? (
                <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 700, letterSpacing: '.4px', color: isUnresolved ? 'var(--amber)' : 'var(--text3)' }}>
                  {r.bucket.replace(/_/g, ' ')}
                </span>
              ) : null}
              {' · '}
              {r.portfolio_role || 'UNKNOWN'}
              {' · '}
              <span style={{
                color: r.thesis_state === 'THIN' ? 'var(--amber)'
                  : r.thesis_state === 'CURRENT' ? 'var(--green)'
                  : r.thesis_state === 'RESEARCH_REQUIRED' ? 'var(--amber)'
                  : 'inherit',
                fontWeight: r.thesis_state === 'THIN' || r.thesis_state === 'CURRENT' ? 700 : 500,
              }}>
                {r.thesis_state || 'RESEARCH_REQUIRED'}
              </span>
              {r.thesis_version != null ? ` · ${String(r.thesis_version)}` : ''}
            </button>
            )
          })}
        </div>
      )}
      {cardLoading && sym && <div style={muted}>Loading {sym} thesis…</div>}
      {cardError && sym && (
        <div style={{ color: 'var(--amber)', fontSize: 13 }}>
          Symbol thesis unavailable for {sym}: {String(cardError)}
        </div>
      )}
      {sym && !cardError && <SymbolThesisCard card={mergedCard} />}
    </div>
  )
}

function InvestmentBooksPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/cio/investment-product', 30_000)
  const [reentryLimit, setReentryLimit] = useState(30)
  const p = data?.product || {}
  const temp = p.temperament || {}
  const re = p.reentry_book || {}
  const opp = p.opportunity_book || {}
  const act = p.action_book || {}
  const reentryNames: any[] = re.names || []
  return <div data-testid="cio-investment-books" style={{ display: 'grid', gap: 14 }}>
    <div style={{ fontSize: 12, color: 'var(--text3)' }}>
      Advisory books only. Desk READY/IN_ZONE is not RE_ENTER. MEMORY_BEHAVIOR_INFLUENCE={temp?.influence?.memory_behavior_influence || '0'}.
    </div>
    {loading && <div>Loading books…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    {p.what_changed && (
      <section data-testid="cio-what-changed" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
        <div style={{ fontWeight: 800 }}>What changed</div>
        <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>
          trigger {p.trigger || '—'}
          {p.what_changed.material ? ' · MATERIAL' : ' · no material investment change'}
        </div>
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--text3)' }}>Product IDs</summary>
          <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'monospace', marginTop: 2 }}>
            prior {p.previous_product_id || '—'} · now {p.product_id || p.decision_id || '—'}
          </div>
        </details>
        {(p.what_changed.items || []).slice(0, 16).map((it: any, i: number) => (
          <div key={i} style={{ fontSize: 13, marginTop: 4 }}>
            {it.kind}{it.symbol ? ` · ${it.symbol}` : ''}{it.from ? ` ${it.from}` : ''}{it.to ? ` → ${it.to}` : ''}
          </div>
        ))}
        {(p.what_changed.items || []).length === 0 && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 6 }}>—</div>}
      </section>
    )}
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
      <div style={{ fontWeight: 800 }}>Market Temperament</div>
      <div style={{ marginTop: 6, fontWeight: 700 }}>{temp.title || '—'}</div>
      <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 6 }}>{temp.narrative}</div>
      <div style={{ fontSize: 13, marginTop: 8 }}>{temp.portfolio_implication}</div>
      {(temp.cash != null || temp.cash_pct != null) && (
        <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 8 }} data-testid="cio-temperament-cash">
          Cash {temp.cash_pct != null ? `${temp.cash_pct}%` : ''}{temp.cash != null ? ` · ${temp.cash}` : ''} · class D
        </div>
      )}
    </section>
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }} data-testid="cio-earnings">
      <div style={{ fontWeight: 800 }}>Earnings (class D)</div>
      <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>
        Next dated events, held first. {(p.earnings_quality && p.earnings_quality.quality) || ''}
        {p.earnings_quality && p.earnings_quality.reason ? ` — ${p.earnings_quality.reason}` : ''}
      </div>
      {((p.earnings || []) as any[]).slice(0, 12).map((e: any, i: number) => (
        <div key={(e.symbol || 'e') + i} style={{ fontSize: 13, marginTop: 4 }}>
          {e.symbol} · {e.earnings_date || '—'} · {e.scope || ''}
        </div>
      ))}
      {((p.earnings || []) as any[]).length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 6 }}>
          {p.earnings_quality && p.earnings_quality.quality === 'DATA_UNAVAILABLE'
            ? `DATA_UNAVAILABLE — ${p.earnings_quality.reason || 'earnings source missing'}`
            : '—'}
        </div>
      )}
    </section>
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }} data-testid="cio-reentry-surface-a">
      <div style={{ fontWeight: 800 }}>Re-Entry Book A</div>
      <div style={{ fontSize: 12, color: 'var(--amber)', marginTop: 4 }}>
        Surface A · {re.scope || 'former holdings vs exit trigger'}
        {re.not_this_book ? ` (not ${re.not_this_book})` : ' (not candidates vs cash-stage R:R under desk thesis)'}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>{re.question || re.precedence || re.note}</div>
      <table style={{ width: '100%', fontSize: 12, marginTop: 8, borderCollapse: 'collapse' }}>
        <thead><tr>{['symbol','status','verdict','setup','what would change'].map(h => <th key={h} style={{ textAlign: 'left', padding: '4px 6px', color: 'var(--text3)' }}>{h}</th>)}</tr></thead>
        <tbody>{reentryNames.slice(0, reentryLimit).map((r: any) => <tr key={r.symbol}>
          <td style={{ padding: '4px 6px' }}>{r.symbol}</td>
          <td style={{ padding: '4px 6px' }}>{r.status}</td>
          <td style={{ padding: '4px 6px' }}>{r.governed_verdict || '—'}</td>
          <td style={{ padding: '4px 6px' }}>{r.setup}</td>
          <td style={{ padding: '4px 6px' }}>{r.what_would_change}</td>
        </tr>)}</tbody>
      </table>
      {reentryNames.length === 0 && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 8 }}>No former holdings in the re-entry universe right now.</div>}
      {reentryNames.length > reentryLimit && (
        <button
          type="button"
          onClick={() => setReentryLimit(reentryNames.length)}
          style={{ marginTop: 8, padding: '6px 12px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg0)', color: 'var(--accent)', cursor: 'pointer' }}
        >
          Show all {reentryNames.length} names
        </button>
      )}
    </section>
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
      <div style={{ fontWeight: 800 }}>Opportunity Book</div>
      <div style={{ fontSize: 12, color: 'var(--text3)' }}>{opp.note}</div>
      {(opp.top || []).slice(0, 12).map((o: any) => (
        <div key={o.symbol + String(o.rank)} style={{ fontSize: 13, marginTop: 6 }}>
          {o.rank}. {o.symbol} — {o.verdict || o.state || 'WATCH'} ({o.source}) · vs former {o.vs_former_holdings}
        </div>
      ))}
    </section>
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
      <div style={{ fontWeight: 800 }}>Portfolio Action Book</div>
      {(['DO_NOW','WATCH_CLOSELY','RE_ENTER_IF','NEW_POSITION_IF','HOLD_CASH_FOR','AVOID','CURRENT_HOLDINGS_THESIS','RESEARCH_NEXT'] as const).map(k => (
        <div key={k} style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text3)' }}>{cioLabel(k)}</div>
          {((act as any)[k] || []).slice(0, 8).map((r: any, i: number) => (
            <div key={k + i} style={{ fontSize: 13 }}>{r.symbol} — {r.action}: {r.why ?? r.why_still_held ?? r.thesis_state ?? '—'}</div>
          ))}
          {((act as any)[k] || []).length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--text3)' }}>
              {k === 'NEW_POSITION_IF' && act.NEW_POSITION_IF_REASON ? act.NEW_POSITION_IF_REASON : '—'}
            </div>
          )}
        </div>
      ))}
    </section>
    {(() => {
      const cases = p.case_summaries || p.research_cases || {}
      const items: any[] = cases.items || []
      return (
        <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }} data-testid="cio-case-summaries">
          <div style={{ fontWeight: 800 }}>Research cases</div>
          <div style={{ fontSize: 12, color: 'var(--amber)', marginTop: 4 }}>
            {cases.banner || 'A-context · NON_AUTHORITATIVE · does not change action'}
          </div>
          {items.slice(0, 12).map((c: any) => (
            <div key={c.memory_id || c.subject} style={{ fontSize: 13, marginTop: 8 }}>
              <div>{c.subject || 'research_case'}{(c.symbols || []).length ? ` · ${(c.symbols || []).join(', ')}` : ''}</div>
              <div style={{ fontSize: 12, color: 'var(--text3)' }}>{(c.content || '').slice(0, 220)}</div>
            </div>
          ))}
          {items.length === 0 && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 6 }}>No ACTIVE CASE_SUMMARY memories on this surface.</div>}
        </section>
      )
    })()}
    <div style={{ fontSize: 12, color: 'var(--text3)' }}>{p.summary}</div>
  </div>
}

function OpportunitiesSection({ opp }: { opp: Opportunities }) {
  const list = (items: { symbol: string; signal: string; source: string }[]) =>
    items.length === 0 ? <Empty text="None." /> : (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {items.map((it, i) => (
          <span
            key={i}
            data-testid="cio-opp-chip"
            title={`${it.signal} · source: ${it.source}`}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 6, background: 'var(--bg0)', border: '1px solid var(--border)', fontSize: 12,
            }}
          >
            <strong data-testid="cio-opp-symbol" style={{ color: 'var(--text0)' }}>{it.symbol}</strong>
            <span data-testid="cio-opp-verdict" style={{ color: 'var(--text2)' }}>{it.signal || 'Watch'}</span>
          </span>
        ))}
      </div>
    )

  return (
    <div data-testid="opportunities-section">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={card}>
          <SectionTitle>Watch candidates</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>
            Sourced from the advisory, defense, and CIO desks.
            {opp.watch_total != null && opp.watch_total > opp.watch.length ? ` · showing ${opp.watch.length} of ${opp.watch_total}` : ''}
          </div>
          {list(opp.watch)}
        </div>
        <div style={card} data-testid="cio-home-reentry-surface-a">
          <SectionTitle>Re-entry A</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>
            Surface A · former holdings vs exit trigger (not candidates vs cash-stage R:R under desk thesis).
            {opp.surface_a_reentry_count != null && opp.surface_a_reentry_count > 0
              ? ` · book ${opp.surface_a_reentry_count} (NEAR ${opp.surface_a_reentry_near ?? 0} · REENTER ${opp.surface_a_reentry_reenter ?? 0})`
              : ''}
            {opp.reentry.length > 0 && opp.reentry_total != null && opp.reentry_total > opp.reentry.length
              ? ` · queue chips ${opp.reentry.length} of ${opp.queue_reentry_total ?? opp.reentry_total}`
              : ''}
            {opp.reentry_pipes && opp.reentry_pipes.merged === false
              ? ' · dual pipes not merged'
              : ''}
          </div>
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

      <YoutubeResearchQueuePanel />
    </div>
  )
}

function YoutubeResearchQueuePanel() {
  const [items, setItems] = useState<any[]>([])
  const [meta, setMeta] = useState<{ count?: number; built_at?: string; min_quality?: number; error?: string }>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(`/api/v2/cio/youtube-research-queue?_=${Date.now()}`, { cache: 'no-store' })
      .then(async r => {
        const j = await r.json().catch(() => ({}))
        if (cancelled) return
        setItems(Array.isArray(j?.items) ? j.items : [])
        setMeta({
          count: j?.count ?? 0,
          built_at: j?.built_at,
          min_quality: j?.min_quality ?? 70,
          error: j?.error,
        })
      })
      .catch(e => {
        if (!cancelled) setMeta({ count: 0, error: String(e?.message || e) })
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const count = meta.count ?? items.length
  return (
    <div style={{ ...card, marginTop: 16 }} data-testid="cio-youtube-research-queue">
      <SectionTitle>YouTube research queue</SectionTitle>
      <div style={{ ...faint, marginBottom: 8 }}>
        Material-only · promoted transcripts across stocks, ETFs, bonds, and options income · quality ≥ {meta.min_quality ?? 70}
        {meta.built_at ? ` · built ${new Date(meta.built_at).toLocaleString()}` : ''}
        {count ? ` · ${count} items` : ''}
      </div>
      {loading ? <Empty text="Loading…" /> : meta.error ? (
        <div style={{ fontSize: 12, color: 'var(--red)' }}>{meta.error}</div>
      ) : items.length === 0 ? (
        <Empty text="No material YouTube items yet (Q≥70 promoted)." />
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {items.slice(0, 12).map((it: any, i: number) => (
            <div key={it.video_id ?? it.source_id ?? i} style={{
              padding: '8px 10px', borderRadius: 6, background: 'var(--bg2)',
              border: '1px solid var(--border)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <strong style={{ fontSize: 12, color: 'var(--text0)' }}>{it.title ?? 'Untitled'}</strong>
                <span style={{ fontSize: 10, color: 'var(--text3)', whiteSpace: 'nowrap' }}>
                  Q{it.quality_score ?? '—'}
                  {it.asset_class ? ` · ${String(it.asset_class).replace(/_/g, ' ')}` : ''}
                </span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>
                {(it.tickers ?? []).slice(0, 6).join(', ') || '—'}
                {(it.strategy_tags?.length) ? ` · ${(it.strategy_tags ?? []).slice(0, 3).map((t: string) => String(t).replace(/_/g, ' ')).join(', ')}` : ''}
              </div>
              {it.summary && (
                <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4 }}>
                  {String(it.summary).slice(0, 180)}{String(it.summary).length > 180 ? '…' : ''}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
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
          {report.as_of ? `As of ${formatAsOfET(report.as_of)}` : 'No report generated yet.'}
        </div>
        {report.source_sha && (
          <details style={{ ...faint, marginBottom: 8 }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text3)' }}>Provenance</summary>
            <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 11 }}>
              source {String(report.source_sha).slice(0, 12)}
              {report.manifest_hash ? ` · manifest ${String(report.manifest_hash).slice(0, 12)}` : ''}
            </div>
          </details>
        )}
        {report.render_errors.length > 0 && (
          <div style={{ ...faint, color: 'var(--amber)', marginBottom: 8 }}>
            PDF not rendered in this environment: {report.render_errors.join('; ')}
          </div>
        )}
        {report.fields_unavailable.length > 0 && (
          <div style={{ ...faint, marginBottom: 8 }}>
            Unavailable: {report.fields_unavailable.map(f => cioLabel(f)).join(' · ')}
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
            Full report{generatedAt ? ` · generated ${formatAsOfET(generatedAt)}` : ''}
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
        <Stat label="As of" value={evidence.as_of ? formatAsOfET(evidence.as_of) : '—'} help="When the data snapshot was taken (Eastern Time)." />
        <Stat label="Source refs" value={evidence.source_refs.length} help="Named source artifacts with integrity hashes (see below)." />
      </div>

      {(evidence.source_sha || evidence.run_ids.length > 0) && (
        <details style={{ ...card, fontSize: 12, color: 'var(--text3)' }} data-testid="evidence-provenance">
          <summary style={{ cursor: 'pointer', color: 'var(--text2)' }}>Provenance (hashes / run IDs)</summary>
          <div style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 11 }}>
            {evidence.source_sha ? <div>source SHA {String(evidence.source_sha)}</div> : null}
            {evidence.run_ids.slice(0, 8).map((r, i) => (
              <div key={i}>{r.id} · {r.state}</div>
            ))}
          </div>
        </details>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={card}>
          <SectionTitle>Source references</SectionTitle>
          {evidence.source_refs.length === 0 ? <Empty text="None." /> : (
            <details open={false}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--text2)', marginBottom: 6 }}>
                {evidence.source_refs.length} source{evidence.source_refs.length === 1 ? '' : 's'} (hashes collapsed)
              </summary>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <tbody>
                  {evidence.source_refs.map((s, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '5px 4px', fontSize: 12, color: 'var(--text1)' }}>{cioLabel(s.name)}</td>
                      <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text3)', textAlign: 'right', fontFamily: 'monospace' }} title={String(s.sha256)}>{String(s.sha256).slice(0, 12)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
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
                    <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text3)', textAlign: 'right' }}>{v.ts ? formatAsOfET(v.ts, { utcSuffix: false }) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={card}>
          <SectionTitle>Run / handoff IDs</SectionTitle>
          {evidence.run_ids.length === 0 ? <Empty text="None." /> : (
            <details>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--text2)', marginBottom: 6 }}>
                {evidence.run_ids.length} run ID{evidence.run_ids.length === 1 ? '' : 's'} (collapsed)
              </summary>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <tbody>
                  {evidence.run_ids.map((r, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text1)', fontFamily: 'monospace' }} title={String(r.id)}>{String(r.id || '').slice(0, 24)}{String(r.id || '').length > 24 ? '…' : ''}</td>
                      <td style={{ padding: '5px 4px', fontSize: 11, color: 'var(--text3)', textAlign: 'right' }}>{r.state}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>

        <div style={card}>
          <SectionTitle>Internal codes</SectionTitle>
          <div style={{ ...faint, marginBottom: 8 }}>Fields the report explicitly marks unavailable (never estimated).</div>
          {evidence.internal_codes.length === 0 ? <Empty text="None." /> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {evidence.internal_codes.map((c, i) => (
                <span key={i} title={c} style={{ padding: '3px 8px', borderRadius: 4, background: 'var(--bg0)', border: '1px solid var(--border)', fontSize: 11, color: 'var(--text2)' }}>{cioLabel(c)}</span>
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

type PolicyField = {
  value: unknown
  status: string
  kind: 'range_pct' | 'money' | 'text' | 'list' | 'object'
  operator_confirmed: boolean
  version: number
}

type OperatorPolicyPayload = {
  schema: string
  status: string
  confirmed_field_count: number
  required_field_count: number
  missing_fields: string[]
  fields: Record<string, PolicyField>
  legacy_conflicts: { field: string; claims: { value: unknown; source: string }[] }[]
}

function policyLabel(value: string): string {
  return value.replace(/_pct$/, ' (%)').replace(/_usd$/, ' ($)').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function OperatorPolicyPanel() {
  const [policy, setPolicy] = useState<OperatorPolicyPayload | null>(null)
  const [fieldName, setFieldName] = useState('')
  const [textValue, setTextValue] = useState('')
  const [rangeMin, setRangeMin] = useState('')
  const [rangeMax, setRangeMax] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(() => {
    fetch('/api/v3/cio/brain/policy', { cache: 'no-store' })
      .then(r => r.json())
      .then(j => {
        if (j?.ok && j.policy) {
          setPolicy(j.policy)
          setFieldName((current) => current || j.policy.missing_fields?.[0] || Object.keys(j.policy.fields || {})[0] || '')
        }
      })
      .catch(() => setMessage('Policy state unavailable'))
  }, [])

  useEffect(() => { load() }, [load])

  const selected = fieldName ? policy?.fields?.[fieldName] : undefined
  const submit = async () => {
    if (!selected || !fieldName) return
    let value: unknown = textValue
    try {
      if (selected.kind === 'range_pct') value = { min: Number(rangeMin), max: Number(rangeMax) }
      if (selected.kind === 'money') value = Number(textValue)
      if (selected.kind === 'list') value = textValue.split(',').map(v => v.trim()).filter(Boolean)
      if (selected.kind === 'object') value = JSON.parse(textValue)
      setBusy(true); setMessage(null)
      const response = await fetch('/api/v3/cio/brain/policy/ratify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field_name: fieldName, value, operator_identity_class: 'OPERATOR' }),
      })
      const result = await response.json()
      if (!response.ok || !result?.ok) throw new Error(result?.detail || result?.error || `HTTP ${response.status}`)
      setPolicy(result.policy)
      setFieldName(result.policy.missing_fields?.[0] || fieldName)
      setTextValue(''); setRangeMin(''); setRangeMax('')
      setMessage(`${policyLabel(fieldName)} confirmed`)
    } catch (error: any) {
      setMessage(String(error?.message || error))
    } finally {
      setBusy(false)
    }
  }

  if (!policy) return <div style={{ ...card, color: 'var(--text2)' }}>Loading operator policy…</div>
  const confirmed = policy.confirmed_field_count || 0
  const required = policy.required_field_count || 0

  return (
    <div data-testid="cio-operator-policy">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10, marginBottom: 16 }}>
        <div style={card}>
          <div style={{ ...muted, textTransform: 'uppercase' }}>Policy state</div>
          <div style={{ fontSize: 18, fontWeight: 750, color: policy.status === 'CONFIRMED' ? 'var(--green)' : 'var(--amber)', marginTop: 4 }}>{policy.status}</div>
        </div>
        <div style={card}>
          <div style={{ ...muted, textTransform: 'uppercase' }}>Confirmed</div>
          <div style={{ fontSize: 18, fontWeight: 750, color: 'var(--text0)', marginTop: 4 }}>{confirmed} / {required}</div>
        </div>
        <div style={card}>
          <div style={{ ...muted, textTransform: 'uppercase' }}>Legacy conflicts</div>
          <div style={{ fontSize: 18, fontWeight: 750, color: policy.legacy_conflicts.length ? 'var(--amber)' : 'var(--green)', marginTop: 4 }}>{policy.legacy_conflicts.length}</div>
        </div>
      </div>

      {policy.legacy_conflicts.length > 0 && (
        <section style={{ marginBottom: 18 }}>
          <SectionTitle>Policy conflicts</SectionTitle>
          {policy.legacy_conflicts.map(conflict => (
            <div key={conflict.field} style={{ borderBottom: '1px solid var(--border)', padding: '9px 0', fontSize: 12 }}>
              <strong style={{ color: 'var(--text0)' }}>{policyLabel(conflict.field)}</strong>
              <span style={{ color: 'var(--text2)', marginLeft: 10 }}>{conflict.claims.map(c => JSON.stringify(c.value)).join(' · ')}</span>
            </div>
          ))}
        </section>
      )}

      <section style={{ marginBottom: 18 }}>
        <SectionTitle>Ratification</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(260px, 2fr) auto', gap: 8, alignItems: 'end' }}>
          <label style={{ ...muted }}>
            Policy field
            <select value={fieldName} onChange={e => { setFieldName(e.target.value); setTextValue(''); setRangeMin(''); setRangeMax('') }} style={{ display: 'block', width: '100%', marginTop: 5, padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg1)', color: 'var(--text0)' }}>
              {Object.keys(policy.fields).map(name => <option key={name} value={name}>{policyLabel(name)}</option>)}
            </select>
          </label>
          {selected?.kind === 'range_pct' ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <label style={muted}>Minimum<input type="number" min="0" max="100" value={rangeMin} onChange={e => setRangeMin(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 5, padding: 8, boxSizing: 'border-box' }} /></label>
              <label style={muted}>Maximum<input type="number" min="0" max="100" value={rangeMax} onChange={e => setRangeMax(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 5, padding: 8, boxSizing: 'border-box' }} /></label>
            </div>
          ) : (
            <label style={muted}>{selected?.kind === 'object' ? 'JSON value' : selected?.kind === 'list' ? 'Comma-separated values' : 'Value'}
              <input type={selected?.kind === 'money' ? 'number' : 'text'} value={textValue} onChange={e => setTextValue(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 5, padding: 8, boxSizing: 'border-box' }} />
            </label>
          )}
          <button type="button" onClick={submit} disabled={busy} style={{ padding: '9px 14px', borderRadius: 6, border: '1px solid var(--accent)', background: 'var(--accent-dim)', color: 'var(--accent)', fontWeight: 700, cursor: busy ? 'wait' : 'pointer' }}>{busy ? 'Confirming…' : 'Confirm'}</button>
        </div>
        {message && <div role="status" style={{ ...muted, marginTop: 8 }}>{message}</div>}
      </section>

      <section>
        <SectionTitle>Mandate</SectionTitle>
        {Object.entries(policy.fields).map(([name, field]) => (
          <div key={name} style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 2fr auto', gap: 10, borderBottom: '1px solid var(--border)', padding: '8px 0', fontSize: 12 }}>
            <span style={{ color: 'var(--text1)' }}>{policyLabel(name)}</span>
            <span style={{ color: field.operator_confirmed ? 'var(--text0)' : 'var(--text3)' }}>{field.value == null ? 'POLICY REQUIRED' : typeof field.value === 'string' ? field.value : JSON.stringify(field.value)}</span>
            <span style={{ color: field.operator_confirmed ? 'var(--green)' : 'var(--amber)' }}>{field.status}</span>
          </div>
        ))}
      </section>
    </div>
  )
}

export default function CioHub({ onDrill }: Props) {
  const [sp, setSp] = useSearchParams()
  const planId = (sp.get('plan') || '').trim()
  const tabParam = (sp.get('tab') || '').trim() as Tab
  const initialTab: Tab = TABS.includes(tabParam) ? tabParam : 'cio-brain'
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
      thesis_id: d.symbol_thesis_id || null,
      thesis_version: d.symbol_thesis_version || null,
      operator_identity_class: 'PRIMARY_OPERATOR',
      source_surface: 'cio_decision_card',
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
        {home?.as_of && <span style={{ color: 'var(--text3)', marginLeft: 12 }}>As of {formatAsOfET(home.as_of)}</span>}
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

      {tab === 'universe-theses' && (
        <div role="tabpanel" aria-label={TAB_LABEL[tab]}>
          <AgentResearchOpsStrip />
          <UniverseThesesPanel />
        </div>
      )}

      {tab === 'investment-books' && <InvestmentBooksPanel />}

      {tab === 'cio-brain' && <CioBrainPanel />}

      {tab === 'operator-policy' && <OperatorPolicyPanel />}

      {(tab === 'notification-gate' || tab === 'telegram-receipts' || tab === 'senses-evidence') && (
        <div role="tabpanel" aria-label={TAB_LABEL[tab]}>
          {tab === 'notification-gate' && <NotificationGatePanel />}
          {tab === 'telegram-receipts' && <TelegramReceiptsPanel />}
          {tab === 'senses-evidence' && <SensesEvidencePanel />}
        </div>
      )}

      {home && tab !== 'cio-brain' && tab !== 'notification-gate' && tab !== 'telegram-receipts' && tab !== 'senses-evidence' && tab !== 'investment-books' && tab !== 'operator-policy' && tab !== 'universe-theses' && (
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
