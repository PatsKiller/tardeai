import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from './DetailDrawer'
import ThresholdProposalModal from './ThresholdProposalModal'

interface Props { onDrill: (ctx: DrillContext) => void }

type TrendPoint = Record<string, number | string | null | undefined | Record<string, number>>

const OUTCOME_METRICS = [
  { key: 'hit_rate_promotions', label: 'Promotions', color: '#a855f7' },
  { key: 'hit_rate_research_actioned', label: 'Research', color: '#60a5fa' },
  { key: 'hit_rate_trades', label: 'Trades', color: '#22c55e' },
] as const

const GATE_COLOR: Record<string, string> = {
  promote_eligible: '#22c55e',
  demote_pressure: '#ef4444',
  pause_eligible: '#ef4444',
  promote_blocked_bad_tag: '#f59e0b',
  neutral: 'var(--text3)',
}

const ALERT_LABELS: Record<string, string> = {
  hit_rate_declining: 'Hit rate declining',
  efficiency_declining: 'Efficiency below threshold (3+ days)',
  scope_creep: 'Scope creep detected',
  stop_quality_divergence: 'Stop quality tier advantage fading',
}

const MATURITY_TIER_COLOR: Record<string, string> = {
  optimized: '#22c55e',
  mature: '#22c55e',
  developing: '#f59e0b',
  nascent: '#ef4444',
  maturing: '#f59e0b',
  at_risk: '#ef4444',
}

const MATURITY_COMPONENT_LABELS: Record<string, string> = {
  outcome_yield: 'Outcome yield',
  scope_discipline: 'Scope discipline',
  stop_quality: 'Stop quality',
  feedback_loop: 'Feedback loop',
  research_actionability: 'Research actionability',
}

const TREND_ARROW: Record<string, string> = {
  improving: '↑ improving',
  stable: '→ stable',
  declining: '↓ declining',
}

const THRESHOLD_STATUS_COLOR: Record<string, string> = {
  static: 'var(--text3)',
  learned: '#a855f7',
  pending_review: '#f59e0b',
}

const THRESHOLD_STATUS_LABEL: Record<string, string> = {
  static: 'static',
  learned: 'learned',
  pending_review: 'pending review',
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#ef4444',
  warning: '#f59e0b',
  info: '#60a5fa',
}

const CONFIDENCE_COLOR: Record<string, string> = {
  high: '#22c55e',
  medium: '#f59e0b',
  low: '#ef4444',
}

const THRESHOLD_SHORT_LABEL: Record<string, string> = {
  'efficiency.tighten_threshold': 'Efficiency',
  'stop_quality.divergence_delta_pp': 'Stop Quality Divergence',
}

const LIFECYCLE_STAGE_COLOR: Record<string, string> = {
  new: '#60a5fa',
  monitoring: 'var(--text3)',
  promoted: '#22c55e',
  demoted: '#f59e0b',
  archived: 'var(--text3)',
  blacklisted: '#ef4444',
}

function confidenceColor(tier?: string | null) {
  return CONFIDENCE_COLOR[String(tier ?? '').toLowerCase()] ?? '#f59e0b'
}

function proposalDeltaText(p: { threshold_id?: string; label?: string; current_value?: number; proposed_value?: number }) {
  const tid = p.threshold_id ?? ''
  const short = THRESHOLD_SHORT_LABEL[tid] ?? (p.label ?? tid).split('(')[0].trim()
  const cur = Number(p.current_value ?? 0)
  const prop = Number(p.proposed_value ?? 0)
  const delta = prop - cur
  const sign = delta > 0 ? '+' : ''
  if (tid.includes('divergence') || tid.startsWith('stop_quality')) {
    return `${short} ${sign}${(delta * 100).toFixed(0)}pp`
  }
  return `${short} ${sign}${delta.toFixed(2)}`
}

