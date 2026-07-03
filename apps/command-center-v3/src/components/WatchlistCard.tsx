import { useState } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  actionProminence,
  buttonStyle,
  rrTooltip,
  confidenceTooltip,
  planValidatedTooltip,
  enrichedTooltip,
  cioViewTooltip,
  dataDoubtTooltip,
  ladderStepTooltip,
  watchlistNeedsRefresh,
  type CardActionType,
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

function ladderFocusIndex(ladder: Ladder | null): number {
  if (!ladder?.steps.length) return -1
  return ladder.steps.length > 1 ? 1 : 0
}

function ladderSummary(ladder: Ladder): string {
  const focus = ladder.steps[ladderFocusIndex(ladder)]
  return focus ? `${focus.label} ${focus.px.toFixed(2)}` : ''
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
  for (const w of warns.slice(0, 1)) {
    riskLines.push({ text: w.text, severity: w.color === WL.urgency.red ? 'red' : 'amber' })
  }
  if (dataDoubt) riskLines.push({ text: dataDoubt, severity: 'amber', doubt: true })
  const sectorLine = sc?.sector || it.profile_sector
    ? [sc?.sector || it.profile_sector, sc?.industry || it.profile_industry].filter(Boolean).join(' · ')
    : null
  const hasContext = !!(sectorLine || it.catalyst_headline || it.synthesis_evidence?.length
    || it.synthesis_narrative_snip || fv || hasMetaContext || !enriched)

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

      {/* 2. Hero — recommended action + primary CTA */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          padding: '14px 14px 12px',
          background: WL.hero.bg,
          borderRadius: WL.body.radius,
          border: `1px solid ${WL.hero.border}`,
          borderLeft: accent ? `4px solid ${accent}` : `4px solid ${WL.hero.border}`,
        }}
      >
        <div style={{
          fontSize: WL.hero.labelSize, color: WL.text.muted, textTransform: 'uppercase',
          letterSpacing: '.08em', fontWeight: 800,
        }}>Recommended action</div>
        <div style={{
          fontSize: heroTextSize, fontWeight: 700, color: WL.text.primary,
          marginTop: 6, lineHeight: 1.35,
        }}>{action.heroText}</div>
        {action.subtext && (
          <div style={{ fontSize: WL.hero.subtextSize, color: WL.text.muted, marginTop: 4, lineHeight: 1.35 }}>{action.subtext}</div>
        )}
        {action.allowPrimary && (
          <div style={{ marginTop: 12 }}>
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

      {/* 5. Exit ladder — compact / collapsible */}
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

      {/* 6. Provenance (single chip — tier/directive live in Context) */}
      {(provenanceText || outcome?.sold) && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          {provenanceText && <Tag text={provenanceText} tip={provenanceTip} />}
          {outcome?.sold && (
            <Tag text={`sold ${(outcome.last_pnl_pct ?? 0) >= 0 ? '+' : ''}${outcome.last_pnl_pct ?? '?'}%`} tip="Prior closed trade" />
          )}
        </div>
      )}

      {/* Context drawer — evidence, catalyst, technicals, fib */}
      {hasContext && (
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
              {sectorLine && <div style={{ fontSize: 10, color: WL.text.dim }}>{sectorLine}</div>}
              {it.catalyst_headline && (
                <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.4 }}>
                  <span style={{ color: WL.text.muted, fontWeight: 700 }}>Catalyst </span>
                  {it.catalyst_url ? (
                    <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: WL.text.secondary, textDecoration: 'underline' }}>
                      {it.catalyst_headline}
                    </a>
                  ) : it.catalyst_headline}
                </div>
              )}
              {fv && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 10, color: WL.text.secondary }}>
                  {['rsi', 'perf_week', 'perf_month', 'perf_ytd', 'sma50'].map(k => (
                    fv[k] != null && <span key={k}><span style={{ color: WL.text.dim }}>{k} </span>{Number(fv[k]).toFixed(1)}{k.includes('perf') || k === 'sma50' ? '%' : ''}</span>
                  ))}
                </div>
              )}
              {it.synthesis_evidence?.length > 0 && (
                <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
              )}
              {it.synthesis_narrative_snip && (
                <div style={{ fontSize: 10, color: WL.text.secondary, lineHeight: 1.45, fontStyle: 'italic' }}>
                  {String(it.synthesis_narrative_snip).slice(0, 200)}
                </div>
              )}
              <FibConfluencePanel symbol={it.symbol} />
            </div>
          )}
        </div>
      )}

      {/* 7. Secondary actions */}
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