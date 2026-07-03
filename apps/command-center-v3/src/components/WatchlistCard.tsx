import { useState } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  rrTooltip,
  confidenceTooltip,
  planValidatedTooltip,
  enrichedTooltip,
  cioViewTooltip,
  dataDoubtTooltip,
  ladderStepTooltip,
  type PrimaryActionKind,
} from '../lib/watchlistCardAction'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import { watchlistNeedsRefresh } from '../lib/watchlistCardAction'
import { watchlistReportEligible } from '../lib/reportLinks'

const TEXT0 = '#f8fafc'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#16a34a'
const RED = '#dc2626'
const AMBER = '#d97706'

const NEUTRAL_TAG = {
  background: 'rgba(30,41,59,.75)',
  border: '1px solid rgba(71,85,105,.45)',
  color: '#cbd5e1',
} as const

const cardPanel: React.CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid rgba(148,163,184,.22)',
  borderRadius: 12,
  padding: 16,
  cursor: 'pointer',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  boxShadow: '0 8px 24px rgba(0,0,0,.16)',
}

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

function urgencyAccent(u: string): string | undefined {
  if (u === 'red') return RED
  if (u === 'amber') return AMBER
  if (u === 'green') return GREEN
  return undefined
}

function Tag({ text, tip }: { text: string; tip?: string }) {
  return (
    <span title={tip} style={{
      fontSize: 9.5, fontWeight: 600, padding: '2px 7px', borderRadius: 5,
      whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default', ...NEUTRAL_TAG,
    }}>{text}</span>
  )
}

function MetricCell({ label, value, tip, warn }: { label: string; value: React.ReactNode; tip?: string; warn?: boolean }) {
  return (
    <div title={tip} style={{ minWidth: 0 }}>
      <div style={{ fontSize: 8.5, color: MUTED, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 800 }}>{label}</div>
      <div style={{
        fontSize: 12, fontWeight: 800, marginTop: 3, lineHeight: 1.15, fontFamily: 'monospace',
        color: warn ? RED : TEXT0,
      }}>{value ?? '—'}</div>
    </div>
  )
}

function ladderFocusIndex(ladder: Ladder | null): number {
  if (!ladder?.steps.length) return -1
  return ladder.steps.length > 1 ? 1 : 0
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
}