function topMetricContributions(contributions?: Record<string, number> | null, limit = 3) {
  if (!contributions) return []
  return Object.entries(contributions)
    .sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])))
    .slice(0, limit)
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${Number(v).toFixed(3)}`)
}

function directionStyle(direction?: string | null) {
  const d = String(direction ?? '').toLowerCase()
  if (d === 'tighten') return { label: 'Tightening', color: '#60a5fa', border: '#60a5fa', bg: 'rgba(96,165,250,.12)' }
  if (d === 'loosen') return { label: 'Loosening', color: '#f59e0b', border: '#f59e0b', bg: 'rgba(245,158,11,.12)' }
  return { label: 'Adjust', color: 'var(--text3)', border: 'var(--border)', bg: 'var(--bg2)' }
}

function DirectionBadge({ direction }: { direction?: string | null }) {
  const s = directionStyle(direction)
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
      color: s.color, background: s.bg, border: `1px solid ${s.border}`,
    }}>
      {s.label}
    </span>
  )
}

function formatThresholdCell(tid: string | undefined, value: number) {
  if (tid?.includes('divergence') || tid?.startsWith('stop_quality')) {
    return `${(value * 100).toFixed(1)}pp`
  }
  return value.toFixed(3)
}

function HoldoutBadge({ holdout }: { holdout?: { passed?: boolean; skipped?: boolean; score_ratio?: number } | null }) {
  if (!holdout || holdout.skipped) return <span style={{ fontSize: 9, color: 'var(--text3)' }}>holdout skipped</span>
  const passed = holdout.passed === true
  return (
    <span style={{
      fontSize: 9, fontWeight: 700,
      color: passed ? '#22c55e' : '#ef4444',
    }}>
      holdout {passed ? 'pass' : 'fail'}
      {holdout.score_ratio != null && ` (${(Number(holdout.score_ratio) * 100).toFixed(0)}%)`}
    </span>
  )
}

function CandidateTable({ rows, tid }: { rows: any[]; tid?: string }) {
  if (!rows?.length) return null
  return (
    <div style={{ marginTop: 8, overflowX: 'auto' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: '0.7fr 0.7fr 0.7fr 0.5fr',
        gap: 6, fontSize: 8, color: 'var(--text3)', padding: '4px 8px',
      }}>
        <span>Value</span><span>Score</span><span>Trigger</span><span />
      </div>
      {rows.map((r: any, i: number) => (
        <div key={i} style={{
          display: 'grid', gridTemplateColumns: '0.7fr 0.7fr 0.7fr 0.5fr',
          gap: 6, fontSize: 10, padding: '4px 8px', borderRadius: 4,
          background: r.is_proposed ? 'rgba(245,158,11,.1)' : r.is_current ? 'rgba(96,165,250,.08)' : 'transparent',
          fontFamily: 'monospace', color: 'var(--text2)',
        }}>
          <span>{formatThresholdCell(tid, Number(r.value))}</span>
          <span>{Number(r.score).toFixed(4)}</span>
          <span>{r.trigger_rate != null ? `${(Number(r.trigger_rate) * 100).toFixed(0)}%` : '—'}</span>
          <span style={{ fontSize: 8, color: r.is_proposed ? '#f59e0b' : r.is_current ? '#60a5fa' : 'transparent' }}>
            {r.is_proposed ? 'proposed' : r.is_current ? 'current' : ''}
          </span>
        </div>
      ))}
    </div>
  )
}

function CliCommandButton({ label, command }: { label: string; command: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }
  return (
    <button onClick={copy} title={command} style={{
      fontSize: 9, padding: '5px 10px', borderRadius: 5, cursor: 'pointer',
      border: '1px solid var(--border)', background: 'var(--bg2)', color: copied ? '#22c55e' : 'var(--text2)',
      fontFamily: 'monospace', textAlign: 'left', maxWidth: '100%',
    }}>
      {copied ? 'Copied' : label}
    </button>
  )
}

function ThresholdReviewModal({ proposals, thresholds, onClose, onRequestAction }: {
  proposals: any[]
  thresholds: any[]
  onClose: () => void
  onRequestAction: (proposal: any, action: 'approve' | 'reject') => void
}) {
  const [modifyId, setModifyId] = useState<string | null>(null)
  const [modifyVal, setModifyVal] = useState('')

  const bandFor = (tid: string) => thresholds.find(t => t.threshold_id === tid)?.safe_band

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12,
        maxWidth: 720, width: '100%', maxHeight: '85vh', overflow: 'auto', padding: 20,
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>Review threshold proposals</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>
              {proposals.length} pending · human approval required in v1
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6,
            padding: '4px 10px', cursor: 'pointer', color: 'var(--text2)', fontSize: 11,
          }}>Close</button>
        </div>

        {proposals.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text3)', padding: 12 }}>No pending threshold adjustments.</div>
        )}

        {proposals.map((p: any) => {
          const band = bandFor(p.threshold_id)
          const evidence = p.evidence ?? {}
          const metrics = evidence.candidate_metrics ?? {}
          const dir = directionStyle(p.direction)
          return (
            <div key={p.id} style={{
              marginBottom: 14, padding: 14, background: 'var(--bg2)', borderRadius: 10,
              borderLeft: `3px solid ${dir.border}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{p.label ?? p.threshold_id}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#f59e0b' }}>
                      {Number(p.current_value).toFixed(3)} → {Number(p.proposed_value).toFixed(3)}
                    </span>
                    <DirectionBadge direction={p.direction} />
                  </div>
                </div>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{p.id}</span>
              </div>

              <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 8 }}>{p.reasoning}</div>
              {p.expected_impact && (
                <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
                  <b style={{ color: 'var(--text2)' }}>Expected impact:</b> {p.expected_impact}
                </div>
              )}

              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10, padding: '8px 10px', background: 'var(--bg1)', borderRadius: 6 }}>
                <b style={{ color: 'var(--text2)' }}>Evidence</b>
                {evidence.confidence && (
                  <span style={{ marginLeft: 8, fontWeight: 700, color: evidence.confidence === 'high' ? '#22c55e' : evidence.confidence === 'low' ? '#ef4444' : '#f59e0b' }}>
                    {String(evidence.confidence).toUpperCase()}
                  </span>
                )}
                <div style={{ marginTop: 4 }}>
                  sample {evidence.sample_days ?? '—'} days
                  {' · '}Δ score {evidence.score_delta ?? '—'}
                  {evidence.runner_up && ` · runner-up ${evidence.runner_up.value} (${Number(evidence.runner_up.score).toFixed(4)})`}
                  {metrics.trigger_rate != null && ` · trigger ${(Number(metrics.trigger_rate) * 100).toFixed(0)}%`}
                  {band && ` · band ${band.min}–${band.max}`}
                </div>
                {evidence.metric_contributions && (
                  <div style={{ marginTop: 4, fontSize: 9 }}>
                    Contributions: {Object.entries(evidence.metric_contributions).map(([k, v]) => `${k}=${Number(v).toFixed(4)}`).join(' · ')}
                  </div>
                )}
                {Array.isArray(evidence.confidence_factors) && evidence.confidence_factors.length > 0 && (
                  <div style={{ marginTop: 4, fontSize: 9 }}>Factors: {evidence.confidence_factors.join(', ')}</div>
                )}
              </div>

              {modifyId === p.id ? (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                  <input value={modifyVal} onChange={e => setModifyVal(e.target.value)} placeholder="Override value"
                    style={{ fontSize: 11, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text0)', width: 100 }} />
                  <button onClick={() => onRequestAction({
                    ...p,
                    proposed_value: parseFloat(modifyVal) || p.proposed_value,
                    _override_value: parseFloat(modifyVal) || p.proposed_value,
                  }, 'approve')}
                    style={{ fontSize: 10, padding: '6px 12px', borderRadius: 6, border: 'none', background: '#22c55e', color: '#000', cursor: 'pointer', fontWeight: 700 }}>
                    Approve override
                  </button>
                  <button onClick={() => setModifyId(null)} style={{ fontSize: 10, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)', cursor: 'pointer' }}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button onClick={() => onRequestAction(p, 'approve')}
                    style={{ fontSize: 10, padding: '6px 14px', borderRadius: 6, border: 'none', background: '#22c55e', color: '#000', cursor: 'pointer', fontWeight: 700 }}>
                    Approve
                  </button>
                  <button onClick={() => { setModifyId(p.id); setModifyVal(String(p.proposed_value)) }}
                    style={{ fontSize: 10, padding: '6px 14px', borderRadius: 6, border: '1px solid #60a5fa', background: 'rgba(96,165,250,.1)', color: '#60a5fa', cursor: 'pointer', fontWeight: 600 }}>
                    Modify
                  </button>
                  <button onClick={() => onRequestAction(p, 'reject')}
                    style={{ fontSize: 10, padding: '6px 14px', borderRadius: 6, border: '1px solid #ef4444', background: 'rgba(239,68,68,.1)', color: '#ef4444', cursor: 'pointer', fontWeight: 600 }}>
                    Reject
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function AlertDrilldownModal({ alert, onClose, onDrill }: {
  alert: any
  onClose: () => void
  onDrill: (ctx: DrillContext) => void
}) {
  const drill = alert.drilldown ?? {}
  const contributors = alert.contributors ?? {}
  const symbols: any[] = contributors.symbols ?? drill.symbols ?? []
  const tags: any[] = contributors.tags ?? drill.tags ?? []
  const tierRows: any[] = drill.stop_quality_by_tier ?? []
  const causes: string[] = drill.root_causes ?? []

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12,
        maxWidth: 640, width: '100%', maxHeight: '85vh', overflow: 'auto', padding: 20,
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: SEVERITY_COLOR[alert.severity] ?? '#f59e0b' }}>
              {alert.label ?? ALERT_LABELS[alert.id] ?? alert.id}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>
              {alert.severity ?? 'warning'}
              {alert.duration_days != null && ` · ${alert.duration_days} day(s)`}
              {alert.since && ` · since ${alert.since}`}
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6,
            padding: '4px 10px', cursor: 'pointer', color: 'var(--text2)', fontSize: 11,
          }}>Close</button>
        </div>

        <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 14, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }}>
          {drill.summary ?? alert.detail}
        </div>

        {causes.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Why this fired</div>
            {causes.map((c, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text2)', padding: '4px 0' }}>• {c}</div>
            ))}
          </div>
        )}

        {symbols.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Contributing symbols</div>
            <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 0.5fr 0.5fr 0.5fr 1fr', fontSize: 8, color: 'var(--text3)', padding: '4px 6px' }}>
              <span>Symbol</span><span>Gate</span><span>Hit rate</span><span>n</span><span>Actions</span>
            </div>
            {symbols.map((s: any) => (
              <div key={s.symbol} style={{ display: 'grid', gridTemplateColumns: '0.7fr 0.5fr 0.5fr 0.5fr 1fr', padding: '6px', borderBottom: '1px solid var(--border)', fontSize: 11, alignItems: 'center' }}>
                <span style={{ fontWeight: 700, fontFamily: 'monospace' }}>{s.symbol}</span>
                <span style={{ color: GATE_COLOR[s.gate] ?? 'var(--text2)', fontSize: 10 }}>{s.gate ?? '—'}</span>
                <span>{pct(s.hit_rate)}</span>
                <span>{s.n ?? '—'}</span>
                <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  <button onClick={() => onDrill({ title: s.symbol, subtitle: s.gate, endpoint: `/api/v2/hermes/outcome-bus?symbol=${s.symbol}`, rows: [s] })}
                    style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer', color: '#60a5fa' }}>
                    Bus
                  </button>
                  <button onClick={() => onDrill({ title: s.symbol, subtitle: 'Governor', endpoint: `/api/v2/hermes/scope-governor?symbol=${s.symbol}`, rows: [s] })}
                    style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer', color: '#a855f7' }}>
                    Governor
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}

        {tags.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Contributing tags</div>
            {tags.map((t: any) => (
              <div key={t.tag} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 8px', background: 'var(--bg2)', borderRadius: 6, marginBottom: 4, fontSize: 11 }}>
                <span style={{ fontFamily: 'monospace', color: (t.lift ?? 0) < 0 ? '#ef4444' : 'var(--text0)' }}>{t.tag}</span>
                <span>lift {t.lift ?? '—'} · n {t.n ?? '—'}</span>
              </div>
            ))}
          </div>
        )}

        {tierRows.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Stop quality by tier</div>
            {tierRows.map((t: any) => (
              <div key={t.tier} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                <span style={{ textTransform: 'capitalize', fontWeight: 600 }}>{t.tier}</span>
                <span>trail {pct(t.trail_activation_rate)} · n {t.sample_n}</span>
              </div>
            ))}
          </div>
        )}

        {drill.metrics_snapshot && (
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>
            Snapshot: {Object.entries(drill.metrics_snapshot).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
          </div>
        )}
      </div>
    </div>
  )
}

function pct(v: number | null | undefined, digits = 1) {
  if (v == null || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function num(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return '—'
  return String(v)
}

function hitRateColor(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return 'var(--text3)'
  if (v >= 0.4) return '#22c55e'
  if (v >= 0.3) return '#f59e0b'
  return '#ef4444'
}

function deltaStr(v: number | null | undefined, asPct = true) {
  if (v == null || Number.isNaN(v)) return null
  const sign = v > 0 ? '+' : ''
  return asPct ? `${sign}${(v * 100).toFixed(1)}pp` : `${sign}${v}`
}

function fmtDay(at?: string | null) {
  if (!at) return '—'
  return at.slice(0, 10)
}

function MiniLineChart({ series, metrics, height = 92 }: {
  series: TrendPoint[]
  metrics: readonly { key: string; label: string; color: string }[]
  height?: number
}) {
  const valid = series.filter(s => metrics.some(m => typeof s[m.key] === 'number'))
  if (valid.length < 2) {
    return <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>No trend data yet — nightly runs will populate this.</div>
  }
  const pad = 6
  const w = 100
  const h = height
  const n = valid.length
  const lines = metrics.map(m => {
    const pts = valid.map((s, i) => {
      const v = Number(s[m.key] ?? 0)
      const x = pad + (i / Math.max(n - 1, 1)) * (w - pad * 2)
      const y = h - pad - Math.min(1, Math.max(0, v)) * (h - pad * 2)
      return `${x},${y}`
    }).join(' ')
    return { ...m, pts }
  })
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }}>
      {[0.25, 0.5, 0.75].map(g => (
        <line key={g} x1={pad} x2={w - pad} y1={h - pad - g * (h - pad * 2)} y2={h - pad - g * (h - pad * 2)}
          stroke="var(--border)" strokeWidth="0.4" strokeDasharray="1.5 2" />
      ))}
      {lines.map(l => (
        <polyline key={l.key} fill="none" stroke={l.color} strokeWidth="1.6" strokeLinejoin="round" points={l.pts} />
      ))}
    </svg>
  )
}

