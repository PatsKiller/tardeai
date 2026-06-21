import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import SynthesizedReportCard from './SynthesizedReportCard'
import type { ReportCardItem } from './SynthesizedReportCard'

// Inference Layers — the Layer-4 higher-order reasoning surface, redesigned as a synthesized, filterable,
// actionable feed (shared SynthesizedReportCard + live multi-LLM ensemble verdicts). Read-only / advisory.
// Source: /api/v2/inference/{latest,regional,sizing}. Aegis safety theses surface as CRITICAL rails.

const REGIME_COLOR: Record<string, string> = {
  risk_on: '#22c55e', neutral: '#94a3b8', risk_off: '#f59e0b', high_vol: '#ef4444',
}
const TYPE_ICON: Record<string, string> = {
  regional_impact: '🌏', journal_pattern: '📓', nav_signal: '💰', opportunity: '🎯',
  risk: '⚠️', sizing: '📐', market_regime: '🌡️', data_gap: '🕳️', research_gap: '🔎', aegis_thesis: '🛡',
}
const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const pct = (v: any) => (v == null ? '—' : `${Math.round(Number(v) * 100)}%`)
const isTicker = (s?: string) => !!s && /^[A-Z]{1,5}$/.test(s)
const humanize = (s?: string) => String(s || '').replace(/_/g, ' ')

// Layer-4 severities (critical/high/medium/low) → the shared card's severity language.
const SEV_MAP: Record<string, string> = { critical: 'critical', high: 'warning', medium: 'info', low: 'info' }
const SEV_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 }

// inference_type → the real v3 route an operator should jump to (one-click action, no dead links).
const ACTION_FOR: Record<string, { label: string; url: string }[]> = {
  risk: [{ label: 'Open Risk', url: '/v3/risk' }],
  aegis_thesis: [{ label: 'Open Risk', url: '/v3/risk' }, { label: 'Hermes', url: '/v3/hermes' }],
  opportunity: [{ label: 'Open Watchlist', url: '/v3/watchlist' }, { label: 'Rotation', url: '/v3/rotation' }],
  nav_signal: [{ label: 'Portfolio', url: '/v3/portfolio' }],
  journal_pattern: [{ label: 'Journal', url: '/v3/journal' }],
  regional_impact: [{ label: 'Intelligence', url: '/v3/intelligence' }],
  research_gap: [{ label: 'Research', url: '/v3/intelligence' }],
  market_regime: [{ label: 'Portfolio', url: '/v3/portfolio' }],
}

function toCard(r: any): ReportCardItem {
  const sym = isTicker(r.subject) ? r.subject : undefined
  const actions = ACTION_FOR[r.inference_type] || [{ label: 'Intelligence', url: '/v3/intelligence' }]
  return {
    id: String(r.id),
    type: `${TYPE_ICON[r.inference_type] || '•'} ${humanize(r.inference_type)}`,
    channel: `${r.layer} · ${r.source_lane || 'local'}`,
    title: r.title,
    summary: r.body || '',
    severity: SEV_MAP[r.severity] || 'info',
    symbol: sym,
    symbols: sym ? [sym] : (r.subject && !isTicker(r.subject) ? [] : []),
    created_at: r.created_at,
    quality_score: r.confidence != null ? Number(r.confidence) : undefined,
    actions,
  }
}

type Facet = 'all' | 'critical' | 'risk' | 'opportunity' | 'nav' | 'regime'
const FACETS: { key: Facet; label: string }[] = [
  { key: 'all', label: 'All' }, { key: 'critical', label: 'Critical / Aegis' }, { key: 'risk', label: 'Risk' },
  { key: 'opportunity', label: 'Opportunity' }, { key: 'nav', label: 'NAV / Income' }, { key: 'regime', label: 'Regime / Regional' },
]
function facetMatch(f: Facet, r: any): boolean {
  switch (f) {
    case 'all': return true
    case 'critical': return r.severity === 'critical' || r.inference_type === 'aegis_thesis'
    case 'risk': return r.inference_type === 'risk' || r.inference_type === 'aegis_thesis'
    case 'opportunity': return r.inference_type === 'opportunity'
    case 'nav': return r.inference_type === 'nav_signal'
    case 'regime': return ['market_regime', 'regional_impact'].includes(r.inference_type)
    default: return true
  }
}

