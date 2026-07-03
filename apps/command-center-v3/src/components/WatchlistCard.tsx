import { useState, type CSSProperties, type ReactNode } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  actionProminence,
  buttonStyle,
  confidenceTooltip,
  planValidatedTooltip,
  enrichedTooltip,
  cioViewTooltip,
  ladderStepTooltip,
  watchlistNeedsRefresh,
  cioRecColor,
  targetVsStreetLabel,
  dataQualityFlags,
  actionReasoning,
  deriveSecondaryActions,
  riskSizingHint,
  rrTooltip,
  type CardActionType,
} from '../lib/watchlistCardAction'
import { WL, heroStateStyle, sectionLabel } from '../lib/watchlistCardTokens'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import { EnsembleValidationInline } from './EnsembleValidationCard'


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

function Section({ label, children, style }: { label: string; children: ReactNode; style?: CSSProperties }) {
  return (
    <div onClick={e => e.stopPropagation()} style={{ ...style }}>
      <div style={sectionLabel}>{label}</div>
      {children}
    </div>
  )
}

function MetricCell({ label, value, warn, tip }: { label: string; value: string; warn?: boolean; tip?: string }) {
  return (
    <div title={tip}>
      <div style={{ fontSize: 9, color: WL.text.dim, fontWeight: 700, letterSpacing: '.06em' }}>{label}</div>
      <div style={{
        fontSize: 14, fontWeight: 800, marginTop: 4, fontFamily: 'monospace',
        color: warn ? WL.urgency.red : WL.text.primary,
      }}>{value}</div>
    </div>
  )
}

const llmMeta = (lane?: string) => (({
  grok: { label: 'Grok', color: '#1d9bf0' },
  chatgpt: { label: 'ChatGPT', color: '#10a37f' },
  claude: { label: 'Claude', color: '#d97757' },
} as Record<string, { label: string; color: string }>)[lane || ''] || { label: lane || 'LLM', color: WL.text.muted })