function StackedTierBars({ series }: { series: TrendPoint[] }) {
  if (series.length === 0) {
    return <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>No governor history yet — tier snapshots appear after scope runs.</div>
  }
  const maxTotal = Math.max(...series.map(s => (Number(s.hot) || 0) + (Number(s.warm) || 0) + (Number(s.cold) || 0)), 1)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100, padding: '8px 10px 4px' }}>
      {series.map((s, i) => {
        const hot = Number(s.hot) || 0
        const warm = Number(s.warm) || 0
        const cold = Number(s.cold) || 0
        const total = hot + warm + cold || 1
        const barH = Math.round((total / maxTotal) * 100)
        return (
          <div key={i} title={`${fmtDay(String(s.day ?? s.at))}\nHot ${hot} · Warm ${warm} · Cold ${cold}`}
            style={{ flex: 1, minWidth: 4, height: `${barH}%`, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', alignSelf: 'flex-end' }}>
            <div style={{ height: `${(hot / total) * 100}%`, background: '#ef4444', minHeight: hot ? 1 : 0 }} />
            <div style={{ height: `${(warm / total) * 100}%`, background: '#f59e0b', minHeight: warm ? 1 : 0 }} />
            <div style={{ height: `${(cold / total) * 100}%`, background: '#60a5fa', minHeight: cold ? 1 : 0 }} />
          </div>
        )
      })}
    </div>
  )
}

