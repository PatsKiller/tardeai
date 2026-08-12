import { Fragment, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

interface Props { onDrill?: (ctx: any) => void }

type Banner = { id: string; severity: string; title: string; detail: string }
type DeskRow = {
  symbol: string
  account?: string
  row_class: string
  verdict: string
  confidence?: number
  market_value?: number
  weight_pct?: number
  gain_loss_pct?: number
  rationale?: string
  rationale_signals?: string[]
  advisory_row_hash?: string
  row_id?: string
  data_quality?: {
    evidence_count?: number
    gap_count?: number
    lot_data_status?: string
    sufficient?: boolean
    evidence_gaps?: string[]
  }
  expand?: {
    lots?: any
    price_action?: any
    analyst?: any
    memory?: any
    evidence_items?: any[]
    opinion?: any
    instrument?: any
  }
}

const VERDICT_COLOR: Record<string, string> = {
  TRIM: 'var(--amber)', EXIT: 'var(--red)', ADD: 'var(--green)',
  HOLD: 'var(--text2)', RE_ENTER: 'var(--accent)', WAIT: 'var(--text3)',
  AVOID: 'var(--orange)', INSUFFICIENT_DATA: 'var(--text3)',
}

const VERDICT_HELP: Record<string, string> = {
  ADD: 'Add / increase — evidence supports a new or larger position.',
  HOLD: 'Hold — within normal parameters; no signal to act.',
  TRIM: 'Trim — reduce size (concentration, gain, or loss trigger).',
  EXIT: 'Exit — close the position.',
  RE_ENTER: 'Re-enter — watch for a recovery/confirmation entry.',
  WAIT: 'Wait — hold off until a trigger clears.',
  AVOID: 'Avoid — do not initiate; negative signal present.',
  INSUFFICIENT_DATA: 'Not enough evidence to act — verdict suppressed.',
}

const SEV_BG: Record<string, string> = {
  critical: 'var(--red-ghost)',
  warn: 'var(--amber-ghost)',
  info: 'var(--bg2)',
}
const SEV_FG: Record<string, string> = {
  critical: 'var(--red)',
  warn: 'var(--amber)',
  info: 'var(--text2)',
}

const BANNER_ACTION: Record<string, string> = {
  OK: 'No action needed.',
  VALIDATION_FAIL: 'Fix validation_errors before relying on verdicts.',
  PLAUSIBILITY_OK: 'Verdict distribution and weight sum are within bounds.',
  PLAUSIBILITY_FAIL: 'Verdict distribution out of bounds — review before acting.',
  LOTS_OK: 'Lot data trusted; cost basis is reliable.',
  UNTRUSTED_LOTS: 'Review affected rows — lot-derived signals are suppressed.',
  LLM_ON: 'Flash/Pro opinions active in this snapshot.',
  LLM_DRY: 'Run enrichment to generate Flash/Pro opinions.',
  LLM_OFF: 'Enable ADVISORY_DESK_V1 to run Flash/Pro enrichment.',
  INVARIANTS_OK: 'No external reality failures.',
  INVARIANT_VIOLATIONS: 'Rows forced to INSUFFICIENT_DATA — resolve data gaps.',
}

// Sub-materiality close-out remnants ($500 floor) clutter the table; hide by default.
const MATERIALITY_FLOOR = 500

function fmtUSD(n: number | null | undefined) {
  if (n == null) return '—'
  const abs = Math.abs(n)
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${Number(n).toFixed(1)}%`
}

const CLASSES = ['all', 'holding', 'watchlist', 'allocation', 'closed_journal'] as const

// ── Typed expand-card renderers (replace the raw JSON dump) ──────────────────

function Field({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '2px 0', fontSize: 11.5 }}>
      <span style={{ color: 'var(--text3)' }}>{label}</span>
      <span style={{ color: tone || 'var(--text)', fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' }}>{value}</span>
    </div>
  )
}

function cardWrap(title: string, children: ReactNode) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10, background: 'var(--bg)' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', marginBottom: 6, letterSpacing: 0.3, textTransform: 'uppercase' }}>{title}</div>
      {children}
    </div>
  )
}

function LotsCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No lot data.</span>
  const lots = Array.isArray(d.lots) ? d.lots : []
  return (
    <div>
      <Field label="Lot data" value={String(d.lot_data_status || '—')} />
      <Field label="Shares" value={d.total_shares != null ? Number(d.total_shares).toLocaleString() : '—'} />
      <Field label="Weighted avg basis" value={d.weighted_avg_basis != null ? fmtUSD(d.weighted_avg_basis) : '—'} />
      <Field label="Holding period" value={String(d.holding_period || '—')} />
      <Field label="Lots" value={`${d.lot_count ?? lots.length} open · ${d.lots_in_profit ?? 0} in profit · ${d.lots_underwater ?? 0} underwater`} />
      {lots.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 6, fontSize: 10.5 }}>
          <thead>
            <tr>
              {['Lot date', 'Shares', 'Cost/sh', 'Open'].map(h => (
                <th key={h} style={miniTh}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lots.slice(0, 8).map((l: any, i: number) => (
              <tr key={i}>
                <td style={miniTd}>{String(l.lot_date || l.acquired_date || '—').slice(0, 10)}</td>
                <td style={{ ...miniTd, textAlign: 'right' }}>{l.shares_remaining != null ? Number(l.shares_remaining).toLocaleString() : '—'}</td>
                <td style={{ ...miniTd, textAlign: 'right' }}>{l.cost_per_share != null ? fmtUSD(l.cost_per_share) : '—'}</td>
                <td style={{ ...miniTd, textAlign: 'right' }}>{l.closed ? 'no' : 'yes'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function PriceActionCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No price-action data.</span>
  const dir = d.trend_direction
  return (
    <div>
      <Field label="1d / 5d / 20d" value={`${fmtPct(d.price_change_pct_1d)} / ${fmtPct(d.price_change_pct_5d)} / ${fmtPct(d.price_change_pct_20d)}`} />
      <Field label="Off 52w high" value={fmtPct(d.pct_off_52w_high)} />
      <Field label="Off 52w low" value={fmtPct(d.pct_off_52w_low)} />
      <Field label="From cost basis" value={fmtPct(d.distance_from_cost_basis_pct)} />
      <Field label="Trend" value={dir ? String(dir) : '—'} tone={dir === 'down' ? 'var(--red)' : dir === 'up' ? 'var(--green)' : undefined} />
      <Field label="Volatility (1w)" value={fmtPct(d.volatility_w_pct)} />
    </div>
  )
}

function AnalystCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No analyst coverage.</span>
  return (
    <div>
      <Field label="Consensus" value={String(d.consensus_rating || d.recommendation_mean) || '—'} />
      <Field label="Target" value={d.price_target_mean != null ? fmtUSD(d.price_target_mean) : '—'} />
      <Field label="Target range" value={d.price_target_low != null && d.price_target_high != null ? `${fmtUSD(d.price_target_low)} – ${fmtUSD(d.price_target_high)}` : '—'} />
      <Field label="vs current" value={fmtPct(d.target_vs_current_pct)} />
      <Field label="Analysts" value={d.analyst_count ?? '—'} />
      <Field label="As of" value={String(d.as_of || '—').slice(0, 10)} />
    </div>
  )
}

function MemoryCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object' || Object.keys(d).length === 0) return <span style={emptyStyle}>No memory signals.</span>
  return (
    <div>
      {d.conviction != null && <Field label="Conviction (pre-thrash)" value={d.conviction_pre_thrash ?? d.conviction} />}
      {d.thrash_penalty != null && <Field label="Thrash penalty" value={Number(d.thrash_penalty).toFixed(2)} tone="var(--amber)" />}
      {d.prior_verdict && <Field label="Prior verdict" value={String(d.prior_verdict)} />}
      {d.feedback_count != null && <Field label="Feedback" value={String(d.feedback_count)} />}
    </div>
  )
}

function OpinionCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object' || Object.keys(d).length === 0) {
    return <span style={emptyStyle}>No LLM opinion on this row (ADVISORY_DESK_V1 off or not yet enriched).</span>
  }
  return (
    <div>
      <Field label="Verdict" value={String(d.verdict || '—')} tone="var(--accent)" />
      <Field label="Conviction" value={d.conviction != null ? String(d.conviction) : '—'} />
      {d.what_changed && <div style={{ fontSize: 11.5, color: 'var(--text)', marginTop: 6 }}>{String(d.what_changed)}</div>}
      {d.rationale && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4 }}>{String(d.rationale)}</div>}
      {d.key_risk && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, lineHeight: 1.4 }}>Risk: {String(d.key_risk)}</div>}
      {d.model && <Field label="Model" value={String(d.model)} />}
    </div>
  )
}

function InstrumentCard({ d }: { d: any }) {
  if (!d || typeof d !== 'object') return <span style={emptyStyle}>No instrument identity.</span>
  return (
    <div>
      <Field label="Name" value={String(d.name || '—')} />
      <Field label="Type" value={String(d.type || '—')} />
      <Field label="Sector" value={String(d.sector || '—')} />
      <Field label="Exchange" value={String(d.exchange || '—')} />
      {d.listing_date && <Field label="Listed" value={String(d.listing_date).slice(0, 10)} />}
      {d.market_cap != null && <Field label="Market cap" value={fmtUSD(d.market_cap)} />}
      {d.is_recent_ipo != null && <Field label="Recent IPO" value={d.is_recent_ipo ? 'yes' : 'no'} />}
    </div>
  )
}

function EvidenceCard({ items }: { items: any[] }) {
  if (!Array.isArray(items) || items.length === 0) return <span style={emptyStyle}>No evidence items.</span>
  return (
    <div>
      {items.slice(0, 12).map((it, i) => (
        <div key={i} style={{ padding: '2px 0', fontSize: 11, color: 'var(--text2)' }}>
          • <span style={{ color: 'var(--text3)' }}>{it?.type || 'evidence'}</span>
          {it?.source ? ` · ${String(it.source).slice(0, 40)}` : ''}
        </div>
      ))}
    </div>
  )
}

function ExpandCard({ title, data }: { title: string; data: any }) {
  const body = title === 'Lots' ? <LotsCard d={data} />
    : title === 'Price action' ? <PriceActionCard d={data} />
    : title === 'Analyst' ? <AnalystCard d={data} />
    : title === 'Memory' ? <MemoryCard d={data} />
    : title === 'Opinion' ? <OpinionCard d={data} />
    : title === 'Instrument' ? <InstrumentCard d={data} />
    : title === 'Evidence' ? <EvidenceCard items={data} />
    : null
  return cardWrap(title, body)
}

const emptyStyle: CSSProperties = { fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }
const miniTh: CSSProperties = { textAlign: 'left', padding: '3px 5px', fontSize: 10, color: 'var(--text3)', fontWeight: 600, borderBottom: '1px solid var(--border)' }
const miniTd: CSSProperties = { padding: '3px 5px', fontSize: 10.5, color: 'var(--text2)', borderBottom: '1px solid var(--border)' }

const COLUMN_HELP: Record<string, string> = {
  Symbol: 'Ticker (account shown beneath).',
  Class: 'holding · watchlist · allocation · closed_journal.',
  Verdict: 'The desk call: ADD, HOLD, TRIM, EXIT, RE_ENTER, WAIT, AVOID, or INSUFFICIENT_DATA.',
  Conf: 'Confidence 0–1 — thesis/evidence quality, not position size.',
  MV: 'Market value (current price × shares).',
  'Wt%': 'Position weight as % of total portfolio value.',
  'P&L%': 'Unrealized gain/loss % vs cost basis.',
  'Data quality': 'Evidence count · gaps · lot data status. Hover a gap to see detail.',
  Rationale: 'Why the desk reached this verdict (top signal shown; hover for all).',
}

export default function AdvisoryDeskHub({ onDrill }: Props) {
  const [cls, setCls] = useState<(typeof CLASSES)[number]>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [feedbackMsg, setFeedbackMsg] = useState<string>('')
  const [showRemnants, setShowRemnants] = useState(false)
  const path = cls === 'all' ? '/api/v3/advisory' : `/api/v3/advisory?class=${cls}`
  const { data, loading, error, refetch } = useApi<any>(path, 60_000)

  const rows: DeskRow[] = useMemo(() => data?.rows ?? [], [data?.rows])
  const banners: Banner[] = useMemo(() => data?.banners ?? [], [data?.banners])

  const visibleRows = useMemo(
    () => rows.filter(r => showRemnants || (r.market_value ?? 0) >= MATERIALITY_FLOOR),
    [rows, showRemnants],
  )
  const hiddenRemnants = rows.length - visibleRows.length

  async function postFeedback(kind: 'rate' | 'ack' | 'snooze', row: DeskRow, extra?: Record<string, string>) {
    try {
      const body: any = {
        symbol: row.symbol,
        row_id: row.row_id,
        ...extra,
      }
      if (row.account) body.symbol = `${row.symbol}:${row.account}`
      const res = await fetch(`/api/v3/advisory/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const j = await res.json()
      setFeedbackMsg(j.ok ? `✓ ${kind} ${row.symbol}` : `✗ ${j.error || 'failed'}`)
      refetch?.()
    } catch (e: any) {
      setFeedbackMsg(`✗ ${e?.message || e}`)
    }
  }

  if (loading) return <div style={{ padding: 32, color: 'var(--text2)' }}>Loading advisory desk…</div>
  if (error) return <div style={{ padding: 32, color: 'var(--red)' }}>Advisory data unavailable: {String(error)}</div>

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1280 }}>
      <div style={hubTitle()}>📋 Advisory Desk</div>
      <div style={hubSubtitle()}>
        READ_ONLY_ADVISORY · deterministic facts + Flash/Pro opinions · memory-aware
        {data?.as_of && (
          <span style={{ color: 'var(--text3)', marginLeft: 16 }}>
            As of: {new Date(data.as_of).toLocaleString()}
          </span>
        )}
      </div>

      {/* Banner states with a "what to do" line */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 8, margin: '12px 0 16px' }}>
        {banners.map((b) => (
          <div
            key={b.id}
            data-testid={`banner-${b.id}`}
            style={{
              background: SEV_BG[b.severity] || 'var(--bg2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: 11, color: SEV_FG[b.severity] || 'var(--text3)', fontWeight: 600 }}>
              {b.id}
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginTop: 2 }}>{b.title}</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>{b.detail}</div>
            {BANNER_ACTION[b.id] && (
              <div style={{ fontSize: 10.5, color: 'var(--accent)', marginTop: 4 }}>{BANNER_ACTION[b.id]}</div>
            )}
          </div>
        ))}
      </div>

      {/* Synthesis */}
      {data?.synthesis && (
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8,
          padding: 14, marginBottom: 16, fontSize: 13, lineHeight: 1.5, color: 'var(--text)',
        }}>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 6, fontWeight: 600 }}>DESK SYNTHESIS</div>
          {data.synthesis}
        </div>
      )}

      {/* Class filter + remnant toggle */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        {CLASSES.map((c) => (
          <button
            key={c}
            onClick={() => setCls(c)}
            style={{
              padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)',
              background: cls === c ? 'var(--accent)' : 'var(--bg2)',
              color: cls === c ? 'var(--text0)' : 'var(--text2)', cursor: 'pointer', fontSize: 12,
            }}
          >
            {c}{c !== 'all' && data?.by_class?.[c] != null ? ` (${data.by_class[c]})` : ''}
          </button>
        ))}
        <button
          onClick={() => setShowRemnants(v => !v)}
          title="Toggle sub-$500 close-out remnants"
          style={{
            padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)',
            background: showRemnants ? 'var(--bg2)' : 'var(--bg)', cursor: 'pointer', fontSize: 12,
            color: showRemnants ? 'var(--text2)' : 'var(--text)',
          }}
        >
          {showRemnants ? `Hide remnants` : `Show ${hiddenRemnants} remnants`}
        </button>
        <span style={{ fontSize: 12, color: 'var(--text3)', marginLeft: 8 }}>
          {data?.row_count ?? 0} rows · validation {data?.metadata?.validation_ok ? 'OK' : 'FAIL'}
        </span>
        {feedbackMsg && <span style={{ fontSize: 12, color: 'var(--green)', marginLeft: 8 }}>{feedbackMsg}</span>}
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg2)', textAlign: 'left' }}>
              {['Symbol', 'Class', 'Verdict', 'Conf', 'MV', 'Wt%', 'P&L%', 'Data quality', 'Rationale', ''].map((h) => (
                <th key={h} title={COLUMN_HELP[h]} style={{ padding: '8px 10px', color: 'var(--text3)', fontWeight: 600, borderBottom: '1px solid var(--border)', cursor: 'help' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((r) => {
              const key = `${r.symbol}:${r.account || ''}:${r.advisory_row_hash || ''}`
              const open = expanded === key
              const dq = r.data_quality || {}
              const signals = r.rationale_signals || []
              const headline = signals[0] || r.rationale || '—'
              return (
                <Fragment key={key}>
                  <tr
                    style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                    onClick={() => setExpanded(open ? null : key)}
                  >
                    <td style={{ padding: '8px 10px', fontWeight: 600 }}>{r.symbol}
                      {r.account ? <div style={{ fontSize: 10, color: 'var(--text3)' }}>{r.account}</div> : null}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text2)' }}>{r.row_class}</td>
                    <td style={{ padding: '8px 10px', fontWeight: 700, color: VERDICT_COLOR[r.verdict] || 'var(--text)' }}
                      title={VERDICT_HELP[r.verdict]}>{r.verdict}</td>
                    <td style={{ padding: '8px 10px' }} title="Confidence 0–1 (thesis/evidence quality)">{r.confidence != null ? Number(r.confidence).toFixed(2) : '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{fmtUSD(r.market_value)}</td>
                    <td style={{ padding: '8px 10px' }}>{r.weight_pct != null ? `${Number(r.weight_pct).toFixed(2)}%` : '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{fmtPct(r.gain_loss_pct)}</td>
                    <td style={{ padding: '8px 10px' }} data-testid="data-quality" title={(dq.evidence_gaps || []).join('\n') || 'No data gaps'}>
                      <span>
                        ev {dq.evidence_count ?? 0}
                        {dq.gap_count ? ` · gaps ${dq.gap_count}` : ''}
                        {dq.lot_data_status ? ` · ${dq.lot_data_status}` : ''}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text2)', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={signals.join('\n')}>
                      {headline}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text3)' }}>{open ? '▾' : '▸'}</td>
                  </tr>
                  {open && (
                    <tr style={{ background: 'var(--bg2)' }}>
                      <td colSpan={10} style={{ padding: 14 }}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 12 }}>
                          <ExpandCard title="Lots" data={r.expand?.lots} />
                          <ExpandCard title="Price action" data={r.expand?.price_action} />
                          <ExpandCard title="Analyst" data={r.expand?.analyst} />
                          <ExpandCard title="Memory" data={r.expand?.memory} />
                          <ExpandCard title="Opinion" data={r.expand?.opinion} />
                          <ExpandCard title="Instrument" data={r.expand?.instrument} />
                          <ExpandCard title="Evidence" data={r.expand?.evidence_items} />
                        </div>
                        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          <button type="button" style={btnStyle} onClick={(e) => { e.stopPropagation(); postFeedback('ack', r) }}>Ack</button>
                          <button type="button" style={btnStyle} onClick={(e) => { e.stopPropagation(); postFeedback('snooze', r) }}>Snooze</button>
                          <button type="button" style={btnStyle} onClick={(e) => {
                            e.stopPropagation()
                            postFeedback('rate', r, { rating: 'useful' })
                          }}>Useful</button>
                          <button type="button" style={btnStyle} onClick={(e) => {
                            e.stopPropagation()
                            postFeedback('rate', r, { rating: 'notuseful', reason_code: 'DISAGREE_THESIS', note: 'held through' })
                          }}>Not useful · DISAGREE_THESIS</button>
                          {onDrill && (
                            <button type="button" style={btnStyle} onClick={(e) => {
                              e.stopPropagation()
                              onDrill({ title: r.symbol, subtitle: r.verdict, endpoint: '/api/v3/advisory', rows: [r] })
                            }}>Drill</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {visibleRows.length === 0 && (
              <tr><td colSpan={10} style={{ padding: 16, color: 'var(--text3)', textAlign: 'center' }}>No rows in this class.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const btnStyle: CSSProperties = {
  padding: '5px 10px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg)',
  color: 'var(--text2)',
  cursor: 'pointer',
  fontSize: 12,
}
