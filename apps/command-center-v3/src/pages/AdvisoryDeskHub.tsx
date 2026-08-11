import { Fragment, useMemo, useState, type CSSProperties } from 'react'
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

export default function AdvisoryDeskHub({ onDrill }: Props) {
  const [cls, setCls] = useState<(typeof CLASSES)[number]>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [feedbackMsg, setFeedbackMsg] = useState<string>('')
  const path = cls === 'all' ? '/api/v3/advisory' : `/api/v3/advisory?class=${cls}`
  const { data, loading, error, refetch } = useApi<any>(path, 60_000)

  const rows: DeskRow[] = useMemo(() => data?.rows ?? [], [data?.rows])
  const banners: Banner[] = useMemo(() => data?.banners ?? [], [data?.banners])

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

      {/* 5 banner states */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, margin: '12px 0 16px' }}>
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

      {/* Class filter */}
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
                <th key={h} style={{ padding: '8px 10px', color: 'var(--text3)', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const key = `${r.symbol}:${r.account || ''}:${r.advisory_row_hash || ''}`
              const open = expanded === key
              const dq = r.data_quality || {}
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
                    <td style={{ padding: '8px 10px', fontWeight: 700, color: VERDICT_COLOR[r.verdict] || 'var(--text)' }}>{r.verdict}</td>
                    <td style={{ padding: '8px 10px' }}>{r.confidence != null ? Number(r.confidence).toFixed(2) : '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{fmtUSD(r.market_value)}</td>
                    <td style={{ padding: '8px 10px' }}>{r.weight_pct != null ? `${Number(r.weight_pct).toFixed(2)}%` : '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{fmtPct(r.gain_loss_pct)}</td>
                    <td style={{ padding: '8px 10px' }} data-testid="data-quality">
                      <span title={(dq.evidence_gaps || []).join(', ')}>
                        ev {dq.evidence_count ?? 0}
                        {dq.gap_count ? ` · gaps ${dq.gap_count}` : ''}
                        {dq.lot_data_status ? ` · ${dq.lot_data_status}` : ''}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text2)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.rationale || '—'}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'var(--text3)' }}>{open ? '▾' : '▸'}</td>
                  </tr>
                  {open && (
                    <tr style={{ background: 'var(--bg2)' }}>
                      <td colSpan={10} style={{ padding: 14 }}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                          <ExpandCard title="Lots" data={r.expand?.lots} />
                          <ExpandCard title="Price action" data={r.expand?.price_action} />
                          <ExpandCard title="Analyst" data={r.expand?.analyst} />
                          <ExpandCard title="Memory" data={r.expand?.memory} />
                          <ExpandCard title="Opinion" data={r.expand?.opinion} />
                          <ExpandCard title="Instrument" data={r.expand?.instrument} />
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
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ExpandCard({ title, data }: { title: string; data: any }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10, background: 'var(--bg)' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text3)', marginBottom: 6 }}>{title}</div>
      <pre style={{ margin: 0, fontSize: 11, color: 'var(--text2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 180, overflow: 'auto' }}>
        {data && Object.keys(data).length ? JSON.stringify(data, null, 2) : '—'}
      </pre>
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
