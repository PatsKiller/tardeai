/**
 * Research Intelligence v2.6 — editorial intelligence desk (CC v3).
 * Transparent conviction, data gates, analyst/options snapshots, action bar.
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
  operator_note?: string | null
  status?: string
  investment_implications?: string
  ticker_recommendations?: {
    symbol?: string
    role?: string
    suggested_weight_pct?: string | null
    rationale?: string
    conviction_tier?: string
    conviction_score?: number
    conviction_breakdown?: Record<string, number>
    conviction_breakdown_lines?: string[]
    why_selected?: string
    data_complete?: boolean
    incomplete_reason?: string
    technical_snapshot?: Record<string, unknown>
    analyst_snapshot?: Record<string, unknown>
    options_flow_snapshot?: Record<string, unknown>
    actions?: { id?: string; label?: string; href?: string }[]
    security?: {
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
      iv_rank?: number | null
      options_sentiment?: string
      data_complete?: boolean
    }
  }[]
  sizing_guidance?: string
  sizing_reason?: string | null
  risk_caveat?: string
  quality_tier?: 'A' | 'B' | 'C' | string
  actions?: { id?: string; label?: string; href?: string }[]
  quality_gate?: { pass?: boolean; note?: string | null; incomplete_tickers?: number }
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

/* Soft editorial palette — pleasant, not alarm-heavy */
const C = {
  ink: '#e8eef7',
  muted: '#8b95a8',
  soft: '#5c6578',
  card: 'rgba(22, 28, 42, 0.92)',
  cardHover: 'rgba(28, 36, 54, 0.98)',
  line: 'rgba(120, 140, 180, 0.14)',
  lineStrong: 'rgba(120, 140, 180, 0.22)',
  accent: '#7eb6ff',
  accentSoft: 'rgba(126, 182, 255, 0.12)',
  retire: '#c4a1ff',
  retireSoft: 'rgba(196, 161, 255, 0.12)',
  income: '#6ee7b7',
  incomeSoft: 'rgba(110, 231, 183, 0.10)',
  macro: '#fcd34d',
  macroSoft: 'rgba(252, 211, 77, 0.10)',
  live: '#34d399',
  fresh: '#7dd3fc',
  aging: '#fbbf24',
  stale: '#fb923c',
  archive: '#94a3b8',
  bull: '#6ee7b7',
  bear: '#f9a8d4',
  star: '#fde68a',
  cta: '#93c5fd',
  ctaBg: 'linear-gradient(135deg, rgba(96,165,250,.18), rgba(167,139,250,.12))',
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
  compounding_wealth: '#5eead4',
  risk_regime: '#fca5a5',
  catalyst_event: '#fcd34d',
  company_ticker: '#94a3b8',
  academic_pro: '#d8b4fe',
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

function FreshnessDot({ tier, label }: { tier?: string; label?: string }) {
  const t = TIER[tier || 'aging'] || TIER.aging
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: t.color, fontWeight: 600 }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%', background: t.color,
        boxShadow: `0 0 8px ${t.color}88`,
      }} />
      {label || t.label}
    </span>
  )
}

const ROLE_COLOR: Record<string, string> = {
  add_candidate: C.income,
  trim_candidate: C.bear,
  hold_review: C.accent,
  protect: C.stale,
  watchlist: C.macro,
  plan: C.retire,
  context: C.soft,
}

const QUALITY: Record<string, { color: string; label: string; hint: string }> = {
  A: { color: C.income, label: 'Tier A', hint: 'Deep + portfolio-aware' },
  B: { color: C.accent, label: 'Tier B', hint: 'Solid advisory floor' },
  C: { color: C.soft, label: 'Tier C', hint: 'Thin — verify sources' },
}

const CONC_COLOR: Record<string, string> = {
  extreme: C.bear,
  high: C.stale,
  caution: C.macro,
  elevated: C.aging,
  normal: C.income,
  full: C.stale,
  moderate: C.aging,
  room: C.income,
}