export default function WatchlistCard({
  it, adv, sc, pa, outcome, llms, fv, reportEntry, paMap,
  ensOpen, refreshState, onDrill, onToggleStar, onRefresh, onToggleEns, isStarred,
}: WatchlistCardProps) {
  const [techOpen, setTechOpen] = useState(false)

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
  const accent = urgencyAccent(action.urgency)
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
    title: `${it.symbol}${it.hermes_rank != null ? ` — Hermes #${it.hermes_rank} (${it.hermes_composite_score})` : ''}`,
    subtitle: `${it.origin_system ?? it.source ?? ''} · ${it.status}`,
    endpoint: `/api/v2/hermes/intel/${it.symbol}`,
    rows: [adv ? { ...it, setup_advisory_note: adv.note, setup_advisory_flag: adv.advisory_flag, current_rsi: adv.rsi, rsi_band: adv.band } : it],
  }

  const originLabel = ({ trade_ai_screener: 'Screener', agent_discovery: 'AI', operator: 'Operator', hermes: 'Hermes', portfolio: 'Portfolio', social: 'Social' } as Record<string, string>)[it.origin_system || ''] || (it.origin_system || 'screener')

  const statusTags: { text: string; tip?: string }[] = []
  statusTags.push({ text: originLabel, tip: it.provenance_reason || it.source })
  if (it.source_tier) statusTags.push({ text: it.source_tier, tip: 'source tier' })
  if (it.directive_id) statusTags.push({ text: 'directive', tip: 'operator watch directive' })
  if (it.in_portfolio || outcome?.held) statusTags.push({ text: 'held', tip: outcome?.held ? `unrealized ${outcome.unrealized_pnl_pct ?? '?'}%` : 'in portfolio' })
  const lists = String(it.watch_lists || '').split(' · ').map((s: string) => s.trim()).filter(Boolean)
  if (lists.length === 1) statusTags.push({ text: lists[0], tip: 'watch list' })
  else if (lists.length > 1) statusTags.push({ text: `+${lists.length} lists`, tip: lists.join(' · ') })
  if (llms.length === 1) statusTags.push({ text: llms[0].lane || 'curated', tip: `Curated by ${llms[0].lane}` })
  const visibleTags = statusTags.slice(0, 4)

  const rsi = it.rsi != null ? Number(it.rsi) : (fv?.rsi != null ? Number(fv.rsi) : null)
  const techParts: string[] = []
  if (rsi != null) techParts.push(`RSI ${rsi.toFixed(0)}`)
  if (it.trend) techParts.push(String(it.trend))
  if (adv?.band) techParts.push(`${adv.advisory_flag === 'caution' ? 'caution' : adv.band} band`)
  if (it.score != null) techParts.push(`score ${Number(it.score).toFixed(0)}`)
  if (stale) techParts.push('technicals stale')

  const sectorLine = sc?.sector || it.profile_sector
    ? [sc?.sector || it.profile_sector, sc?.industry || it.profile_industry].filter(Boolean).join(' · ')
    : null

  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''

  const primaryBtnStyle = (kind: PrimaryActionKind): React.CSSProperties => {
    const solid = kind === 'propose' || kind === 'build'
    const outlinePrimary = kind === 'adjust' || kind === 'review'
    return {
      fontSize: 11, fontWeight: 800, padding: '8px 16px', borderRadius: 8, cursor: 'pointer',
      border: solid ? `1px solid ${GREEN}` : outlinePrimary ? `1px solid ${AMBER}` : '1px solid var(--border)',
      background: solid ? GREEN : outlinePrimary ? 'rgba(217,119,6,.12)' : 'transparent',
      color: solid ? '#fff' : outlinePrimary ? '#fcd34d' : MUTED,
      textDecoration: 'none',
      whiteSpace: 'nowrap',
    }
  }

  const handlePrimary = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (action.primaryKind === 'refresh') onRefresh(e)
    else if (action.primaryKind === 'intel' || action.primaryKind === 'review') onDrill(drillCtx)
    else if (action.primaryKind === 'propose' || action.primaryKind === 'adjust' || action.primaryKind === 'build') {
      window.location.href = `/v3/trading?symbol=${it.symbol}`
    }
  }

  return (
    <div
      onClick={() => onDrill(drillCtx)}
      style={{
        ...cardPanel,
        borderLeft: accent ? `4px solid ${accent}` : '4px solid transparent',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleStar(e) }}
            title={isStarred ? 'Unstar' : 'Star — shows first + faster refresh'}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, padding: 0, lineHeight: 1, color: isStarred ? '#fbbf24' : MUTED }}
          >{isStarred ? '★' : '☆'}</button>
          <span style={{ fontWeight: 950, color: TEXT0, fontFamily: 'monospace', fontSize: 18 }}>{it.symbol}</span>
          {it.hermes_rank != null && (
            <span
              title={`Hermes #${it.hermes_rank} · composite ${it.hermes_composite_score}`}
              style={{ fontSize: 9.5, fontWeight: 700, padding: '2px 6px', borderRadius: 4, ...NEUTRAL_TAG }}
            >#{it.hermes_rank}</span>
          )}
          <ProAnalystPill symbol={it.symbol} map={paMap} compact neutral />
          {it.private_nontradeable && (
            <span title={it.private_note} style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: RED, border: `1px solid ${RED}55`, background: 'rgba(220,38,38,.12)' }}>
              PRIVATE
            </span>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 17, fontWeight: 900, color: TEXT0 }}>{it.price != null ? money(it.price) : '—'}</div>
            {it.change_pct != null && (
              <div style={{ fontSize: 12, fontWeight: 800, color: Number(it.change_pct) >= 0 ? GREEN : RED }}>
                {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
              </div>
            )}
          </div>
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh Finviz/RSI + re-queue synthesis"
            style={{
              fontSize: 9, fontWeight: 600, padding: '3px 8px', borderRadius: 5, cursor: refreshState ? 'wait' : 'pointer',
              border: `1px solid ${needsRefresh ? AMBER + '66' : 'rgba(71,85,105,.5)'}`,
              background: 'transparent', color: needsRefresh ? AMBER : DIM,
            }}
          >{refreshState ? `↻ ${refreshState}` : '↻ Refresh'}</button>
        </div>
      </div>

      {/* Recommended action */}
      <div style={{
        padding: '10px 12px',
        background: 'rgba(15,23,42,.55)',
        borderLeft: accent ? `3px solid ${accent}` : '3px solid rgba(71,85,105,.4)',
        borderRadius: 8,
      }}>
        <div style={{ fontSize: 8.5, color: MUTED, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 800 }}>
          Recommended action
        </div>
        <div style={{ fontSize: 13, fontWeight: 700, color: TEXT0, marginTop: 4, lineHeight: 1.4 }}>{action.text}</div>
        {action.subtext && <div style={{ fontSize: 10, color: MUTED, marginTop: 3, lineHeight: 1.35 }}>{action.subtext}</div>}
      </div>

      {/* Key decision metrics */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
        gap: 10,
        padding: '10px 12px',
        background: 'rgba(2,6,23,.32)',
        border: '1px solid rgba(148,163,184,.15)',
        borderRadius: 10,
      }}>
        <MetricCell label="Entry model" value={it.entry_model || '—'} />
        <MetricCell label="R:R" value={rr != null ? rr.toFixed(2) : '—'} tip={rrTooltip(entry, stop, planTarget, rr)} warn={rr != null && rr < 1.5} />
        <MetricCell label="Limit" value={money(it.entry_limit)} />
        <MetricCell label="Stop" value={money(it.entry_stop)} warn={hasPlan && stop == null} />
        <MetricCell label="Street" value={street != null ? money(street) : '—'} tip={pa?.n ? `${pa.n} analysts · mean target` : undefined} />
      </div>

      {/* Conviction block */}
      <div style={{
        padding: '8px 12px',
        background: 'rgba(2,6,23,.28)',
        border: '1px solid rgba(148,163,184,.12)',
        borderRadius: 8,
        fontSize: 10.5,
        color: TEXT2,
        lineHeight: 1.5,
      }}>
        <span title={cioViewTooltip(it)} style={{ cursor: 'help' }}>
          <b style={{ color: MUTED, fontWeight: 700 }}>CIO</b> {cioLabel}
        </span>
        <span style={{ color: DIM, margin: '0 6px' }}>·</span>
        <span title={confidenceTooltip(it)} style={{ cursor: 'help' }}>
          <b style={{ color: MUTED, fontWeight: 700 }}>Conf</b> {confVal}
        </span>
        <span style={{ color: DIM, margin: '0 6px' }}>·</span>
        <span title={enrichedTooltip(it)} style={{ cursor: 'help' }}>
          <b style={{ color: MUTED, fontWeight: 700 }}>Enriched</b> {enrichVal}
        </span>
        <span style={{ color: DIM, margin: '0 6px' }}>·</span>
        <span title={planValidatedTooltip(it)} style={{ cursor: 'help' }}>
          <b style={{ color: MUTED, fontWeight: 700 }}>Validated</b> {validatedVal}
        </span>
        {it.models_agree === true && (
          <span title={`Grok + ChatGPT agree (${it.grok_recommendation})`} style={{ marginLeft: 8, fontSize: 9.5, color: MUTED }}>✓ 2 models</span>
        )}
        {it.models_agree === false && (
          <span title={`Grok: ${it.grok_recommendation} · ChatGPT: ${it.chatgpt_recommendation}`} style={{ marginLeft: 8, fontSize: 9.5, color: AMBER }}>⚠ models split</span>
        )}
      </div>

      {/* Exit ladder — before status/tags per hierarchy */}
      {ladder && (
        <div onClick={e => e.stopPropagation()} style={{
          background: 'rgba(2,6,23,.32)',
          border: '1px solid rgba(148,163,184,.15)',
          borderRadius: 10,
          padding: '9px 11px',
        }}>
          <div style={{ fontSize: 9, color: MUTED, fontWeight: 800, textTransform: 'uppercase', marginBottom: 6 }}>
            Exit ladder · R = ${ladder.R.toFixed(2)}/sh
          </div>
          {ladder.steps.map((s, i) => {
            const active = i === focusIdx
            return (
              <div
                key={i}
                title={ladderStepTooltip(s.label, s.px, s.action)}
                style={{
                  fontSize: 11, marginTop: i ? 4 : 0, padding: '4px 8px', borderRadius: 6,
                  background: active ? 'rgba(51,65,85,.35)' : 'transparent',
                  borderLeft: active ? `2px solid ${AMBER}` : '2px solid transparent',
                  color: active ? TEXT0 : TEXT2,
                }}
              >
                <span style={{ fontWeight: active ? 800 : 600, fontFamily: 'monospace' }}>{s.label} {s.px.toFixed(2)}</span>
                <span style={{ color: MUTED, fontSize: 10 }}> — {s.action}</span>
              </div>
            )
          })}
          <div style={{ fontSize: 9, color: DIM, marginTop: 6 }}>In-trade: {MONITOR_RULES}</div>
        </div>
      )}

      {/* Plan / risk warnings */}
      {warns.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {warns.map((w, i) => (
            <div key={i} style={{
              fontSize: 10.5, fontWeight: 700, color: w.color === RED ? RED : AMBER,
              padding: '6px 10px', borderRadius: 6,
              background: w.color === RED ? 'rgba(220,38,38,.1)' : 'rgba(217,119,6,.1)',
              border: `1px solid ${w.color === RED ? RED : AMBER}44`,
            }}>⚠ {w.text}</div>
          ))}
        </div>
      )}

      {dataDoubt && (
        <div
          title={dataDoubtTooltip(dataDoubt)}
          style={{
            display: 'flex', gap: 8, alignItems: 'flex-start',
            fontSize: 10.5, fontWeight: 650, color: AMBER,
            padding: '7px 10px', borderRadius: 6,
            background: 'rgba(217,119,6,.1)', border: `1px solid ${AMBER}44`,
            lineHeight: 1.4, cursor: 'help',
          }}
        >
          <span style={{ fontSize: 12, lineHeight: 1 }} aria-hidden>⚠</span>
          <span><b style={{ fontWeight: 800 }}>Data doubt</b> — {dataDoubt}</span>
        </div>
      )}

      {it.synthesis_evidence?.length > 0 && (
        <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
      )}

      {it.synthesis_narrative_snip && (
        <div style={{ fontSize: 10.5, color: TEXT2, lineHeight: 1.45, fontStyle: 'italic' }}>
          {String(it.synthesis_narrative_snip).slice(0, 200)}{String(it.synthesis_narrative_snip).length > 200 ? '…' : ''}
        </div>
      )}

      {/* Status tags */}
      {visibleTags.length > 0 && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          {visibleTags.map(t => <Tag key={t.text} text={t.text} tip={t.tip} />)}
          {outcome?.sold && (
            <Tag
              text={`sold ${(outcome.last_pnl_pct ?? 0) >= 0 ? '+' : ''}${outcome.last_pnl_pct ?? '?'}%`}
              tip={`Prior closed trade${outcome.closed_trades > 1 ? ` · ${outcome.closed_trades}×` : ''}`}
            />
          )}
        </div>
      )}

      {/* Technicals — collapsed */}
      {(techParts.length > 0 || fv) && (
        <div onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setTechOpen(v => !v)}
            style={{
              fontSize: 9.5, fontWeight: 700, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
              border: '1px solid rgba(71,85,105,.45)', background: 'transparent', color: MUTED,
            }}
          >{techOpen ? '▾' : '▸'} Technicals{techParts.length ? ` · ${techParts.join(' · ')}` : ''}</button>
          {techOpen && fv && (
            <div title="Finviz daily metrics" style={{
              display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 6, padding: '6px 10px',
              background: 'rgba(2,6,23,.28)', borderRadius: 8, fontSize: 10, color: TEXT2,
            }}>
              {['rsi', 'perf_week', 'perf_month', 'perf_ytd', 'sma50'].map(k => (
                fv[k] != null && <span key={k}><span style={{ color: DIM }}>{k} </span>{Number(fv[k]).toFixed(1)}{k.includes('perf') || k === 'sma50' ? '%' : ''}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {sectorLine && <div style={{ fontSize: 10, color: DIM }}>{sectorLine}</div>}

      {it.catalyst_headline && (
        <div style={{ fontSize: 10, color: TEXT2, lineHeight: 1.4 }}>
          <span style={{ color: MUTED, fontWeight: 700 }}>Catalyst </span>
          {it.catalyst_url ? (
            <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#bfdbfe', textDecoration: 'none' }}>
              {it.catalyst_headline}
            </a>
          ) : it.catalyst_headline}
          {it.catalyst_at && <span style={{ color: DIM, marginLeft: 6 }}>{ago(it.catalyst_at)}</span>}
        </div>
      )}

      {!enriched && <div style={{ fontSize: 10.5, color: MUTED, fontStyle: 'italic' }}>awaiting enrichment…</div>}

      <div onClick={e => e.stopPropagation()}>
        <FibConfluencePanel symbol={it.symbol} />
      </div>

      {/* Actions */}
      <div style={{
        display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
        borderTop: '1px solid rgba(148,163,184,.15)', paddingTop: 10,
      }}>
        {['propose', 'build', 'adjust'].includes(action.primaryKind) ? (
          <a href={`/v3/trading?symbol=${it.symbol}`} onClick={e => e.stopPropagation()} style={primaryBtnStyle(action.primaryKind)}>
            {action.primaryLabel}
          </a>
        ) : (
          <button onClick={handlePrimary} style={primaryBtnStyle(action.primaryKind)}>{action.primaryLabel}</button>
        )}
        <button
          onClick={e => { e.stopPropagation(); onDrill(drillCtx) }}
          style={{ fontSize: 10, fontWeight: 600, padding: '6px 10px', borderRadius: 6, border: 'none', background: 'transparent', color: MUTED, cursor: 'pointer' }}
        >Open</button>
        <a
          href={`/v3/rec-intel?symbol=${it.symbol}`}
          onClick={e => e.stopPropagation()}
          style={{ fontSize: 10, fontWeight: 600, padding: '6px 10px', color: MUTED, textDecoration: 'none' }}
        >Rec-Intel</a>
        <button
          onClick={e => { e.stopPropagation(); onToggleEns() }}
          style={{ fontSize: 10, fontWeight: 600, padding: '6px 10px', borderRadius: 6, border: 'none', background: 'transparent', color: MUTED, cursor: 'pointer' }}
        >Ensemble {ensOpen ? '▲' : '▾'}</button>
        {watchlistReportEligible(it) && (
          <HoldingReportLinks
            symbol={it.symbol}
            entry={reportEntry}
            reportType={reportEntry?.report_type || 'symbol_watchlist'}
            compact
          />
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