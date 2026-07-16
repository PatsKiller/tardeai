/**
 * Research Intelligence v2.7 — stage trades, cross-theme, concentration banner.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

interface Props { onDrill: (ctx: DrillContext) => void }

type Cat = {
  id: string
  label: string
  color?: string
  description?: string
  priority?: number
  pillar?: boolean
}

type NextAction = { label?: string; detail?: string; href_hint?: string }

type Item = {
  id: string
  title: string
  summary?: string
  thesis?: string | null
  lede?: string
  executive_summary?: string[]
  key_takeaways?: string[]
  bull_case?: string | null
  bear_case?: string | null
  why_it_matters?: string
  next_action?: NextAction
  next_action_label?: string
  next_action_detail?: string
  narrative_source?: string
  reading_minutes?: number
  symbol?: string | null
  categories?: string[]
  primary_category?: string
  priority?: string
  confidence?: number | null
  freshness_hours?: number | null
  freshness_tier?: string
  freshness_label?: string
  needs_refresh?: boolean
  is_archived?: boolean
  created_at?: string
  source_system?: string
  research_type?: string
  is_holdings?: boolean
  sources?: { title?: string; url?: string; source?: string }[]
  source_count?: number
  actionability?: string
  model?: string
  sentiment?: string
  key_questions?: string[]
  data_gaps?: string[]
  starred?: boolean
  vote?: number | null
  hidden?: boolean
  feedback_updated_at?: string | null
  quality_flags?: string[]
  counter_view?: string | null
  operator_note?: string | null
  status?: string
  investment_implications?: string
  hermes_score?: { composite?: number; rank?: number | null; scope_tier?: string | null }
  score_divergence?: { ri_tier?: string; hermes_composite?: number }
  external_intel?: { lane?: string; recommendation?: string; confidence?: number | null; dissent?: string | null; created_at?: string }[]
  watch_directive?: { id?: number; label?: string }
  ticker_recommendations?: {
    symbol?: string
    role?: string
    scope?: string
    hermes?: { composite?: number; rank?: number | null; scope_tier?: string | null }
    score_divergence?: { ri_tier?: string; hermes_composite?: number }
    watch_directive?: boolean
    suggested_weight_pct?: string | null
    rationale?: string
    conviction_tier?: string
    conviction_score?: number
    conviction_breakdown?: Record<string, number>
    conviction_breakdown_lines?: string[]
    why_selected?: string
    data_complete?: boolean
    incomplete_reason?: string
    company?: string | null
    sector?: string | null
    industry?: string | null
    what_they_do?: string | null
    analyst_prediction?: string | null
    news_sentiment?: string | null
    news_headlines?: {
      title?: string
      source?: string
      hours_old?: number
      sentiment?: string
      summary?: string | null
      url?: string
    }[]
    identity?: {
      symbol?: string
      company?: string | null
      sector?: string | null
      industry?: string | null
      what_they_do?: string | null
      is_etf?: boolean
    }
    technical_snapshot?: Record<string, unknown>
    analyst_snapshot?: {
      consensus?: string | null
      prediction?: string | null
      counts?: { buy?: number; hold?: number; sell?: number; n?: number }
      pe?: number | null
      peg?: number | null
      eps_next_y?: number | null
      earnings_momentum?: string
      valuation?: string
      coverage_flag?: string
      as_of?: string | null
      provider?: string | null
      target?: number | null
    }
    news_snapshot?: {
      sentiment?: string
      headlines?: {
        title?: string
        source?: string
        hours_old?: number
        sentiment?: string
        summary?: string | null
      }[]
      count?: number
      note?: string | null
    }
    options_flow_snapshot?: Record<string, unknown>
    actions?: { id?: string; label?: string; href?: string }[]
    security?: {
      company?: string | null
      sector?: string | null
      industry?: string | null
      what_they_do?: string | null
      rsi?: number | null
      rsi_status?: string
      rel_strength_month_pct?: number | null
      rel_strength_vs_spy_month_pct?: number | null
      rel_strength_vs_qqq_month_pct?: number | null
      sma50_pct?: number | null
      sma200_pct?: number | null
      pe?: number | null
      peg?: number | null
      valuation?: string
      earnings_momentum?: string
      beta?: number | null
      liquidity?: string
      analyst_rating?: string
      analyst_counts?: { buy?: number; hold?: number; sell?: number; n?: number }
      analyst_prediction?: string | null
      news_sentiment?: string | null
      news_headlines?: {
        title?: string
        source?: string
        hours_old?: number
        sentiment?: string
        summary?: string | null
      }[]
      news_count?: number
      iv_rank?: number | null
      options_sentiment?: string
      data_complete?: boolean
    }
  }[]
  sizing_guidance?: string
  sizing_reason?: string | null
  risk_caveat?: string
  quality_tier?: 'A' | 'B' | 'C' | string
  actions?: { id?: string; label?: string; href?: string; primary?: boolean; symbol?: string; role?: string; side?: string }[]
  quality_gate?: { pass?: boolean; note?: string | null; incomplete_tickers?: number; stage_eligible?: boolean }
  related_themes?: {
    items?: { id?: string; label?: string; strength?: string; reason?: string }[]
    impact_note?: string | null
    impact_notes?: string[]
  }
  stage_payload?: Record<string, unknown> | null
  funding_context?: { require_funding_trim?: boolean; funding_symbol?: string; schg_pct?: number }
  portfolio_snapshot?: {
    total_mv?: number
    related_weights?: Record<string, number>
    flags?: string[]
    sleeves?: Record<string, number>
    concentration?: {
      book_level?: string
      score?: number
      top3_pct?: number
      names?: { symbol?: string; weight_pct?: number; level?: string }[]
    }
    heat?: {
      portfolio_heat_pct?: number
      level?: string
      pct_protected?: number
    }
    theme_capacity?: Record<string, {
      current_pct?: number
      target_max_pct?: number
      room_pct?: number
      level?: string
    }>
  }
}

/* Institutional desk palette — muted steel/ink, no Christmas-tree neons */
const C = {
  ink: '#e6eaf0',
  muted: '#9aa3b2',
  soft: '#6b7385',
  dim: '#4e5668',
  card: 'rgba(16, 20, 30, 0.96)',
  cardHover: 'rgba(22, 27, 40, 0.98)',
  line: 'rgba(148, 163, 184, 0.12)',
  lineStrong: 'rgba(148, 163, 184, 0.20)',
  accent: '#8ba3c7',
  accentSoft: 'rgba(139, 163, 199, 0.10)',
  // Category accents: desaturated, same family
  retire: '#a8a3c4',
  retireSoft: 'rgba(168, 163, 196, 0.10)',
  income: '#8fad9a',
  incomeSoft: 'rgba(143, 173, 154, 0.10)',
  macro: '#b0a890',
  macroSoft: 'rgba(176, 168, 144, 0.10)',
  // Status — readable, not neon
  live: '#8fad9a',
  fresh: '#8ba3c7',
  aging: '#b0a890',
  stale: '#b89191',
  archive: '#7a8294',
  bull: '#8fad9a',
  bear: '#b89191',
  star: '#c4b896',
  cta: '#a8b8cc',
  ctaBg: 'rgba(139, 163, 199, 0.08)',
  positive: '#8fad9a',
  negative: '#b89191',
  caution: '#b0a890',
}

const TIER: Record<string, { color: string; label: string }> = {
  live: { color: C.live, label: 'Live' },
  fresh: { color: C.fresh, label: 'Fresh' },
  aging: { color: C.aging, label: 'Aging' },
  stale: { color: C.stale, label: 'Stale' },
  archive: { color: C.archive, label: 'Archive' },
}

const CAT_TINT: Record<string, string> = {
  retirement_tax: C.retire,
  dividend_income: C.income,
  macro_geo: C.macro,
  sector_thematic: C.accent,
  compounding_wealth: C.income,
  risk_regime: C.stale,
  catalyst_event: C.macro,
  company_ticker: C.muted,
  academic_pro: C.retire,
}

function confPct(c?: number | null) {
  if (c == null || !Number.isFinite(Number(c))) return null
  const n = Number(c)
  return Math.round(n * (n <= 1 ? 100 : 1))
}

async function postFeedback(body: Record<string, unknown>) {
  const r = await fetch('/api/v2/research-intelligence/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

function SoftChip({ label, color, active, onClick }: {
  label: string; color?: string; active?: boolean; onClick?: () => void
}) {
  const c = color || C.accent
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        fontSize: 11, fontWeight: 650, letterSpacing: '0.01em',
        padding: '6px 12px', borderRadius: 999, cursor: onClick ? 'pointer' : 'default',
        border: `1px solid ${active ? `${c}66` : C.line}`,
        background: active ? `${c}18` : 'rgba(255,255,255,0.02)',
        color: active ? c : C.muted,
        transition: 'background .15s, border-color .15s, color .15s',
      }}
    >
      {label}
    </button>
  )
}

function Tag({ children, color }: { children: ReactNode; color?: string }) {
  const c = color || C.muted
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
      color: c, background: `${c}14`, border: `1px solid ${c}33`,
      borderRadius: 6, padding: '3px 8px',
    }}>
      {children}
    </span>
  )
}

function FreshnessDot({ tier, label, asOf }: { tier?: string; label?: string; asOf?: string | null }) {
  const t = TIER[tier || 'aging'] || TIER.aging
  // v3.1 (C2): relative on screen, absolute ET on hover — every claim carries when it was true
  return (
    <span title={asOf ? `${fmtET(asOf)} ET` : undefined}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: C.muted, fontWeight: 550 }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: t.color, opacity: 0.85,
      }} />
      {label || t.label}
    </span>
  )
}

const ROLE_COLOR: Record<string, string> = {
  add_candidate: C.positive,
  trim_candidate: C.negative,
  hold_review: C.accent,
  protect: C.caution,
  watchlist: C.muted,
  plan: C.accent,
  context: C.soft,
}

const QUALITY: Record<string, { color: string; label: string; hint: string }> = {
  A: { color: C.positive, label: 'Tier A', hint: 'Deep + portfolio-aware' },
  B: { color: C.accent, label: 'Tier B', hint: 'Solid advisory floor' },
  C: { color: C.soft, label: 'Tier C', hint: 'Thin — verify sources' },
}

const CONC_COLOR: Record<string, string> = {
  extreme: C.negative,
  high: C.stale,
  caution: C.caution,
  elevated: C.aging,
  normal: C.positive,
  full: C.stale,
  moderate: C.aging,
  room: C.positive,
}

function sentColor(s?: string | null) {
  const v = (s || '').toLowerCase()
  if (v.includes('construct') || v.includes('bull') || v === 'positive') return C.positive
  if (v.includes('cautious') || v.includes('bear') || v === 'negative') return C.negative
  return C.muted
}