export default function HermesClosedLoopPanel({ onDrill }: Props) {
  const [trendDays, setTrendDays] = useState<7 | 30>(30)
  const { data: busData, loading: busLoading } = useApi<any>('/api/v2/hermes/outcome-bus', 120_000)
  const { data: govData, loading: govLoading } = useApi<any>('/api/v2/hermes/scope-governor', 60_000)
  const { data: histData, loading: histLoading } = useApi<any>(`/api/v2/hermes/outcome-bus/history?days=${trendDays}`, 120_000)
  const { data: thresholdData, refetch: refetchThresholds } = useApi<any>('/api/v2/hermes/thresholds', 120_000)
  const { data: evalData } = useApi<any>('/api/v2/hermes/thresholds/evaluations', 120_000)

  const bus = busData?.bus ?? busData ?? {}
  const global = bus.global ?? {}
  const gov = govData?.universe ?? {}
  const heat = gov.counts_by_heat ?? govData?.universe?.counts_by_heat ?? {}
  const feedback: any[] = bus.feedback_to_governor ?? []
  const audit: any[] = govData?.recent_audit ?? []
  const watchlistLifecycle = govData?.watchlist_lifecycle ?? {}
  const lifecyclePanelRows: any[] = watchlistLifecycle?.panel_rows ?? []
  const lifecyclePending: any[] = watchlistLifecycle?.pending_transitions ?? []
  const lifecycleSummary: Record<string, number> = watchlistLifecycle?.summary ?? {}
  const lifecyclePendingCount = watchlistLifecycle?.pending_count ?? lifecyclePending.length
  const bySymbol: Record<string, any> = bus.by_symbol ?? {}
  const stopQ = bus.stop_quality ?? {}
  const resource = bus.resource_efficiency ?? {}

  const efficiencyScore = useMemo(() => {
    const s = resource.score ?? resource.resource_efficiency_score
    if (s != null) return Math.max(0, Math.min(1, Number(s)))
    const wr = resource.write_reduction_vs_baseline_pct
    if (wr == null) return null
    return Math.max(0, Math.min(1, Number(wr)))
  }, [resource.score, resource.resource_efficiency_score, resource.write_reduction_vs_baseline_pct])

  const scoreComponents = resource.components ?? resource.score_components ?? {}
  const trend7d = resource.trend_7d ?? 'stable'
  const calcVersion = resource.calculation_version ?? 'v1.1'
  const stopByTier: Record<string, any> = stopQ.by_tier ?? {}
  const stopCorrelations: any[] = stopQ.correlations ?? []
  const alerts: any[] = bus.alerts?.active ?? busData?.active_alerts ?? []
  const alertCount = bus.alerts?.active_count ?? alerts.length
  const maturity = bus.maturity ?? busData?.maturity ?? histData?.maturity ?? {}
  const maturityTier = maturity.tier ?? maturity.overall_status ?? '—'
  const maturityComposite = maturity.composite_score ?? (maturity.maturity_score != null ? Number(maturity.maturity_score) * 20 : null)
  const maturityTrendLabel = maturity.trend ?? histData?.maturity_trend?.trend ?? 'stable'
  const maturityTrendSeries: TrendPoint[] = histData?.maturity_trend?.series ?? []
  const maturityTrendDelta = histData?.maturity_trend?.delta_window ?? null
  const maturityComponents: Record<string, any> = maturity.components ?? {}
  const busReactions: any[] = govData?.bus_reactions ?? govData?.universe?.bus_reactions ?? []
  const reactionReviewMode = govData?.bus_reaction_review_mode === true
  const thresholdRows: any[] = thresholdData?.thresholds ?? []
  const pendingThresholds: any[] = thresholdData?.pending_proposals ?? []
  const thresholdReviewMode = thresholdData?.review_mode === true
  const evalSummary = evalData?.summary ?? thresholdData?.evaluation_summary ?? {}
  const recentEvaluations: any[] = evalData?.evaluations ?? []
  const lastThresholdEval = thresholdData?.last_evaluated_at
  const lastThresholdChange = thresholdData?.last_changed_at ?? thresholdData?.updated_at
  const historyDays = thresholdData?.history_days ?? null
  const minHistoryDays = thresholdData?.min_history_days ?? 14
  const learningReady = thresholdData?.learning_ready ?? (historyDays == null ? null : historyDays >= minHistoryDays)
  const learningStatus = thresholdData?.learning_status ?? (learningReady === false ? 'collecting_data' : 'active')
  const pendingSummary = thresholdData?.pending_summary
    ?? (pendingThresholds.length > 0
      ? `${pendingThresholds.length} proposal${pendingThresholds.length !== 1 ? 's' : ''} pending review (${pendingThresholds.map(proposalDeltaText).join(', ')})`
      : 'No pending adjustments')
  const thresholdAudit: any[] = thresholdData?.recent_audit ?? []
  const cliCommands: Record<string, string> = thresholdData?.cli_commands ?? {
    status: '.venv/bin/python scripts/hermes_threshold_learner.py --status',
    learn: '.venv/bin/python scripts/hermes_threshold_learner.py --learn',
    learn_apply: '.venv/bin/python scripts/hermes_threshold_learner.py --learn --apply',
    approve: pendingThresholds[0]?.id
      ? `.venv/bin/python scripts/hermes_threshold_learner.py --approve ${pendingThresholds[0].id}`
      : '.venv/bin/python scripts/hermes_threshold_learner.py --approve <proposal_id>',
    evaluate: '.venv/bin/python scripts/hermes_threshold_learner.py --evaluate',
  }
  const thresholdActionable = pendingThresholds.length > 0
    || thresholdRows.some((t: any) => t.status === 'pending_review' || t.status === 'learned' || t.is_learned)
  const [thresholdModalOpen, setThresholdModalOpen] = useState(false)
  const [thresholdExpanded, setThresholdExpanded] = useState(false)
  const [candidateTableOpen, setCandidateTableOpen] = useState(false)
  const lastLearn = thresholdData?.last_learn ?? {}
  const learnSnapshots: any[] = lastLearn.snapshots ?? []
  const [thresholdConfirm, setThresholdConfirm] = useState<{ proposal: any; action: 'approve' | 'reject' } | null>(null)
  const [thresholdToast, setThresholdToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)

  const showThresholdToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setThresholdToast({ message: msg, type })
    setTimeout(() => setThresholdToast(null), 4000)
  }

  const handleThresholdActionSuccess = () => {
    refetchThresholds()
    setThresholdModalOpen(false)
  }

  const openThresholdConfirm = (proposal: any, action: 'approve' | 'reject') => {
    setThresholdConfirm({ proposal, action })
  }

  useEffect(() => {
    if (thresholdActionable || (thresholdData && learningReady === false)) {
      setThresholdExpanded(true)
    }
  }, [thresholdActionable, thresholdData, learningReady])

  const symbolRows = useMemo(() => {
    const fbBySym = Object.fromEntries(feedback.map(f => [String(f.symbol).toUpperCase(), f]))
    return Object.entries(bySymbol)
      .map(([sym, meta]) => ({
        sym,
        meta,
        fb: fbBySym[sym.toUpperCase()],
        tier: (gov.symbols ?? []).find((s: any) => String(s.symbol).toUpperCase() === sym.toUpperCase()),
      }))
      .sort((a, b) => {
        const pri = (fb: any) => fb?.action === 'pause' ? 0 : fb?.action === 'demote_pressure' ? 1 : fb?.action === 'promote_eligible' ? 2 : 9
        return pri(a.fb) - pri(b.fb) || String(a.sym).localeCompare(b.sym)
      })
  }, [bySymbol, feedback, gov.symbols])

  const tagRows = useMemo(() =>
    Object.entries(bus.by_tag ?? {})
      .sort((a: any, b: any) => (b[1]?.n ?? 0) - (a[1]?.n ?? 0))
      .slice(0, 8),
  [bus.by_tag])

  const outcomeSeries: TrendPoint[] = histData?.outcome?.series ?? []
  const tierSeries: TrendPoint[] = histData?.tiers?.series ?? []
  const outcomeSummary = histData?.outcome?.summary ?? {}
  const promoMax = useMemo(() => Math.max(0.5, ...outcomeSeries.map(s => Number(s.hit_rate_promotions) || 0)), [outcomeSeries])
  const scopeMax = useMemo(() => Math.max(1, ...outcomeSeries.map(s => Number(s.symbols_in_bus) || 0)), [outcomeSeries])
  const effTrendMax = useMemo(() => Math.max(0.5, ...outcomeSeries.map(s => Number(s.resource_efficiency_score) || 0)), [outcomeSeries])
  const trailTrendMax = useMemo(() => Math.max(0.3, ...outcomeSeries.map(s => Number(s.trail_activation_rate) || 0)), [outcomeSeries])
  const [expandedTrend, setExpandedTrend] = useState<number | null>(null)
  const [drilldownAlert, setDrilldownAlert] = useState<any | null>(null)
  const maturityChartMax = useMemo(
    () => Math.max(100, ...maturityTrendSeries.map(s => Number(s.composite_score ?? s.maturity_score) || 0)),
    [maturityTrendSeries],
  )

  if (busLoading && !bus.version) {
    return <div style={{ color: 'var(--text3)', fontSize: 12, padding: 16 }}>Loading outcome bus…</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {drilldownAlert && (
        <AlertDrilldownModal alert={drilldownAlert} onClose={() => setDrilldownAlert(null)} onDrill={onDrill} />
      )}
      {thresholdConfirm && (
        <ThresholdProposalModal
          proposal={thresholdConfirm.proposal}
          action={thresholdConfirm.action}
          onClose={() => setThresholdConfirm(null)}
          onSuccess={(msg) => { showThresholdToast(msg, 'success'); handleThresholdActionSuccess() }}
          onError={(msg) => showThresholdToast(msg, 'error')}
        />
      )}
      {thresholdModalOpen && (
        <ThresholdReviewModal
          proposals={pendingThresholds}
          thresholds={thresholdRows}
          onClose={() => setThresholdModalOpen(false)}
          onRequestAction={(proposal, action) => openThresholdConfirm(proposal, action)}
        />
      )}
      {thresholdToast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 1200,
          padding: '12px 18px', borderRadius: 8, fontSize: 12, fontWeight: 600,
          background: thresholdToast.type === 'success' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)',
          border: thresholdToast.type === 'success'
            ? '1px solid rgba(34,197,94,.4)' : '1px solid rgba(239,68,68,.4)',
          color: thresholdToast.type === 'success' ? '#22c55e' : '#ef4444',
          boxShadow: '0 4px 20px rgba(0,0,0,.35)',
        }}>
          {thresholdToast.message}
        </div>
      )}

      {/* Alerts banner — prominent when active, compact when healthy */}
      {alertCount > 0 ? (
        <div style={{
          background: 'linear-gradient(135deg, rgba(239,68,68,.18) 0%, rgba(245,158,11,.12) 100%)',
          border: '2px solid rgba(239,68,68,.55)',
          borderRadius: 12,
          padding: '14px 16px',
          boxShadow: '0 0 0 1px rgba(239,68,68,.15)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <span style={{ fontSize: 18 }}>⚠</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 800, color: '#ef4444' }}>
                {alertCount} active alert{alertCount !== 1 ? 's' : ''} — closed-loop attention needed
              </div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                Evaluated {bus.alerts?.evaluated_at?.slice(0, 19) ?? '—'} · conservative thresholds
              </div>
            </div>
          </div>
          {alerts.map((a: any) => {
            const topSyms = (a.contributors?.symbols ?? []).slice(0, 3)
            const topTags = (a.contributors?.tags ?? []).slice(0, 2)
            return (
              <div key={a.id} style={{
                fontSize: 11, padding: '10px 12px', marginBottom: 6,
                background: 'rgba(0,0,0,.2)', borderRadius: 8,
                borderLeft: `3px solid ${SEVERITY_COLOR[a.severity] ?? '#f59e0b'}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, color: 'var(--text0)', fontSize: 12 }}>
                      {a.label ?? ALERT_LABELS[a.id] ?? a.id}
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                      <span style={{ color: SEVERITY_COLOR[a.severity] ?? '#f59e0b', fontWeight: 600 }}>{a.severity ?? 'warning'}</span>
                      {a.duration_days != null && ` · ${a.duration_days}d`}
                      {a.since && ` · since ${a.since}`}
                    </div>
                  </div>
                  <button onClick={() => setDrilldownAlert(a)} style={{
                    fontSize: 9, padding: '4px 10px', borderRadius: 5, border: '1px solid rgba(239,68,68,.4)',
                    background: 'rgba(239,68,68,.12)', color: '#fca5a5', cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
                  }}>View details</button>
                </div>
                <div style={{ marginTop: 6, color: 'var(--text2)', lineHeight: 1.4 }}>{a.detail}</div>
                {(topSyms.length > 0 || topTags.length > 0) && (
                  <div style={{ marginTop: 8, fontSize: 9, color: 'var(--text3)' }}>
                    {topSyms.length > 0 && (
                      <span>Symbols: {topSyms.map((s: any) => s.symbol).join(', ')}</span>
                    )}
                    {topTags.length > 0 && (
                      <span style={{ marginLeft: topSyms.length ? 10 : 0 }}>
                        Tags: {topTags.map((t: any) => t.tag).join(', ')}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div style={{
          fontSize: 11, color: '#22c55e', padding: '8px 12px',
          background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.25)', borderRadius: 8,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>✓</span>
          <span>No active alerts — system healthy · maturity <b>{maturityTier}</b>
            {maturityComposite != null && ` (${Math.round(Number(maturityComposite))}/100)`}</span>
        </div>
      )}

      <div style={{ fontSize: 10, color: '#60a5fa', padding: '6px 10px', background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.25)', borderRadius: 6 }}>
        Closed-loop coordination · outcome yield outranks throughput · bus v{bus.version ?? '1'} · generated {bus.generated_at?.slice(0, 19) ?? '—'}
      </div>

      {/* Maturity composite + component breakdown */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Maturity score (v2)</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>
              Composite {maturityComposite != null ? `${Math.round(Number(maturityComposite))}/100` : '—'}
              {' · '}{TREND_ARROW[maturityTrendLabel] ?? maturityTrendLabel}
              {maturityTrendDelta != null && ` · Δ ${maturityTrendDelta > 0 ? '+' : ''}${maturityTrendDelta}`}
              {maturity.version && ` · ${maturity.version}`}
            </div>
          </div>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '4px 12px', borderRadius: 5, textTransform: 'capitalize',
            background: `${MATURITY_TIER_COLOR[maturityTier] ?? '#f59e0b'}22`,
            color: MATURITY_TIER_COLOR[maturityTier] ?? '#f59e0b',
            border: `1px solid ${MATURITY_TIER_COLOR[maturityTier] ?? '#f59e0b'}44`,
          }}>{maturityTier}</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
            {Object.entries(MATURITY_COMPONENT_LABELS).map(([key, label]) => {
              const dim = maturityComponents[key] ?? {}
              const score = dim.score ?? null
              const weight = dim.weight != null ? Math.round(Number(dim.weight) * 100) : null
              const compTrend = dim.trend ?? 'stable'
              const scoreColor = score == null ? 'var(--text3)' : Number(score) >= 70 ? '#22c55e' : Number(score) >= 50 ? '#f59e0b' : '#ef4444'
              return (
                <div key={key} style={{ padding: '10px 8px', background: 'var(--bg2)', borderRadius: 8 }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: scoreColor }}>{score != null ? Math.round(Number(score)) : '—'}</div>
                  <div style={{ fontSize: 9, color: 'var(--text0)', marginTop: 4 }}>{label}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>
                    {weight != null && `${weight}% weight · `}{TREND_ARROW[compTrend] ?? compTrend}
                  </div>
                </div>
              )
            })}
          </div>

          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>
              Maturity trend ({trendDays}d composite)
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 72, padding: '6px 8px 4px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
              {maturityTrendSeries.length < 2 && !histLoading && (
                <div style={{ fontSize: 10, color: 'var(--text3)', padding: 4 }}>Trend populates after nightly bus history accumulates.</div>
              )}
              {histLoading && maturityTrendSeries.length === 0 && (
                <div style={{ fontSize: 10, color: 'var(--text3)', padding: 4 }}>Loading…</div>
              )}
              {maturityTrendSeries.map((s, i) => {
                const score = Number(s.composite_score ?? (s.maturity_score != null ? Number(s.maturity_score) * 20 : 0)) || 0
                const tier = String(s.tier ?? s.overall_status ?? '')
                const barColor = MATURITY_TIER_COLOR[tier] ?? '#60a5fa'
                return (
                  <div key={i}
                    title={`${fmtDay(String(s.day))}\nComposite ${Math.round(score)}/100 · ${tier}\nAlerts ${s.active_alert_count ?? 0}`}
                    style={{
                      flex: 1, minWidth: 4,
                      height: `${Math.round((score / maturityChartMax) * 100)}%`,
                      background: barColor,
                      borderRadius: '2px 2px 0 0', alignSelf: 'flex-end', opacity: 0.9,
                    }} />
                )
              })}
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
              Bar height = composite 0–100 · color = maturity tier
            </div>
          </div>
        </div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
          Config: config/hermes_maturity.yaml · daily snapshot: state/hermes/hermes_maturity.json
        </div>
      </div>

      {/* Adaptive thresholds — collapsible; expands when actionable or collecting data */}
      <div style={{
        background: 'var(--bg1)',
        border: `1px solid ${pendingThresholds.length > 0 ? 'rgba(245,158,11,.45)' : 'var(--border)'}`,
        borderRadius: 10,
        padding: thresholdExpanded ? 16 : '12px 16px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
          <button
            onClick={() => setThresholdExpanded(v => !v)}
            style={{
              background: 'none', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left', flex: 1, minWidth: 200,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 10, color: 'var(--text3)' }}>{thresholdExpanded ? '▼' : '▶'}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Adaptive thresholds</div>
                <div style={{
                  fontSize: 10, marginTop: 4,
                  color: pendingThresholds.length > 0 ? '#f59e0b' : learningStatus === 'collecting_data' ? '#60a5fa' : '#22c55e',
                }}>
                  {learningReady === false && historyDays != null
                    ? `Collecting data… ${historyDays}/${minHistoryDays} bus days · ${pendingSummary}`
                    : pendingSummary}
                </div>
              </div>
            </div>
          </button>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {thresholdReviewMode && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: 'rgba(96,165,250,.12)', color: '#60a5fa', border: '1px solid rgba(96,165,250,.3)' }}>
                REVIEW MODE
              </span>
            )}
            {!thresholdExpanded && thresholdRows.length > 0 && (
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>
                {thresholdRows.map((t: any) => `${THRESHOLD_SHORT_LABEL[t.threshold_id] ?? t.label?.split(' ')[0] ?? t.threshold_id}: ${Number(t.active_value).toFixed(2)}`).join(' · ')}
              </span>
            )}
            {pendingThresholds.length > 0 && (
              <button onClick={() => { setThresholdExpanded(true); setThresholdModalOpen(true) }} style={{
                fontSize: 10, fontWeight: 700, padding: '6px 14px', borderRadius: 6, border: 'none',
                background: '#f59e0b', color: '#000', cursor: 'pointer',
              }}>
                Review ({pendingThresholds.length})
              </button>
            )}
          </div>
        </div>

        {thresholdExpanded && (
          <>
            {learningReady === false && (
              <div style={{
                fontSize: 11, color: '#60a5fa', marginTop: 12, marginBottom: 10, padding: '10px 12px',
                background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.25)', borderRadius: 8,
                lineHeight: 1.45,
              }}>
                Collecting data… Threshold learning will activate after {minHistoryDays} days of outcome bus history
                {historyDays != null && ` (currently ${historyDays} day${historyDays !== 1 ? 's' : ''})`}.
                Active values remain at static defaults until then.
              </div>
            )}

            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 10, marginBottom: 8 }}>
              Last evaluated {lastThresholdEval ? lastThresholdEval.slice(0, 19) : '—'}
              {' · '}last changed {lastThresholdChange ? lastThresholdChange.slice(0, 19) : '—'}
              {' · '}scoring {thresholdData?.scoring_version ?? 'scoring-v2'}
            </div>

            {pendingThresholds.length === 0 && learningReady !== false && (
              <div style={{
                fontSize: 11, color: '#22c55e', marginBottom: 10, padding: '8px 10px',
                background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.2)', borderRadius: 6,
                lineHeight: 1.45,
              }}>
                No pending adjustments.
                {' '}Run <code style={{ fontSize: 10 }}>hermes_threshold_learner.py --learn --apply</code> to scan candidates and generate proposals when signal warrants.
              </div>
            )}

            <div style={{ fontSize: 8, color: 'var(--text3)', display: 'grid', gridTemplateColumns: '1.3fr 0.55fr 0.55fr 0.5fr 0.55fr', gap: 8, padding: '4px 10px', marginBottom: 4 }}>
              <span>Threshold</span><span>Active</span><span>Static</span><span>Proposed</span><span>Status</span>
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              {thresholdRows.map((t: any) => {
                const status = t.status ?? (t.is_learned ? 'learned' : 'static')
                const delta = t.active_value != null && t.static_default != null
                  ? Number(t.active_value) - Number(t.static_default) : null
                return (
                  <div key={t.threshold_id} style={{
                    display: 'grid', gridTemplateColumns: '1.3fr 0.55fr 0.55fr 0.5fr 0.55fr', gap: 8,
                    padding: '8px 10px', background: 'var(--bg2)', borderRadius: 6, fontSize: 11, alignItems: 'center',
                    borderLeft: status === 'pending_review' ? '3px solid #f59e0b' : status === 'learned' ? '3px solid #a855f7' : '3px solid transparent',
                  }}>
                    <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{t.label ?? t.threshold_id}</span>
                    <span style={{ fontFamily: 'monospace', color: status === 'learned' ? '#a855f7' : status === 'pending_review' ? '#f59e0b' : '#22c55e' }} title={delta != null ? `Δ static ${delta > 0 ? '+' : ''}${delta.toFixed(3)}` : undefined}>
                      {t.active_value != null ? Number(t.active_value).toFixed(2) : '—'}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'monospace' }}>{Number(t.static_default).toFixed(2)}</span>
                    <span style={{ fontSize: 10, fontFamily: 'monospace', color: t.proposed_value != null ? '#f59e0b' : 'var(--text3)' }}>
                      {t.proposed_value != null ? Number(t.proposed_value).toFixed(2) : '—'}
                    </span>
                    <span style={{
                      fontSize: 9, fontWeight: 600, textTransform: 'capitalize',
                      color: THRESHOLD_STATUS_COLOR[status] ?? 'var(--text3)',
                    }}>{THRESHOLD_STATUS_LABEL[status] ?? status}</span>
                  </div>
                )
              })}
            </div>

            {pendingThresholds.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase' }}>
                  Pending proposals
                </div>
                {pendingThresholds.map((p: any) => {
                  const evidence = p.evidence ?? {}
                  const metrics = topMetricContributions(evidence.metric_contributions)
                  const dir = directionStyle(p.direction)
                  const keyDays: any[] = (evidence.key_trigger_days ?? []).slice(0, 3)
                  const evalCtx = p.evaluation_context ?? evidence.evaluation_context
                  return (
                    <div key={p.id} style={{
                      marginBottom: 8, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8,
                      borderLeft: `3px solid ${dir.border}`, fontSize: 10,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                        <div style={{ fontWeight: 700, color: 'var(--text0)', fontSize: 11 }}>
                          {p.label ?? p.threshold_id}
                          <span style={{ marginLeft: 8, fontFamily: 'monospace', color: dir.color }}>
                            {formatThresholdCell(p.threshold_id, Number(p.current_value))} → {formatThresholdCell(p.threshold_id, Number(p.proposed_value))}
                          </span>
                          <span style={{ marginLeft: 8 }}><DirectionBadge direction={p.direction} /></span>
                        </div>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          {evidence.confidence && (
                            <span style={{ fontSize: 9, fontWeight: 700, color: confidenceColor(evidence.confidence) }}>
                              {String(evidence.confidence).toUpperCase()} confidence
                            </span>
                          )}
                          <HoldoutBadge holdout={evidence.holdout_validation} />
                        </div>
                      </div>
                      <div style={{ color: 'var(--text2)', lineHeight: 1.45, marginBottom: 6 }}>{p.reasoning}</div>
                      {evidence.runner_up && (
                        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
                          <b style={{ color: 'var(--text2)' }}>Runner-up:</b>{' '}
                          {formatThresholdCell(p.threshold_id, Number(evidence.runner_up.value))} (score {Number(evidence.runner_up.score).toFixed(4)})
                        </div>
                      )}
                      {p.expected_impact && (
                        <div style={{ color: 'var(--text3)', marginBottom: 4 }}>
                          <b style={{ color: 'var(--text2)' }}>Expected impact:</b> {p.expected_impact}
                        </div>
                      )}
                      {evalCtx && (
                        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
                          <b style={{ color: 'var(--text2)' }}>Last evaluation:</b>{' '}
                          {evalCtx.verdict} → {evalCtx.recommendation}
                          {evalCtx.impact_score != null && ` (impact ${Number(evalCtx.impact_score).toFixed(2)})`}
                        </div>
                      )}
                      {metrics.length > 0 && (
                        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
                          <b style={{ color: 'var(--text2)' }}>Top metrics:</b> {metrics.join(' · ')}
                        </div>
                      )}
                      {evidence.counterfactual && (
                        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
                          <b style={{ color: 'var(--text2)' }}>Would fire:</b>{' '}
                          {evidence.counterfactual.trigger_count ?? 0}× / {evidence.counterfactual.window_days ?? 14}d
                          {evidence.current_trigger_count != null && (
                            <span> (now {evidence.current_trigger_count.trigger_count ?? 0}×)</span>
                          )}
                        </div>
                      )}
                      {keyDays.length > 0 && (
                        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
                          <b style={{ color: 'var(--text2)' }}>Key trigger days:</b>{' '}
                          {keyDays.map((d: any) => String(d.day ?? '').slice(5)).join(', ')}
                        </div>
                      )}
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                        <button onClick={() => openThresholdConfirm(p, 'approve')} style={{
                          fontSize: 10, fontWeight: 700, padding: '5px 12px', borderRadius: 5, border: 'none',
                          background: '#22c55e', color: '#000', cursor: 'pointer',
                        }}>Approve</button>
                        <button onClick={() => openThresholdConfirm(p, 'reject')} style={{
                          fontSize: 10, fontWeight: 600, padding: '5px 12px', borderRadius: 5,
                          border: '1px solid #ef4444', background: 'rgba(239,68,68,.1)', color: '#ef4444', cursor: 'pointer',
                        }}>Reject</button>
                      </div>
                    </div>
                  )
                })}
                <button onClick={() => setThresholdModalOpen(true)} style={{
                  fontSize: 10, fontWeight: 600, padding: '6px 14px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer', marginTop: 4,
                }}>
                  Full review details
                </button>
              </div>
            )}

            {learnSnapshots.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <button
                  onClick={() => setCandidateTableOpen(v => !v)}
                  style={{
                    background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                    fontSize: 10, fontWeight: 700, color: 'var(--text2)', textTransform: 'uppercase',
                  }}
                >
                  {candidateTableOpen ? '▼' : '▶'} Last learn candidate grid
                  {lastLearn.at && (
                    <span style={{ marginLeft: 8, fontWeight: 400, color: 'var(--text3)', textTransform: 'none' }}>
                      {String(lastLearn.at).slice(0, 19)} · {lastLearn.history_days ?? '—'}d history
                    </span>
                  )}
                </button>
                {candidateTableOpen && learnSnapshots.map((snap: any) => (
                  <div key={snap.threshold_id} style={{
                    marginTop: 8, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8,
                  }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>
                      {THRESHOLD_SHORT_LABEL[snap.threshold_id] ?? snap.threshold_id}
                      {snap.current_score != null && (
                        <span style={{ marginLeft: 8, fontFamily: 'monospace', color: 'var(--text3)', fontWeight: 400 }}>
                          current score {Number(snap.current_score).toFixed(4)}
                        </span>
                      )}
                      <span style={{ marginLeft: 8 }}><HoldoutBadge holdout={snap.holdout_validation} /></span>
                    </div>
                    <CandidateTable rows={snap.candidate_table ?? []} tid={snap.threshold_id} />
                  </div>
                ))}
              </div>
            )}

            {(evalSummary.count > 0 || recentEvaluations.length > 0) && (
              <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Threshold evaluations</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
                  {evalSummary.count ?? recentEvaluations.length} recorded
                  {evalSummary.by_recommendation && ` · keep ${evalSummary.by_recommendation.keep ?? 0} · monitor ${evalSummary.by_recommendation.monitor ?? 0} · revert ${evalSummary.by_recommendation.revert ?? 0}`}
                </div>
                {recentEvaluations.slice(-2).reverse().map((e: any) => (
                  <div key={e.id} style={{ fontSize: 10, color: 'var(--text2)', padding: '4px 0', borderTop: '1px solid var(--border)' }}>
                    <span style={{ fontWeight: 600, color: e.verdict === 'helped' ? '#22c55e' : e.verdict === 'hurt' ? '#ef4444' : '#f59e0b' }}>{e.verdict}</span>
                    {' · '}{e.threshold_id} · rec <b>{e.recommendation}</b> · impact {e.impact_score != null ? Number(e.impact_score).toFixed(3) : '—'}
                  </div>
                ))}
              </div>
            )}

            {thresholdAudit.length > 0 && (
              <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase' }}>
                  Recent threshold audit
                </div>
                {thresholdAudit.slice(0, 5).map((a: any, i: number) => {
                  const action = a.action ?? '—'
                  const actionColor = action.includes('approved') ? '#22c55e'
                    : action === 'rejected' ? '#ef4444'
                    : action === 'proposed' ? '#f59e0b' : 'var(--text3)'
                  return (
                    <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '5px 0', borderTop: i ? '1px solid var(--border)' : undefined }}>
                      <span style={{ fontWeight: 700, color: actionColor }}>{action}</span>
                      {' · '}{a.threshold_id ?? a.proposal?.threshold_id ?? '—'}
                      {a.from != null && a.to != null && (
                        <span style={{ fontFamily: 'monospace', marginLeft: 6 }}>{a.from}→{a.to}</span>
                      )}
                      <span style={{ color: 'var(--text3)', marginLeft: 6 }}>{String(a.at ?? '').slice(0, 19)}</span>
                    </div>
                  )
                })}
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
                  Full log: data/runtime/hermes_threshold_audit.jsonl
                </div>
              </div>
            )}

            <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase' }}>
                Review in CLI
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                <CliCommandButton label="--status" command={cliCommands.status} />
                <CliCommandButton label="--learn" command={cliCommands.learn} />
                <CliCommandButton label="--learn --apply" command={cliCommands.learn_apply} />
                {pendingThresholds.length > 0 && (
                  <CliCommandButton label="--approve" command={cliCommands.approve} />
                )}
                <CliCommandButton label="--evaluate" command={cliCommands.evaluate} />
              </div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                {cliCommands.learn_apply}
              </div>
            </div>

            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
              config/hermes_thresholds.yaml · runtime: data/runtime/hermes_thresholds.json
            </div>
          </>
        )}
      </div>

      {/* Governor bus reactions */}
      {(busReactions.length > 0 || reactionReviewMode) && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>
              Scope Governor reactions
            </div>
            {reactionReviewMode && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: 'rgba(245,158,11,.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,.35)' }}>
                REVIEW MODE
              </span>
            )}
          </div>
          {busReactions.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>No reactions triggered this cycle.</div>
          ) : (
            busReactions.map((rx: any, i: number) => (
              <div key={`${rx.id}-${i}`} style={{
                fontSize: 11, padding: '10px 12px', marginBottom: 6, background: 'var(--bg2)', borderRadius: 8,
                borderLeft: `3px solid ${reactionReviewMode ? '#f59e0b' : '#a855f7'}`,
              }}>
                <div style={{ fontWeight: 700, color: 'var(--text0)', fontSize: 12 }}>{rx.id ?? 'reaction'}</div>
                <div style={{ marginTop: 4, color: 'var(--text2)', lineHeight: 1.4 }}>{rx.reason}</div>
                {rx.metrics && (
                  <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
                    {Object.entries(rx.metrics).slice(0, 6).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
                  </div>
                )}
              </div>
            ))
          )}
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
            Tunable via config/hermes_reactions.yaml · dry-run: <code>--reaction-review</code>
          </div>
        </div>
      )}

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {[
          { label: 'Symbols in bus', value: num(Object.keys(bySymbol).length), sub: 'price-graded only', color: '#60a5fa' },
          { label: 'Governor feedback', value: num(feedback.length), sub: 'nightly actions', color: feedback.length > 15 ? '#ef4444' : '#22c55e' },
          { label: 'Hit rate (promotions)', value: pct(global.hit_rate_promotions), sub: 'price-graded', color: '#a855f7' },
          { label: 'Resource efficiency', value: pct(efficiencyScore), sub: `${trend7d} · ${calcVersion}`, color: efficiencyScore != null && efficiencyScore >= 0.6 ? '#22c55e' : '#f59e0b' },
        ].map(c => (
          <div key={c.label} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px', textAlign: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: c.color }}>{c.value}</div>
            <div style={{ fontSize: 11, color: 'var(--text0)', marginTop: 4 }}>{c.label}</div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Trend charts */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Outcome yield trends</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {([7, 30] as const).map(d => (
              <button key={d} onClick={() => setTrendDays(d)} style={{
                padding: '3px 10px', fontSize: 10, borderRadius: 5, border: 'none', cursor: 'pointer',
                background: trendDays === d ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
                color: trendDays === d ? '#60a5fa' : 'var(--text3)', fontWeight: trendDays === d ? 700 : 400,
              }}>{d}d</button>
            ))}
          </div>
        </div>

        {histLoading && outcomeSeries.length === 0 ? (
          <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>Loading trend history…</div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 8, marginBottom: 14 }}>
              {[
                { label: 'Promotions (now)', value: pct(outcomeSummary.current_hit_rate_promotions), color: hitRateColor(outcomeSummary.current_hit_rate_promotions) },
                { label: 'Δ window', value: deltaStr(outcomeSummary.delta_hit_rate_promotions) ?? '—', color: (outcomeSummary.delta_hit_rate_promotions ?? 0) >= 0 ? '#22c55e' : '#ef4444' },
                { label: 'Symbols in bus', value: num(outcomeSummary.current_symbols_in_bus), color: '#60a5fa' },
                { label: 'Efficiency score', value: pct(outcomeSummary.current_resource_efficiency_score), color: (outcomeSummary.current_resource_efficiency_score ?? 0) >= 0.6 ? '#22c55e' : '#f59e0b' },
                { label: 'Runs', value: num(histData?.outcome?.count), color: 'var(--text0)' },
              ].map(s => (
                <div key={s.label} style={{ padding: '8px 10px', background: 'var(--bg2)', borderRadius: 8, textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 800, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Hit rates ({trendDays}d)</div>
                <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px 4px' }}>
                  <MiniLineChart series={outcomeSeries} metrics={OUTCOME_METRICS} />
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
                  {OUTCOME_METRICS.map(m => (
                    <span key={m.key} style={{ fontSize: 9, color: m.color }}>● {m.label}</span>
                  ))}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>One point per UTC day · latest nightly bus run</div>
              </div>

              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Promotion hit rate bars</div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100, padding: '8px 10px 4px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  {outcomeSeries.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No history yet.</div>}
                  {outcomeSeries.map((s, i) => {
                    const v = Number(s.hit_rate_promotions) || 0
                    return (
                      <div key={i}
                        title={`${fmtDay(String(s.day))} · ${pct(v)}\nSymbols ${s.symbols_in_bus} · feedback ${s.governor_feedback_count}`}
                        onClick={() => setExpandedTrend(expandedTrend === i ? null : i)}
                        style={{
                          flex: 1, minWidth: 4, height: `${Math.round((v / promoMax) * 100)}%`,
                          background: hitRateColor(v), borderRadius: '2px 2px 0 0', alignSelf: 'flex-end', cursor: 'pointer',
                          outline: expandedTrend === i ? '2px solid #60a5fa' : 'none',
                        }} />
                    )
                  })}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Green ≥40% · amber ≥30% · click bar for day context</div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Resource efficiency ({trendDays}d)</div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100, padding: '8px 10px 4px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  {outcomeSeries.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>Insufficient data</div>}
                  {outcomeSeries.map((s, i) => {
                    const v = Number(s.resource_efficiency_score) || 0
                    return (
                      <div key={i} title={`${fmtDay(String(s.day))} · efficiency ${pct(v)}`}
                        style={{
                          flex: 1, minWidth: 4, height: `${Math.round((v / effTrendMax) * 100)}%`,
                          background: v >= 0.6 ? '#22c55e' : v >= 0.45 ? '#f59e0b' : '#ef4444',
                          borderRadius: '2px 2px 0 0', alignSelf: 'flex-end',
                        }} />
                    )
                  })}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
                  Δ window {deltaStr(outcomeSummary.delta_resource_efficiency_score) ?? '—'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Stop quality trend ({trendDays}d)</div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100, padding: '8px 10px 4px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  {outcomeSeries.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>Insufficient data</div>}
                  {outcomeSeries.map((s, i) => {
                    const v = Number(s.trail_activation_rate) || 0
                    return (
                      <div key={i} title={`${fmtDay(String(s.day))} · trail ${pct(v)} · aligned ${pct(Number(s.aligned_pct))}`}
                        style={{
                          flex: 1, minWidth: 4, height: `${Math.round((v / trailTrendMax) * 100)}%`,
                          background: '#a855f7', borderRadius: '2px 2px 0 0', alignSelf: 'flex-end',
                        }} />
                    )
                  })}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Trail activation rate · nightly bus snapshot</div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Scope & throughput</div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100, padding: '8px 10px 4px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  {outcomeSeries.map((s, i) => (
                    <div key={i} title={`${fmtDay(String(s.day))}\nSymbols ${s.symbols_in_bus} · research rows ${s.throughput_research_rows_7d}`}
                      style={{ flex: 1, minWidth: 4, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', alignSelf: 'flex-end', height: '100%', gap: 1 }}>
                      <div style={{ height: `${Math.round((Number(s.symbols_in_bus) / scopeMax) * 55)}%`, background: '#60a5fa', borderRadius: '2px 2px 0 0', minHeight: 2 }} />
                      <div style={{ height: `${Math.round(Math.min(45, (Number(s.governor_feedback_count) / 20) * 45))}%`, background: '#f59e0b', borderRadius: '2px 2px 0 0', minHeight: 1 }} />
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Blue = symbols in bus · amber = governor feedback count</div>
              </div>

              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Tier distribution ({trendDays}d)</div>
                <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  <StackedTierBars series={tierSeries} />
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
                  <span style={{ fontSize: 9, color: '#ef4444' }}>■ Hot</span>
                  <span style={{ fontSize: 9, color: '#f59e0b' }}>■ Warm</span>
                  <span style={{ fontSize: 9, color: '#60a5fa' }}>■ Cold</span>
                </div>
              </div>
            </div>

            {expandedTrend != null && outcomeSeries[expandedTrend] && (
              <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8, fontSize: 11, color: 'var(--text2)' }}>
                <b style={{ color: 'var(--text0)' }}>{fmtDay(String(outcomeSeries[expandedTrend].day))}</b>
                {' · '}promotions {pct(Number(outcomeSeries[expandedTrend].hit_rate_promotions))}
                {' · '}research {pct(Number(outcomeSeries[expandedTrend].hit_rate_research_actioned))}
                {' · '}symbols {num(Number(outcomeSeries[expandedTrend].symbols_in_bus))}
                {' · '}feedback {num(Number(outcomeSeries[expandedTrend].governor_feedback_count))}
                {' · '}research rows {num(Number(outcomeSeries[expandedTrend].throughput_research_rows_7d))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Split hit rates + tier distribution */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Outcome yield (split)</div>
          {[
            ['Promotions / external recs', global.hit_rate_promotions],
            ['Research actioned', global.hit_rate_research_actioned],
            ['Closed trades', global.hit_rate_trades],
            ['Avg R (trades 90d)', global.avg_realized_r_trades_90d != null ? String(global.avg_realized_r_trades_90d) : '—'],
          ].map(([k, v]) => (
            <div key={String(k)} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 4px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <span style={{ color: 'var(--text2)' }}>{k}</span>
              <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{typeof v === 'number' && v <= 1 ? pct(v) : v}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/outcome-bus</div>
        </div>

        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Tier distribution (governor)</div>
          {govLoading && !heat.hot ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading…</div> : (
            <>
              {[
                { label: 'Hot (S0+S1)', n: heat.hot, color: '#ef4444', pct: heat.hot / Math.max(gov.live_universe ?? 1, 1) },
                { label: 'Warm (S2)', n: heat.warm, color: '#f59e0b', pct: heat.warm / Math.max(gov.live_universe ?? 1, 1) },
                { label: 'Cold (S3)', n: heat.cold, color: '#60a5fa', pct: (heat.cold ?? 0) / Math.max((heat.hot ?? 0) + (heat.warm ?? 0) + (heat.cold ?? 0), 1) },
              ].map(t => (
                <div key={t.label} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span style={{ color: 'var(--text2)' }}>{t.label}</span>
                    <span style={{ fontWeight: 700, color: t.color }}>{t.n ?? '—'}</span>
                  </div>
                  <div style={{ height: 8, background: 'var(--bg2)', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${Math.min(100, (t.pct ?? 0) * 100)}%`, background: t.color }} />
                  </div>
                </div>
              ))}
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
                Live universe: {gov.live_universe ?? '—'} / cap {govData?.config_total_cap ?? 800}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Resource efficiency */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Resource efficiency</div>
        {efficiencyScore == null && resource.notes === 'no_log_yet' ? (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Insufficient data — score populates after nightly bus run + Hermes API traffic.</div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
              <div style={{ fontSize: 32, fontWeight: 800, color: (efficiencyScore ?? 0) >= 0.6 ? '#22c55e' : '#f59e0b' }}>
                {efficiencyScore != null ? `${(efficiencyScore * 100).toFixed(0)}%` : '—'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>
                {trend7d} · {num(scoreComponents.research_rows_per_positive_outcome ?? resource.research_rows_per_positive_outcome)} rows/outcome · {calcVersion}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8, marginBottom: 12 }}>
              {[
                { label: 'Hit rate (promotions)', value: pct(Number(scoreComponents.hit_rate_promotions)), color: '#a855f7' },
                { label: 'API overhead factor', value: num(scoreComponents.api_overhead_factor), color: '#60a5fa' },
                { label: 'Universe stability', value: pct(Number(scoreComponents.universe_stability)), color: 'var(--text3)' },
                { label: 'Positive outcomes (7d)', value: num(resource.positive_outcomes_7d), color: '#60a5fa' },
                { label: 'Research rows / outcome', value: num(scoreComponents.research_rows_per_positive_outcome ?? resource.research_rows_per_positive_outcome), color: 'var(--text0)' },
                { label: 'LLM calls / outcome', value: num(resource.llm_calls_per_positive_outcome), color: 'var(--text0)' },
                { label: 'Hermes API calls (7d)', value: num(resource.hermes_api_calls_7d), color: 'var(--text0)' },
                { label: 'Live universe / baseline', value: pct(resource.live_universe_vs_baseline_pct), color: '#a855f7' },
              ].map(c => (
                <div key={c.label} style={{ padding: '8px 10px', background: 'var(--bg2)', borderRadius: 8, textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 800, color: c.color }}>{c.value}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{c.label}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Score components</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6 }}>
              {Object.entries(scoreComponents).map(([k, v]) => (
                <div key={k} style={{ padding: '6px 8px', background: 'var(--bg2)', borderRadius: 6, fontSize: 10 }}>
                  <div style={{ color: 'var(--text3)', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</div>
                  <div style={{ fontWeight: 700, color: (Number(v) ?? 0) >= 0.6 ? '#22c55e' : 'var(--text0)' }}>{pct(Number(v))}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div>Write reduction: <b>{pct(resource.write_reduction_vs_baseline_pct)}</b> · Score writes (7d): <b>{num(resource.score_history_writes_7d)}</b></div>
              <div>Research rows (7d): <b>{num(resource.research_rows_7d)}</b> · LLM calls (7d): <b>{num(resource.external_llm_calls_7d)}</b></div>
            </div>
          </>
        )}
      </div>

      {/* Stop quality */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Stop quality</div>
        {(stopQ.sample_n ?? 0) < 5 || stopQ.notes === 'insufficient_sample' ? (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Insufficient data — need ≥5 closed trades in protection_advisory_outcomes (sample n={stopQ.sample_n ?? 0}).</div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8, marginBottom: 12 }}>
              {[
                { label: 'Aligned', value: pct(stopQ.aligned_pct), color: '#22c55e' },
                { label: 'Trail activation', value: pct(stopQ.trail_activation_rate), color: '#a855f7' },
                { label: 'R left on table', value: stopQ.r_left_on_table_avg ?? '—', color: 'var(--text0)' },
                { label: 'MAE exceeded stop', value: pct(stopQ.mae_exceeded_planned_stop_pct), color: '#f59e0b' },
                { label: 'Sample n', value: num(stopQ.sample_n), color: 'var(--text3)' },
              ].map(c => (
                <div key={c.label} style={{ padding: '8px 10px', background: 'var(--bg2)', borderRadius: 8, textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 800, color: c.color }}>{c.value}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{c.label}</div>
                </div>
              ))}
            </div>

            {Object.keys(stopByTier).length > 0 && (
              <>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>By tier (current scope)</div>
                <div style={{ display: 'grid', gridTemplateColumns: '0.8fr repeat(4, 1fr)', fontSize: 8, color: 'var(--text3)', padding: '4px 6px', textTransform: 'uppercase' }}>
                  <span>Tier</span><span>Trail</span><span>Aligned</span><span>MAE exceeded</span><span>n</span>
                </div>
                {(['hot', 'warm', 'cold'] as const).map(tier => {
                  const t = stopByTier[tier] ?? {}
                  const tierColor = tier === 'hot' ? '#ef4444' : tier === 'warm' ? '#f59e0b' : '#60a5fa'
                  if ((t.sample_n ?? 0) === 0) {
                    return (
                      <div key={tier} style={{ display: 'grid', gridTemplateColumns: '0.8fr repeat(4, 1fr)', padding: '6px', borderBottom: '1px solid var(--border)', fontSize: 11, color: 'var(--text3)' }}>
                        <span style={{ fontWeight: 700, color: tierColor, textTransform: 'capitalize' }}>{tier}</span>
                        <span style={{ gridColumn: 'span 4' }}>Insufficient data</span>
                      </div>
                    )
                  }
                  return (
                    <div key={tier} style={{ display: 'grid', gridTemplateColumns: '0.8fr repeat(4, 1fr)', padding: '6px', borderBottom: '1px solid var(--border)', fontSize: 11, alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, color: tierColor, textTransform: 'capitalize' }}>{tier}</span>
                      <span>{pct(t.trail_activation_rate)}</span>
                      <span>{pct(t.aligned_pct)}</span>
                      <span>{pct(t.mae_exceeded_planned_stop_pct)}</span>
                      <span style={{ color: 'var(--text3)' }}>{t.sample_n}</span>
                    </div>
                  )
                })}
              </>
            )}

            {stopCorrelations.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Correlations</div>
                {stopCorrelations.map((c: any, i: number) => (
                  <div key={i} style={{ fontSize: 11, color: 'var(--text2)', padding: '6px 8px', background: 'var(--bg2)', borderRadius: 6, marginBottom: 4 }}>
                    {c.note ?? c.metric}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Tag multipliers */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Tag lift → research depth</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.6fr 0.6fr 0.6fr 0.5fr', fontSize: 8, color: 'var(--text3)', padding: '4px 6px', textTransform: 'uppercase' }}>
          <span>Tag</span><span>Lift</span><span>Precision</span><span>Multiplier</span><span>n</span>
        </div>
        {tagRows.map(([tag, meta]: [string, any]) => (
          <div key={tag} style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.6fr 0.6fr 0.6fr 0.5fr', padding: '6px', borderBottom: '1px solid var(--border)', fontSize: 11, alignItems: 'center' }}>
            <span style={{ fontFamily: 'monospace', color: meta.flagged ? '#ef4444' : 'var(--text0)' }}>{tag}</span>
            <span style={{ color: (meta.lift ?? 0) < 0 ? '#ef4444' : '#22c55e' }}>{meta.lift ?? '—'}</span>
            <span>{meta.precision ?? '—'}</span>
            <span style={{ fontWeight: 700, color: (meta.quality_multiplier ?? 1) < 1 ? '#ef4444' : '#22c55e' }}>{meta.quality_multiplier ?? 1}</span>
            <span style={{ color: 'var(--text3)' }}>{meta.n}</span>
          </div>
        ))}
      </div>

      {/* Watchlist lifecycle */}
      <div style={{
        background: 'var(--bg1)',
        border: `1px solid ${lifecyclePendingCount > 0 ? 'rgba(245,158,11,.4)' : 'var(--border)'}`,
        borderRadius: 10,
        padding: 16,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Watchlist lifecycle</div>
            <div style={{ fontSize: 10, color: lifecyclePendingCount > 0 ? '#f59e0b' : 'var(--text3)', marginTop: 4 }}>
              {lifecyclePendingCount > 0
                ? `${lifecyclePendingCount} pending tier transition${lifecyclePendingCount !== 1 ? 's' : ''}`
                : 'Outcome-driven stages parallel to scope tiers (S0–S3)'}
            </div>
          </div>
          {watchlistLifecycle?.review_mode && (
            <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: 'rgba(96,165,250,.12)', color: '#60a5fa', border: '1px solid rgba(96,165,250,.3)' }}>
              ADVISORY
            </span>
          )}
        </div>
        {Object.keys(lifecycleSummary).length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            {Object.entries(lifecycleSummary).map(([st, n]) => (
              <span key={st} style={{
                fontSize: 9, padding: '3px 8px', borderRadius: 4,
                color: LIFECYCLE_STAGE_COLOR[st] ?? 'var(--text3)',
                background: 'var(--bg2)', border: '1px solid var(--border)',
              }}>
                {st} {n}
              </span>
            ))}
          </div>
        )}
        {lifecyclePanelRows.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>
            No lifecycle snapshot yet — run <code style={{ fontSize: 10 }}>hermes_scope_governor.py --dry-run</code> or wait for the :07/:37 cron.
          </div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '0.65fr 0.75fr 0.45fr 0.45fr 0.55fr 1fr', fontSize: 8, color: 'var(--text3)', padding: '4px 6px', textTransform: 'uppercase' }}>
              <span>Symbol</span><span>Stage</span><span>Tier</span><span>Conviction</span><span>Gate</span><span>Reason / pending</span>
            </div>
            {lifecyclePanelRows.map((row: any) => {
              const st = row.lifecycle_stage ?? 'monitoring'
              const pending = row.pending_transition
              return (
                <div key={row.symbol} style={{
                  display: 'grid', gridTemplateColumns: '0.65fr 0.75fr 0.45fr 0.45fr 0.55fr 1fr',
                  padding: '6px', borderBottom: '1px solid var(--border)', fontSize: 11, alignItems: 'center',
                  borderLeft: pending ? '3px solid #f59e0b' : '3px solid transparent',
                }}>
                  <span style={{ fontWeight: 700, fontFamily: 'monospace' }}>{row.symbol}</span>
                  <span style={{ color: LIFECYCLE_STAGE_COLOR[st] ?? 'var(--text2)', fontWeight: 600, fontSize: 10 }}>
                    {row.lifecycle_label ?? st}
                  </span>
                  <span style={{ color: 'var(--text3)', fontFamily: 'monospace' }}>{row.scope_tier ?? '—'}</span>
                  <span style={{ fontWeight: 700, color: (row.conviction_score ?? 0) >= 65 ? '#22c55e' : (row.conviction_score ?? 0) < 40 ? '#ef4444' : '#f59e0b' }}>
                    {row.conviction_score != null ? Math.round(Number(row.conviction_score)) : '—'}
                  </span>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{row.outcome_gate ?? '—'}</span>
                  <span style={{ fontSize: 9, color: pending ? '#f59e0b' : 'var(--text3)' }}>
                    {pending
                      ? `${pending.from_tier}→${pending.to_tier} (${pending.action})`
                      : String(row.stage_reason ?? '').slice(0, 60)}
                  </span>
                </div>
              )
            })}
          </>
        )}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
          Config: config/hermes_watchlist_lifecycle.yaml · override: POST /api/v2/hermes/watchlist-lifecycle/override
        </div>
      </div>

      {/* Symbol table */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Symbols in outcome bus</div>
        <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 0.5fr 0.5fr 0.6fr 0.5fr 1fr', fontSize: 8, color: 'var(--text3)', padding: '4px 6px', textTransform: 'uppercase' }}>
          <span>Symbol</span><span>Gate</span><span>Tier</span><span>Lift</span><span>n</span><span>Governor action</span>
        </div>
        {symbolRows.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No price-graded symbols yet.</div> :
          symbolRows.slice(0, 40).map(({ sym, meta, fb, tier }) => (
            <div key={sym}
              onClick={() => onDrill({ title: sym, subtitle: meta.gate, endpoint: '/api/v2/hermes/outcome-bus?symbol=' + sym, rows: [meta, fb].filter(Boolean) })}
              style={{ display: 'grid', gridTemplateColumns: '0.7fr 0.5fr 0.5fr 0.6fr 0.5fr 1fr', padding: '6px', borderBottom: '1px solid var(--border)', fontSize: 11, cursor: 'pointer', alignItems: 'center' }}>
              <span style={{ fontWeight: 700, fontFamily: 'monospace' }}>{sym}</span>
              <span style={{ color: GATE_COLOR[meta.gate] ?? 'var(--text2)', fontSize: 10 }}>{meta.gate ?? '—'}</span>
              <span style={{ color: 'var(--text3)' }}>{tier?.scope_tier ?? '—'}</span>
              <span style={{ color: (meta.lift ?? 0) < 0 ? '#ef4444' : 'var(--text2)' }}>{meta.lift ?? '—'}</span>
              <span>{meta.n}</span>
              <span style={{ color: fb ? '#f59e0b' : 'var(--text3)', fontSize: 10 }}>{fb?.action ?? '—'}</span>
            </div>
          ))}
      </div>

      {/* Recent governor audit */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Recent governor decisions</div>
        {audit.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No recent audit rows.</div> :
          audit.slice(0, 10).map((a: any, i: number) => (
            <div key={i} style={{ padding: '6px 4px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{a.symbol}</span>
              <span style={{ marginLeft: 8, color: '#60a5fa' }}>{a.from_tier}→{a.to_tier}</span>
              <span style={{ marginLeft: 8, color: 'var(--text3)' }}>{a.action}</span>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{String(a.reason ?? '').slice(0, 120)}</div>
            </div>
          ))}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Sources: outcome-bus + scope-governor APIs</div>
      </div>
    </div>
  )
}