export default function InferenceLayersPanel() {
  const { data, stale, loading } = useApi<any>('/api/v2/inference/latest', 120_000)
  const { data: regional } = useApi<any>('/api/v2/inference/regional', 300_000)
  const { data: sizing } = useApi<any>('/api/v2/inference/sizing', 300_000)

  const run = data?.run
  const allResults: any[] = data?.results ?? []
  const regime = run?.regime ?? 'unknown'
  const regSignals: any[] = regional?.data ?? []
  const sizeRecs: any[] = sizing?.data ?? []

  const [facet, setFacet] = useState<Facet>('all')
  const [q, setQ] = useState('')

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return allResults
      .filter(r => facetMatch(facet, r))
      .filter(r => !needle || `${r.title} ${r.body} ${r.subject} ${r.inference_type}`.toLowerCase().includes(needle))
      .sort((a, b) => (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0) || Number(b.confidence) - Number(a.confidence))
  }, [allResults, facet, q])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const r of allResults) c[r.severity] = (c[r.severity] || 0) + 1
    return c
  }, [allResults])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Header / regime + severity tally */}
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>
            Inference Layers {stale && <span style={{ fontSize: 9, color: '#f59e0b' }}>· stale</span>}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>
            {run ? `run #${run.id} · ${run.trigger} · ${allResults.length} inferences` : 'no runs yet'}
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 7, flexWrap: 'wrap' }}>
            {(['critical', 'high', 'medium', 'low'] as const).map(s => counts[s] ? (
              <span key={s} style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
                background: (SEV_MAP[s] === 'critical' ? '#ef4444' : SEV_MAP[s] === 'warning' ? '#f59e0b' : '#60a5fa') + '1c',
                color: SEV_MAP[s] === 'critical' ? '#ef4444' : SEV_MAP[s] === 'warning' ? '#f59e0b' : '#60a5fa' }}>{counts[s]} {s}</span>
            ) : null)}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .4 }}>Market regime</div>
          <div style={{ fontSize: 20, fontWeight: 900, color: REGIME_COLOR[regime] ?? 'var(--text1)' }}>{String(regime).replace('_', ' ')}</div>
          {run?.summary && <div style={{ fontSize: 10, color: 'var(--text3)', maxWidth: 320, marginTop: 2 }}>{String(run.summary).slice(0, 120)}</div>}
        </div>
      </div>

      {/* Unified search + facet filters */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search inferences — ticker, theme, type…"
          style={{ flex: '1 1 240px', minWidth: 180, fontSize: 12, padding: '7px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 7, color: 'var(--text0)' }} />
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {FACETS.map(f => {
            const on = facet === f.key
            return <button key={f.key} onClick={() => setFacet(f.key)} style={{ fontSize: 11, fontWeight: on ? 800 : 600, padding: '6px 11px', borderRadius: 7, cursor: 'pointer',
              border: `1px solid ${on ? '#a855f7' : 'var(--border)'}`, background: on ? 'rgba(168,85,247,.12)' : 'var(--bg1)', color: on ? '#d8b4fe' : 'var(--text2)' }}>{f.label}</button>
          })}
        </div>
      </div>

      {/* Inference feed — shared card + live ensemble verdict (high/critical get the panel auto) */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {results.length === 0 && (
          <div style={{ ...card, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
            {loading && allResults.length === 0 ? 'loading inferences…' : allResults.length === 0 ? 'No inferences in the latest cycle.' : 'No inferences match this filter.'}
          </div>
        )}
        {results.map((r) => {
          const heavy = r.severity === 'high' || r.severity === 'critical'
          return (
            <SynthesizedReportCard
              key={r.id}
              item={toCard(r)}
              footer={heavy && r.id ? (
                <EnsembleValidationInline targetType="inference" targetId={r.id} subject={r.subject} content={`${r.title}\n${r.body ?? ''}`} />
              ) : undefined}
            />
          )
        })}
      </div>

      {/* Cross-regional signals */}
      {regSignals.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>🌏 Cross-Regional Signals</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {regSignals.slice(0, 8).map((s, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text2)', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ fontWeight: 800, color: 'var(--text0)' }}>{s.region}</span>
                <span style={{ color: 'var(--text3)' }}> · {s.theme} · </span>
                <span style={{ color: s.direction === 'bearish' ? '#ef4444' : s.direction === 'bullish' ? '#22c55e' : '#94a3b8' }}>{s.direction}</span>
                <span style={{ color: 'var(--text3)' }}> · {pct(s.confidence)}</span>
                {s.us_impact && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{String(s.us_impact).slice(0, 200)}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risk-adjusted sizing (advisory) */}
      {sizeRecs.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>📐 Risk-Adjusted Sizing <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)' }}>· advisory, re-validated through risk_gate</span></div>
          <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                <th style={{ padding: 4 }}>Symbol</th><th>Strategy</th><th>Base</th><th>Rec</th><th>Tilt</th><th>Gate</th>
              </tr>
            </thead>
            <tbody>
              {sizeRecs.slice(0, 12).map((s, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--border)', color: 'var(--text1)' }}>
                  <td style={{ padding: 4, fontWeight: 700 }}>{s.symbol}</td>
                  <td style={{ color: 'var(--text3)' }}>{s.strategy_id}</td>
                  <td>{s.base_shares}</td>
                  <td style={{ fontWeight: 700, color: s.recommended_shares === 0 ? '#ef4444' : 'var(--text0)' }}>{s.recommended_shares}</td>
                  <td>{Number(s.tilt).toFixed(2)}</td>
                  <td style={{ color: s.risk_gate_result === 'APPROVED' ? '#22c55e' : '#f59e0b' }}>{s.risk_gate_result ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