async function postStage(body: Record<string, unknown>) {
  const r = await fetch('/api/v2/research-intelligence/stage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

async function postStageUpdate(body: Record<string, unknown>) {
  const r = await fetch('/api/v2/research-intelligence/stage/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

async function postDirectiveCreate(symbol: string, rationale: string) {
  const r = await fetch('/api/v2/watch/directives', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind: 'ticker', label: symbol, spec: { symbol },
      rationale, created_by: 'operator_ri',
    }),
  })
  return r.json()
}

function ActionStrip({
  item, catColor, onStage, onThemeClick, staging,
}: {
  item: Item
  catColor: string
  onStage?: (payload: Record<string, unknown>) => Promise<void>
  onThemeClick?: (themeId: string) => void
  staging?: boolean
}) {
  const [dirState, setDirState] = useState<'idle' | 'busy' | 'done' | 'fail'>('idle')
  // v3 (B4): no CTA label when the desk has none — a fake default guides nothing
  const label = item.next_action_label || item.next_action?.label || null
  const detail = item.next_action_detail || item.next_action?.detail || ''
  // v3 (B3): rich security cards carry THIS BRIEF's tickers only; book-context
  // weights (SCHG trim etc.) live in the desk-level concentration banner
  const ticks = (item.ticker_recommendations || []).filter(t => t.scope !== 'book')
  const hasAdvisory = ticks.length > 0 || !!item.sizing_guidance || !!item.investment_implications
  const related = item.related_themes
  const stageOk = item.quality_gate?.stage_eligible !== false && item.stage_payload

  const runAction = async (a: { id?: string; href?: string; symbol?: string; role?: string; side?: string }, e: MouseEvent) => {
    e.stopPropagation()
    const id = a.id || ''
    if ((id === 'stage_trade' || id === 'ri_ideas' || id === 'propose_trim') && onStage) {
      const base = (item.stage_payload || {}) as Record<string, unknown>
      const payload: Record<string, unknown> = {
        ...base,
        source_item_id: item.id,
        source_title: item.title,
        primary_category: item.primary_category,
        allow_stage: true,
        data_complete: true,
      }
      if (id === 'propose_trim') {
        payload.symbol = a.symbol || item.funding_context?.funding_symbol || 'SCHG'
        payload.side = 'sell'
        payload.role = 'trim_candidate'
        payload.require_funding_trim = true
        payload.funding_symbol = payload.symbol
        payload.funding_source = `Trim ${payload.symbol}`
      }
      if (id === 'ri_ideas' && a.symbol) {
        payload.symbol = a.symbol
      }
      await onStage(payload)
      return
    }
    if (a.href) {
      window.location.href = a.href.startsWith('/') ? a.href : `/${a.href}`
    }
  }

  return (
    <div style={{
      marginTop: 2, padding: '14px 16px', borderRadius: 10,
      background: C.card,
      border: `1px solid ${C.lineStrong}`,
      display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.soft }}>
          Operator next step
        </div>
        {hasAdvisory && (
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.muted }}>
            Portfolio-aware
          </div>
        )}
      </div>
      {label && (
        <div style={{ fontSize: 15, fontWeight: 750, color: C.ink, letterSpacing: '-0.01em' }}>{label}</div>
      )}
      {label && detail && (
        <div style={{ fontSize: 12.5, color: C.muted, lineHeight: 1.55 }}>{detail}</div>
      )}

      {/* Primary action bar — top of strip for hierarchy */}
      {((item.actions && item.actions.length > 0) || stageOk || !!item.symbol) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
          {/* C4: operator-clicked directive creation — prefilled from this brief */}
          {item.symbol && !item.watch_directive && (
            <button
              type="button"
              disabled={dirState === 'busy' || dirState === 'done'}
              onClick={async e => {
                e.stopPropagation()
                setDirState('busy')
                try {
                  const r = await postDirectiveCreate(
                    String(item.symbol).toUpperCase(),
                    `RI brief: ${item.title || ''} — ${(item.lede || item.summary || '').slice(0, 200)}`,
                  )
                  setDirState(r?.ok ? 'done' : 'fail')
                } catch { setDirState('fail') }
              }}
              style={{
                fontSize: 11, fontWeight: 700, padding: '7px 11px', borderRadius: 8, cursor: 'pointer',
                border: '1px solid #f59e0b55', background: 'rgba(245,158,11,0.08)', color: '#f59e0b',
              }}
            >
              {dirState === 'done' ? '✓ Directive created' : dirState === 'busy' ? 'Creating…'
                : dirState === 'fail' ? 'Directive failed — retry' : `Create Watch Directive · ${item.symbol}`}
            </button>
          )}
          {(item.actions || []).slice(0, 6).map((a, i) => {
            const primary = a.primary || a.id === 'stage_trade'
            const isStage = a.id === 'stage_trade' || a.id === 'ri_ideas' || a.id === 'propose_trim'
            if (a.id === 'stage_trade' && !stageOk) return null
            return (
              <button
                key={`${a.id}-${i}`}
                type="button"
                disabled={!!staging && isStage}
                onClick={e => runAction(a, e)}
                style={{
                  fontSize: primary ? 12.5 : 11, fontWeight: 700,
                  padding: primary ? '8px 14px' : '6px 10px',
                  borderRadius: 7, cursor: 'pointer',
                  border: `1px solid ${primary ? C.accent : C.lineStrong}`,
                  background: primary ? C.accentSoft : 'transparent',
                  color: primary ? C.ink : C.muted,
                }}
              >
                {staging && isStage ? 'Staging…' : a.label}
              </button>
            )
          })}
        </div>
      )}

      {item.sizing_guidance && (
        <div style={{
          fontSize: 13, color: C.ink, lineHeight: 1.5,
          padding: '10px 12px', borderRadius: 8,
          background: C.accentSoft, border: `1px solid ${C.lineStrong}`,
        }}>
          <span style={{ fontWeight: 700, color: C.muted }}>Why this size · </span>
          {item.sizing_guidance}
        </div>
      )}
      {item.sizing_reason && !item.sizing_guidance?.includes(item.sizing_reason.slice(0, 40)) && (
        <div style={{ fontSize: 11.5, color: C.muted, lineHeight: 1.45 }}>
          <span style={{ fontWeight: 650, color: C.soft }}>Sizing factors · </span>
          {item.sizing_reason}
        </div>
      )}

      {item.investment_implications && (
        <div style={{
          fontSize: 12.5, color: C.ink, lineHeight: 1.55,
          padding: '8px 10px', borderRadius: 8,
          background: 'rgba(0,0,0,.18)', border: `1px solid ${C.line}`,
        }}>
          <span style={{ fontWeight: 700, color: C.muted }}>Investment implications · </span>
          {item.investment_implications}
        </div>
      )}
      {ticks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: C.soft }}>
            Tickers · company · news · analysts
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {ticks.slice(0, 6).map((t, i) => {
              const role = t.role || 'review'
              const rc = ROLE_COLOR[role] || C.accent
              const ct = t.conviction_tier
              const sec = t.security
              const company = t.company || t.identity?.company || sec?.company
              const sector = t.sector || t.identity?.sector || sec?.sector
              const industry = t.industry || t.identity?.industry || sec?.industry
              const what = t.what_they_do || t.identity?.what_they_do || sec?.what_they_do
              const headlines = (
                t.news_headlines
                || t.news_snapshot?.headlines
                || sec?.news_headlines
                || []
              ).slice(0, 3)
              const newsSent = t.news_sentiment || t.news_snapshot?.sentiment || sec?.news_sentiment
              const prediction = (
                t.analyst_prediction
                || t.analyst_snapshot?.prediction
                || sec?.analyst_prediction
                || null
              )
              const consensus = t.analyst_snapshot?.consensus || sec?.analyst_rating
              const counts = t.analyst_snapshot?.counts || sec?.analyst_counts
              return (
                <div key={`${t.symbol}-${i}`} style={{
                  border: `1px solid ${C.lineStrong}`,
                  background: 'rgba(0,0,0,.22)',
                  borderRadius: 10,
                  padding: '12px 14px',
                  borderLeft: `3px solid ${rc}`,
                }}>
                  {/* Header: symbol + company + role */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'baseline' }}>
                        <span style={{ fontFamily: 'var(--mono)', fontWeight: 800, fontSize: 15, color: C.ink, letterSpacing: '0.02em' }}>
                          {t.symbol}
                        </span>
                        {company && (
                          <span style={{ fontSize: 13.5, fontWeight: 650, color: C.ink }}>
                            {company}
                          </span>
                        )}
                        {t.hermes && (
                          <span title="Hermes composite score · rank · scope tier (read-only join)" style={{
                            fontFamily: 'var(--mono)', fontSize: 10.5, fontWeight: 800, color: C.accent,
                            border: `1px solid ${C.accent}44`, borderRadius: 6, padding: '1px 6px',
                          }}>
                            ★{t.hermes.rank != null ? `#${t.hermes.rank}` : ''} · {t.hermes.composite}
                            {t.hermes.scope_tier ? ` · ${String(t.hermes.scope_tier).toUpperCase()}` : ''}
                          </span>
                        )}
                        {t.score_divergence && (
                          <span title="RI conviction and Hermes composite disagree — both shown, neither blended" style={{
                            fontSize: 10, fontWeight: 800, color: C.stale,
                            border: `1px solid ${C.stale}55`, borderRadius: 6, padding: '1px 6px',
                          }}>
                            ⚠ divergence: RI {t.score_divergence.ri_tier} / Hermes {t.score_divergence.hermes_composite}
                          </span>
                        )}
                        {t.watch_directive && (
                          <span title="Active watch directive on this symbol" style={{
                            fontSize: 10, fontWeight: 800, color: '#f59e0b',
                            border: '1px solid #f59e0b55', borderRadius: 6, padding: '1px 6px',
                          }}>
                            Directive
                          </span>
                        )}
                      </div>
                      {(sector || industry) && (
                        <div style={{ fontSize: 11.5, color: C.muted, marginTop: 3, lineHeight: 1.4 }}>
                          {[sector, industry].filter(Boolean).join(' · ')}
                        </div>
                      )}
                      {what && (
                        <div style={{ fontSize: 12, color: C.soft, marginTop: 4, lineHeight: 1.45 }}>
                          {what}
                        </div>
                      )}
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        {(role || '').replace(/_/g, ' ')}
                      </div>
                      {ct && (
                        <div
                          style={{ fontSize: 11, fontWeight: 650, color: C.soft, marginTop: 3, cursor: 'help' }}
                          title={(t.conviction_breakdown_lines || []).join('\n') || 'Conviction score'}
                        >
                          Conv {ct}{t.conviction_score != null ? ` · ${Number(t.conviction_score).toFixed(0)}` : ''}
                        </div>
                      )}
                      {t.suggested_weight_pct && (
                        <div style={{ fontSize: 12, fontWeight: 700, color: C.ink, marginTop: 4 }}>
                          {t.suggested_weight_pct}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Analyst reviews / predictions */}
                  <div style={{
                    marginTop: 10, paddingTop: 9, borderTop: `1px solid ${C.line}`,
                    fontSize: 11.5, color: C.muted, lineHeight: 1.5,
                  }}>
                    <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.soft, marginBottom: 3 }}>
                      Analyst reviews
                    </div>
                    {consensus && (
                      <div style={{ color: C.ink, fontWeight: 650, marginBottom: 2 }}>
                        Consensus: {consensus}
                        {counts?.n != null && (
                          <span style={{ color: C.muted, fontWeight: 500 }}>
                            {' '}· {counts.buy ?? 0} buy / {counts.hold ?? 0} hold / {counts.sell ?? 0} sell (n={counts.n})
                          </span>
                        )}
                      </div>
                    )}
                    {prediction && (
                      <div style={{ color: C.muted }}>{prediction}</div>
                    )}
                    {!consensus && !prediction && (
                      <div style={{ color: C.soft }}>No Street consensus on file</div>
                    )}
                  </div>

                  {/* Latest news + sentiment */}
                  <div style={{
                    marginTop: 9, paddingTop: 9, borderTop: `1px solid ${C.line}`,
                    fontSize: 11.5, lineHeight: 1.45,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                      <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.soft }}>
                        Latest news
                      </div>
                      {newsSent && (
                        <div style={{ fontSize: 10.5, fontWeight: 650, color: sentColor(newsSent), textTransform: 'capitalize' }}>
                          Sentiment: {(newsSent || '').replace(/_/g, ' ')}
                        </div>
                      )}
                    </div>
                    {headlines.length > 0 ? (
                      <ul style={{ margin: 0, paddingLeft: 16, color: C.muted }}>
                        {headlines.map((h, hi) => (
                          <li key={hi} style={{ marginBottom: 3 }}>
                            <span style={{ color: C.ink }}>{h.title}</span>
                            {(h.source || h.hours_old != null) && (
                              <span style={{ color: C.soft, fontSize: 10.5 }}>
                                {' · '}{h.source || 'news'}
                                {h.hours_old != null ? ` · ${Number(h.hours_old).toFixed(0)}h` : ''}
                                {h.sentiment ? ` · ${h.sentiment}` : ''}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div style={{ color: C.soft, fontSize: 11.5 }}>
                        {t.news_snapshot?.note || 'No recent desk news for this ticker'}
                      </div>
                    )}
                  </div>

                  {/* Technicals row — compact, secondary */}
                  {(sec?.rsi != null || sec?.rel_strength_vs_spy_month_pct != null || sec?.sma50_pct != null) && (
                    <div style={{
                      marginTop: 9, paddingTop: 8, borderTop: `1px solid ${C.line}`,
                      fontSize: 11, color: C.soft, lineHeight: 1.45,
                    }}>
                      <span style={{ fontWeight: 650, color: C.muted }}>Technicals · </span>
                      {sec?.rsi != null && <span>RSI {Number(sec.rsi).toFixed(0)} ({sec.rsi_status || '—'}) </span>}
                      {sec?.rel_strength_vs_spy_month_pct != null && (
                        <span>· vs SPY {Number(sec.rel_strength_vs_spy_month_pct) >= 0 ? '+' : ''}{Number(sec.rel_strength_vs_spy_month_pct).toFixed(1)}% </span>
                      )}
                      {sec?.rel_strength_vs_qqq_month_pct != null && (
                        <span>· vs QQQ {Number(sec.rel_strength_vs_qqq_month_pct) >= 0 ? '+' : ''}{Number(sec.rel_strength_vs_qqq_month_pct).toFixed(1)}% </span>
                      )}
                      {sec?.sma50_pct != null && <span>· SMA50 {Number(sec.sma50_pct) >= 0 ? '+' : ''}{Number(sec.sma50_pct).toFixed(1)}% </span>}
                      {sec?.sma200_pct != null && <span>· SMA200 {Number(sec.sma200_pct) >= 0 ? '+' : ''}{Number(sec.sma200_pct).toFixed(1)}%</span>}
                    </div>
                  )}

                  {/* Options — muted secondary */}
                  {sec?.options_sentiment && !String(sec.options_sentiment).includes('No unusual') && (
                    <div style={{ fontSize: 11, color: C.soft, marginTop: 6, lineHeight: 1.4 }}>
                      <span style={{ fontWeight: 650, color: C.muted }}>Options · </span>
                      {sec.options_sentiment}
                      {sec.iv_rank != null && <span> · IV rank {Number(sec.iv_rank).toFixed(0)}</span>}
                    </div>
                  )}

                  {(t.why_selected || t.rationale) && (
                    <div style={{ fontSize: 11.5, color: C.muted, lineHeight: 1.45, marginTop: 8 }}>
                      {t.why_selected || t.rationale}
                    </div>
                  )}
                  {t.data_complete === false && (
                    <div style={{ fontSize: 11, color: C.caution, fontWeight: 650, marginTop: 6 }}>
                      {t.incomplete_reason || 'Incomplete data — lower confidence'}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {/* Related themes strip */}
      {((related?.items?.length ?? 0) > 0 || related?.impact_note) && (
        <div style={{
          fontSize: 11.5, lineHeight: 1.45, padding: '8px 10px', borderRadius: 8,
          background: 'rgba(0,0,0,.16)', border: `1px solid ${C.line}`,
        }}>
          <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.soft, marginBottom: 4 }}>
            Related themes
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: related?.impact_note ? 4 : 0 }}>
            {(related?.items || []).map(r => (
              <button
                key={r.id}
                type="button"
                onClick={e => { e.stopPropagation(); r.id && onThemeClick?.(r.id) }}
                title={r.reason || ''}
                style={{
                  fontSize: 11, fontWeight: 650, cursor: onThemeClick ? 'pointer' : 'default',
                  border: `1px solid ${C.lineStrong}`, background: C.accentSoft, color: C.muted,
                  borderRadius: 6, padding: '3px 8px',
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
          {related?.impact_note && (
            <div style={{ color: C.muted, fontSize: 11 }}>{related.impact_note}</div>
          )}
        </div>
      )}

      {item.portfolio_snapshot?.heat && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 11, color: C.soft }}>
          {item.portfolio_snapshot.heat.portfolio_heat_pct != null && (
            <span>
              Heat{' '}
              <strong style={{ color: CONC_COLOR[item.portfolio_snapshot.heat.level || ''] || C.ink }}>
                {Number(item.portfolio_snapshot.heat.portfolio_heat_pct).toFixed(1)}%
              </strong>
              {item.portfolio_snapshot.heat.level ? ` (${item.portfolio_snapshot.heat.level})` : ''}
            </span>
          )}
          {item.portfolio_snapshot.concentration?.book_level && (
            <span>
              Book conc.{' '}
              <strong style={{
                color: CONC_COLOR[item.portfolio_snapshot.concentration.book_level] || C.ink,
              }}>
                {item.portfolio_snapshot.concentration.book_level}
              </strong>
              {item.portfolio_snapshot.concentration.top3_pct != null
                ? ` · top-3 ${Number(item.portfolio_snapshot.concentration.top3_pct).toFixed(0)}%`
                : ''}
            </span>
          )}
        </div>
      )}
      {item.risk_caveat && (
        <div style={{ fontSize: 11, color: C.soft, lineHeight: 1.4, fontStyle: 'italic' }}>
          {item.risk_caveat}
        </div>
      )}
      {item.quality_gate?.note && (
        <div style={{ fontSize: 11, color: C.stale, lineHeight: 1.4, fontWeight: 650 }}>
          {item.quality_gate.note}
        </div>
      )}
    </div>
  )
}

function ArticleCard({
  item, catMeta, featured, view, onOpen, onFeedback, onStage, onThemeClick, staging,
}: {
  item: Item
  catMeta: Record<string, Cat>
  featured?: boolean
  view: 'cards' | 'list' | 'compact'
  onOpen: () => void
  onFeedback: (id: string, patch: Partial<Item>) => void
  onStage?: (payload: Record<string, unknown>) => Promise<void>
  onThemeClick?: (themeId: string) => void
  staging?: boolean
}) {
  const primary = item.primary_category || item.categories?.[0] || ''
  const catColor = CAT_TINT[primary] || catMeta[primary]?.color || C.accent
  const paras = item.executive_summary?.length
    ? item.executive_summary
    : (item.summary ? [item.summary] : [])
  const takeaways = item.key_takeaways?.length ? item.key_takeaways : []

  const toggleStar = async (e: MouseEvent) => {
    e.stopPropagation()
    const next = !item.starred
    onFeedback(item.id, { starred: next })
    await postFeedback({
      item_id: item.id, starred: next, source_system: item.source_system,
      symbol: item.symbol, categories: item.categories,
    })
  }
  const vote = async (e: MouseEvent, v: number) => {
    e.stopPropagation()
    const next = item.vote === v ? 0 : v
    onFeedback(item.id, { vote: next || null })
    await postFeedback({
      item_id: item.id, vote: next, source_system: item.source_system,
      symbol: item.symbol, categories: item.categories,
    })
  }
  // v3.1 (B2): operator curation only — the Hermes row is untouched
  const hideCard = async (e: MouseEvent) => {
    e.stopPropagation()
    onFeedback(item.id, { hidden: true })
    await postFeedback({
      item_id: item.id, hidden: true, source_system: item.source_system,
      symbol: item.symbol, categories: item.categories,
    })
  }
  const savedAgo = (() => {
    if (!item.starred || !item.feedback_updated_at) return null
    const h = (Date.now() - new Date(item.feedback_updated_at).getTime()) / 3_600_000
    if (!Number.isFinite(h) || h < 0) return null
    return h < 24 ? `saved ${Math.max(1, Math.round(h))}h ago` : `saved ${Math.round(h / 24)}d ago`
  })()

  if (view === 'compact') {
    return (
      <div
        onClick={onOpen}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
        style={{
          display: 'grid',
          gridTemplateColumns: '28px 1fr auto auto',
          gap: 12, alignItems: 'center',
          padding: '11px 14px',
          borderBottom: `1px solid ${C.line}`,
          cursor: 'pointer',
          background: item.starred ? 'rgba(253,230,138,.04)' : 'transparent',
        }}
      >
        <button type="button" onClick={toggleStar} style={iconBtn(item.starred ? C.star : C.soft)}>
          {item.starred ? '★' : '☆'}
        </button>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 13, fontWeight: 700, color: C.ink,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {item.symbol && <span style={{ color: C.accent, marginRight: 8 }}>{item.symbol}</span>}
            {item.title}
          </div>
          {item.lede && (
            <div style={{
              fontSize: 11.5, color: C.muted, marginTop: 2,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {item.lede}
            </div>
          )}
        </div>
        <Tag color={catColor}>{catMeta[primary]?.label || primary}</Tag>
        <FreshnessDot tier={item.freshness_tier} label={item.freshness_label} asOf={item.created_at} />
      </div>
    )
  }

  const shell: CSSProperties = {
    borderRadius: featured ? 14 : 12,
    border: `1px solid ${featured ? C.lineStrong : C.line}`,
    background: C.card,
    padding: featured ? '20px 22px' : view === 'list' ? '16px 18px' : '14px 16px',
    cursor: 'pointer',
    display: 'flex',
    flexDirection: 'column',
    gap: featured ? 12 : 10,
    boxShadow: featured ? '0 8px 28px rgba(0,0,0,.22)' : '0 2px 12px rgba(0,0,0,.14)',
    transition: 'border-color .15s, background .15s',
    position: 'relative',
    overflow: 'hidden',
  }

  return (
    <article
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
      style={shell}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(148,163,184,.28)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = featured ? C.lineStrong : C.line }}
    >
      {/* subtle top rule — single steel accent, not category neon */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 1,
        background: featured ? C.lineStrong : C.line,
      }} />

      {/* meta row */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, alignItems: 'center' }}>
          <button type="button" onClick={toggleStar} style={iconBtn(item.starred ? C.star : C.soft)} title="Star">
            {item.starred ? '★' : '☆'}
          </button>
          {savedAgo && <span style={{ fontSize: 9.5, color: C.star }}>{savedAgo}</span>}
          <button type="button" onClick={hideCard} className="ri-hide-btn"
            title="Hide from desk — operator curation only; the research row is untouched"
            style={{ ...iconBtn(C.soft), fontSize: 11, opacity: 0.35 }}>
            ✕
          </button>
          {item.symbol && (
            <span style={{
              fontFamily: 'var(--mono)', fontWeight: 800, fontSize: 12,
              color: C.accent, letterSpacing: '0.04em',
            }}>
              {item.symbol}
            </span>
          )}
          <Tag color={catColor}>{catMeta[primary]?.label || primary}</Tag>
          {item.quality_tier && QUALITY[item.quality_tier] && (
            <span title={QUALITY[item.quality_tier].hint}>
              <Tag color={QUALITY[item.quality_tier].color}>{QUALITY[item.quality_tier].label}</Tag>
            </span>
          )}
          {item.is_holdings && <Tag color={C.income}>In portfolio</Tag>}
          {item.hermes_score && (
            <span title="Hermes composite · rank · scope tier (read-only join)">
              <Tag color={C.accent}>
                ★{item.hermes_score.rank != null ? `#${item.hermes_score.rank}` : ''} · {item.hermes_score.composite}
                {item.hermes_score.scope_tier ? ` · ${String(item.hermes_score.scope_tier).toUpperCase()}` : ''}
              </Tag>
            </span>
          )}
          {item.score_divergence && (
            <span title="RI conviction and Hermes composite disagree — both shown, neither blended">
              <Tag color={C.stale}>
                ⚠ RI {item.score_divergence.ri_tier} / Hermes {item.score_divergence.hermes_composite}
              </Tag>
            </span>
          )}
          {(item.external_intel?.length ?? 0) > 0 && item.external_intel!.map((x, i) => (
            <span key={`ext-${i}`} title={
              `${x.lane || 'external'} · conf ${x.confidence ?? '—'}\n${x.recommendation || ''}${x.dissent ? `\nCounter-view: ${x.dissent}` : ''}`
            }>
              <Tag color={C.macro}>✦ {String(x.lane || 'ext').replace(/_/g, ' ')}</Tag>
            </span>
          ))}
          {item.watch_directive && (
            <span title={`Active watch directive: ${item.watch_directive.label || item.symbol}`}>
              <Tag color="#f59e0b">Directive</Tag>
            </span>
          )}
          {(item.ticker_recommendations?.filter(t => t.scope !== 'book').length ?? 0) > 0 && (
            <Tag color={C.macro}>Tickers & size</Tag>
          )}
          {item.portfolio_snapshot?.concentration?.book_level &&
            item.portfolio_snapshot.concentration.book_level !== 'normal' && (
            <Tag color={CONC_COLOR[item.portfolio_snapshot.concentration.book_level] || C.stale}>
              Conc. {item.portfolio_snapshot.concentration.book_level}
            </Tag>
          )}
          {/* v3.1 (WS-D): QA flags demote and DISCLOSE — honest gray chips, never hidden */}
          {(item.quality_flags || []).map((f, i) => (
            <span key={`qf-${i}`} title="Deterministic QA lint flag — this brief is capped below Tier A">
              <Tag color="#6b7280">{f.startsWith('duplicate_of:') ? 'duplicate' : f.replace(/_/g, ' ')}</Tag>
            </span>
          ))}
          {(item.quality_flags || []).includes('no_counter_view') && (
            <Tag color="#9ca3af">single-view — treat as unconfirmed</Tag>
          )}
          {item.is_archived && <Tag color={C.archive}>Archived</Tag>}
          {item.needs_refresh && <Tag color={C.stale}>Due refresh</Tag>}
          {item.priority === 'high' && <Tag color={C.macro}>Priority</Tag>}
          {item.sentiment && item.sentiment !== 'neutral' && (
            <Tag color={item.sentiment === 'bullish' ? C.bull : C.bear}>{item.sentiment}</Tag>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <FreshnessDot tier={item.freshness_tier} label={item.freshness_label} asOf={item.created_at} />
          {item.reading_minutes != null && (
            <span style={{ fontSize: 11, color: C.soft }}>{item.reading_minutes} min read</span>
          )}
        </div>
      </div>

      {/* byline — Seeking Alpha / Yahoo style */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
        fontSize: 11.5, color: C.soft,
      }}>
        <span style={{ fontWeight: 700, color: C.muted }}>
          {item.source_system === 'hermes' ? 'Hermes Research Desk'
            : item.source_system === 'topic_monitor' ? 'Topic Monitor · Standing watch'
            : item.source_system === 'auto_research' ? 'Auto Research'
            : 'Intelligence Desk'}
        </span>
        <span>·</span>
        <FreshnessDot tier={item.freshness_tier} label={item.freshness_label} asOf={item.created_at} />
        {item.narrative_source === 'stored_llm' && (
          <>
            <span>·</span>
            <span style={{ color: C.retire, fontWeight: 700 }}>LLM editorial</span>
          </>
        )}
      </div>

      {/* headline */}
      <h2 style={{
        margin: 0, fontSize: featured ? 22 : view === 'list' ? 17 : 15.5,
        fontWeight: 780, letterSpacing: '-0.02em', lineHeight: 1.28, color: C.ink,
      }}>
        {item.title}
      </h2>

      {/* lede / dek */}
      {item.lede && (
        <p style={{
          margin: 0, fontSize: featured ? 15 : 13.5, lineHeight: 1.55,
          color: C.muted, fontWeight: 500,
        }}>
          {item.lede}
        </p>
      )}

      {/* body prose */}
      {(featured || view === 'list') && paras.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {paras.slice(0, featured ? 3 : 2).map((p, i) => (
            <p key={i} style={{
              margin: 0, fontSize: featured ? 14 : 13, lineHeight: 1.65,
              color: i === 0 ? C.ink : C.muted, fontWeight: i === 0 ? 450 : 400,
            }}>
              {p}
            </p>
          ))}
        </div>
      )}
      {view === 'cards' && !featured && (
        <>
          {paras[0] && (
            <p style={{
              margin: 0, fontSize: 13, lineHeight: 1.6, color: C.muted,
              display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
            }}>
              {paras[0]}
            </p>
          )}
          {takeaways[0] && (
            <div style={{ fontSize: 12, color: C.ink, lineHeight: 1.45 }}>
              <span style={{ color: catColor, fontWeight: 750 }}>Takeaway · </span>
              {takeaways[0]}
            </div>
          )}
          {item.why_it_matters && (
            <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.45 }}>
              <span style={{ fontWeight: 750, color: catColor }}>Why it matters · </span>
              {item.why_it_matters}
            </div>
          )}
          {(() => {
            // v3 (B3): per-card strip carries THIS BRIEF's tickers only — book
            // context (SCHG trim / concentration weights) lives in the desk-level
            // concentration banner, not on every card
            const briefTicks = (item.ticker_recommendations || []).filter(t => t.scope !== 'book')
            if (briefTicks.length === 0) {
              return (item.ticker_recommendations?.length ?? 0) > 0 ? (
                <div style={{ fontSize: 11, color: C.soft, fontStyle: 'italic' }}>
                  No ticker mapping — book context in the concentration banner
                </div>
              ) : null
            }
            return (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
                <span style={{ fontSize: 9.5, fontWeight: 800, letterSpacing: '0.07em', textTransform: 'uppercase', color: C.soft }}>
                  This brief
                </span>
                {briefTicks.slice(0, 4).map((t, i) => {
                  const rc = ROLE_COLOR[t.role || ''] || C.accent
                  return (
                    <span key={`${t.symbol}-${i}`} style={{
                      fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 800,
                      color: C.accent, background: `${rc}14`, border: `1px solid ${rc}44`,
                      borderRadius: 6, padding: '3px 8px',
                    }}>
                      {t.symbol}
                      {t.suggested_weight_pct ? (
                        <span style={{ color: C.muted, fontWeight: 600, marginLeft: 5 }}>
                          {t.suggested_weight_pct}
                        </span>
                      ) : null}
                    </span>
                  )
                })}
              </div>
            )
          })()}
        </>
      )}

      {/* key takeaways */}
      {(featured || view === 'list') && takeaways.length > 0 && (
        <div style={{
          padding: '12px 14px', borderRadius: 10,
          background: 'rgba(255,255,255,0.025)', border: `1px solid ${C.line}`,
        }}>
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.soft, marginBottom: 8 }}>
            Key takeaways
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {takeaways.slice(0, featured ? 4 : 3).map((t, i) => (
              <li key={i} style={{ fontSize: 12.5, lineHeight: 1.45, color: C.ink }}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      {/* bull / bear */}
      {(featured || view === 'list') && (item.bull_case || item.bear_case) && (
        <div style={{ display: 'grid', gridTemplateColumns: item.bull_case && item.bear_case ? '1fr 1fr' : '1fr', gap: 8 }}>
          {item.bull_case && (
            <div style={{ padding: '10px 12px', borderRadius: 10, background: C.incomeSoft, border: `1px solid ${C.income}33` }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: C.income, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Bull case</div>
              <div style={{ fontSize: 12, lineHeight: 1.45, color: C.ink }}>{item.bull_case}</div>
            </div>
          )}
          {item.bear_case && (
            <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(249,168,212,0.08)', border: `1px solid ${C.bear}33` }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: C.bear, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Bear case</div>
              <div style={{ fontSize: 12, lineHeight: 1.45, color: C.ink }}>{item.bear_case}</div>
            </div>
          )}
        </div>
      )}

      {/* why it matters */}
      {item.why_it_matters && (featured || view === 'list') && (
        <div style={{ fontSize: 12.5, lineHeight: 1.5, color: C.muted }}>
          <span style={{ fontWeight: 750, color: catColor }}>Why it matters · </span>
          {item.why_it_matters}
        </div>
      )}

      <ActionStrip
        item={item}
        catColor={catColor}
        onStage={onStage}
        onThemeClick={onThemeClick}
        staging={staging}
      />

      {/* footer */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, color: C.soft }}>
          {item.source_system}
          {item.research_type ? ` · ${item.research_type}` : ''}
          {item.source_count ? ` · ${item.source_count} sources` : ''}
          {confPct(item.confidence) != null ? ` · ${confPct(item.confidence)}% conf` : ''}
          {item.narrative_source === 'stored_llm' ? ' · LLM narrative' : ''}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button type="button" onClick={e => vote(e, 1)} style={voteBtn(item.vote === 1, C.bull)} title="Useful">▲</button>
          <button type="button" onClick={e => vote(e, -1)} style={voteBtn(item.vote === -1, C.bear)} title="Not useful">▼</button>
          <span style={{ fontSize: 11, fontWeight: 700, color: C.accent }}>Open full brief →</span>
        </div>
      </div>
    </article>
  )
}

function iconBtn(color: string): CSSProperties {
  return {
    border: 'none', background: 'transparent', cursor: 'pointer',
    color, fontSize: 15, padding: 0, lineHeight: 1,
  }
}
function voteBtn(active: boolean, color: string): CSSProperties {
  return {
    fontSize: 11, fontWeight: 800, padding: '3px 7px', borderRadius: 6, cursor: 'pointer',
    border: `1px solid ${active ? color : C.line}`,
    background: active ? `${color}22` : 'transparent',
    color: active ? color : C.soft,
  }
}

type StagedIdea = {
  id?: string
  symbol?: string
  side?: string
  role?: string
  status?: string
  suggested_weight_pct?: string
  funding_source?: string
  funding_symbol?: string
  conviction_tier?: string
  conviction_score?: number
  source_title?: string
  staged_at?: string
  expires_at?: string
  provisional_stop_note?: string
  require_funding_trim?: boolean
}

// v3.1 (C5): ONE Eastern-time formatter for every timestamp the desk renders.
export function fmtET(iso: string | null | undefined, withDate = true): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    const time = d.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false })
    if (!withDate) return time
    const day = d.toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' })
    const today = new Date().toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' })
    return day === today ? time : `${day}, ${time}`
  } catch { return '—' }
}

