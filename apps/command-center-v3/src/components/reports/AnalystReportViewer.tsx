/** AnalystReportViewer — polished analyst report with charts, action queue, and modals. */
import { useMemo, useState } from 'react'
import ThesisValidityBar from '../ThesisValidityBar'
import { EnsembleValidationCard, normalizeEnsembleResult } from '../EnsembleValidationCard'
import type { ThesisValidity } from '../../lib/brokerThesis'
import ActionDeck, { buildDeckActions, type DeckAction } from './ActionDeck'
import AnalystActionModal from './AnalystActionModal'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }

const REC_COLORS: Record<string, string> = {
  BUY: '#22c55e', ADD: '#22c55e', HOLD: '#60a5fa', TRIM: '#f59e0b', SELL: '#ef4444',
  AVOID: '#ef4444', REVIEW: '#9ca3af', MONITOR: '#a78bfa',
}

const THESIS_COLORS: Record<string, string> = {
  'Still valid': '#22c55e', 'At risk': '#f59e0b', 'Broken': '#ef4444',
}

const RELEVANCE_COLORS: Record<string, string> = {
  'Relevant': '#22c55e', 'Mixed': '#f59e0b', 'Low value': '#9ca3af',
  'Aligned': '#22c55e', 'Divergent': '#f59e0b', 'Low': '#9ca3af',
}

const DIGEST_TYPES = new Set(['daily_digest', 'weekly_review', 'intelligence_deep', 'event_driven'])

function chartSrc(path?: string) {
  if (!path) return null
  if (path.startsWith('/')) return path
  const idx = path.indexOf('/data/')
  return idx >= 0 ? path.slice(idx) : `/data/portfolios/reports/analyst/charts/${path.split('/').pop()}`
}

function normConfidence(val: unknown): number | null {
  if (val == null || val === '') return null
  const n = Number(val)
  if (!Number.isFinite(n)) return null
  return n > 0 && n <= 1 ? n * 100 : n
}

function formatMetric(key: string, val: unknown): string {
  const n = Number(val)
  if (key === 'confidence') {
    const c = normConfidence(val)
    return c != null ? `${c.toFixed(0)}%` : String(val)
  }
  if (key.endsWith('_pct') && Number.isFinite(n)) return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
  if ((key === 'unrealized_pnl' || key === 'cost_basis' || key === 'market_value' || key === 'entry_price') && Number.isFinite(n)) {
    return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }
  if (key === 'price' && Number.isFinite(n)) return `$${n.toFixed(2)}`
  if (key === 'score' && Number.isFinite(n)) return `${n.toFixed(1)}/10`
  if (key === 'consensus') return val ? 'yes' : 'no'
  if (typeof val === 'boolean') return val ? 'yes' : 'no'
  return String(val)
}

function relevanceColor(text: string): string {
  const t = String(text || '')
  if (t.startsWith('Relevant') || t.startsWith('Aligned')) return RELEVANCE_COLORS['Aligned']
  if (t.startsWith('Mixed') || t.startsWith('Divergent')) return RELEVANCE_COLORS['Divergent']
  if (t.startsWith('Low')) return RELEVANCE_COLORS['Low']
  return 'var(--text3)'
}

function CalloutBox({ label, text, accent = '#f59e0b' }: { label: string; text: string; accent?: string }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, color: 'var(--text0)', padding: '10px 14px', marginBottom: 8,
      borderLeft: `4px solid ${accent}`, background: 'var(--bg2)', borderRadius: '0 8px 8px 0',
      lineHeight: 1.45,
    }}>
      <span style={{ fontWeight: 800, color: accent }}>{label}: </span>{text}
    </div>
  )
}

function GaugeBar({ value, max, label, color, suffix = '' }: { value: number; max: number; label: string; color: string; suffix?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ fontWeight: 700, color: 'var(--text1)' }}>{value.toFixed(1)}{suffix}</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: 'var(--bg0)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width .3s' }} />
      </div>
    </div>
  )
}

