import { useState } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  actionProminence,
  buttonStyle,
  verdictColor,
  rrTooltip,
  confidenceTooltip,
  planValidatedTooltip,
  enrichedTooltip,
  cioViewTooltip,
  dataDoubtTooltip,
  ladderStepTooltip,
  watchlistNeedsRefresh,
  type CardActionType,
  type CardVerdict,
} from '../lib/watchlistCardAction'
import { WL, urgencyColor } from '../lib/watchlistCardTokens'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import { watchlistReportEligible } from '../lib/reportLinks'

function ago(v: any) {
  if (!v) return ''
  const t = new Date(v).getTime()
  if (!Number.isFinite(t)) return ''
  const h = Math.round((Date.now() - t) / 36e5)
  if (h < 1) return 'just now'
  if (h < 48) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

function money(v: any) {
  const n = Number(v)
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : '—'
}

function Tag({ text, tip }: { text: string; tip?: string }) {
  return (
    <span title={tip} style={{
      fontSize: 9.5, fontWeight: 600, padding: '2px 7px', borderRadius: 5,
      whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default',
      background: WL.tag.background, border: WL.tag.border, color: WL.tag.color,
    }}>{text}</span>
  )
}

function IntelPill({ text, color, tip }: { text: string; color: string; tip?: string }) {
  return (
    <span title={tip} style={{
      fontSize: 9.5, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
      whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default',
      background: `${color}22`, border: `1px solid ${color}55`, color,
    }}>{text}</span>
  )
}

const llmMeta = (lane?: string) => (({
  grok: { label: 'Grok', color: '#1d9bf0' },
  chatgpt: { label: 'ChatGPT', color: '#10a37f' },
  claude: { label: 'Claude', color: '#d97757' },
} as Record<string, { label: string; color: string }>)[lane || ''] || { label: lane || 'LLM', color: WL.text.muted })

function FinvizStrip({ fv }: { fv: any }) {
  const pc = (v: any) => v == null ? WL.text.muted : Number(v) > 0 ? WL.urgency.green : Number(v) < 0 ? WL.urgency.red : WL.text.muted
  const rsiC = fv.rsi == null ? WL.text.muted : fv.rsi >= 70 ? WL.urgency.red : fv.rsi <= 30 ? WL.urgency.green : WL.text.primary
  const cell = (label: string, val: any, color: string, suffix = '') => (
    <span style={{ display: 'flex', gap: 4, alignItems: 'baseline' }}>
      <span style={{ fontSize: 8.5, color: WL.text.muted, fontWeight: 700 }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 800, fontFamily: 'monospace', color }}>
        {val == null ? '—' : `${Number(val) > 0 && suffix ? '+' : ''}${Number(val).toFixed(suffix ? 1 : 0)}${suffix}`}
      </span>
    </span>
  )
  return (
    <div
      title="Finviz daily metrics"
      onClick={e => e.stopPropagation()}
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 12, padding: '5px 10px',
        background: 'rgba(96,165,250,.07)', border: '1px solid rgba(96,165,250,.18)', borderRadius: 8,
      }}
    >
      {cell('RSI', fv.rsi, rsiC)}
      {cell('W', fv.perf_week, pc(fv.perf_week), '%')}
      {cell('M', fv.perf_month, pc(fv.perf_month), '%')}
      {cell('YTD', fv.perf_ytd, pc(fv.perf_ytd), '%')}
      {cell('vs50d', fv.sma50, pc(fv.sma50), '%')}
      <span style={{ fontSize: 8, color: WL.text.dim, alignSelf: 'center' }}>finviz</span>
    </div>
  )
}

function ladderFocusIndex(ladder: Ladder | null): number {
  if (!ladder?.steps.length) return -1
  return ladder.steps.length > 1 ? 1 : 0
}

function ladderSummary(ladder: Ladder): string {
  const focus = ladder.steps[ladderFocusIndex(ladder)]
  return focus ? `${focus.label} ${focus.px.toFixed(2)}` : ''
}