function FinvizStrip({ fv }: { fv: any }) {
  const pc = (v: any) => v == null ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`
  const rsi = fv.rsi == null ? '—' : String(Math.round(Number(fv.rsi)))
  return (
    <div title="Finviz daily metrics" style={{ fontSize: 10.5, color: WL.text.muted, lineHeight: 1.5 }}>
      <span style={{ color: WL.text.dim, fontWeight: 700 }}>Technicals </span>
      RSI {rsi} · 1W {pc(fv.perf_week)} · 1M {pc(fv.perf_month)} · YTD {pc(fv.perf_ytd)} · vs 50d {pc(fv.sma50)}
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

function RrBadge({ rr, tip }: { rr: number; tip: string }) {
  const c = rr >= 2 ? WL.urgency.teal : rr >= 1.5 ? WL.urgency.amber : WL.urgency.red
  return (
    <span title={tip} style={{
      fontSize: 12, fontWeight: 900, padding: '5px 10px', borderRadius: 6,
      fontFamily: 'monospace', color: c, border: `1px solid ${c}44`, background: `${c}12`, whiteSpace: 'nowrap',
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
  const [evidenceOpen, setEvidenceOpen] = useState(false)

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
  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''
  const action = deriveRecommendedAction({
    it, hasPlan, rr, warns, stale, enriched, entry, adv, pa, dataDoubt, needsRefresh,
  })
  const cioRec = it.latest_recommendation
    ? String(it.latest_recommendation).replace(/_/g, ' ')
    : 'none'
  const prominence = actionProminence(action, hasPlan)
  const heroState = heroStateStyle(action.verdict, action.urgency)
  const focusIdx = ladderFocusIndex(ladder)
  const heroTextSize = prominence.heroScale === 'large' ? WL.hero.textLarge : WL.hero.textMedium
  const cioAccent = cioRecColor(it.latest_recommendation || cioRec)
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

  // Supplemental risk line only when matrix banner does not already cover it.
  const riskLines: { text: string; severity: 'red' | 'amber'; doubt?: boolean }[] = []
  if (!action.warning && action.verdict !== 'FIX') {
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
  const hasMore = !!(it.synthesis_evidence?.length || it.synthesis_narrative_snip
    || action.detail || llms.length)
  const reasoning = actionReasoning({ it, pa, adv, action, hasPlan, rr, stale, enriched })
  const dqFlags = dataQualityFlags({ it, stale, enriched, needsRefresh, dataDoubt, adv })
  const exitVsStreet = targetVsStreetLabel(planTarget, street)
  const analystDivergent = pa?.divergence === 'divergent'
  const secondaryActions = deriveSecondaryActions(action, hasPlan)
  const sizingHint = riskSizingHint(action, hasPlan, rr)
  const alertText = action.warning?.text
    ?? (dqFlags.length ? dqFlags.map(f => f.label).join(' · ') : null)

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
      case 'REC_INTEL':
        window.location.href = `/v3/rec-intel?symbol=${encodeURIComponent(it.symbol)}`
        break
      case 'ENSEMBLE':
        onToggleEns()
        break
      default:
        break
    }
  }

  const handlePrimary = (e: React.MouseEvent) => {
    if (!action.allowPrimary) return
    executeAction(e, action.type)
  }

  const panel: CSSProperties = {
    padding: '12px 14px',
    background: WL.surface.raised,
    border: `1px solid ${WL.surface.divider}`,
    borderRadius: WL.body.radius,
  }

  return (
    <div
      onClick={() => onDrill(drillCtx)}
      style={{
        background: WL.surface.card,
        border: WL.card.border,
        borderLeft: `3px solid ${heroState.rail}`,
        borderRadius: WL.card.radius,
        padding: 16,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        boxShadow: WL.card.shadow,
        minWidth: 0,
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      {/* Header — symbol + price only */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleStar(e) }}
            title={isStarred ? 'Unstar' : 'Star'}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 15, padding: 0, color: isStarred ? WL.text.secondary : WL.text.dim }}
          >{isStarred ? '★' : '☆'}</button>
          <div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 900, color: WL.text.primary, fontFamily: 'monospace', fontSize: 22, letterSpacing: '.02em' }}>{it.symbol}</span>
              {isHeld && <span title={heldTip} style={{ fontSize: 9, fontWeight: 700, color: WL.urgency.amber }}>HELD</span>}
              {provenanceText && <span style={{ fontSize: 10, color: WL.text.dim }}>{provenanceText}</span>}
            </div>
            <div style={{ marginTop: 4, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <ProAnalystPill symbol={it.symbol} map={paMap} compact neutral={!analystDivergent} />
              {analystDivergent && <span style={{ fontSize: 10, color: WL.urgency.red, fontWeight: 700 }}>CIO ≠ Street</span>}
            </div>
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }} onClick={e => e.stopPropagation()}>
          <div style={{ fontSize: 20, fontWeight: 900, color: WL.text.primary, fontFamily: 'monospace' }}>{it.price != null ? money(it.price) : '—'}</div>
          {it.change_pct != null && (
            <div style={{ fontSize: 12, fontWeight: 700, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
              {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
            </div>
          )}
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh Finviz + re-queue synthesis"
            style={{
              marginTop: 6, fontSize: 10, fontWeight: 600, padding: '3px 8px', borderRadius: 5,
              cursor: refreshState ? 'wait' : 'pointer', border: `1px solid ${WL.tag.border}`,
              background: 'transparent', color: needsRefresh ? WL.urgency.amber : WL.text.dim,
            }}
          >{refreshState ? `Refresh ${refreshState}` : 'Refresh'}</button>
        </div>
      </div>

      {/* Recommended action — dominant panel */}
      <div
        onClick={e => e.stopPropagation()}
        title={action.detail}
        style={{
          ...panel,
          background: heroState.bg,
          border: `1px solid ${heroState.border}`,
          borderLeft: `4px solid ${heroState.rail}`,
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) auto',
          gap: 16,
          alignItems: 'start',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: WL.hero.labelSize, fontWeight: 800, letterSpacing: '.12em', color: heroState.accent, marginBottom: 6 }}>
            {heroState.label} · {action.verdict}
          </div>
          <div style={{ fontSize: heroTextSize, fontWeight: 800, color: WL.text.primary, lineHeight: 1.25 }}>{action.heroText}</div>
          {action.subtext && action.subtext !== reasoning && (
            <div style={{ fontSize: WL.hero.subtextSize, color: WL.text.muted, marginTop: 5 }}>{action.subtext}</div>
          )}
          <div style={{ fontSize: 11.5, color: WL.text.secondary, marginTop: 8, lineHeight: 1.5 }} title={reasoning}>{reasoning}</div>
          {alertText && (
            <div style={{
              marginTop: 10, fontSize: 11, fontWeight: 600, lineHeight: 1.45, color: heroState.accent,
              padding: '8px 10px', borderRadius: 6, background: WL.surface.inset,
            }}>
              {alertText}
            </div>
          )}
          {action.detail && (
            <div style={{ marginTop: 8, fontSize: 11, color: WL.text.muted, lineHeight: 1.45, fontStyle: 'italic' }}>
              {action.detail}
            </div>
          )}
          {sizingHint && (
            <div style={{ marginTop: 8, fontSize: 10.5, color: WL.text.muted, lineHeight: 1.4 }}>{sizingHint}</div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, minWidth: 148 }}>
          {rr != null && hasPlan && <RrBadge rr={rr} tip={rrTooltip(entry, stop, planTarget, rr)} />}
          {action.allowPrimary && (
            <button onClick={handlePrimary} style={buttonStyle(action.buttonVariant, false, true)}>{action.primaryLabel}</button>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'flex-end' }}>
            {secondaryActions.map(sec => (
              <button key={sec.label} onClick={e => executeAction(e, sec.type)} style={buttonStyle('neutral', true)}>
                {sec.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* CIO + conviction */}
      <Section label="CIO view">
        <div style={{ ...panel, display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, color: cioAccent, textTransform: 'capitalize' }} title={cioViewTooltip(it)}>
              {cioLabel.replace(/_/g, ' ')}
            </div>
            <div
              title={[confidenceTooltip(it), enrichedTooltip(it), planValidatedTooltip(it)].join('\n')}
              style={{ marginTop: 6, fontSize: 10.5, color: WL.text.muted, lineHeight: 1.5 }}
            >
              Confidence {confVal} · Enriched {enrichVal} · Validated {validatedVal}
              {it.entry_model ? ` · Model ${it.entry_model}` : ''}
              {it.models_agree === true ? ' · Models agree' : it.models_agree === false ? ' · Models split' : ''}
            </div>
          </div>
          {(setupLabel || urgencyLabel || hasZone) && (
            <div style={{ fontSize: 11, color: WL.text.secondary, textAlign: 'right', lineHeight: 1.5 }}>
              {setupLabel && <div>{setupLabel}</div>}
              {urgencyLabel && <div>{urgencyLabel}</div>}
              {hasZone && <div style={{ fontFamily: 'monospace', fontWeight: 700 }}>Zone {money(zoneLo)}–{money(zoneHi)}</div>}
            </div>
          )}
        </div>
      </Section>

      {/* Key levels — always visible */}
      <Section label="Trade plan">
        <div style={panel}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 14 }}>
            <MetricCell label="Limit" value={money(it.entry_limit)} />
            <MetricCell label="Stop" value={money(it.entry_stop)} warn={hasPlan && stop == null} />
            <MetricCell label="Target" value={money(it.entry_target)} />
            <MetricCell label="R:R" value={rr != null ? `${rr.toFixed(2)}` : '—'} warn={rr != null && rr < 1.5} tip={rrTooltip(entry, stop, planTarget, rr)} />
          </div>
          {exitVsStreet && (
            <div style={{ marginTop: 10, fontSize: 11, color: WL.text.muted, lineHeight: 1.45 }} title={exitVsStreet}>{exitVsStreet}</div>
          )}
          {riskLines.length > 0 && riskLines.map((r, i) => (
            <div key={i} style={{ marginTop: 8, fontSize: 10.5, color: r.severity === 'red' ? WL.urgency.red : WL.urgency.amber }}>{r.text}</div>
          ))}
        </div>
      </Section>

      {/* Exit ladder — inline summary */}
      {ladder && (
        <Section label="Exit ladder">
          <div style={{ ...panel, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
            {ladder.steps.map((s, i) => {
              const active = i === focusIdx
              return (
                <div
                  key={i}
                  title={ladderStepTooltip(s.label, s.px, s.action)}
                  style={{
                    fontSize: 11, padding: '6px 10px', borderRadius: 6,
                    background: active ? 'rgba(245,158,11,.1)' : WL.surface.inset,
                    border: `1px solid ${active ? 'rgba(245,158,11,.25)' : WL.surface.divider}`,
                    color: active ? WL.text.primary : WL.text.muted,
                  }}
                >
                  <span style={{ fontWeight: 800, fontFamily: 'monospace' }}>{s.label}</span>
                  <span style={{ marginLeft: 6, fontFamily: 'monospace' }}>{s.px.toFixed(2)}</span>
                </div>
              )
            })}
            <span style={{ fontSize: 10, color: WL.text.dim }}>R ${ladder.R.toFixed(2)}/sh · {MONITOR_RULES.split('.')[0]}</span>
          </div>
        </Section>
      )}

      <FibConfluencePanel symbol={it.symbol} />

      {/* Market context — visible by default */}
      <Section label="Context">
        <div style={{ ...panel, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {fv && <FinvizStrip fv={fv} />}
          {(sectorLine || sc?.vs_sector_week != null) && (
            <div style={{ fontSize: 11, color: WL.text.secondary, lineHeight: 1.5 }}>
              {sectorLine && <span>{sectorLine}</span>}
              {sc?.vs_sector_week != null && (
                <span style={{ marginLeft: sectorLine ? 8 : 0, color: sc.vs_sector_week >= 0 ? WL.urgency.teal : WL.urgency.red }}>
                  {sc.vs_sector_week >= 0 ? '+' : ''}{sc.vs_sector_week}% vs sector (1w)
                </span>
              )}
            </div>
          )}
          {it.catalyst_headline && (
            <div style={{ fontSize: 11, color: WL.text.secondary, lineHeight: 1.45 }}>
              <span style={{ color: WL.text.dim, fontWeight: 700 }}>Catalyst </span>
              {it.catalyst_url ? (
                <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#93c5fd', textDecoration: 'none' }}>{it.catalyst_headline}</a>
              ) : it.catalyst_headline}
              {it.catalyst_at && <span style={{ color: WL.text.dim, marginLeft: 6 }}>{ago(it.catalyst_at)}</span>}
            </div>
          )}
          {companyOneLiner && (
            <div style={{ fontSize: 11, color: WL.text.muted, lineHeight: 1.5 }}>{companyOneLiner}</div>
          )}
          {topNews && (
            <div style={{ fontSize: 11, lineHeight: 1.45, overflowWrap: 'anywhere' }}>
              <span style={{ color: WL.text.dim, fontWeight: 700 }}>News </span>
              <span style={{ color: WL.text.dim }}>{cleanNewsSource(topNews.source)}{topNews.at ? ` · ${ago(topNews.at)}` : ''} </span>
              {topNews.url ? (
                <a href={topNews.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#93c5fd', textDecoration: 'none' }}>{topNews.title}</a>
              ) : <span style={{ color: WL.text.secondary }}>{topNews.title}</span>}
            </div>
          )}
          {llms.length > 0 && (
            <div style={{ fontSize: 10, color: WL.text.dim }}>
              External intel: {llms.map((e: any) => llmMeta(e.lane).label).join(' · ')}
            </div>
          )}
        </div>
      </Section>

      {/* Weekly due diligence reports — always shown */}
      <Section label="Due diligence reports">
        <div style={{ ...panel, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 11, color: WL.text.muted, lineHeight: 1.45, maxWidth: 420 }}>
            Latest weekly analyst prospectus for <b style={{ color: WL.text.secondary }}>{it.symbol}</b>
            {reportEntry?.generated_at ? ` · generated ${ago(reportEntry.generated_at)}` : ' · generate if missing'}
          </div>
          <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} />
        </div>
      </Section>

      {hasMore && (
        <div onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setEvidenceOpen(v => !v)}
            style={{ fontSize: 10, fontWeight: 700, padding: '4px 0', border: 'none', background: 'transparent', color: WL.text.dim, cursor: 'pointer' }}
          >{evidenceOpen ? 'Hide CIO evidence' : 'Show CIO evidence'}</button>
          {evidenceOpen && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {it.synthesis_evidence?.length > 0 && (
                <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
              )}
              {it.synthesis_narrative_snip && (
                <div style={{ fontSize: 11, color: WL.text.muted, fontStyle: 'italic', lineHeight: 1.45 }}>
                  {String(it.synthesis_narrative_snip).slice(0, 320)}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div
        onClick={e => e.stopPropagation()}
        style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', borderTop: `1px solid ${WL.surface.divider}`, paddingTop: 10 }}
      >
        <button onClick={e => { e.stopPropagation(); onDrill(drillCtx) }} style={{ fontSize: 10, fontWeight: 600, padding: 0, border: 'none', background: 'transparent', color: WL.text.dim, cursor: 'pointer' }}>Intel drawer</button>
        <a href={`/v3/rec-intel?symbol=${it.symbol}`} onClick={e => e.stopPropagation()} style={{ fontSize: 10, fontWeight: 600, color: WL.text.dim, textDecoration: 'none' }}>Rec-Intel</a>
        <button onClick={e => { e.stopPropagation(); onToggleEns() }} style={{ fontSize: 10, fontWeight: 600, padding: 0, border: 'none', background: 'transparent', color: WL.text.dim, cursor: 'pointer' }}>Ensemble {ensOpen ? '▲' : '▾'}</button>
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