function KpiTile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', minWidth: 100 }}>
      <div style={{ fontSize: 8, fontWeight: 700, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, color: color || 'var(--text0)', marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function actionDisplayText(a: any): string {
  const text = String(a.text || a.message || '').trim()
  const title = String(a.title || '').trim()
  if (text.length >= 24 && text !== title) return text
  if (title.length >= 12) return title
  return text || title || 'Review this item'
}

function toDeckAction(a: any): DeckAction {
  const text = actionDisplayText(a)
  const sym = a.symbol ? String(a.symbol).toUpperCase() : undefined
  let actionClass = a.action_class
  let route = a.route
  let routeLabel = a.route_label
  if (/recovery watch|reentry candidate/i.test(text)) {
    actionClass = 'recovery'
    if (sym) {
      route = `/v3/risk?symbol=${sym}&drawer=recovery`
      routeLabel = 'Recovery'
    } else {
      route = '/v3/risk?tab=Recovery'
      routeLabel = 'Recovery'
    }
  } else if (/stop.*triggered|unprotected/i.test(text) && !route?.includes('/v3/risk')) {
    actionClass = actionClass || 'stop_triggered'
    route = sym ? `/v3/risk?symbol=${sym}&drawer=stops` : '/v3/risk?drawer=stops'
    routeLabel = routeLabel || 'Risk'
  } else if (/proposal/i.test(text) && !route?.includes('/v3/trading')) {
    route = '/v3/trading?tab=Broker%20Proposals'
    routeLabel = routeLabel || 'Trading'
  }
  return {
    id: a.id,
    text,
    symbol: sym,
    severity: a.severity,
    route,
    route_label: routeLabel,
    source: a.source || actionClass,
    action_class: actionClass,
  } as DeckAction & { action_class?: string }
}

export default function AnalystReportViewer({ report }: { report: any }) {
  const [modalAction, setModalAction] = useState<DeckAction | null>(null)
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({})

  const meta = report?.meta || {}
  const kpis = meta.kpis || {}
  const sections = report.sections || []
  const visuals = report.visuals || []
  const items = report.items || []
  const sectors = report.sectors || []
  const isDigest = DIGEST_TYPES.has(meta.report_type)
  const isAllScope = meta.scope === 'all'

  const actions: DeckAction[] = useMemo(() => {
    const raw = report.action_items || []
    if (raw.length) return raw.map(toDeckAction)
    return buildDeckActions({ briefActions: [], cap: 0 })
  }, [report.action_items])

  const thesisVis = visuals.find((v: any) => v.type === 'thesis_validity_bar')
  const priceVis = visuals.find((v: any) => v.type === 'price_levels')
  const riskVis = visuals.find((v: any) => v.type === 'risk_profile')
  const chartVisuals = visuals.filter((v: any) =>
    (v.chart_path && chartSrc(v.chart_path)) || (v.type === 'health_gauge' && v.score != null)
  )
  const intelSec = sections.find((s: any) => s.id === 'intelligence_view')
  const ensembleSec = sections.find((s: any) => s.id === 'ensemble_validation')
  const ensembleRaw = intelSec?.ensemble || ensembleSec?.ensemble
  const ensembleResult = ensembleRaw ? normalizeEnsembleResult(ensembleRaw) : null
  const actionPlanSec = sections.find((s: any) => s.id === 'action_plan' || s.id === 'recommendation')
  const headerSec = sections.find((s: any) => s.id === 'header_context')
  const execSec = sections.find((s: any) => s.id === 'executive_summary')

  const rec = String(kpis.recommendation || meta.recommendation || '').toUpperCase()
  const recColor = REC_COLORS[rec] || REC_COLORS[rec.split(' ')[0]] || '#60a5fa'
  const conf = normConfidence(kpis.confidence)
  const price = kpis.price != null ? Number(kpis.price) : null
  const dayPct = kpis.day_change_pct != null ? Number(kpis.day_change_pct) : null
  const thesisStatus = String(kpis.thesis_status || execSec?.metrics?.thesis_status || '')
  const thesisColor = THESIS_COLORS[thesisStatus] || '#60a5fa'
  const entryPrice = kpis.entry_price != null ? Number(kpis.entry_price) : null
  const unrealPct = kpis.unrealized_pnl_pct != null ? Number(kpis.unrealized_pnl_pct) : null
  const unrealPnl = kpis.unrealized_pnl != null ? Number(kpis.unrealized_pnl) : null
  const whatNow = execSec?.metrics?.what_to_do_now || actionPlanSec?.bullets?.[0]

  const legacyAgentIds = new Set(['agent_synthesis', 'agent_performance_note', 'ensemble_validation'])
  const digestSkip = new Set(['agent_synthesis', 'intelligence_view', 'risk_assessment'])
  const eventSkip = new Set(['risk_assessment', 'key_risks', 'fundamental_news'])
  const intelSkip = new Set(['fundamental_news', 'key_risks'])
  const pinnedIds = new Set(['action_plan', 'recommendation', 'header_context'])
  const visibleSections = sections.filter((s: any) => {
    if (pinnedIds.has(s.id)) return false
    if (s.id in legacyAgentIds && intelSec) return false
    if (s.id === 'ensemble_validation' && (ensembleResult || intelSec)) return false
    if (isDigest && actions.length > 0 && digestSkip.has(s.id)) return false
    if (meta.report_type === 'event_driven' && actions.length > 0 && eventSkip.has(s.id)) return false
    if (meta.report_type === 'intelligence_deep' && actions.length > 0 && intelSkip.has(s.id)) return false
    if (meta.report_type === 'intelligence_deep' && actions.length > 0 && s.id === 'ensemble_validation' && !(s.bullets || []).length) return false
    return true
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <AnalystActionModal action={modalAction} onClose={() => setModalAction(null)} />

      {/* Hero */}
      <div style={{ ...card, background: 'linear-gradient(135deg, var(--bg1) 0%, rgba(96,165,250,.06) 100%)' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 18, fontWeight: 900, color: 'var(--text0)' }}>{meta.title}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>
              {meta.type_label} · {meta.generated_at ? new Date(meta.generated_at).toLocaleString() : ''}
              {meta.symbol && <> · <span style={{ fontFamily: 'monospace', color: '#60a5fa' }}>{meta.symbol}</span></>}
              {meta.version && <span style={{ marginLeft: 6, color: '#a78bfa', fontWeight: 700 }}>v{meta.version}</span>}
              {isAllScope && <span style={{ color: '#22c55e', fontWeight: 700 }}> · ALL {meta.instrument_count || kpis.instrument_count || ''}</span>}
            </div>
            {(execSec?.callouts || []).length > 0 && !isDigest ? (
              <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {(execSec.callouts as any[]).map((co: any, i: number) => (
                  <CalloutBox
                    key={i}
                    label={co.label || 'Note'}
                    text={co.text || ''}
                    accent={String(co.label || '').includes('Thesis') ? thesisColor : '#f59e0b'}
                  />
                ))}
              </div>
            ) : whatNow && !isDigest ? (
              <div style={{ fontSize: 11, color: 'var(--text1)', marginTop: 10, padding: '8px 12px', borderRadius: 8, background: 'var(--bg2)', border: '1px solid var(--border)', lineHeight: 1.45 }}>
                <span style={{ fontWeight: 800, color: '#f59e0b' }}>What to do now: </span>{whatNow}
              </div>
            ) : null}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
            {rec && (
              <div style={{
                fontSize: 11, fontWeight: 800, padding: '6px 14px', borderRadius: 8,
                background: `${recColor}18`, color: recColor, border: `1px solid ${recColor}55`,
              }}>{rec}</div>
            )}
            {thesisStatus && (
              <div style={{
                fontSize: 9, fontWeight: 700, padding: '4px 10px', borderRadius: 6,
                background: `${thesisColor}18`, color: thesisColor, border: `1px solid ${thesisColor}44`,
              }}>Thesis: {thesisStatus}</div>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 14 }}>
          {price != null && price > 0 && (
            <KpiTile label="Price" value={`$${price.toFixed(2)}`} sub={dayPct != null ? `${dayPct >= 0 ? '+' : ''}${dayPct.toFixed(2)}% today` : undefined} color={dayPct != null ? (dayPct >= 0 ? '#22c55e' : '#ef4444') : undefined} />
          )}
          {kpis.portfolio_value != null && (
            <KpiTile label="Portfolio" value={`$${Number(kpis.portfolio_value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`} sub={kpis.day_change_pct != null ? `${Number(kpis.day_change_pct).toFixed(2)}% today` : undefined} />
          )}
          {(kpis.instrument_count != null || meta.instrument_count != null) && (
            <KpiTile label="Instruments" value={String(kpis.instrument_count ?? meta.instrument_count)} />
          )}
          {kpis.sector_count != null && (
            <KpiTile label="Sectors" value={String(kpis.sector_count)} />
          )}
          {kpis.health_score != null && (
            <KpiTile label="Health" value={String(kpis.health_score)} sub={kpis.health_status} color={Number(kpis.health_score) >= 75 ? '#22c55e' : Number(kpis.health_score) >= 50 ? '#f59e0b' : '#ef4444'} />
          )}
          {conf != null && (
            <KpiTile label="Confidence" value={`${conf.toFixed(0)}%`} sub={kpis.confidence_label} color={conf >= 70 ? '#22c55e' : conf >= 45 ? '#f59e0b' : '#ef4444'} />
          )}
          {entryPrice != null && entryPrice > 0 && (
            <KpiTile label="Entry" value={`$${entryPrice.toFixed(2)}`} sub="cost basis avg" />
          )}
          {unrealPct != null && (
            <KpiTile
              label="Unrealized P&L"
              value={`${unrealPct >= 0 ? '+' : ''}${unrealPct.toFixed(2)}%`}
              sub={unrealPnl != null ? `$${unrealPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : undefined}
              color={unrealPct >= 0 ? '#22c55e' : '#ef4444'}
            />
          )}
          {kpis.portfolio_pct != null && (
            <KpiTile label="Allocation" value={`${Number(kpis.portfolio_pct).toFixed(2)}%`} sub="of portfolio" />
          )}
          {meta.event_count != null && (
            <KpiTile label="Events" value={String(meta.event_count)} sub={`${meta.hours || 24}h window`} color="#f59e0b" />
          )}
          {kpis.action_items != null && (
            <KpiTile label="Actions" value={String(kpis.action_items)} sub="click queue below" color="#f59e0b" />
          )}
        </div>
      </div>

      {/* v2 — personal context header */}
      {headerSec?.metrics && !isDigest && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>{headerSec.title || 'Identification & Personal Context'}</div>
          {headerSec.content && <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 10, lineHeight: 1.5 }}>{headerSec.content}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
            {Object.entries(headerSec.metrics).filter(([k, v]) => v != null && !['text', 'date_generated'].includes(k)).map(([k, v]) => (
              <div key={k} style={{ background: 'var(--bg2)', borderRadius: 6, padding: '8px 10px', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 8, fontWeight: 700, color: 'var(--text4)', textTransform: 'uppercase' }}>{k.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginTop: 2 }}>{formatMetric(k, v)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* v2 — action plan (pinned above sections) */}
      {actionPlanSec && !isDigest && (
        <div style={{ ...card, borderColor: `${recColor}66`, background: `linear-gradient(135deg, var(--bg1) 0%, ${recColor}10 100%)` }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
            {actionPlanSec.title || 'Recommendation & Action Plan'}
          </div>
          {actionPlanSec.content && (
            <div style={{ fontSize: 12, color: 'var(--text1)', marginBottom: 10, lineHeight: 1.5 }}>{actionPlanSec.content}</div>
          )}
          {(actionPlanSec.bullets || []).map((b: string, i: number) => (
            <div key={i} style={{
              fontSize: 11, fontWeight: 600, color: 'var(--text0)', padding: '8px 12px', marginBottom: 6,
              borderLeft: `4px solid ${recColor}`, background: 'var(--bg2)', borderRadius: '0 8px 8px 0',
            }}>{b}</div>
          ))}
        </div>
      )}

      {/* Action queue — digest + aggregate reports */}
      {actions.length > 0 && (
        <div style={{ ...card, borderColor: '#f59e0b55' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>
              Action Queue <span style={{ color: '#f59e0b' }}>({actions.length})</span>
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>Click any item to open address modal</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {actions.slice(0, 12).map((a, i) => {
              const c = a.severity === 'urgent' || a.severity === 'critical' ? '#ef4444' : a.severity === 'warning' ? '#f59e0b' : '#60a5fa'
              return (
                <button
                  key={a.id || i}
                  onClick={() => setModalAction(a)}
                  style={{
                    textAlign: 'left', cursor: 'pointer', padding: '10px 12px', borderRadius: 8,
                    border: '1px solid var(--border)', borderLeft: `4px solid ${c}`,
                    background: 'var(--bg2)', color: 'var(--text1)', fontSize: 11,
                  }}
                >
                  <div style={{ fontWeight: 600, lineHeight: 1.45 }}>{a.text}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
                    {a.symbol && <span style={{ fontFamily: 'monospace', color: '#60a5fa', marginRight: 8 }}>{a.symbol}</span>}
                    Tap to address →
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Sector overview — all-sectors report */}
      {sectors.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>
            Sector Matrix ({sectors.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 280, overflowY: 'auto' }}>
            {sectors.map((sec: any) => (
              <button
                key={sec.sector}
                onClick={() => setModalAction(toDeckAction({
                  text: `Review ${sec.sector} — ${Number(sec.weight_pct || 0).toFixed(1)}% portfolio weight`,
                  severity: Number(sec.weight_pct) > 15 ? 'warning' : 'info',
                  action_class: 'portfolio_review',
                  route: '/v3/sectors',
                  route_label: 'Sectors',
                }))}
                style={{
                  display: 'flex', gap: 10, alignItems: 'center', padding: '8px 10px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer', textAlign: 'left',
                }}
              >
                <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', flex: 1 }}>{sec.sector}</span>
                <span style={{ fontSize: 10, fontWeight: 700, color: Number(sec.weight_pct) > 15 ? '#f59e0b' : '#60a5fa' }}>
                  {Number(sec.weight_pct || 0).toFixed(1)}%
                </span>
                <span style={{ fontSize: 9, color: 'var(--text3)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(sec.symbols || []).slice(0, 4).join(', ')}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Aggregate instrument table */}
      {items.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>
            Instrument Matrix ({items.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 320, overflowY: 'auto' }}>
            {items.slice(0, 50).map((it: any) => (
              <button
                key={it.symbol}
                onClick={() => setModalAction(toDeckAction(it))}
                style={{
                  display: 'flex', gap: 10, alignItems: 'center', padding: '8px 10px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer', textAlign: 'left',
                }}
              >
                <span style={{ fontFamily: 'monospace', fontWeight: 800, color: '#60a5fa', width: 52 }}>{it.symbol}</span>
                <span style={{ fontSize: 10, fontWeight: 700, color: REC_COLORS[String(it.recommendation || '').toUpperCase()] || 'var(--text2)', width: 48 }}>{it.recommendation}</span>
                <span style={{ fontSize: 10, color: 'var(--text1)', flex: 1 }}>
                  ${Number(it.price || 0).toFixed(2)}
                  {it.day_change_pct != null && (
                    <span style={{ color: Number(it.day_change_pct) >= 0 ? '#22c55e' : '#ef4444', marginLeft: 6 }}>
                      {Number(it.day_change_pct) >= 0 ? '+' : ''}{Number(it.day_change_pct).toFixed(2)}%
                    </span>
                  )}
                  {it.portfolio_pct != null && <span style={{ color: 'var(--text3)', marginLeft: 6 }}>{Number(it.portfolio_pct).toFixed(2)}% port</span>}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Charts */}
      {chartVisuals.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 12 }}>Visual Analysis</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
            {chartVisuals.map((vis: any, i: number) => (
              <div key={`${vis.type}-${i}`} style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', marginBottom: 6, textTransform: 'uppercase' }}>
                  {String(vis.type || 'chart').replace(/_/g, ' ')}
                  {vis.symbol && <> · <span style={{ color: '#60a5fa' }}>{vis.symbol}</span></>}
                </div>
                {vis.type === 'health_gauge' && vis.score != null ? (
                  <div style={{ textAlign: 'center', padding: '12px 0' }}>
                    <div style={{ fontSize: 32, fontWeight: 900, color: Number(vis.score) >= 75 ? '#22c55e' : Number(vis.score) >= 50 ? '#f59e0b' : '#ef4444' }}>
                      {Number(vis.score).toFixed(0)}
                    </div>
                  </div>
                ) : (
                  <img src={chartSrc(vis.chart_path)!} alt={vis.type} style={{ width: '100%', borderRadius: 6, display: 'block' }} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {(thesisVis && thesisVis.entry && thesisVis.stop) && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>Thesis Validity Range</div>
          {thesisVis.chart_path && chartSrc(thesisVis.chart_path) ? (
            <img src={chartSrc(thesisVis.chart_path)!} alt="Thesis validity" style={{ width: '100%', borderRadius: 8, marginBottom: 10 }} />
          ) : null}
          <ThesisValidityBar tv={{
            ok: true, entry: Number(thesisVis.entry) || 0, stop: Number(thesisVis.stop) || 0,
            target: Number(thesisVis.target1) || 0, current_price: Number(thesisVis.price) || null,
            zone_status: String(thesisVis.zone_status || ''),
          } as ThesisValidity} />
        </div>
      )}

      {(priceVis || riskVis) && !isAllScope && (
        <div style={{ ...card, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {priceVis && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 8 }}>TECHNICAL SNAPSHOT</div>
              {priceVis.rsi != null && <GaugeBar value={Number(priceVis.rsi)} max={100} label="RSI" color="#60a5fa" />}
            </div>
          )}
          {riskVis && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 8 }}>RISK PROFILE</div>
              {[
                ['Beta (vs S&P 500)', riskVis.beta != null ? Number(riskVis.beta).toFixed(2) : '—'],
                ['Portfolio weight', riskVis.portfolio_pct != null ? `${Number(riskVis.portfolio_pct).toFixed(2)}%` : '—'],
              ].map(([k, v]) => (
                <div key={String(k)} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '4px 0' }}>
                  <span style={{ color: 'var(--text3)' }}>{k}</span>
                  <span style={{ fontWeight: 600 }}>{String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {ensembleResult && (
        <div style={card}>
          <EnsembleValidationCard result={ensembleResult} />
        </div>
      )}

      {/* Text sections — collapsed for digest types */}
      {visibleSections.map((sec: any) => {
        const bullets = sec.bullets || []
        const isLong = isDigest && bullets.length > 4
        const expanded = expandedSections[sec.id] || !isLong
        const showBullets = expanded ? bullets : bullets.slice(0, 3)

        return (
          <div key={sec.id || sec.title} style={card}>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 8, borderLeft: '3px solid #60a5fa', paddingLeft: 10 }}>
              {sec.title}
              {isLong && !expanded && <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 8 }}>+{bullets.length - 3} more</span>}
            </div>
            {sec.content && (
              <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.55, marginBottom: 8 }}>{sec.content}</div>
            )}
            {(sec.callouts || []).map((co: any, ci: number) => (
              <CalloutBox key={ci} label={co.label || 'Action'} text={co.text || ''} />
            ))}
            {sec.metrics && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                {Object.entries(sec.metrics).filter(([k, v]) => v != null && k !== 'text').map(([k, v]) => (
                  <span key={k} style={{ fontSize: 9, padding: '4px 10px', borderRadius: 6, background: 'var(--bg2)', border: '1px solid var(--border)' }}>
                    {k.replace(/_/g, ' ')}: <b>{formatMetric(k, v)}</b>
                  </span>
                ))}
              </div>
            )}
            {showBullets.map((b: string, i: number) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text2)', padding: '6px 10px', marginBottom: 4, borderLeft: '2px solid var(--border)', background: 'var(--bg2)', borderRadius: '0 6px 6px 0' }}>{b}</div>
            ))}
            {(sec.agents || []).length > 0 && (
              <div style={{ marginTop: 10, overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg2)', textAlign: 'left' }}>
                      {['Agent', 'Rec', 'Weight'].map(h => (
                        <th key={h} style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text3)', fontWeight: 700 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sec.agents.map((ag: any, i: number) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '6px 8px', fontWeight: 700, color: '#60a5fa' }}>{ag.agent}</td>
                        <td style={{ padding: '6px 8px', fontWeight: 700 }}>{ag.recommendation}</td>
                        <td style={{ padding: '6px 8px', color: relevanceColor(ag.weight || ag.relevance), fontWeight: 600 }}>
                          {ag.weight || ag.relevance}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {isLong && (
              <button
                onClick={() => setExpandedSections(s => ({ ...s, [sec.id]: !expanded }))}
                style={{ fontSize: 10, color: '#60a5fa', background: 'none', border: 'none', cursor: 'pointer', marginTop: 6 }}
              >
                {expanded ? 'Show less' : `Show all ${bullets.length} items`}
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}