function truncate(text: string, max: number): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1).trimEnd()}…`
}

function cleanNewsSource(raw?: string): string {
  if (!raw) return 'news'
  return String(raw)
    .replace(/^(google_news|yahoo_rss|finviz_news|hermes):\s*/i, '')
    .replace(/^hermes\s*·\s*/i, '')
    .trim() || 'news'
}

function VerdictChip({ verdict }: { verdict: CardVerdict }) {
  const c = verdictColor(verdict)
  return (
    <span style={{
      fontSize: 9, fontWeight: 900, padding: '2px 7px', borderRadius: 4,
      letterSpacing: '.06em', color: c, border: `1px solid ${c}66`, background: `${c}18`,
    }}>{verdict}</span>
  )
}

export type WatchlistCardProps = {
  it: any
  adv?: any
  sc?: any
  pa?: any
  outcome?: any
  llms: any[]
  fv?: any
  reportEntry?: any
  paMap: Record<string, any>
  ensOpen: boolean
  refreshState?: string
  onDrill: (ctx: DrillContext) => void
  onToggleStar: (e: React.MouseEvent) => void
  onRefresh: (e: React.MouseEvent) => void
  onToggleEns: () => void
  isStarred: boolean
  onPropose?: (it: any) => void
  onAdjust?: (it: any) => void
  onBuildPlan?: (symbol: string) => void
  onOpenDesk?: (symbol: string) => void
}

export default function WatchlistCard({
  it, adv, sc, pa, outcome, llms, fv, reportEntry, paMap,
  ensOpen, refreshState, onDrill, onToggleStar, onRefresh, onToggleEns, isStarred,
  onPropose, onAdjust, onBuildPlan, onOpenDesk,
}: WatchlistCardProps) {
  const [contextOpen, setContextOpen] = useState(false)
  const [researchOpen, setResearchOpen] = useState(false)
  const [ladderOpen, setLadderOpen] = useState<boolean | null>(null)
  const [rulesOpen, setRulesOpen] = useState(false)

  const enriched = !!it.last_enriched_at
  const stale = enriched && (Date.now() - new Date(it.last_enriched_at).getTime()) > 3600 * 1000
  const needsRefresh = watchlistNeedsRefresh(it, stale)
  const street = pa?.target != null && Number(pa.target) > 0 ? Number(pa.target) : null
  const entry = it.entry_limit != null ? Number(it.entry_limit) : null
  const stop = it.entry_stop != null ? Number(it.entry_stop) : null
  const planTarget = it.entry_target != null ? Number(it.entry_target) : null
  const rr = it.entry_rr != null ? Number(it.entry_rr)
    : (entry && stop && planTarget && entry > stop && planTarget > entry ? (planTarget - entry) / (entry - stop) : null)
  const hasPlan = entry != null && stop != null
  const ladder = entry != null || stop != null ? exitLadder(entry, stop, planTarget, street) : null
  const warns = entry != null || stop != null
    ? planWarnings({ entry, stop, planTarget, rr, pctCash: null, streetTarget: street, analystUpside: pa?.upside != null ? Number(pa.upside) : null })
    : []
  const action = deriveRecommendedAction({ it, hasPlan, rr, warns, stale, enriched, entry, adv })
  const prominence = actionProminence(action, hasPlan)
  const accent = urgencyColor(action.urgency)
  const focusIdx = ladderFocusIndex(ladder)
  const ladderExpanded = ladderOpen ?? prominence.ladderDefaultOpen

  const cioLabel = it.latest_recommendation
    ? String(it.latest_recommendation).replace(/_/g, ' ')
    : (pa?.rec ? String(pa.rec).replace(/_/g, ' ') : 'watch')
  const confVal = it.research_confidence != null
    ? Number(it.research_confidence).toFixed(2)
    : (it.hermes_score_components?._confidence ?? '—')
  const enrichVal = ago(it.last_enriched_at) || 'pending'
  const validatedVal = ago(it.entry_planned_at) || ago(it.last_validated_at) || 'pending'

  const drillCtx: DrillContext = {
    title: `${it.symbol}${it.hermes_rank != null ? ` — Hermes #${it.hermes_rank}` : ''}`,
    subtitle: `${it.origin_system ?? it.source ?? ''} · ${it.status}`,
    endpoint: `/api/v2/hermes/intel/${it.symbol}`,
    rows: [adv ? { ...it, setup_advisory_note: adv.note, setup_advisory_flag: adv.advisory_flag, current_rsi: adv.rsi, rsi_band: adv.band } : it],
  }

  const originLabel = ({ trade_ai_screener: 'Screener', agent_discovery: 'AI', operator: 'Operator', hermes: 'Hermes', portfolio: 'Portfolio', social: 'Social' } as Record<string, string>)[it.origin_system || ''] || (it.origin_system || 'screener')

  const provenanceText = [it.hermes_rank != null ? `#${it.hermes_rank}` : null, originLabel].filter(Boolean).join(' · ')
  const provenanceTip = [
    it.hermes_rank != null ? `Hermes #${it.hermes_rank} · composite ${it.hermes_composite_score ?? '—'}` : null,
    it.provenance_reason || it.source || originLabel,
    it.source_tier ? `tier ${it.source_tier}` : null,
    it.directive_id ? `directive #${it.directive_id}` : null,
  ].filter(Boolean).join(' · ')
  const isHeld = it.in_portfolio || outcome?.held
  const heldTip = outcome?.held ? `unrealized ${outcome.unrealized_pnl_pct ?? '?'}%` : 'in portfolio'
  const hasMetaContext = !!(it.source_tier || it.directive_id)

  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''

  const riskLines: { text: string; severity: 'red' | 'amber'; doubt?: boolean }[] = []
  if (dataDoubt) riskLines.push({ text: dataDoubt, severity: 'amber', doubt: true })
  else if (action.verdict !== 'FIX') {
    for (const w of warns.slice(0, 1)) {
      riskLines.push({ text: w.text, severity: w.color === WL.urgency.red ? 'red' : 'amber' })
    }
  }
  const sectorLine = sc?.sector || it.profile_sector
    ? [sc?.sector || it.profile_sector, sc?.industry || it.profile_industry].filter(Boolean).join(' · ')
    : null
  const companyDesc = sc?.description || it.profile_description || null
  const companyOneLiner = companyDesc ? truncate(companyDesc, 80) : null
  const allNews: any[] = sc?.news ?? []
  const newsCount = allNews.length || (it.news_7d != null ? Number(it.news_7d) : 0)
  const topNews = allNews[0] ?? null
  const intelSummaryParts = [
    companyOneLiner,
    sc?.sector || it.profile_sector || null,
    it.catalyst_type ? `⚡ ${String(it.catalyst_type).replace(/_/g, ' ')}` : null,
    newsCount > 0 ? `${newsCount} news` : null,
    fv?.rsi != null ? `RSI ${Math.round(Number(fv.rsi))}` : null,
  ].filter(Boolean)
  const hasResearch = !!(companyDesc || sectorLine || it.catalyst_headline || allNews.length
    || fv || llms.length || sc?.vs_sector_week != null)
  const hasContext = !!(it.synthesis_evidence?.length || it.synthesis_narrative_snip
    || hasMetaContext || !enriched)

  const heroTextSize = prominence.heroScale === 'large' ? WL.hero.textLarge : WL.hero.textMedium
  const metricColor = prominence.metricsMuted ? WL.text.dim : WL.text.primary

  const executeAction = (e: React.MouseEvent, type: CardActionType) => {
    e.stopPropagation()
    switch (type) {
      case 'REFRESH_DATA':
        onRefresh(e)
        break
      case 'VIEW_INTEL':
      case 'REVIEW_SETUP':
        onDrill(drillCtx)
        break
      case 'PROPOSE_ENTRY':
        onPropose?.(it)
        break
      case 'ADJUST_PLAN':
      case 'REVIEW_EXIT':
        onAdjust?.(it)
        break
      case 'BUILD_PLAN':
        onBuildPlan?.(it.symbol)
        break
      case 'WATCH_ON_DESK':
      case 'QUEUE_PROPOSAL':
        onOpenDesk?.(it.symbol)
        break
      default:
        break
    }
  }

  const handlePrimary = (e: React.MouseEvent) => {
    if (!action.allowPrimary) return
    executeAction(e, action.type)
  }

  return (
    <div
      onClick={() => onDrill(drillCtx)}
      style={{
        background: WL.card.bg,
        border: WL.card.border,
        borderRadius: WL.card.radius,
        padding: 16,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        boxShadow: WL.card.shadow,
        minWidth: 0,
        width: '100%',
        boxSizing: 'border-box',
        overflow: 'visible',
      }}
    >
      {/* 1. Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleStar(e) }}
            title={isStarred ? 'Unstar' : 'Star for priority refresh'}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 15, padding: 0, color: isStarred ? WL.text.secondary : WL.text.dim }}
          >{isStarred ? '★' : '☆'}</button>
          <span style={{ fontWeight: 950, color: WL.text.primary, fontFamily: 'monospace', fontSize: 18 }}>{it.symbol}</span>
          <VerdictChip verdict={action.verdict} />
          <ProAnalystPill symbol={it.symbol} map={paMap} compact neutral />
          {isHeld && (
            <span title={heldTip} style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4, color: '#ffa726', border: '1px solid rgba(255,167,38,.45)', background: 'rgba(255,167,38,.12)' }}>
              HELD
            </span>
          )}
          {it.private_nontradeable && (
            <span title={it.private_note} style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: WL.urgency.red, border: `1px solid ${WL.urgency.red}55`, background: 'rgba(220,38,38,.1)' }}>
              PRIVATE
            </span>
          )}
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: 17, fontWeight: 900, color: WL.text.primary }}>{it.price != null ? money(it.price) : '—'}</div>
          {it.change_pct != null && (
            <div style={{ fontSize: 12, fontWeight: 800, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
              {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
            </div>
          )}
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh Finviz/RSI + re-queue synthesis"
            style={{
              marginTop: 4, fontSize: 9, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
              cursor: refreshState ? 'wait' : 'pointer', border: `1px solid ${WL.tag.border}`,
              background: 'transparent', color: needsRefresh ? WL.urgency.amber : WL.text.dim,
            }}
          >{refreshState ? `↻ ${refreshState}` : '↻'}</button>
        </div>
      </div>

      {/* 2. Hero — verdict + action + primary CTA */}
      <div
        onClick={e => e.stopPropagation()}
        title={action.detail}
        style={{
          padding: '12px 14px',
          background: WL.hero.bg,
          borderRadius: WL.body.radius,
          border: `1px solid ${WL.hero.border}`,
          borderLeft: accent ? `4px solid ${accent}` : `4px solid ${WL.hero.border}`,
        }}
      >
        <div style={{
          fontSize: heroTextSize, fontWeight: 800, color: WL.text.primary, lineHeight: 1.3,
        }}>{action.heroText}</div>
        {action.subtext && (
          <div style={{ fontSize: WL.hero.subtextSize, color: WL.text.muted, marginTop: 4, lineHeight: 1.35 }}>{action.subtext}</div>
        )}
        {action.allowPrimary && (
          <div style={{ marginTop: 10 }}>
            <button
              onClick={handlePrimary}
              style={buttonStyle(action.buttonVariant)}
            >{action.primaryLabel}</button>
          </div>
        )}
      </div>

      {/* 3–4. Plan metrics + conviction (single surface) */}
      <div style={{
        padding: '10px 12px',
        background: WL.body.bg,
        border: `1px solid ${WL.body.border}`,
        borderRadius: WL.body.radius,
        opacity: prominence.metricsMuted ? 0.72 : 1,
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: 10,
        }}>
          {[
            { label: 'Entry model', value: it.entry_model || '—' },
            { label: 'R:R', value: rr != null ? rr.toFixed(2) : '—', tip: rrTooltip(entry, stop, planTarget, rr), warn: rr != null && rr < 1.5 },
            { label: 'Limit', value: money(it.entry_limit) },
            { label: 'Stop', value: money(it.entry_stop), warn: hasPlan && stop == null },
          ].map(m => (
            <div key={m.label} title={m.tip} style={{ minWidth: 0 }}>
              <div style={{ fontSize: 8, color: WL.text.muted, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 800 }}>{m.label}</div>
              <div style={{
                fontSize: 12, fontWeight: 800, marginTop: 3, fontFamily: 'monospace', lineHeight: 1.1,
                color: m.warn ? WL.urgency.red : metricColor,
              }}>{m.value}</div>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 10, paddingTop: 10, borderTop: `1px solid ${WL.body.border}`,
          fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.5,
        }}>
          <span title={cioViewTooltip(it)} style={{ cursor: 'help' }}><b style={{ color: WL.text.muted, fontWeight: 700 }}>CIO</b> {cioLabel}</span>
          <span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span>
          <span title={confidenceTooltip(it)} style={{ cursor: 'help' }}><b style={{ color: WL.text.muted, fontWeight: 700 }}>Conf</b> {confVal}</span>
          <span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span>
          <span title={enrichedTooltip(it)} style={{ cursor: 'help' }}><b style={{ color: WL.text.muted, fontWeight: 700 }}>Enriched</b> {enrichVal}</span>
          <span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span>
          <span title={planValidatedTooltip(it)} style={{ cursor: 'help' }}><b style={{ color: WL.text.muted, fontWeight: 700 }}>Validated</b> {validatedVal}</span>
          {it.models_agree === true && <span style={{ marginLeft: 6, fontSize: 9, color: WL.text.dim }}>✓ 2 models</span>}
          {it.models_agree === false && <span style={{ marginLeft: 6, fontSize: 9, color: WL.text.muted }}>models split</span>}
        </div>
      </div>

      {/* Risk strip (merged warnings + data doubt) */}
      {riskLines.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {riskLines.map((r, i) => {
            const c = r.severity === 'red' ? WL.urgency.red : WL.urgency.amber
            return (
              <div
                key={i}
                title={r.doubt ? dataDoubtTooltip(r.text) : undefined}
                style={{
                  fontSize: 10, fontWeight: 650, color: c, padding: '6px 10px', borderRadius: 6,
                  background: r.severity === 'red' ? 'rgba(220,38,38,.08)' : 'rgba(217,119,6,.08)',
                  border: `1px solid ${c}33`, lineHeight: 1.4, cursor: r.doubt ? 'help' : 'default',
                }}
              >
                ⚠ {r.doubt ? <><b>Data doubt</b> — {r.text}</> : r.text}
              </div>
            )
          })}
        </div>
      )}

      {/* 5. Research — one-line scan + expandable drawer */}
      {hasResearch && (
        <div onClick={e => e.stopPropagation()}>
          {intelSummaryParts.length > 0 && (
            <div style={{
              fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.4,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {intelSummaryParts.join(' · ')}
            </div>
          )}
          {topNews && !researchOpen && (
            <div style={{ fontSize: 10, color: WL.text.muted, marginTop: 4, lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {cleanNewsSource(topNews.source)}{topNews.at ? ` · ${ago(topNews.at)}` : ''}{' '}
              {topNews.url ? (
                <a href={topNews.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#bfdbfe', textDecoration: 'none', fontWeight: 600 }}>
                  {topNews.title}
                </a>
              ) : <span style={{ color: WL.text.secondary }}>{topNews.title}</span>}
            </div>
          )}
          <button
            onClick={() => setResearchOpen(v => !v)}
            style={{
              marginTop: 6, fontSize: 9.5, fontWeight: 700, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${WL.tag.border}`, background: 'transparent', color: WL.text.muted,
            }}
          >{researchOpen ? '▾' : '▸'} Research</button>
          {researchOpen && (
            <div style={{
              marginTop: 8, padding: '10px 12px', borderRadius: WL.body.radius,
              background: WL.body.bg, border: `1px solid ${WL.body.border}`,
              display: 'flex', flexDirection: 'column', gap: 8,
            }}>
              {companyDesc && (
                <div style={{ fontSize: 11, color: WL.text.secondary, lineHeight: 1.45, overflowWrap: 'anywhere' }}>
                  {companyDesc}
                </div>
              )}
              {(sc?.sector || it.profile_sector || sc?.vs_sector_week != null) && (
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                  {(sc?.sector || it.profile_sector) && (
                    <IntelPill
                      text={`${sc?.sector || it.profile_sector}${sc?.sector_etf ? ` (${sc.sector_etf})` : ''}`}
                      color="#60a5fa"
                      tip={sc?.industry || it.profile_industry || undefined}
                    />
                  )}
                  {sc?.vs_sector_week != null && (
                    <IntelPill
                      text={`${sc.vs_sector_week >= 0 ? '+' : ''}${sc.vs_sector_week}% vs sector (1w)`}
                      color={sc.vs_sector_week >= 0 ? WL.urgency.green : WL.urgency.red}
                    />
                  )}
                </div>
              )}
              {it.catalyst_headline && (
                <div style={{ fontSize: 10.5, color: WL.text.secondary, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', lineHeight: 1.4 }}>
                  {it.catalyst_type && (
                    <IntelPill
                      text={`⚡ ${String(it.catalyst_type).replace(/_/g, ' ')}`}
                      color={it.catalyst_severity === 'critical' || it.catalyst_severity === 'high' ? WL.urgency.green : WL.urgency.amber}
                      tip={`latest catalyst · impact ${it.catalyst_impact ?? '—'}`}
                    />
                  )}
                  {it.catalyst_url ? (
                    <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#bfdbfe', textDecoration: 'none', fontWeight: 650 }}>
                      {it.catalyst_headline}
                    </a>
                  ) : <span>{it.catalyst_headline}</span>}
                  {it.catalyst_at && <span style={{ color: WL.text.muted, fontSize: 9.5 }}>{ago(it.catalyst_at)}</span>}
                </div>
              )}
              {allNews.slice(0, 3).map((n: any, i: number) => (
                <div key={i} style={{ fontSize: 10.5, lineHeight: 1.4, overflowWrap: 'anywhere' }}>
                  <span style={{ color: WL.text.muted }}>
                    {cleanNewsSource(n.source)}
                    {n.at ? ` · ${ago(n.at)}` : ''}
                    {' '}
                  </span>
                  {n.url ? (
                    <a href={n.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#bfdbfe', textDecoration: 'none', fontWeight: 650 }}>
                      {n.title}
                    </a>
                  ) : <span style={{ color: WL.text.secondary }}>{n.title}</span>}
                </div>
              ))}
              {!allNews.length && newsCount > 0 && (
                <div style={{ fontSize: 10, color: WL.text.muted }}>
                  {newsCount} news article{newsCount === 1 ? '' : 's'} (7d)
                  {it.news_top_score != null ? ` · top score ${it.news_top_score}` : ''}
                </div>
              )}
              {fv && <FinvizStrip fv={fv} />}
              {llms.length > 0 && (
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {llms.map((e: any, i: number) => {
                    const m = llmMeta(e.lane)
                    return (
                      <IntelPill
                        key={`llm-${i}`}
                        text={`✦ ${m.label}`}
                        color={m.color}
                        tip={`Curated by ${m.label}${e.recommendation ? ` — ${e.recommendation}` : ''}${e.at ? `\n${new Date(e.at).toLocaleString()}` : ''}`}
                      />
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 6. Exit ladder — compact / collapsible */}
      {prominence.showLadder && ladder && (
        <div onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setLadderOpen(v => !(v ?? prominence.ladderDefaultOpen))}
            style={{
              width: '100%', textAlign: 'left', fontSize: 10, fontWeight: 700, padding: '6px 10px',
              borderRadius: 6, cursor: 'pointer', border: `1px solid ${WL.body.border}`,
              background: WL.body.bg, color: WL.text.muted,
            }}
          >
            {ladderExpanded ? '▾' : '▸'} Exit ladder
            {!ladderExpanded && (
              <span style={{ fontWeight: 600, marginLeft: 8, color: WL.text.secondary, fontFamily: 'monospace' }}>
                · {ladderSummary(ladder)} · R ${ladder.R.toFixed(2)}/sh
              </span>
            )}
          </button>
          {ladderExpanded && (
            <div style={{ marginTop: 6, padding: '8px 10px', borderRadius: WL.body.radius, background: WL.body.bg, border: `1px solid ${WL.body.border}` }}>
              {ladder.steps.map((s, i) => {
                const active = i === focusIdx
                return (
                  <div
                    key={i}
                    title={ladderStepTooltip(s.label, s.px, s.action)}
                    style={{
                      fontSize: 10.5, marginTop: i ? 3 : 0, padding: '3px 6px', borderRadius: 4,
                      borderLeft: active ? `2px solid ${WL.urgency.amber}` : '2px solid transparent',
                      color: active ? WL.text.primary : WL.text.secondary,
                    }}
                  >
                    <span style={{ fontWeight: active ? 800 : 500, fontFamily: 'monospace' }}>{s.label} {s.px.toFixed(2)}</span>
                    <span style={{ color: WL.text.dim, fontSize: 9.5 }}> — {s.action}</span>
                  </div>
                )
              })}
              <button
                onClick={() => setRulesOpen(v => !v)}
                style={{
                  marginTop: 6, fontSize: 9, fontWeight: 600, padding: 0, border: 'none',
                  background: 'none', color: WL.text.dim, cursor: 'pointer',
                }}
              >{rulesOpen ? '▾' : '▸'} In-trade rules</button>
              {rulesOpen && <div style={{ fontSize: 9, color: WL.text.dim, marginTop: 4, lineHeight: 1.4 }}>{MONITOR_RULES}</div>}
            </div>
          )}
        </div>
      )}

      {/* 7. Provenance (single chip — tier/directive live in Context) */}
      {(provenanceText || outcome?.sold) && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          {provenanceText && <Tag text={provenanceText} tip={provenanceTip} />}
          {outcome?.sold && (
            <Tag text={`sold ${(outcome.last_pnl_pct ?? 0) >= 0 ? '+' : ''}${outcome.last_pnl_pct ?? '?'}%`} tip="Prior closed trade" />
          )}
        </div>
      )}

      {/* Context drawer — CIO evidence, narrative, fib (deep dive) */}
      {(hasContext || hasMetaContext) && (
        <div onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setContextOpen(v => !v)}
            style={{
              fontSize: 9.5, fontWeight: 700, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${WL.tag.border}`, background: 'transparent', color: WL.text.muted,
            }}
          >{contextOpen ? '▾' : '▸'} Context</button>
          {contextOpen && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {!enriched && <div style={{ fontSize: 10, color: WL.text.muted, fontStyle: 'italic' }}>awaiting enrichment…</div>}
              {hasMetaContext && (
                <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.45 }}>
                  {it.source_tier && <span><span style={{ color: WL.text.muted, fontWeight: 700 }}>Tier </span>{it.source_tier}</span>}
                  {it.source_tier && it.directive_id && <span style={{ color: WL.text.dim, margin: '0 6px' }}>·</span>}
                  {it.directive_id && <span><span style={{ color: WL.text.muted, fontWeight: 700 }}>Directive </span>#{it.directive_id}</span>}
                </div>
              )}
              {it.synthesis_evidence?.length > 0 && (
                <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
              )}
              {action.detail && (
                <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.45 }}>
                  <span style={{ color: WL.text.muted, fontWeight: 700 }}>Advisory </span>{action.detail}
                </div>
              )}
              {it.synthesis_narrative_snip && (
                <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.45, fontStyle: 'italic' }}>
                  {String(it.synthesis_narrative_snip).slice(0, 280)}
                </div>
              )}
              <FibConfluencePanel symbol={it.symbol} />
            </div>
          )}
        </div>
      )}

      {/* 8. Secondary actions */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center',
          borderTop: `1px solid ${WL.body.border}`, paddingTop: 10,
        }}
      >
        <button
          onClick={e => { e.stopPropagation(); onDrill(drillCtx) }}
          style={{ fontSize: 10, fontWeight: 600, padding: '4px 0', border: 'none', background: 'transparent', color: WL.text.muted, cursor: 'pointer' }}
        >View intel</button>
        <a href={`/v3/rec-intel?symbol=${it.symbol}`} onClick={e => e.stopPropagation()} style={{ fontSize: 10, fontWeight: 600, color: WL.text.muted, textDecoration: 'none' }}>Rec-Intel</a>
        <button
          onClick={e => { e.stopPropagation(); onToggleEns() }}
          style={{ fontSize: 10, fontWeight: 600, padding: '4px 0', border: 'none', background: 'transparent', color: WL.text.muted, cursor: 'pointer' }}
        >Ensemble {ensOpen ? '▲' : '▾'}</button>
        {watchlistReportEligible(it) && (
          <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} compact />
        )}
      </div>

      {ensOpen && (
        <div onClick={e => e.stopPropagation()}>
          <EnsembleValidationInline
            targetType="signal"
            targetId={it.id}
            subject={it.symbol}
            content={`${it.symbol} watchlist — ${it.latest_recommendation || it.trend || ''} · ${it.profile_sector || ''}`}
          />
        </div>
      )}
    </div>
  )
}