function ActionStrip({ item, catColor }: { item: Item; catColor: string }) {
  const label = item.next_action_label || item.next_action?.label || item.actionability || 'Read full analysis'
  const detail = item.next_action_detail || item.next_action?.detail || item.why_it_matters || ''
  const ticks = item.ticker_recommendations || []
  const hasAdvisory = ticks.length > 0 || !!item.sizing_guidance || !!item.investment_implications
  return (
    <div style={{
      marginTop: 2, padding: '14px 16px', borderRadius: 12,
      background: hasAdvisory
        ? `linear-gradient(145deg, ${catColor}16 0%, rgba(96,165,250,.12) 45%, rgba(167,139,250,.10) 100%)`
        : C.ctaBg,
      border: `1px solid ${hasAdvisory ? `${catColor}55` : `${catColor}44`}`,
      display: 'flex', flexDirection: 'column', gap: 10,
      boxShadow: `inset 0 0 0 1px ${catColor}14, 0 4px 16px rgba(0,0,0,.12)`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.cta }}>
          Recommended next step
        </div>
        {hasAdvisory && (
          <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.macro }}>
            Portfolio-aware
          </div>
        )}
      </div>
      <div style={{ fontSize: 14.5, fontWeight: 800, color: C.ink, letterSpacing: '-0.01em' }}>{label}</div>
      {detail && (
        <div style={{ fontSize: 12.5, color: C.muted, lineHeight: 1.5 }}>{detail}</div>
      )}
      {item.investment_implications && (
        <div style={{
          fontSize: 12.5, color: C.ink, lineHeight: 1.55,
          padding: '8px 10px', borderRadius: 8,
          background: 'rgba(0,0,0,.18)', border: `1px solid ${C.line}`,
        }}>
          <span style={{ fontWeight: 800, color: catColor }}>Investment implications · </span>
          {item.investment_implications}
        </div>
      )}
      {ticks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.ink }}>
            Tickers & allocation guidance
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
            {ticks.slice(0, 6).map((t, i) => {
              const role = t.role || 'review'
              const rc = ROLE_COLOR[role] || C.accent
              const ct = t.conviction_tier
              const qc = ct && QUALITY[ct] ? QUALITY[ct].color : C.soft
              const sec = t.security
              return (
                <div key={`${t.symbol}-${i}`} style={{
                  border: `1px solid ${rc}55`, background: `${rc}14`, borderRadius: 9,
                  padding: '8px 11px', minWidth: 148, maxWidth: 260,
                  boxShadow: `0 2px 8px ${rc}12`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                    <span style={{ fontFamily: 'var(--mono)', fontWeight: 900, fontSize: 14, color: C.accent }}>
                      {t.symbol}
                    </span>
                    <span style={{ fontSize: 9, fontWeight: 800, color: rc, textTransform: 'uppercase' }}>
                      {(role || '').replace(/_/g, ' ')}
                    </span>
                  </div>
                  {ct && (
                    <div
                      style={{ fontSize: 10, fontWeight: 800, color: qc, marginTop: 2, cursor: 'help' }}
                      title={(t.conviction_breakdown_lines || []).join('\n') || 'Conviction score'}
                    >
                      Conv {ct}{t.conviction_score != null ? ` · ${Number(t.conviction_score).toFixed(0)}` : ''}
                      {t.data_complete === false ? ' · incomplete' : ''}
                    </div>
                  )}
                  {t.suggested_weight_pct && (
                    <div style={{ fontSize: 12, fontWeight: 800, color: C.ink, marginTop: 3, letterSpacing: '-0.01em' }}>
                      {t.suggested_weight_pct}
                    </div>
                  )}
                  {/* Technical snapshot */}
                  {(sec?.rsi != null || sec?.rel_strength_vs_spy_month_pct != null || sec?.sma50_pct != null) && (
                    <div style={{ fontSize: 10, color: C.soft, marginTop: 4, lineHeight: 1.4 }}>
                      <div style={{ fontWeight: 750, color: C.ink, marginBottom: 1 }}>Technicals</div>
                      {sec?.rsi != null && <span>RSI {Number(sec.rsi).toFixed(0)} ({sec.rsi_status || '—'}) · </span>}
                      {sec?.rel_strength_vs_spy_month_pct != null && (
                        <span>vs SPY {Number(sec.rel_strength_vs_spy_month_pct) >= 0 ? '+' : ''}{Number(sec.rel_strength_vs_spy_month_pct).toFixed(1)}% · </span>
                      )}
                      {sec?.rel_strength_vs_qqq_month_pct != null && (
                        <span>vs QQQ {Number(sec.rel_strength_vs_qqq_month_pct) >= 0 ? '+' : ''}{Number(sec.rel_strength_vs_qqq_month_pct).toFixed(1)}% · </span>
                      )}
                      {sec?.sma50_pct != null && <span>SMA50 {Number(sec.sma50_pct) >= 0 ? '+' : ''}{Number(sec.sma50_pct).toFixed(1)}% </span>}
                      {sec?.sma200_pct != null && <span>SMA200 {Number(sec.sma200_pct) >= 0 ? '+' : ''}{Number(sec.sma200_pct).toFixed(1)}%</span>}
                    </div>
                  )}
                  {/* Analyst snapshot */}
                  {(sec?.analyst_rating || sec?.analyst_counts || sec?.pe != null) && (
                    <div style={{ fontSize: 10, color: C.soft, marginTop: 3, lineHeight: 1.4 }}>
                      <div style={{ fontWeight: 750, color: C.ink, marginBottom: 1 }}>Analyst</div>
                      {sec?.analyst_rating && <span>{sec.analyst_rating} </span>}
                      {sec?.analyst_counts?.n != null && (
                        <span>({sec.analyst_counts.buy ?? 0}B/{sec.analyst_counts.hold ?? 0}H/{sec.analyst_counts.sell ?? 0}S) </span>
                      )}
                      {sec?.pe != null && <span>P/E {Number(sec.pe).toFixed(1)} </span>}
                      {sec?.peg != null && <span>PEG {Number(sec.peg).toFixed(2)}</span>}
                      {!sec?.analyst_counts?.n && !sec?.analyst_rating && <span>No coverage flag</span>}
                    </div>
                  )}
                  {/* Options flow */}
                  {sec?.options_sentiment && (
                    <div style={{ fontSize: 10, color: C.soft, marginTop: 3, lineHeight: 1.4 }}>
                      <div style={{ fontWeight: 750, color: C.ink, marginBottom: 1 }}>Options flow</div>
                      <span>{sec.options_sentiment}</span>
                      {sec.iv_rank != null && <span> · IV rank {Number(sec.iv_rank).toFixed(0)}</span>}
                    </div>
                  )}
                  {/* Conviction breakdown (compact) */}
                  {(t.conviction_breakdown_lines || []).length > 0 && (
                    <div
                      style={{ fontSize: 9.5, color: C.muted, marginTop: 4, lineHeight: 1.35, maxHeight: 72, overflow: 'hidden' }}
                      title={(t.conviction_breakdown_lines || []).join('\n')}
                    >
                      {(t.conviction_breakdown_lines || []).slice(0, 5).map((line, li) => (
                        <div key={li}>{line}</div>
                      ))}
                    </div>
                  )}
                  {(t.why_selected || t.rationale) && (
                    <div style={{ fontSize: 10.5, color: C.muted, lineHeight: 1.35, marginTop: 3 }}>
                      {t.why_selected || t.rationale}
                    </div>
                  )}
                  {t.data_complete === false && (
                    <div style={{ fontSize: 10, color: C.stale, fontWeight: 700, marginTop: 3 }}>
                      {t.incomplete_reason || 'Incomplete data — lower confidence'}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {item.sizing_guidance && (
        <div style={{
          fontSize: 12.5, color: C.ink, lineHeight: 1.5,
          padding: '9px 11px', borderRadius: 8,
          background: `${C.macro}12`, border: `1px solid ${C.macro}44`,
        }}>
          <span style={{ fontWeight: 800, color: C.macro }}>Sizing guidance · </span>
          {item.sizing_guidance}
        </div>
      )}
      {item.sizing_reason && (
        <div style={{ fontSize: 11.5, color: C.muted, lineHeight: 1.45 }}>
          <span style={{ fontWeight: 750, color: C.soft }}>Why this size · </span>
          {item.sizing_reason}
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
        <div style={{ fontSize: 11, color: C.stale, lineHeight: 1.4 }}>
          {item.quality_gate.note}
        </div>
      )}
      {/* Action bar */}
      {((item.actions && item.actions.length > 0) || ticks.some(t => (t.actions || []).length > 0)) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
          {(item.actions && item.actions.length > 0
            ? item.actions
            : (ticks[0]?.actions || [])
          ).slice(0, 5).map((a, i) => (
            <Link
              key={`${a.id || a.label}-${i}`}
              to={a.href || '/watch'}
              onClick={e => e.stopPropagation()}
              style={{
                fontSize: 11, fontWeight: 750, textDecoration: 'none',
                padding: '6px 10px', borderRadius: 8,
                border: `1px solid ${C.accent}55`, background: `${C.accent}18`, color: C.accent,
              }}
            >
              {a.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

function ArticleCard({
  item, catMeta, featured, view, onOpen, onFeedback,
}: {
  item: Item
  catMeta: Record<string, Cat>
  featured?: boolean
  view: 'cards' | 'list' | 'compact'
  onOpen: () => void
  onFeedback: (id: string, patch: Partial<Item>) => void
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
        <FreshnessDot tier={item.freshness_tier} label={item.freshness_label} />
      </div>
    )
  }

  const shell: CSSProperties = {
    borderRadius: featured ? 18 : 14,
    border: `1px solid ${featured ? `${catColor}44` : C.line}`,
    background: featured
      ? `linear-gradient(155deg, ${catColor}14 0%, ${C.card} 42%, rgba(12,16,28,.95) 100%)`
      : C.card,
    padding: featured ? '22px 24px' : view === 'list' ? '18px 20px' : '16px 18px',
    cursor: 'pointer',
    display: 'flex',
    flexDirection: 'column',
    gap: featured ? 14 : 11,
    boxShadow: featured ? `0 12px 40px rgba(0,0,0,.28), 0 0 0 1px ${catColor}18` : '0 4px 18px rgba(0,0,0,.18)',
    transition: 'border-color .15s, transform .12s, background .15s',
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
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = `${catColor}66` }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = featured ? `${catColor}44` : C.line }}
    >
      {/* top accent */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: featured ? 3 : 2,
        background: `linear-gradient(90deg, ${catColor}, transparent 70%)`,
      }} />

      {/* meta row */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, alignItems: 'center' }}>
          <button type="button" onClick={toggleStar} style={iconBtn(item.starred ? C.star : C.soft)} title="Star">
            {item.starred ? '★' : '☆'}
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
          {(item.ticker_recommendations?.length ?? 0) > 0 && (
            <Tag color={C.macro}>Tickers & size</Tag>
          )}
          {item.portfolio_snapshot?.concentration?.book_level &&
            item.portfolio_snapshot.concentration.book_level !== 'normal' && (
            <Tag color={CONC_COLOR[item.portfolio_snapshot.concentration.book_level] || C.stale}>
              Conc. {item.portfolio_snapshot.concentration.book_level}
            </Tag>
          )}
          {item.is_archived && <Tag color={C.archive}>Archived</Tag>}
          {item.needs_refresh && <Tag color={C.stale}>Due refresh</Tag>}
          {item.priority === 'high' && <Tag color={C.macro}>Priority</Tag>}
          {item.sentiment && item.sentiment !== 'neutral' && (
            <Tag color={item.sentiment === 'bullish' ? C.bull : C.bear}>{item.sentiment}</Tag>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <FreshnessDot tier={item.freshness_tier} label={item.freshness_label} />
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
        <FreshnessDot tier={item.freshness_tier} label={item.freshness_label} />
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
          {(item.ticker_recommendations?.length ?? 0) > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {item.ticker_recommendations!.slice(0, 4).map((t, i) => {
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
          )}
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

      <ActionStrip item={item} catColor={catColor} />

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
    p.set('limit', '100')
    return p.toString()
  }, [q, category, priority, holdingsOnly, includeArchived, starredOnly, freshness, sentiment])

  const { data, loading, error, refetch } = useApi<any>(
    `/api/v2/research-intelligence?${qs}`,
    90_000,
  )
  const { data: freshData } = useApi<any>('/api/v2/research-intelligence/freshness', 120_000)

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

  const lanes = data?.priority_lanes || {}
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
    // Lanes use server priority_lanes when available (full universe, not empty filter page)
    if (lane === 'retirement') {
      const laneItems = (lanes.retirement as Item[] | undefined) || []
      if (laneItems.length) return laneItems.map(it => ({ ...it, ...(localPatch[it.id] || {}) }))
      return items.filter(i => i.primary_category === 'retirement_tax')
    }
    if (lane === 'dividends') {
      const laneItems = (lanes.dividends as Item[] | undefined) || []
      if (laneItems.length) return laneItems.map(it => ({ ...it, ...(localPatch[it.id] || {}) }))
      return items.filter(i => i.primary_category === 'dividend_income')
    }
    if (lane === 'macro_sector') {
      const laneItems = (lanes.macro_sector as Item[] | undefined) || []
      if (laneItems.length) return laneItems.map(it => ({ ...it, ...(localPatch[it.id] || {}) }))
      return items.filter(i =>
        i.primary_category === 'macro_geo' || i.primary_category === 'sector_thematic')
    }
    // Category already applied server-side; keep items as returned
    return items
  }, [lane, items, lanes, localPatch])

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
        borderRadius: 18,
        padding: '20px 22px',
        background: 'linear-gradient(135deg, rgba(30,41,72,.9) 0%, rgba(18,22,36,.95) 55%, rgba(40,28,58,.55) 100%)',
        border: `1px solid ${C.lineStrong}`,
        boxShadow: '0 10px 36px rgba(0,0,0,.25)',
      }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 14 }}>
          <div style={{ maxWidth: 720 }}>
            <div style={{
              fontSize: 11, fontWeight: 800, letterSpacing: '0.14em', textTransform: 'uppercase',
              color: C.retire, marginBottom: 8,
            }}>
              Command Center · Intelligence Desk
            </div>
            <div style={{ ...hubTitle(), fontSize: 26, letterSpacing: '-0.03em', marginBottom: 6 }}>
              Research Intelligence
            </div>
            <div style={{ ...hubSubtitle(terminalUi), fontSize: 13.5, lineHeight: 1.5, color: C.muted, maxWidth: 560 }}>
              Editorial briefings with takeaways, bull/bear framing, and clear next steps —
              retirement, dividends, macro, and holdings-aware research in one desk.
              {stats.matched != null && ` · ${stats.matched} in view`}
              {stats.universe != null && stats.universe !== stats.matched && ` · ${stats.universe} on desk`}
              {loading ? ' · loading…' : ''}
              {data?.version ? ` · v${data.version}` : ''}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
              <Link to="/retirement" style={navLink(C.retire)}>Retirement plan →</Link>
              <Link to="/portfolio" style={navLink(C.income)}>Portfolio →</Link>
              <Link to="/hermes" style={navLink(C.accent)}>Hermes →</Link>
              <Link to="/risk" style={navLink('#fca5a5')}>Risk →</Link>
              <button type="button" onClick={() => refetch()} style={refreshBtn}>↻ Refresh desk</button>
            </div>
            <div style={{ display: 'flex', gap: 14, fontSize: 12, color: C.muted, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <span><b style={{ color: C.live }}>{tierCounts.live || 0}</b> live</span>
              <span><b style={{ color: C.fresh }}>{tierCounts.fresh || 0}</b> fresh</span>
              <span><b style={{ color: C.aging }}>{tierCounts.aging || 0}</b> aging</span>
              <span><b style={{ color: C.stale }}>{tierCounts.stale || 0}</b> stale</span>
              <span><b style={{ color: C.retire }}>{stats.lane_counts?.retirement ?? stats.by_category?.retirement_tax ?? retStats?.count ?? '—'}</b> retirement</span>
            </div>
          </div>
        </div>
      </header>

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
                active={lane === id}
                onClick={() => { setLane(id); if (id !== 'all') setCategory(null) }}
              />
            ))}
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
            <>{staleTopics.length} monitors need refresh
              ({staleTopics.slice(0, 4).map((t: any) => t.topic_id).join(', ')}
              {staleTopics.length > 4 ? '…' : ''}).{' '}
            </>
          )}
          {retStats && (
            <>Retirement pillar: {retStats.count} briefs · freshest {retStats.freshest_h}h · {retStats.needs_refresh} aging.</>
          )}
        </div>
      )}

      {error && (
        <div style={{ padding: 14, borderRadius: 12, border: '1px solid rgba(248,113,113,.35)', color: '#fca5a5', fontSize: 13 }}>
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
                  <strong style={{ color: '#5eead4' }}>Compounding & long-term wealth</strong> has no primary-tagged
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
                  />
                </div>
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
                      onOpen={() => openItem(item)} onFeedback={onFeedback} />
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
                      onOpen={() => openItem(item)} onFeedback={onFeedback} />
                  ))}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {rest.map(item => (
                    <ArticleCard key={item.id} item={item} catMeta={catMeta} view="list"
                      onOpen={() => openItem(item)} onFeedback={onFeedback} />
                  ))}
                </div>
              )}
            </>
          )}
        </main>

        {/* Right rail */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 12, position: 'sticky', top: 12 }}>
          {!!(data?.portfolio_context?.top?.length) && (
            <RailCard title="Book weights" accent={C.income}>
              <div style={{ fontSize: 11, color: C.soft, marginBottom: 6 }}>
                ${(Number(data.portfolio_context.total_mv || 0) / 1e6).toFixed(2)}M household
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
