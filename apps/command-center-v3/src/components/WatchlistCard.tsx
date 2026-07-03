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
  const [detailsOpen, setDetailsOpen] = useState(false)
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
  const hasDetails = !!(companyDesc || sectorLine || it.catalyst_headline || allNews.length
    || fv || llms.length || riskLines.length || ladder
    || it.synthesis_evidence?.length || it.synthesis_narrative_snip || action.detail)

  const planLine = [
    hasPlan ? `L ${money(entry)}` : null,
    hasPlan ? `S ${money(stop)}` : null,
    rr != null ? `R:R ${rr.toFixed(1)}` : null,
    `CIO ${cioLabel}`,
    fv?.rsi != null ? `RSI ${Math.round(Number(fv.rsi))}` : null,
    sc?.sector || it.profile_sector || null,
    provenanceText || null,
  ].filter(Boolean).join(' · ')

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

  const rowBorder = accent ? `1px solid ${accent}44` : WL.card.border

  return (
    <div
      style={{
        background: WL.card.bg,
        border: rowBorder,
        borderLeft: accent ? `3px solid ${accent}` : `3px solid transparent`,
        borderRadius: 8,
        minWidth: 0,
        width: '100%',
        boxSizing: 'border-box',
        overflow: 'hidden',
      }}
    >
      {/* Single scan row */}
      <div
        onClick={() => onDrill(drillCtx)}
        title={action.detail}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '8px 12px',
          cursor: 'pointer',
          minWidth: 0,
        }}
      >
        <button
          onClick={e => { e.stopPropagation(); onToggleStar(e) }}
          title={isStarred ? 'Unstar' : 'Star'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: 0, flexShrink: 0, color: isStarred ? WL.text.secondary : WL.text.dim }}
        >{isStarred ? '★' : '☆'}</button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, minWidth: 118 }}>
          <span style={{ fontWeight: 950, color: WL.text.primary, fontFamily: 'monospace', fontSize: 15 }}>{it.symbol}</span>
          <VerdictChip verdict={action.verdict} />
          {isHeld && (
            <span title={heldTip} style={{ fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 3, color: '#ffa726', border: '1px solid rgba(255,167,38,.45)', background: 'rgba(255,167,38,.12)' }}>H</span>
          )}
        </div>

        <ProAnalystPill symbol={it.symbol} map={paMap} compact neutral />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: WL.text.primary, whiteSpace: 'nowrap' }}>{action.heroText}</span>
            {action.subtext && (
              <span style={{ fontSize: 10, color: WL.text.muted, whiteSpace: 'nowrap' }}>{action.subtext}</span>
            )}
          </div>
          <div style={{
            fontSize: 10, color: WL.text.secondary, marginTop: 2,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={planLine}>{planLine}</div>
        </div>

        <div style={{ textAlign: 'right', flexShrink: 0, minWidth: 72 }}>
          <div style={{ fontSize: 14, fontWeight: 900, color: WL.text.primary, fontFamily: 'monospace' }}>{it.price != null ? money(it.price) : '—'}</div>
          {it.change_pct != null && (
            <div style={{ fontSize: 10, fontWeight: 800, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
              {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
            </div>
          )}
        </div>

        <div onClick={e => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {action.allowPrimary && (
            <button onClick={handlePrimary} style={buttonStyle(action.buttonVariant, true)}>{action.primaryLabel}</button>
          )}
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh"
            style={{
              fontSize: 10, fontWeight: 600, padding: '4px 7px', borderRadius: 4,
              cursor: refreshState ? 'wait' : 'pointer', border: `1px solid ${WL.tag.border}`,
              background: 'transparent', color: needsRefresh ? WL.urgency.amber : WL.text.dim,
            }}
          >{refreshState ? '↻' : '↻'}</button>
          {hasDetails && (
            <button
              onClick={e => { e.stopPropagation(); setDetailsOpen(v => !v) }}
              title="Expand details"
              style={{
                fontSize: 10, fontWeight: 700, padding: '4px 7px', borderRadius: 4, cursor: 'pointer',
                border: `1px solid ${WL.tag.border}`, background: detailsOpen ? WL.body.bg : 'transparent', color: WL.text.muted,
              }}
            >{detailsOpen ? '▾' : '▸'}</button>
          )}
        </div>
      </div>

      {/* Expanded details — one panel */}
      {detailsOpen && (
        <div
          onClick={e => e.stopPropagation()}
          style={{
            padding: '8px 12px 10px',
            borderTop: `1px solid ${WL.body.border}`,
            background: WL.body.bg,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          {riskLines.map((r, i) => {
            const c = r.severity === 'red' ? WL.urgency.red : WL.urgency.amber
            return (
              <div key={i} title={r.doubt ? dataDoubtTooltip(r.text) : undefined} style={{ fontSize: 10, color: c, lineHeight: 1.4 }}>
                ⚠ {r.doubt ? <>Data doubt — {r.text}</> : r.text}
              </div>
            )
          })}

          <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.5 }}>
            <span title={cioViewTooltip(it)}><b style={{ color: WL.text.muted }}>CIO</b> {cioLabel}</span>
            <span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span>
            <span title={confidenceTooltip(it)}><b style={{ color: WL.text.muted }}>Conf</b> {confVal}</span>
            <span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span>
            <span title={enrichedTooltip(it)}><b style={{ color: WL.text.muted }}>Enriched</b> {enrichVal}</span>
            <span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span>
            <span title={planValidatedTooltip(it)}><b style={{ color: WL.text.muted }}>Validated</b> {validatedVal}</span>
            {it.entry_model && <><span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span><span><b style={{ color: WL.text.muted }}>Model</b> {it.entry_model}</span></>}
            {outcome?.sold && <><span style={{ color: WL.text.dim, margin: '0 5px' }}>·</span><span>sold {(outcome.last_pnl_pct ?? 0) >= 0 ? '+' : ''}{outcome.last_pnl_pct ?? '?'}%</span></>}
          </div>

          {action.detail && (
            <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.45 }}>
              <span style={{ color: WL.text.muted, fontWeight: 700 }}>Advisory </span>{action.detail}
            </div>
          )}

          {companyDesc && (
            <div style={{ fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.45 }}>{companyDesc}</div>
          )}

          {it.catalyst_headline && (
            <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.4 }}>
              {it.catalyst_type && <IntelPill text={`⚡ ${String(it.catalyst_type).replace(/_/g, ' ')}`} color={WL.urgency.amber} />}{' '}
              {it.catalyst_url ? (
                <a href={it.catalyst_url} target="_blank" rel="noreferrer" style={{ color: '#bfdbfe', textDecoration: 'none' }}>{it.catalyst_headline}</a>
              ) : it.catalyst_headline}
            </div>
          )}

          {allNews.slice(0, 2).map((n: any, i: number) => (
            <div key={i} style={{ fontSize: 10, lineHeight: 1.35, overflowWrap: 'anywhere' }}>
              <span style={{ color: WL.text.muted }}>{cleanNewsSource(n.source)}{n.at ? ` · ${ago(n.at)}` : ''} </span>
              {n.url ? (
                <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#bfdbfe', textDecoration: 'none' }}>{n.title}</a>
              ) : <span style={{ color: WL.text.secondary }}>{n.title}</span>}
            </div>
          ))}

          {fv && <FinvizStrip fv={fv} />}

          {prominence.showLadder && ladder && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: WL.text.muted, marginBottom: 4 }}>Exit ladder · R ${ladder.R.toFixed(2)}/sh</div>
              {ladder.steps.map((s, i) => {
                const active = i === focusIdx
                return (
                  <div key={i} title={ladderStepTooltip(s.label, s.px, s.action)} style={{
                    fontSize: 10, marginTop: i ? 2 : 0, color: active ? WL.text.primary : WL.text.secondary,
                  }}>
                    <span style={{ fontWeight: active ? 800 : 500, fontFamily: 'monospace' }}>{s.label} {s.px.toFixed(2)}</span>
                    <span style={{ color: WL.text.dim, fontSize: 9 }}> — {s.action}</span>
                  </div>
                )
              })}
              <button onClick={() => setRulesOpen(v => !v)} style={{ marginTop: 4, fontSize: 9, border: 'none', background: 'none', color: WL.text.dim, cursor: 'pointer' }}>
                {rulesOpen ? '▾' : '▸'} In-trade rules
              </button>
              {rulesOpen && <div style={{ fontSize: 9, color: WL.text.dim, lineHeight: 1.4 }}>{MONITOR_RULES}</div>}
            </div>
          )}

          {it.synthesis_evidence?.length > 0 && (
            <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
          )}
          {it.synthesis_narrative_snip && (
            <div style={{ fontSize: 10, color: WL.text.secondary, fontStyle: 'italic', lineHeight: 1.45 }}>
              {String(it.synthesis_narrative_snip).slice(0, 280)}
            </div>
          )}
          <FibConfluencePanel symbol={it.symbol} />

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', paddingTop: 4 }}>
            <button onClick={e => { e.stopPropagation(); onDrill(drillCtx) }} style={{ fontSize: 10, fontWeight: 600, padding: 0, border: 'none', background: 'transparent', color: WL.text.muted, cursor: 'pointer' }}>Intel</button>
            <a href={`/v3/rec-intel?symbol=${it.symbol}`} onClick={e => e.stopPropagation()} style={{ fontSize: 10, fontWeight: 600, color: WL.text.muted, textDecoration: 'none' }}>Rec-Intel</a>
            <button onClick={e => { e.stopPropagation(); onToggleEns() }} style={{ fontSize: 10, fontWeight: 600, padding: 0, border: 'none', background: 'transparent', color: WL.text.muted, cursor: 'pointer' }}>Ensemble {ensOpen ? '▲' : '▾'}</button>
            {llms.map((e: any, i: number) => {
              const m = llmMeta(e.lane)
              return <IntelPill key={`llm-${i}`} text={`✦ ${m.label}`} color={m.color} tip={m.label} />
            })}
            {watchlistReportEligible(it) && (
              <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} compact />
            )}
          </div>

          {ensOpen && (
            <EnsembleValidationInline
              targetType="signal"
              targetId={it.id}
              subject={it.symbol}
              content={`${it.symbol} watchlist — ${it.latest_recommendation || it.trend || ''} · ${it.profile_sector || ''}`}
            />
          )}
        </div>
      )}
    </div>
  )
}