const STAGED_STATUS_META: Record<string, { label: string; color: string }> = {
  staged: { label: 'Staged', color: '#34d399' },
  watchlisted: { label: 'Watchlisted', color: '#60a5fa' },
  directive_created: { label: 'Directive', color: '#f59e0b' },
  proposed_paper: { label: 'Paper proposal', color: '#a78bfa' },
  expired: { label: 'Expired', color: '#64748b' },
  dismissed: { label: 'Dismissed', color: '#64748b' },
}

const THEME_TO_CATEGORY: Record<string, string> = {
  dividend_income: 'dividend_income',
  retirement: 'retirement_tax',
  growth: 'compounding_wealth',
  ai_infra: 'sector_thematic',
  power_infra: 'sector_thematic',
  industrials: 'sector_thematic',
  defense: 'sector_thematic',
  bonds: 'macro_geo',
}

export default function ResearchIntelligenceHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const [priority, setPriority] = useState<string | null>(null)
  const [holdingsOnly, setHoldingsOnly] = useState(false)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [starredOnly, setStarredOnly] = useState(false)
  const [freshness, setFreshness] = useState<string | null>(null)
  const [sentiment, setSentiment] = useState<string | null>(null)
  const [lane, setLane] = useState<'all' | 'retirement' | 'dividends' | 'macro_sector'>('all')
  const [view, setView] = useState<'cards' | 'list' | 'compact'>('list')
  const [localPatch, setLocalPatch] = useState<Record<string, Partial<Item>>>({})
  const [stagedIdeas, setStagedIdeas] = useState<StagedIdea[]>([])
  const [showStaged, setShowStaged] = useState(false)
  const [bannerDismissed, setBannerDismissed] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [staging, setStaging] = useState(false)
  const [queuedTopics, setQueuedTopics] = useState<Record<string, boolean>>({})
  const [rebuilding, setRebuilding] = useState(false)

  // v3 (D1/D2/D4): enqueue a topic or coverage-gap category for the after-close
  // research drain — nothing runs during RTH, the cron drains at 16:45/02:40
  const queueResearch = useCallback(async (payload: { topic_id?: string; category?: string }) => {
    const key = payload.topic_id || payload.category || ''
    try {
      const raw = await fetch('/api/v2/research-intelligence/run-topic', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(x => x.json())
      const res = raw?.data && typeof raw.data === 'object' ? { ...raw.data, ok: raw.ok && raw.data.ok !== false } : raw
      if (res?.ok) {
        setQueuedTopics(p => ({ ...p, [key]: true }))
        setToast(res.note ? `${key}: ${res.note}` : `${key} queued for after close`)
      } else {
        setToast(`Queue failed: ${res?.error || 'error'}`)
      }
    } catch {
      setToast('Queue failed — server unreachable')
    }
  }, [])


  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (category) p.set('category', category)
    if (priority) p.set('priority', priority)
    if (holdingsOnly) p.set('holdings_only', '1')
    if (includeArchived) p.set('include_archived', '1')
    if (starredOnly) p.set('starred_only', '1')
    if (freshness) p.set('freshness', freshness)
    if (sentiment) p.set('sentiment', sentiment)
    if (lane !== 'all') p.set('lane', lane)
    // 50 cards max — full 100 was ~3MB JSON and timed out the desk under Tailscale load
    p.set('limit', '50')
    return p.toString()
  }, [q, category, priority, holdingsOnly, includeArchived, starredOnly, freshness, sentiment, lane])

  const { data, loading, refreshing, error, refetch } = useApi<any>(
    `/api/v2/research-intelligence?${qs}`,
    300_000,
  )
  const { data: freshData, refetch: refetchFresh } = useApi<any>('/api/v2/research-intelligence/freshness', 300_000)
  // v3 (D5): Discovery Inbox TOPIC_CANDIDATEs — proposals only, operator decides
  const { data: proposedData, refetch: refetchProposed } = useApi<any>(
    '/api/v2/hermes/discovery-inbox?type=TOPIC_CANDIDATE&status=DISCOVERED&limit=6', 600_000,
  )

  // v3 (D5): route a proposed topic through the GOVERNED discovery pathways —
  // approve-research-topic / reject; never a direct topic_monitor write from here
  const decideProposedTopic = useCallback(async (candidateId: number, action: 'approve-research-topic' | 'reject') => {
    try {
      const raw = await fetch(`/api/v2/hermes/discovery-inbox/${candidateId}/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor: 'operator', notes: 'decided from RI desk (v3 proposed-topics rail)' }),
      }).then(x => x.json())
      const ok = raw?.ok ?? raw?.data?.ok
      setToast(ok
        ? (action === 'reject' ? 'Proposal dismissed' : 'Approved → research topic pipeline')
        : `Decision failed: ${raw?.error || raw?.data?.error || 'error'}`)
      refetchProposed()
    } catch {
      setToast('Decision failed — server unreachable')
    }
  }, [refetchProposed])
  const { data: stagedData, refetch: refetchStaged } = useApi<any>(
    '/api/v2/research-intelligence/staged?limit=40',
    300_000,
  )

  // Visible feedback when operator clicks Refresh desk (refetch alone looked like a no-op)
  const wasRefreshing = useRef(false)
  useEffect(() => {
    if (refreshing) {
      wasRefreshing.current = true
      setToast('Refreshing desk…')
      return
    }
    if (wasRefreshing.current) {
      wasRefreshing.current = false
      if (error) {
        setToast(`Desk refresh failed — ${error}`)
      } else {
        const n = data?.stats?.matched ?? data?.items?.length
        setToast(
          typeof n === 'number'
            ? `Desk refreshed · ${n} brief${n === 1 ? '' : 's'} in view`
            : 'Desk refreshed',
        )
      }
    }
  }, [refreshing, error, data?.stats?.matched, data?.items?.length])

  const refreshDesk = useCallback(() => {
    refetch()
    refetchStaged?.()
    refetchFresh?.()
  }, [refetch, refetchStaged, refetchFresh])

  useEffect(() => {
    if (stagedData?.ideas) setStagedIdeas(stagedData.ideas)
    else if (stagedData?.data?.ideas) setStagedIdeas(stagedData.data.ideas)
  }, [stagedData])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 4200)
    return () => window.clearTimeout(t)
  }, [toast])

  const handleStage = useCallback(async (payload: Record<string, unknown>) => {
    setStaging(true)
    try {
      let res = await postStage(payload)
      // v3 (E3): no exit note = no plan — collect one inline and retry
      if (!res?.ok && (res?.error === 'stop_note_required' || res?.data?.error === 'stop_note_required')) {
        const note = window.prompt(
          `Exit/stop note required to stage ${payload.symbol} — where does protection go, and why?`)
        if (note && note.trim()) {
          res = await postStage({ ...payload, provisional_stop_note: note.trim() })
        } else {
          setToast('Stage blocked: exit/stop note required — a staged idea without an exit note is not a plan')
          setStaging(false)
          return
        }
      }
      if (res?.ok) {
        setToast(res.message || `Staged ${payload.symbol}`)
        setShowStaged(true)
        refetchStaged?.()
        // also refresh list
        const list = await fetch('/api/v2/research-intelligence/staged?limit=40').then(r => r.json())
        const ideas = list?.ideas || list?.data?.ideas || []
        setStagedIdeas(ideas)
      } else {
        setToast(res?.detail || res?.error || 'Stage failed')
      }
    } catch {
      setToast('Stage request failed')
    } finally {
      setStaging(false)
    }
  }, [refetchStaged])

  const handleDismissStaged = useCallback(async (id: string) => {
    await postStageUpdate({ id, dismiss: true })
    setStagedIdeas(prev => prev.filter(x => x.id !== id))
    setToast('Staged idea dismissed')
  }, [])

  // v3 (E2): operator-clicked promotion into existing pathways — never automatic
  const handlePromoteStaged = useCallback(async (id: string, target: 'watchlist' | 'directive' | 'paper_proposal') => {
    try {
      const raw = await fetch('/api/v2/research-intelligence/stage/promote', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, target }),
      }).then(x => x.json())
      const res = raw?.data && typeof raw.data === 'object' ? raw.data : raw
      if (res?.ok) {
        setToast(target === 'paper_proposal'
          ? `Promoted → PENDING paper proposal #${res.proposal_id ?? ''} (normal review chain)`
          : `Promoted → ${target}`)
        setStagedIdeas(prev => prev.map(x => (x.id === id ? { ...x, ...(res.idea || {}) } : x)))
        refetchStaged?.()
      } else {
        setToast(`Promotion failed: ${res?.error || 'error'}`)
      }
    } catch {
      setToast('Promotion failed — server unreachable')
    }
  }, [refetchStaged])

  const handleThemeClick = useCallback((themeId: string) => {
    const cat = THEME_TO_CATEGORY[themeId]
    if (cat) {
      setCategory(cat)
      setLane('all')
    }
  }, [])

  const cats: Cat[] = data?.taxonomy?.categories || []
  const catMeta = useMemo(() => {
    const m: Record<string, Cat> = {}
    for (const c of cats) m[c.id] = c
    return m
  }, [cats])

  const items: Item[] = useMemo(() => {
    const raw: Item[] = data?.items || []
    return raw.map(it => ({ ...it, ...(localPatch[it.id] || {}) }))
  }, [data?.items, localPatch])

  const stats = data?.stats || {}
  // Universe freshness for masthead (not zeroed by empty category filter)
  const tierCounts = stats.by_freshness || {}

  const hasActiveFilters = !!(
    category || priority || holdingsOnly || includeArchived || starredOnly
    || freshness || sentiment || q.trim() || lane !== 'all'
  )

  const clearFilters = useCallback(() => {
    setQ('')
    setCategory(null)
    setPriority(null)
    setHoldingsOnly(false)
    setIncludeArchived(false)
    setStarredOnly(false)
    setFreshness(null)
    setSentiment(null)
    setLane('all')
  }, [])

  // Auto-clear only truly empty filters (0 matches) when the desk has a full universe —
  // e.g. stuck on Compounding primary=0. Do NOT clear intentional narrow filters (1–N stories).
  const didAutoClear = useRef(false)
  useEffect(() => {
    if (didAutoClear.current || loading || !data?.stats) return
    const matched = Number(data.stats.matched ?? 0)
    const universe = Number(data.stats.universe ?? 0)
    const deskBig = universe >= 20 || (data.stats.by_category
      && Object.values(data.stats.by_category as Record<string, number>).reduce((a, b) => a + (Number(b) || 0), 0) >= 20)
    if (hasActiveFilters && matched === 0 && deskBig) {
      didAutoClear.current = true
      clearFilters()
    }
  }, [data?.stats, loading, hasActiveFilters, clearFilters])

  const displayItems: Item[] = useMemo(() => {
    // Lane + category are applied server-side (lane= param); items ARE the lane
    // view. Locally-hidden cards (B2) drop out immediately.
    return items.filter(i => !i.hidden)
  }, [items])

  const featured = useMemo(() => {
    // Prefer real Hermes/LLM briefs — never feature empty topic_monitor stubs
    const pool = displayItems
    const isStub = (i: Item) =>
      i.research_type === 'topic_monitor'
      || (i.summary || '').includes('standing watch on the Research Intelligence desk')
    const rich = (i: Item) =>
      i.narrative_source === 'stored_llm'
      || (i.executive_summary && i.executive_summary.join('').length > 200)
      || ((i.summary || '').length > 280 && !isStub(i))
    return (
      pool.find(i => i.primary_category === 'retirement_tax' && rich(i) && !isStub(i))
      || pool.find(i => rich(i) && !isStub(i) && i.priority === 'high')
      || pool.find(i => rich(i) && !isStub(i))
      || pool.find(i => !isStub(i))
      || pool[0]
      || null
    )
  }, [displayItems])

  const rest = useMemo(() => {
    if (!featured) return displayItems
    return displayItems.filter(i => i.id !== featured.id)
  }, [displayItems, featured])

  const onFeedback = useCallback((id: string, patch: Partial<Item>) => {
    setLocalPatch(prev => ({ ...prev, [id]: { ...(prev[id] || {}), ...patch } }))
  }, [])

  const openItem = (item: Item) => {
    onDrill({
      title: item.symbol ? `${item.symbol} · ${item.title}` : item.title,
      subtitle: [
        item.freshness_label,
        item.next_action_label || item.actionability,
        item.primary_category && (catMeta[item.primary_category]?.label || item.primary_category),
      ].filter(Boolean).join(' · '),
      endpoint: '/api/v2/research-intelligence',
      rows: [{
        ...item,
        // flatten for drawer readability
        article_lede: item.lede,
        article_body: (item.executive_summary || []).join('\n\n'),
        article_takeaways: (item.key_takeaways || []).join(' | '),
        article_bull: item.bull_case,
        article_bear: item.bear_case,
        article_why: item.why_it_matters,
        article_next: `${item.next_action_label || ''} — ${item.next_action_detail || ''}`,
      }],
    })
  }

  const staleTopics = freshData?.stale_topics || []
  const retStats = freshData?.by_category?.retirement_tax

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 1280 }}>
      {/* Masthead */}
      <header style={{
        borderRadius: 12,
        padding: '18px 20px',
        background: C.card,
        border: `1px solid ${C.lineStrong}`,
      }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 14 }}>
          <div style={{ maxWidth: 720 }}>
            <div style={{
              fontSize: 11, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase',
              color: C.soft, marginBottom: 8,
            }}>
              Command Center · Intelligence Desk
            </div>
            <div style={{ ...hubTitle(), fontSize: 24, letterSpacing: '-0.02em', marginBottom: 6, color: C.ink }}>
              Research Intelligence
            </div>
            <div style={{ ...hubSubtitle(terminalUi), fontSize: 13.5, lineHeight: 1.55, color: C.muted, maxWidth: 580 }}>
              Company identity, news &amp; sentiment, analyst consensus, and portfolio-aware sizing —
              retirement, dividends, macro, and holdings research in one desk.
              {' '}Content production runs overnight / after close only (not during RTH).
              {stats.matched != null && ` · ${stats.matched} in view`}
              {stats.universe != null && stats.universe !== stats.matched && ` · ${stats.universe} on desk`}
              {loading ? ' · loading…' : ''}
              {refreshing ? ' · refreshing…' : ''}
              {data?.version ? ` · v${data.version}` : ''}
            </div>
            {data?.meta?.generated_at && (
              <div style={{ fontSize: 11, color: C.soft, marginTop: 4, fontFamily: 'var(--mono)' }}>
                Desk built {fmtET(data.meta.generated_at)} ET
                {data.meta.served_from === 'snapshot' ? ' · snapshot' : ' · live build'}
                {' · next build 16:45 / 02:40 ET'}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
              <Link to="/retirement" style={navLink(C.muted)}>Retirement plan →</Link>
              <Link to="/portfolio" style={navLink(C.muted)}>Portfolio →</Link>
              <Link to="/hermes" style={navLink(C.muted)}>Hermes →</Link>
              <Link to="/risk" style={navLink(C.muted)}>Risk →</Link>
              <button
                type="button"
                onClick={refreshDesk}
                disabled={!!refreshing}
                title="Reload Research Intelligence feed from the server"
                style={{
                  ...refreshBtn,
                  opacity: refreshing ? 0.7 : 1,
                  cursor: refreshing ? 'wait' : 'pointer',
                }}
              >
                {refreshing ? '↻ Refreshing…' : '↻ Refresh desk'}
              </button>
              <button
                type="button"
                disabled={rebuilding}
                onClick={async () => {
                  setRebuilding(true)
                  setToast('Rebuilding desk snapshots (~30s)…')
                  try {
                    const raw = await fetch('/api/v2/research-intelligence/rebuild', { method: 'POST' }).then(x => x.json())
                    const res = raw?.data && typeof raw.data === 'object' ? raw.data : raw
                    setToast(res?.ok ? 'Desk rebuilt — refreshing' : `Rebuild failed: ${res?.error || 'busy'}`)
                    if (res?.ok) refetch()
                  } catch { setToast('Rebuild failed — server unreachable') }
                  setRebuilding(false)
                }}
                title="Recompute the desk snapshots from current rows (compute only — new research still queues to after close)"
                style={{ ...refreshBtn, opacity: rebuilding ? 0.7 : 1, cursor: rebuilding ? 'wait' : 'pointer' }}
              >
                {rebuilding ? '⟳ Rebuilding…' : '⟳ Rebuild desk (~30s)'}
              </button>
              <button
                type="button"
                onClick={() => setShowStaged(s => !s)}
                style={{
                  ...refreshBtn,
                  borderColor: C.lineStrong,
                  color: C.ink,
                  background: C.accentSoft,
                }}
              >
                Staged Ideas ({stagedIdeas.length})
              </button>
            </div>
            <div style={{ display: 'flex', gap: 14, fontSize: 12, color: C.soft, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <span><b style={{ color: C.ink }}>{tierCounts.live || 0}</b> live</span>
              <span><b style={{ color: C.ink }}>{tierCounts.fresh || 0}</b> fresh</span>
              <span><b style={{ color: C.ink }}>{tierCounts.aging || 0}</b> aging</span>
              <span><b style={{ color: C.ink }}>{tierCounts.stale || 0}</b> stale</span>
              <span><b style={{ color: C.ink }}>{stats.lane_counts?.retirement ?? stats.by_category?.retirement_tax ?? retStats?.count ?? '—'}</b> retirement</span>
            </div>
          </div>
        </div>
      </header>

      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 80,
          padding: '12px 16px', borderRadius: 12, maxWidth: 360,
          background: 'rgba(16,24,40,.96)', border: `1px solid ${C.income}66`,
          color: C.ink, fontSize: 13, fontWeight: 650, boxShadow: '0 12px 40px rgba(0,0,0,.4)',
        }}>
          {toast}
        </div>
      )}

      {/* Concentration banner */}
      {!bannerDismissed && data?.portfolio_context?.concentration_banner?.active && (
        <div style={{
          borderRadius: 10, padding: '12px 16px',
          background: C.card, border: `1px solid ${C.lineStrong}`,
          display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start',
        }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: C.caution, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>
              {data.portfolio_context.concentration_banner.title || 'Concentration active'}
            </div>
            <div style={{ fontSize: 12.5, color: C.muted, lineHeight: 1.45 }}>
              {data.portfolio_context.concentration_banner.body}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setBannerDismissed(true)}
            style={{ border: 'none', background: 'transparent', color: C.soft, cursor: 'pointer', fontSize: 16 }}
            title="Dismiss for this session"
          >
            ×
          </button>
        </div>
      )}

      {/* Staged ideas panel */}
      {showStaged && (
        <div style={{
          background: C.card, border: `1px solid ${C.income}44`, borderRadius: 14, padding: 14,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 850, color: C.income }}>Staged Ideas · RI desk</div>
            <button type="button" onClick={() => setShowStaged(false)} style={{ ...iconBtn(C.soft), fontSize: 13 }}>Close</button>
          </div>
          {stagedIdeas.length === 0 ? (
            <div style={{ fontSize: 12, color: C.muted }}>No staged ideas yet. Use <b style={{ color: C.income }}>Stage Trade</b> on a complete card.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {stagedIdeas.filter(i => i.status !== 'expired').map(idea => {
                const sm = STAGED_STATUS_META[idea.status || 'staged'] || STAGED_STATUS_META.staged
                const promotable = (idea.status || 'staged') === 'staged'
                return (
                <div key={idea.id} style={{
                  display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 10, alignItems: 'center',
                  padding: '10px 12px', borderRadius: 10, border: `1px solid ${C.line}`, background: 'rgba(0,0,0,.15)',
                }}>
                  <span style={{ fontFamily: 'var(--mono)', fontWeight: 900, color: C.accent, fontSize: 14 }}>{idea.symbol}</span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 750, color: C.ink, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span>{(idea.side || 'buy').toUpperCase()} · {idea.suggested_weight_pct || 'size TBD'}
                        {idea.conviction_tier ? ` · Conv ${idea.conviction_tier}` : ''}</span>
                      <span style={{
                        fontSize: 9.5, fontWeight: 800, letterSpacing: '0.05em', textTransform: 'uppercase',
                        color: sm.color, border: `1px solid ${sm.color}55`, borderRadius: 999, padding: '1px 8px',
                      }}>{sm.label}</span>
                      {idea.staged_at && (
                        <span style={{ fontSize: 9.5, color: C.soft }} title={String(idea.staged_at)}>
                          created {fmtET(idea.staged_at)} ET
                        </span>
                      )}
                      {idea.expires_at && promotable && (() => {
                        const daysLeft = Math.ceil((new Date(idea.expires_at).getTime() - Date.now()) / 86_400_000)
                        const amber = Number.isFinite(daysLeft) && daysLeft <= 3
                        return (
                          <span style={{
                            fontSize: 9.5, fontWeight: amber ? 800 : 500,
                            color: amber ? '#f59e0b' : C.soft,
                            border: amber ? '1px solid #f59e0b55' : 'none',
                            borderRadius: 999, padding: amber ? '0 6px' : 0,
                          }}>
                            expires in {daysLeft}d
                          </span>
                        )
                      })()}
                    </div>
                    <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
                      {idea.funding_source || (idea.require_funding_trim ? `Fund via ${idea.funding_symbol || 'SCHG'}` : 'Cash / rebalance')}
                      {idea.source_title ? ` · ${idea.source_title.slice(0, 60)}` : ''}
                    </div>
                    {idea.provisional_stop_note && (
                      <div style={{ fontSize: 10.5, color: C.stale, marginTop: 2 }}>
                        Exit: {idea.provisional_stop_note.slice(0, 110)}
                      </div>
                    )}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                      {promotable && idea.id && (
                        <>
                          <button type="button" onClick={() => handlePromoteStaged(idea.id!, 'watchlist')}
                            style={{ fontSize: 10, fontWeight: 750, color: '#60a5fa', border: '1px solid #60a5fa44', background: 'transparent', borderRadius: 6, padding: '3px 8px', cursor: 'pointer' }}>
                            → Watchlist
                          </button>
                          <button type="button" onClick={() => handlePromoteStaged(idea.id!, 'directive')}
                            style={{ fontSize: 10, fontWeight: 750, color: '#f59e0b', border: '1px solid #f59e0b44', background: 'transparent', borderRadius: 6, padding: '3px 8px', cursor: 'pointer' }}>
                            → Watch Directive
                          </button>
                          <button type="button" onClick={() => handlePromoteStaged(idea.id!, 'paper_proposal')}
                            style={{ fontSize: 10, fontWeight: 750, color: '#a78bfa', border: '1px solid #a78bfa44', background: 'transparent', borderRadius: 6, padding: '3px 8px', cursor: 'pointer' }}>
                            → Paper proposal
                          </button>
                        </>
                      )}
                      <Link to={`/trading?symbol=${idea.symbol}&side=${idea.side === 'sell' ? 'sell' : 'buy'}&intent=ri_staged`}
                        style={{ fontSize: 10, fontWeight: 750, color: C.accent, textDecoration: 'none' }}>
                        Send to Trading →
                      </Link>
                      <Link to={`/portfolio?tab=Stop%20Management&symbol=${idea.symbol}`}
                        style={{ fontSize: 10, fontWeight: 750, color: C.stale, textDecoration: 'none' }}>
                        Set stop →
                      </Link>
                      {idea.funding_symbol && (
                        <Link to={`/trading?symbol=${idea.funding_symbol}&side=sell&intent=ri_fund`}
                          style={{ fontSize: 10, fontWeight: 750, color: C.bear, textDecoration: 'none' }}>
                          Trim {idea.funding_symbol} →
                        </Link>
                      )}
                    </div>
                  </div>
                  <button type="button" onClick={() => idea.id && handleDismissStaged(idea.id)}
                    style={{ fontSize: 10, fontWeight: 700, color: C.soft, border: `1px solid ${C.line}`, background: 'transparent', borderRadius: 6, padding: '4px 8px', cursor: 'pointer' }}>
                    Dismiss
                  </button>
                </div>
                )
              })}
              {/* Expired fold — auto-expired after 14d, kept visible, never deleted */}
              {stagedIdeas.some(i => i.status === 'expired') && (
                <details>
                  <summary style={{ fontSize: 11, color: C.soft, cursor: 'pointer' }}>
                    Expired ({stagedIdeas.filter(i => i.status === 'expired').length}) — undecided past 14 days
                  </summary>
                  {stagedIdeas.filter(i => i.status === 'expired').map(idea => (
                    <div key={idea.id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 12px', fontSize: 11.5, color: C.soft }}>
                      <span style={{ fontFamily: 'var(--mono)', fontWeight: 800 }}>{idea.symbol}</span>
                      <span>{(idea.side || 'buy').toUpperCase()} · staged {String(idea.staged_at || '').slice(0, 10)}</span>
                      <span style={{ color: C.soft }}>expired</span>
                    </div>
                  ))}
                </details>
              )}
            </div>
          )}
        </div>
      )}

      {/* Desk controls */}
      <section style={{
        background: C.card, border: `1px solid ${C.line}`, borderRadius: 16, padding: 16,
      }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12, alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {([
              ['all', 'Top stories', C.accent],
              ['retirement', 'Retirement desk', C.retire],
              ['dividends', 'Income & dividends', C.income],
              ['macro_sector', 'Macro & sectors', C.macro],
            ] as const).map(([id, lab, col]) => (
              <SoftChip
                key={id}
                label={lab}
                color={col}
                active={lane === id && !starredOnly}
                onClick={() => { setLane(id); setStarredOnly(false); if (id !== 'all') setCategory(null) }}
              />
            ))}
            {/* v3.1 (B1): the saved shelf — starred briefs as a first-class tab */}
            <SoftChip
              label={`★ Saved${starredOnly && stats.matched != null ? ` ${stats.matched}` : ''}`}
              color={C.star}
              active={starredOnly}
              onClick={() => { setStarredOnly(v => !v); setLane('all') }}
            />
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {(['list', 'cards', 'compact'] as const).map(v => (
              <SoftChip key={v} label={v === 'list' ? 'Article' : v === 'cards' ? 'Cards' : 'Wire'} color={C.muted}
                active={view === v} onClick={() => setView(v)} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          <SoftChip label="All topics" active={!category} onClick={() => setCategory(null)} />
          {cats.map(c => (
            <SoftChip
              key={c.id}
              label={`${c.pillar ? '◆ ' : ''}${c.label}${stats.by_category?.[c.id] != null ? ` (${stats.by_category[c.id]})` : ''}`}
              color={CAT_TINT[c.id] || c.color}
              active={category === c.id}
              onClick={() => {
                // Toggle: click active chip again clears filter
                setCategory(category === c.id ? null : c.id)
                setLane('all')
              }}
            />
          ))}
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search briefs — Roth, IRMAA, SCHD, Fed, thesis…"
            style={{
              flex: '1 1 260px', minWidth: 200, fontSize: 13.5, padding: '11px 14px', borderRadius: 12,
              border: `1px solid ${C.lineStrong}`, background: 'rgba(0,0,0,.25)', color: C.ink,
              outline: 'none',
            }}
          />
          <SoftChip label="High priority" color={C.macro} active={priority === 'high'}
            onClick={() => setPriority(priority === 'high' ? null : 'high')} />
          <SoftChip label="Holdings" color={C.income} active={holdingsOnly}
            onClick={() => setHoldingsOnly(v => !v)} />
          <SoftChip label="★ Starred" color={C.star} active={starredOnly}
            onClick={() => setStarredOnly(v => !v)} />
          <SoftChip label="Archive" color={C.archive} active={includeArchived}
            onClick={() => setIncludeArchived(v => !v)} />
          {(['live', 'fresh', 'aging', 'stale'] as const).map(t => (
            <SoftChip key={t} label={`${t}${tierCounts[t] != null ? ` ${tierCounts[t]}` : ''}`}
              color={TIER[t].color} active={freshness === t}
              onClick={() => setFreshness(freshness === t ? null : t)} />
          ))}
          {hasActiveFilters && (
            <button type="button" onClick={clearFilters} style={{
              fontSize: 11, fontWeight: 750, padding: '6px 12px', borderRadius: 999, cursor: 'pointer',
              border: `1px solid ${C.lineStrong}`, background: 'rgba(255,255,255,0.04)', color: C.ink,
            }}>
              Clear all filters
            </button>
          )}
        </div>
        {hasActiveFilters && (
          <div style={{ marginTop: 10, fontSize: 12, color: C.soft }}>
            Active:{' '}
            {lane !== 'all' && <span style={{ color: C.accent }}>lane={lane} </span>}
            {category && <span style={{ color: CAT_TINT[category] || C.accent }}>category={catMeta[category]?.label || category} </span>}
            {freshness && <span style={{ color: TIER[freshness]?.color || C.muted }}>freshness={freshness} </span>}
            {priority && <span>priority={priority} </span>}
            {holdingsOnly && <span>holdings </span>}
            {starredOnly && <span>starred </span>}
            {q.trim() && <span>q=“{q.trim()}” </span>}
            {stats.matched === 0 && (
              <span style={{ color: C.stale }}> · no stories match — clear filters or pick another chip</span>
            )}
          </div>
        )}
      </section>

      {/* Filtered strip — always visible when not full desk */}
      {hasActiveFilters && (stats.universe != null || stats.matched != null) && (
        <div style={{
          padding: '10px 14px', borderRadius: 12, display: 'flex', flexWrap: 'wrap', gap: 10,
          alignItems: 'center', justifyContent: 'space-between',
          border: `1px solid ${C.accent}44`, background: C.accentSoft, fontSize: 12.5, color: C.ink,
        }}>
          <span>
            Showing <b>{stats.matched ?? displayItems.length}</b>
            {stats.universe != null && <> of <b>{stats.universe}</b> desk stories</>}
            {category && <> · category <b style={{ color: CAT_TINT[category] || C.accent }}>{catMeta[category]?.label || category}</b></>}
            {freshness && <> · freshness <b>{freshness}</b></>}
          </span>
          <button type="button" onClick={clearFilters} style={{
            fontSize: 12, fontWeight: 750, padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
            border: `1px solid ${C.accent}66`, background: 'rgba(0,0,0,.2)', color: C.accent,
          }}>
            Show all stories
          </button>
        </div>
      )}

      {/* Stale / retirement SLO banner */}
      {(staleTopics.length > 0 || (retStats && retStats.needs_refresh > 10)) && (
        <div style={{
          padding: '12px 16px', borderRadius: 12,
          border: `1px solid ${C.retire}44`, background: C.retireSoft,
          fontSize: 12.5, color: C.ink, lineHeight: 1.45,
        }}>
          <strong style={{ color: C.retire }}>Desk status · </strong>
          {staleTopics.length > 0 && (
            <>{staleTopics.length} monitors need refresh.{' '}</>
          )}
          {retStats && (
            <>Retirement pillar: {retStats.count} briefs · freshest {retStats.freshest_h}h · {retStats.needs_refresh} aging.</>
          )}
          {staleTopics.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
              {staleTopics.slice(0, 8).map((t: any) => (
                <button key={t.topic_id} type="button"
                  disabled={!!queuedTopics[t.topic_id]}
                  onClick={() => queueResearch({ topic_id: t.topic_id })}
                  title={`age ${t.age_hours ?? '—'}h · max ${t.max_age_hours}h — queue for the after-close research drain`}
                  style={{
                    fontSize: 10.5, fontWeight: 700, padding: '4px 9px', borderRadius: 999, cursor: 'pointer',
                    border: `1px solid ${C.retire}55`, color: queuedTopics[t.topic_id] ? C.soft : C.retire,
                    background: 'transparent',
                  }}>
                  {queuedTopics[t.topic_id] ? `✓ ${t.topic_id} queued` : `↻ Queue ${t.topic_id}`}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ padding: 14, borderRadius: 10, border: `1px solid ${C.lineStrong}`, color: C.caution, fontSize: 13 }}>
          Could not load the intelligence desk: {error}
        </div>
      )}

      {/* Main layout: feed + rail */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) 280px',
        gap: 18,
        alignItems: 'start',
      }}
        className="ri-desk-grid"
      >
        <main style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
          {loading && !data ? (
            <div style={{ padding: 56, textAlign: 'center', color: C.soft, fontSize: 13 }}>
              Composing intelligence briefings…
            </div>
          ) : displayItems.length === 0 ? (
            <div style={{
              padding: 48, textAlign: 'center', color: C.muted, fontSize: 13,
              border: `1px dashed ${C.line}`, borderRadius: 16, background: C.card,
            }}>
              <div style={{ fontWeight: 750, color: C.ink, marginBottom: 8 }}>No stories match these filters</div>
              {category === 'compounding_wealth' && (
                <div style={{ marginBottom: 10, maxWidth: 420, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.5 }}>
                  <strong style={{ color: C.ink }}>Compounding & long-term wealth</strong> has no primary-tagged
                  briefs yet (we no longer mis-tag “growth compounder” tickers as compounding).
                  Desk still has {stats.universe ?? stats.by_category?.retirement_tax ?? 'many'} other stories —
                  clear filters or open Retirement / Dividends.
                </div>
              )}
              {freshness === 'live' && (tierCounts.live || 0) === 0 && (
                <div style={{ marginBottom: 10, lineHeight: 1.5 }}>
                  Nothing is in the <strong style={{ color: C.live }}>live</strong> tier (≤2h) right now.
                  Try <strong style={{ color: C.fresh }}>fresh</strong> or clear freshness.
                </div>
              )}
              {category && category !== 'compounding_wealth' && (
                <div style={{ marginBottom: 8 }}>
                  Category <strong>{catMeta[category]?.label || category}</strong> has{' '}
                  {stats.by_category?.[category] ?? 0} primary items on the full desk
                  {stats.matched === 0 ? ' but none survive the other active filters' : ''}.
                </div>
              )}
              <button type="button" onClick={clearFilters} style={{
                marginTop: 8, fontSize: 12, fontWeight: 750, padding: '8px 16px', borderRadius: 10,
                cursor: 'pointer', border: `1px solid ${C.accent}55`, background: C.accentSoft, color: C.accent,
              }}>
                Clear all filters → show full desk
              </button>
            </div>
          ) : (
            <>
              {featured && view !== 'compact' && (
                <div>
                  <div style={{
                    fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase',
                    color: C.soft, marginBottom: 10,
                  }}>
                    {lane === 'retirement' ? 'Featured · Retirement desk' : 'Featured briefing'}
                  </div>
                  <ArticleCard
                    item={featured}
                    catMeta={catMeta}
                    featured
                    view={view === 'cards' ? 'list' : view}
                    onOpen={() => openItem(featured)}
                    onFeedback={onFeedback}
                    onStage={handleStage}
                    onThemeClick={handleThemeClick}
                    staging={staging}
                  />
                </div>
              )}

              {/* C3: Hermes alert wire — score spikes / rank surges / divergence flips (48h) */}
              {lane === 'all' && (data?.hermes_wire?.length ?? 0) > 0 && (
                <section>
                  <div style={{
                    fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase',
                    color: C.soft, marginBottom: 8,
                  }}>
                    Hermes wire
                    <span style={{ fontWeight: 600, marginLeft: 8, letterSpacing: 0, textTransform: 'none' }}>
                      composite moves · rank surges · analyst divergence · 48h
                    </span>
                  </div>
                  <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 12, overflow: 'hidden' }}>
                    {(data.hermes_wire as {
                      alert_type?: string; symbol?: string; text?: string; created_at?: string
                    }[]).map((w, i) => (
                      <Link key={`${w.symbol}-${i}`} to="/hermes" style={{
                        display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px',
                        borderBottom: `1px solid ${C.line}`, fontSize: 12, textDecoration: 'none', color: C.ink,
                      }}>
                        <span style={{ fontFamily: 'var(--mono)', fontWeight: 800, color: C.accent, minWidth: 52 }}>
                          {w.symbol}
                        </span>
                        <span style={{ color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                          {w.text}
                        </span>
                        <span style={{ color: C.soft, fontSize: 10.5, whiteSpace: 'nowrap' }}>
                          {fmtET(w.created_at)}
                        </span>
                      </Link>
                    ))}
                  </div>
                </section>
              )}

              <div style={{
                fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase',
                color: C.soft, marginTop: featured && view !== 'compact' ? 6 : 0,
              }}>
                {view === 'compact' ? 'Wire feed' : 'Latest briefings'}
                <span style={{ fontWeight: 600, color: C.soft, marginLeft: 8, letterSpacing: 0, textTransform: 'none' }}>
                  {rest.length + (featured && view === 'compact' ? 1 : 0)} stories
                </span>
              </div>

              {view === 'compact' ? (
                <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 14, overflow: 'hidden' }}>
                  {displayItems.map(item => (
                    <ArticleCard key={item.id} item={item} catMeta={catMeta} view="compact"
                      onOpen={() => openItem(item)} onFeedback={onFeedback}
                      onStage={handleStage} onThemeClick={handleThemeClick} staging={staging} />
                  ))}
                </div>
              ) : view === 'cards' ? (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
                  gap: 14,
                }}>
                  {rest.map(item => (
                    <ArticleCard key={item.id} item={item} catMeta={catMeta} view="cards"
                      onOpen={() => openItem(item)} onFeedback={onFeedback}
                      onStage={handleStage} onThemeClick={handleThemeClick} staging={staging} />
                  ))}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {rest.map(item => (
                    <ArticleCard key={item.id} item={item} catMeta={catMeta} view="list"
                      onOpen={() => openItem(item)} onFeedback={onFeedback}
                      onStage={handleStage} onThemeClick={handleThemeClick} staging={staging} />
                  ))}
                </div>
              )}

              {/* Queued research — un-run topics are work, not intelligence (v3 B1) */}
              {(data?.queued_research?.length ?? 0) > 0 && (
                <section style={{ marginTop: 8 }}>
                  <div style={{
                    fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase',
                    color: C.soft, marginBottom: 8,
                  }}>
                    Queued research
                    <span style={{ fontWeight: 600, marginLeft: 8, letterSpacing: 0, textTransform: 'none' }}>
                      {data.queued_research.length} topics awaiting a research run — not briefings
                    </span>
                  </div>
                  <div style={{ background: C.card, border: `1px dashed ${C.lineStrong}`, borderRadius: 12, overflow: 'hidden' }}>
                    {(data.queued_research as {
                      id: string; title?: string; primary_category?: string
                      freshness_label?: string; source_system?: string; needs_refresh?: boolean
                      source_table?: string; source_id?: string | number
                    }[]).slice(0, 15).map(qi => {
                      const topicId = qi.source_table === 'topic_monitor' ? String(qi.source_id || '') : ''
                      return (
                      <div key={qi.id} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
                        padding: '8px 12px', borderBottom: `1px solid ${C.line}`, fontSize: 12,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                          <span style={{ color: C.soft, whiteSpace: 'nowrap', fontSize: 10, fontWeight: 700 }}>QUEUED</span>
                          <span style={{ color: C.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {qi.title}
                          </span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap' }}>
                          <span style={{ color: CAT_TINT[qi.primary_category || ''] || C.soft, fontSize: 10.5 }}>
                            {catMeta[qi.primary_category || '']?.label || qi.primary_category}
                          </span>
                          {qi.freshness_label && <span style={{ color: C.soft, fontSize: 10.5 }}>{qi.freshness_label}</span>}
                          {topicId ? (
                            <button type="button"
                              disabled={!!queuedTopics[topicId]}
                              onClick={() => queueResearch({ topic_id: topicId })}
                              style={{
                                fontSize: 10.5, fontWeight: 700, padding: '3px 9px', borderRadius: 999,
                                cursor: 'pointer', border: `1px solid ${C.accent}55`,
                                color: queuedTopics[topicId] ? C.soft : C.accent, background: 'transparent',
                              }}>
                              {queuedTopics[topicId] ? '✓ Queued for after close' : '▸ Run research'}
                            </button>
                          ) : (
                            <span style={{ color: C.soft, fontSize: 10, fontStyle: 'italic' }}>no monitor linked</span>
                          )}
                        </div>
                      </div>
                      )
                    })}
                  </div>
                </section>
              )}

              {/* v3.1 (B2): hidden fold — curation states, never deletions */}
              {(stats.hidden_count ?? 0) > 0 && (
                <details style={{ marginTop: 6 }}>
                  <summary style={{ fontSize: 11, color: C.soft, cursor: 'pointer' }}>
                    {stats.hidden_count} hidden · show
                  </summary>
                  {(data?.hidden_items || []).map((hi: { id: string; title?: string; symbol?: string }) => (
                    <div key={hi.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 10px', fontSize: 11.5, color: C.soft }}>
                      {hi.symbol && <span style={{ fontFamily: 'var(--mono)', fontWeight: 800 }}>{hi.symbol}</span>}
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{hi.title}</span>
                      <button type="button"
                        onClick={async () => {
                          await postFeedback({ item_id: hi.id, hidden: false })
                          setToast('Unhidden — back on the desk after refresh')
                          refetch()
                        }}
                        style={{ fontSize: 10, fontWeight: 700, color: C.accent, border: `1px solid ${C.accent}44`, background: 'transparent', borderRadius: 6, padding: '2px 8px', cursor: 'pointer' }}>
                        Unhide
                      </button>
                    </div>
                  ))}
                </details>
              )}
            </>
          )}
        </main>

        {/* Right rail */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 12, position: 'sticky', top: 12 }}>
          {stagedIdeas.length > 0 && (
            <RailCard title="Staged Ideas" accent={C.income}>
              <div style={{ fontSize: 11, color: C.muted, marginBottom: 6 }}>{stagedIdeas.length} active</div>
              {stagedIdeas.slice(0, 5).map(idea => (
                <div key={idea.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0', borderBottom: `1px solid ${C.line}` }}>
                  <span style={{ fontFamily: 'var(--mono)', fontWeight: 800, color: C.accent }}>{idea.symbol}</span>
                  <span style={{ color: C.soft, fontSize: 10 }}>{idea.side}</span>
                </div>
              ))}
              <button type="button" onClick={() => setShowStaged(true)} style={{
                marginTop: 8, fontSize: 11, fontWeight: 750, border: 'none', background: 'transparent',
                color: C.income, cursor: 'pointer', padding: 0,
              }}>
                Open panel →
              </button>
            </RailCard>
          )}
          {/* v3 (D4): categories under their fresh-brief floor — actionable */}
          {(freshData?.coverage_gaps?.length ?? 0) > 0 && (
            <RailCard title="Coverage gaps" accent={C.stale}>
              <div style={{ fontSize: 11, color: C.soft, marginBottom: 6 }}>
                Fresh briefs below the category floor — queue for after close
              </div>
              {(freshData.coverage_gaps as {
                category: string; fresh_briefs: number; floor: number
              }[]).slice(0, 6).map(g => (
                <div key={g.category} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  gap: 8, fontSize: 12, padding: '4px 0', borderBottom: `1px solid ${C.line}`,
                }}>
                  <span style={{ color: CAT_TINT[g.category] || C.ink }}>
                    {catMeta[g.category]?.label || g.category}
                    <span style={{ color: C.soft, marginLeft: 6, fontSize: 10.5 }}>
                      {g.fresh_briefs}/{g.floor}
                    </span>
                  </span>
                  <button type="button"
                    disabled={!!queuedTopics[g.category]}
                    onClick={() => queueResearch({ category: g.category })}
                    style={{
                      fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 999,
                      cursor: 'pointer', border: `1px solid ${C.stale}55`,
                      color: queuedTopics[g.category] ? C.soft : C.stale, background: 'transparent',
                    }}>
                    {queuedTopics[g.category] ? '✓ Queued' : 'Queue'}
                  </button>
                </div>
              ))}
            </RailCard>
          )}

          {/* v3 (D5): Hermes Discovery TOPIC_CANDIDATE proposals — operator decides */}
          <RailCard title="Proposed topics" accent={C.macro}>
            {(proposedData?.candidates?.length ?? 0) > 0 ? (
              (proposedData.candidates as {
                id: number; label?: string; summary?: string; discovery_score?: number
              }[]).slice(0, 5).map(cand => (
                <div key={cand.id} style={{ padding: '6px 0', borderBottom: `1px solid ${C.line}` }}>
                  <div style={{ fontSize: 12, color: C.ink, lineHeight: 1.35 }}>{cand.label}</div>
                  {cand.summary && (
                    <div style={{ fontSize: 10.5, color: C.soft, lineHeight: 1.35, marginTop: 2, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                      {cand.summary}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 6, marginTop: 5 }}>
                    <button type="button" onClick={() => decideProposedTopic(cand.id, 'approve-research-topic')}
                      style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 999, cursor: 'pointer', border: `1px solid ${C.income}55`, color: C.income, background: 'transparent' }}>
                      Approve → topic
                    </button>
                    <button type="button" onClick={() => decideProposedTopic(cand.id, 'reject')}
                      style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 999, cursor: 'pointer', border: `1px solid ${C.lineStrong}`, color: C.soft, background: 'transparent' }}>
                      Dismiss
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 11, color: C.soft }}>
                No topic candidates in the Discovery Inbox — verified empty, not an error.
              </div>
            )}
          </RailCard>

          {!!(data?.portfolio_context?.top?.length) && (
            <RailCard title="Book weights" accent={C.income}>
              <div style={{ fontSize: 11, color: C.soft, marginBottom: 6 }}>
                ${(Number(data.portfolio_context.total_mv || 0) / 1e6).toFixed(2)}M securities (ex-cash) — top-strip Portfolio includes cash
              </div>
              {(data.portfolio_context.top as {
                symbol: string
                weight_pct: number
                concentration_level?: string
              }[]).slice(0, 8).map(t => {
                const lvl = t.concentration_level || 'normal'
                const lc = CONC_COLOR[lvl] || C.ink
                return (
                  <div key={t.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 12, padding: '3px 0', gap: 8 }}>
                    <span style={{ fontFamily: 'var(--mono)', fontWeight: 800, color: C.accent }}>{t.symbol}</span>
                    <span style={{ color: lc, fontWeight: 700 }}>
                      {t.weight_pct}%
                      {lvl !== 'normal' ? (
                        <span style={{ fontSize: 9, marginLeft: 5, opacity: 0.9, textTransform: 'uppercase' }}>{lvl}</span>
                      ) : null}
                    </span>
                  </div>
                )
              })}
              {((data.portfolio_context.flags as string[]) || []).slice(0, 3).map((f: string) => (
                <div key={f} style={{ fontSize: 11, color: C.stale, marginTop: 6, lineHeight: 1.4 }}>{f}</div>
              ))}
            </RailCard>
          )}
          {!!(data?.portfolio_context?.heat || data?.portfolio_context?.concentration) && (
            <RailCard title="Concentration & heat" accent={C.stale}>
              {data.portfolio_context.heat && (
                <>
                  <RailStat
                    label="Portfolio heat"
                    value={`${Number(data.portfolio_context.heat.portfolio_heat_pct || 0).toFixed(1)}%`}
                  />
                  <RailStat
                    label="Heat level"
                    value={String(data.portfolio_context.heat.level || '—')}
                  />
                  {data.portfolio_context.heat.pct_protected != null && (
                    <RailStat
                      label="Protected MV"
                      value={`${Number(data.portfolio_context.heat.pct_protected).toFixed(0)}%`}
                    />
                  )}
                </>
              )}
              {data.portfolio_context.concentration && (
                <>
                  <RailStat
                    label="Book concentration"
                    value={String(data.portfolio_context.concentration.book_level || '—')}
                  />
                  <RailStat
                    label="Top-3 weight"
                    value={
                      data.portfolio_context.concentration.top3_pct != null
                        ? `${Number(data.portfolio_context.concentration.top3_pct).toFixed(0)}%`
                        : '—'
                    }
                  />
                </>
              )}
              {data.portfolio_context.theme_capacity && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.soft, marginBottom: 4 }}>
                    Theme capacity
                  </div>
                  {Object.entries(data.portfolio_context.theme_capacity as Record<string, {
                    current_pct?: number
                    room_pct?: number
                    target_max_pct?: number
                    level?: string
                  }>)
                    .filter(([, v]) => (v.current_pct || 0) > 0)
                    .sort((a, b) => (b[1].current_pct || 0) - (a[1].current_pct || 0))
                    .slice(0, 6)
                    .map(([tid, v]) => (
                      <div key={tid} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0', color: C.muted }}>
                        <span>{tid.replace(/_/g, ' ')}</span>
                        <span style={{ color: CONC_COLOR[v.level || ''] || C.ink, fontWeight: 700 }}>
                          {Number(v.current_pct || 0).toFixed(1)}%
                          <span style={{ color: C.soft, fontWeight: 500 }}>
                            {' '}/ {Number(v.target_max_pct || 0).toFixed(0)}%
                          </span>
                        </span>
                      </div>
                    ))}
                </div>
              )}
              <p style={{ margin: '8px 0 0', fontSize: 11, lineHeight: 1.45, color: C.soft }}>
                High concentration and heat shrink new-add size bands and prefer funding trims (e.g. SCHG).
              </p>
            </RailCard>
          )}
          <RailCard title="Retirement pillar" accent={C.retire}>
            <RailStat label="Briefs in filter" value={String(stats.by_category?.retirement_tax ?? retStats?.count ?? '—')} />
            <RailStat label="Freshest" value={retStats?.freshest_h != null ? `${retStats.freshest_h}h` : '—'} />
            <RailStat label="Needs refresh" value={String(retStats?.needs_refresh ?? '—')} />
            <p style={{ margin: '8px 0 0', fontSize: 12, lineHeight: 1.5, color: C.muted }}>
              Roth ladder, Golden Window, IRMAA, conversion pacing, SSDI & MAPT stay on a tight monitor cadence.
            </p>
            <Link to="/retirement" style={{ ...navLink(C.retire), display: 'inline-block', marginTop: 10 }}>
              Open retirement hub →
            </Link>
          </RailCard>

          <RailCard title="Freshness" accent={C.fresh}>
            {(['live', 'fresh', 'aging', 'stale', 'archive'] as const).map(t => (
              <div key={t} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0', color: C.muted }}>
                <FreshnessDot tier={t} />
                <span style={{ color: C.ink, fontWeight: 700 }}>{tierCounts[t] ?? 0}</span>
              </div>
            ))}
            <p style={{ margin: '8px 0 0', fontSize: 11.5, color: C.soft, lineHeight: 1.45 }}>
              Archive never deletes — toggle Archive in filters to search history.
            </p>
          </RailCard>

          <RailCard title="Desk links" accent={C.accent}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Link to="/intelligence?tab=research" style={navLink(C.muted)}>Legacy research topics</Link>
              <Link to="/watch" style={navLink(C.muted)}>Watchlist</Link>
              <Link to="/rebalance" style={navLink(C.muted)}>Rebalance</Link>
              <Link to="/agents" style={navLink(C.muted)}>Agents</Link>
            </div>
          </RailCard>

          <div style={{ fontSize: 10.5, color: C.soft, lineHeight: 1.5, padding: '0 4px' }}>
            {data?.note}
          </div>
        </aside>
      </div>

      <style>{`
        @media (max-width: 980px) {
          .ri-desk-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  )
}

function RailCard({ title, accent, children }: { title: string; accent: string; children: ReactNode }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.line}`, borderRadius: 14, padding: 14,
      borderTop: `2px solid ${accent}66`,
    }}>
      <div style={{
        fontSize: 10, fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase',
        color: accent, marginBottom: 10,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function RailStat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '3px 0' }}>
      <span style={{ color: C.muted }}>{label}</span>
      <span style={{ color: C.ink, fontWeight: 750 }}>{value}</span>
    </div>
  )
}

const navLink = (c: string): CSSProperties => ({
  fontSize: 12, fontWeight: 650, color: c, textDecoration: 'none',
})

const refreshBtn: CSSProperties = {
  fontSize: 12, fontWeight: 750, padding: '7px 12px', borderRadius: 10, cursor: 'pointer',
  border: `1px solid ${C.accent}55`, background: C.accentSoft, color: C.accent,
}
