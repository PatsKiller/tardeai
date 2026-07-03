import { useState } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  actionProminence,
  buttonStyle,
  verdictColor,
  confidenceTooltip,
  planValidatedTooltip,
  enrichedTooltip,
  cioViewTooltip,
  dataDoubtTooltip,
  ladderStepTooltip,
  watchlistNeedsRefresh,
  cioRecColor,
  targetVsStreetLabel,
  dataQualityFlags,
  actionReasoning,
  rrTooltip,
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

function cleanNewsSource(raw?: string): string {
  if (!raw) return 'news'
  return String(raw)
    .replace(/^(google_news|yahoo_rss|finviz_news|hermes):\s*/i, '')
    .replace(/^hermes\s*·\s*/i, '')
    .trim() || 'news'
}

function truncate(text: string, max: number): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1).trimEnd()}…`
}

function ladderSummary(ladder: Ladder): string {
  const focus = ladder.steps[ladder.steps.length > 1 ? 1 : 0]
  return focus ? `${focus.label} ${focus.px.toFixed(2)}` : ''
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

function CioSignalPill({ label, confidence, tip }: { label: string; confidence: string; tip: string }) {
  const c = cioRecColor(label)
  return (
    <span title={tip} style={{
      fontSize: 10, fontWeight: 800, padding: '3px 8px', borderRadius: 5,
      color: c, border: `1px solid ${c}66`, background: `${c}18`, whiteSpace: 'nowrap', cursor: 'help',
    }}>
      CIO {label.replace(/_/g, ' ')}
      {confidence !== '—' && <span style={{ fontWeight: 600, color: WL.text.muted, marginLeft: 5 }}>· {confidence}</span>}
    </span>
  )
}

function RrBadge({ rr, tip }: { rr: number; tip: string }) {
  const c = rr >= 2 ? WL.urgency.green : rr >= 1.5 ? WL.urgency.amber : WL.urgency.red
  return (
    <span title={tip} style={{
      fontSize: 10, fontWeight: 900, padding: '4px 8px', borderRadius: 5,
      fontFamily: 'monospace', color: c, border: `1px solid ${c}55`, background: `${c}14`, whiteSpace: 'nowrap',
    }}>{rr.toFixed(1)}R</span>
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
  const [ladderOpen, setLadderOpen] = useState<boolean | null>(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
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
  const heroTextSize = prominence.heroScale === 'large' ? WL.hero.textLarge : WL.hero.textMedium
  const metricColor = prominence.metricsMuted ? WL.text.dim : WL.text.primary

  const cioRec = it.latest_recommendation
    ? String(it.latest_recommendation).replace(/_/g, ' ')
    : 'none'
  const cioLabel = it.latest_recommendation
    ? cioRec
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
  const isHeld = it.in_portfolio || outcome?.held
  const heldTip = outcome?.held ? `unrealized ${outcome.unrealized_pnl_pct ?? '?'}%` : 'in portfolio'
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
  const allNews: any[] = sc?.news ?? []
  const topNews = allNews[0] ?? null
  const companyOneLiner = companyDesc ? truncate(companyDesc, 140) : null
  const zoneLo = it.entry_zone_low != null ? Number(it.entry_zone_low) : null
  const zoneHi = it.entry_zone_high != null ? Number(it.entry_zone_high) : null
  const hasZone = zoneLo != null && zoneHi != null && Number.isFinite(zoneLo) && Number.isFinite(zoneHi)
  const setupLabel = it.entry_setup ? String(it.entry_setup).replace(/_/g, ' ') : null
  const urgencyLabel = it.entry_urgency
    ? String(it.entry_urgency).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    : null
  const planLine = [
    hasPlan ? `L ${money(entry)}` : null,
    hasPlan ? `S ${money(stop)}` : null,
    rr != null ? `R:R ${rr.toFixed(1)}` : null,
    hasZone ? `zone ${money(zoneLo)}–${money(zoneHi)}` : null,
    setupLabel ? setupLabel : null,
    `CIO ${cioLabel}`,
    fv?.rsi != null ? `RSI ${Math.round(Number(fv.rsi))}` : null,
    sc?.sector || it.profile_sector || null,
    provenanceText || null,
  ].filter(Boolean).join(' · ')
  const hasMore = !!(it.synthesis_evidence?.length || it.synthesis_narrative_snip
    || action.detail || llms.length)
  const reasoning = actionReasoning({ it, pa, adv, action, hasPlan, rr, stale, enriched })
  const dqFlags = dataQualityFlags({ it, stale, enriched, needsRefresh, dataDoubt })
  const exitVsStreet = targetVsStreetLabel(planTarget, street)
  const analystDivergent = pa?.divergence === 'divergent'

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
        borderLeft: accent ? `4px solid ${accent}` : `4px solid transparent`,
        borderRadius: WL.card.radius,
        padding: 14,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 11,
        boxShadow: WL.card.shadow,
        minWidth: 0,
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleStar(e) }}
            title={isStarred ? 'Unstar' : 'Star'}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, padding: 0, color: isStarred ? WL.text.secondary : WL.text.dim }}
          >{isStarred ? '★' : '☆'}</button>
          <span style={{ fontWeight: 950, color: WL.text.primary, fontFamily: 'monospace', fontSize: 20 }}>{it.symbol}</span>
          <CioSignalPill label={cioRec} confidence={String(confVal)} tip={cioViewTooltip(it)} />
          <VerdictChip verdict={action.verdict} />
          <ProAnalystPill symbol={it.symbol} map={paMap} compact neutral={!analystDivergent} />
          {analystDivergent && (
            <IntelPill text="CIO ≠ Street" color={WL.urgency.red} tip="Internal CIO view diverges from Yahoo analyst consensus — weight CIO higher" />
          )}
          {isHeld && (
            <span title={heldTip} style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4, color: '#ffa726', border: '1px solid rgba(255,167,38,.45)', background: 'rgba(255,167,38,.12)' }}>HELD</span>
          )}
          {provenanceText && (
            <span style={{ fontSize: 9, color: WL.text.dim, fontWeight: 600 }}>{provenanceText}</span>
          )}
          {outcome?.sold && (
            <span style={{ fontSize: 9, color: WL.text.muted }}>sold {(outcome.last_pnl_pct ?? 0) >= 0 ? '+' : ''}{outcome.last_pnl_pct ?? '?'}%</span>
          )}
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }} onClick={e => e.stopPropagation()}>
          <div style={{ fontSize: 18, fontWeight: 900, color: WL.text.primary, fontFamily: 'monospace' }}>{it.price != null ? money(it.price) : '—'}</div>
          {it.change_pct != null && (
            <div style={{ fontSize: 12, fontWeight: 800, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
              {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
            </div>
          )}
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh Finviz + re-queue synthesis"
            style={{
              marginTop: 4, fontSize: 9, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
              cursor: refreshState ? 'wait' : 'pointer', border: `1px solid ${WL.tag.border}`,
              background: 'transparent', color: needsRefresh ? WL.urgency.amber : WL.text.dim,
            }}
          >{refreshState ? `↻ ${refreshState}` : '↻'}</button>
        </div>
      </div>

      {/* Data quality — compact, always visible when relevant */}
      {dqFlags.length > 0 && (
        <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {dqFlags.map((f, i) => (
            <IntelPill
              key={i}
              text={f.label}
              color={f.severity === 'red' ? WL.urgency.red : WL.urgency.amber}
              tip={f.label === 'Data doubt' ? dataDoubtTooltip(dataDoubt) : enrichedTooltip(it)}
            />
          ))}
        </div>
      )}

      {/* Action hero */}
      <div
        onClick={e => e.stopPropagation()}
        title={action.detail}
        style={{
          padding: '12px 14px',
          background: WL.hero.bg,
          borderRadius: WL.body.radius,
          border: `1px solid ${WL.hero.border}`,
          borderLeft: accent ? `4px solid ${accent}` : `4px solid ${WL.hero.border}`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: heroTextSize, fontWeight: 800, color: WL.text.primary, lineHeight: 1.3 }}>{action.heroText}</div>
          {action.subtext && action.subtext !== reasoning && (
            <div style={{ fontSize: WL.hero.subtextSize, color: WL.text.muted, marginTop: 4 }}>{action.subtext}</div>
          )}
          <div style={{ fontSize: 11, color: WL.text.secondary, marginTop: 6, lineHeight: 1.45 }} title={reasoning}>
            {reasoning}
          </div>
          {planLine && (
            <div style={{ fontSize: 10, color: WL.text.dim, marginTop: 5, lineHeight: 1.4, fontFamily: 'monospace' }} title={planLine}>
              {planLine}
            </div>
          )}
        </div>
        <div onClick={e => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {rr != null && hasPlan && <RrBadge rr={rr} tip={rrTooltip(entry, stop, planTarget, rr)} />}
          {action.allowPrimary && (
            <button onClick={handlePrimary} style={buttonStyle(action.buttonVariant)}>{action.primaryLabel}</button>
          )}
        </div>
      </div>

      {/* Plan metrics */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          padding: '10px 12px',
          background: WL.body.bg,
          border: `1px solid ${WL.body.border}`,
          borderRadius: WL.body.radius,
          opacity: prominence.metricsMuted ? 0.8 : 1,
        }}
      >
        {(setupLabel || hasZone || urgencyLabel) && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            {setupLabel && (
              <IntelPill
                text={setupLabel}
                color={setupLabel.includes('pullback') ? '#60a5fa' : '#a855f7'}
                tip="Entry planner setup type"
              />
            )}
            {urgencyLabel && (
              <IntelPill
                text={urgencyLabel}
                color={it.entry_urgency === 'ready' ? WL.urgency.green : it.entry_urgency === 'near_entry' ? WL.urgency.amber : WL.text.muted}
                tip="Distance to planned entry zone"
              />
            )}
            {hasZone && (
              <span style={{ fontSize: 11, fontWeight: 800, fontFamily: 'monospace', color: WL.text.primary }}>
                Zone {money(zoneLo)}–{money(zoneHi)}
              </span>
            )}
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 10 }}>
          {[
            { label: 'Limit', value: money(it.entry_limit) },
            { label: 'Stop', value: money(it.entry_stop), warn: hasPlan && stop == null },
            { label: 'Target', value: money(it.entry_target) },
            { label: 'Zone lo', value: hasZone ? money(zoneLo) : '—' },
            { label: 'Zone hi', value: hasZone ? money(zoneHi) : '—' },
            { label: 'R:R', value: rr != null ? rr.toFixed(2) : '—', warn: rr != null && rr < 1.5 },
          ].map(m => (
            <div key={m.label}>
              <div style={{ fontSize: 8, color: WL.text.muted, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 800 }}>{m.label}</div>
              <div style={{
                fontSize: 12, fontWeight: 800, marginTop: 3, fontFamily: 'monospace',
                color: m.warn ? WL.urgency.red : metricColor,
              }}>{m.value}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: `1px solid ${WL.body.border}`, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span title={confidenceTooltip(it)} style={{ fontSize: 10, color: WL.text.secondary }}>
            <b style={{ color: WL.text.muted }}>Conf</b> {confVal}
          </span>
          <span title={enrichedTooltip(it)} style={{ fontSize: 10, color: WL.text.secondary }}>
            <b style={{ color: WL.text.muted }}>Enriched</b> {enrichVal}
          </span>
          <span title={planValidatedTooltip(it)} style={{ fontSize: 10, color: WL.text.secondary }}>
            <b style={{ color: WL.text.muted }}>Validated</b> {validatedVal}
          </span>
          {it.entry_model && (
            <IntelPill text={it.entry_model} color="#a855f7" tip="Entry planner model" />
          )}
          {it.models_agree === true && <IntelPill text="✓ 2 models agree" color={WL.urgency.green} tip="Grok + ChatGPT agree on CIO view" />}
          {it.models_agree === false && <IntelPill text="models split" color={WL.urgency.amber} tip="Grok and ChatGPT disagree — cautious view used" />}
        </div>
        {exitVsStreet && (
          <div style={{ marginTop: 8, fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.4 }} title={exitVsStreet}>
            <b style={{ color: WL.text.muted }}>Exit </b>{exitVsStreet}
          </div>
        )}
      </div>

      {/* Fib / pullback confluence — always on card (lazy-load on expand) */}
      <FibConfluencePanel symbol={it.symbol} />

      {/* Risk */}
      {riskLines.length > 0 && (
        <div onClick={e => e.stopPropagation()} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {riskLines.map((r, i) => {
            const c = r.severity === 'red' ? WL.urgency.red : WL.urgency.amber
            return (
              <div key={i} title={r.doubt ? dataDoubtTooltip(r.text) : undefined} style={{
                fontSize: 10, fontWeight: 650, color: c, padding: '6px 10px', borderRadius: 6,
                background: r.severity === 'red' ? 'rgba(220,38,38,.08)' : 'rgba(217,119,6,.08)',
                border: `1px solid ${c}33`, lineHeight: 1.4,
              }}>
                ⚠ {r.doubt ? <><b>Data doubt</b> — {r.text}</> : r.text}
              </div>
            )
          })}
        </div>
      )}

      {/* Intel strip — always visible */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          padding: '10px 12px',
          background: WL.body.bg,
          border: `1px solid ${WL.body.border}`,
          borderRadius: WL.body.radius,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        {fv && <FinvizStrip fv={fv} />}
        {(sectorLine || sc?.vs_sector_week != null || llms.length > 0) && (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
            {sectorLine && (
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
            {llms.map((e: any, i: number) => {
              const m = llmMeta(e.lane)
              return <IntelPill key={`llm-${i}`} text={`✦ ${m.label}`} color={m.color} tip={m.label} />
            })}
          </div>
        )}
        {it.catalyst_headline && (
          <div style={{ fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.4, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {it.catalyst_type && (
              <IntelPill text={`⚡ ${String(it.catalyst_type).replace(/_/g, ' ')}`} color={WL.urgency.amber} />
            )}
            {it.catalyst_url ? (
              <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#bfdbfe', textDecoration: 'none', fontWeight: 650 }}>{it.catalyst_headline}</a>
            ) : <span>{it.catalyst_headline}</span>}
            {it.catalyst_at && <span style={{ color: WL.text.muted, fontSize: 9.5 }}>{ago(it.catalyst_at)}</span>}
          </div>
        )}
        {(companyOneLiner || topNews) && (
          <button
            onClick={e => { e.stopPropagation(); setContextOpen(v => !v) }}
            style={{
              alignSelf: 'flex-start', fontSize: 9.5, fontWeight: 700, padding: '3px 8px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${WL.tag.border}`, background: 'transparent', color: WL.text.muted,
            }}
          >{contextOpen ? '▾' : '▸'} Company &amp; news</button>
        )}
        {contextOpen && companyOneLiner && (
          <div style={{ fontSize: 11, color: WL.text.secondary, lineHeight: 1.45 }}>{companyOneLiner}</div>
        )}
        {contextOpen && topNews && (
          <div style={{ fontSize: 10.5, lineHeight: 1.4, overflowWrap: 'anywhere' }}>
            <span style={{ color: WL.text.muted }}>{cleanNewsSource(topNews.source)}{topNews.at ? ` · ${ago(topNews.at)}` : ''} </span>
            {topNews.url ? (
              <a href={topNews.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#bfdbfe', textDecoration: 'none', fontWeight: 650 }}>{topNews.title}</a>
            ) : <span style={{ color: WL.text.secondary }}>{topNews.title}</span>}
          </div>
        )}
        {contextOpen && allNews.length > 1 && (
          <div style={{ fontSize: 9.5, color: WL.text.dim }}>+{allNews.length - 1} more in ▸ More</div>
        )}
      </div>

      {/* Exit ladder — show summary by default when plan exists */}
      {ladder && (
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
                  <div key={i} title={ladderStepTooltip(s.label, s.px, s.action)} style={{
                    fontSize: 10.5, marginTop: i ? 3 : 0, padding: '3px 6px', borderRadius: 4,
                    borderLeft: active ? `2px solid ${WL.urgency.amber}` : '2px solid transparent',
                    color: active ? WL.text.primary : WL.text.secondary,
                  }}>
                    <span style={{ fontWeight: active ? 800 : 500, fontFamily: 'monospace' }}>{s.label} {s.px.toFixed(2)}</span>
                    <span style={{ color: WL.text.dim, fontSize: 9.5 }}> — {s.action}</span>
                  </div>
                )
              })}
              <button onClick={() => setRulesOpen(v => !v)} style={{ marginTop: 6, fontSize: 9, border: 'none', background: 'none', color: WL.text.dim, cursor: 'pointer' }}>
                {rulesOpen ? '▾' : '▸'} In-trade rules
              </button>
              {rulesOpen && <div style={{ fontSize: 9, color: WL.text.dim, marginTop: 4, lineHeight: 1.4 }}>{MONITOR_RULES}</div>}
            </div>
          )}
        </div>
      )}

      {/* Deep dive — collapsed */}
      {hasMore && (
        <div onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setMoreOpen(v => !v)}
            style={{
              fontSize: 9.5, fontWeight: 700, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${WL.tag.border}`, background: 'transparent', color: WL.text.muted,
            }}
          >{moreOpen ? '▾' : '▸'} More — advisory detail &amp; evidence</button>
          {moreOpen && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {action.detail && (
                <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.45 }}>
                  <span style={{ color: WL.text.muted, fontWeight: 700 }}>Advisory </span>{action.detail}
                </div>
              )}
              {companyDesc && companyDesc !== companyOneLiner && (
                <div style={{ fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.45 }}>{companyDesc}</div>
              )}
              {allNews.slice(1, 3).map((n: any, i: number) => (
                <div key={i} style={{ fontSize: 10, lineHeight: 1.35 }}>
                  <span style={{ color: WL.text.muted }}>{cleanNewsSource(n.source)}{n.at ? ` · ${ago(n.at)}` : ''} </span>
                  {n.url ? (
                    <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#bfdbfe', textDecoration: 'none' }}>{n.title}</a>
                  ) : <span style={{ color: WL.text.secondary }}>{n.title}</span>}
                </div>
              ))}
              {it.synthesis_evidence?.length > 0 && (
                <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
              )}
              {it.synthesis_narrative_snip && (
                <div style={{ fontSize: 10, color: WL.text.secondary, fontStyle: 'italic', lineHeight: 1.45 }}>
                  {String(it.synthesis_narrative_snip).slice(0, 280)}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Footer links */}
      <div
        onClick={e => e.stopPropagation()}
        style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', borderTop: `1px solid ${WL.body.border}`, paddingTop: 8 }}
      >
        <button onClick={e => { e.stopPropagation(); onDrill(drillCtx) }} style={{ fontSize: 10, fontWeight: 600, padding: 0, border: 'none', background: 'transparent', color: WL.text.muted, cursor: 'pointer' }}>View intel</button>
        <a href={`/v3/rec-intel?symbol=${it.symbol}`} onClick={e => e.stopPropagation()} style={{ fontSize: 10, fontWeight: 600, color: WL.text.muted, textDecoration: 'none' }}>Rec-Intel</a>
        <button onClick={e => { e.stopPropagation(); onToggleEns() }} style={{ fontSize: 10, fontWeight: 600, padding: 0, border: 'none', background: 'transparent', color: WL.text.muted, cursor: 'pointer' }}>Ensemble {ensOpen ? '▲' : '▾'}</button>
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