import { useState, useEffect, type ReactNode, type CSSProperties } from 'react'
import { ResponsiveContainer, LineChart, Line, ReferenceLine } from 'recharts'

export interface DrillContext {
  title: string
  subtitle?: string
  endpoint: string
  rows: Record<string, any>[]
  // Optional navigation links (read-only — no mutation). Rendered as a button row.
  links?: { label: string; href: string; note?: string }[]
}

interface Props {
  ctx: DrillContext | null
  onClose: () => void
}

const GRADE_C: Record<string, string> = { A: '#22c55e', B: '#86efac', C: '#f59e0b', D: '#ef4444' }

// Pull a numeric series out of an arbitrary drilled row (equity curve, etc.)
function extractSeries(rows: Record<string, any>[]): number[] | null {
  for (const row of rows) {
    for (const v of Object.values(row)) {
      let arr: any = v
      if (typeof v === 'string' && v.trim().startsWith('[')) { try { arr = JSON.parse(v) } catch { continue } }
      if (Array.isArray(arr) && arr.length > 2) {
        const nums = arr.map((p: any) => typeof p === 'number' ? p : (p?.value ?? p?.cumulative_r ?? p?.cumulative ?? null)).filter((n: any) => typeof n === 'number')
        if (nums.length > 2) return nums
      }
    }
  }
  return null
}

// Build the backtest trade_key from a drilled trade row, if it looks like a closed trade.
function deriveTradeKey(rows: Record<string, any>[]): string | null {
  const r = rows[0]
  if (!r) return null
  const sym = r.symbol
  const acct = r.account || r.na
  const date = r.close_date || r.exitDate || r.trade_date || r.proposed_date
  if (!sym || !acct || !date) return null
  const d = String(date).slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return null
  return `${sym}:${acct}:${d}`
}

// ── Human-readable field rendering (humanize keys, parse JSON blobs, format values, color statuses) ──
const KEY_LABELS: Record<string, string> = {
  pnl: 'P&L', total_pnl: 'Total P&L', rsi: 'RSI', win_rate: 'Win Rate', avg_confidence: 'Avg Confidence',
  eval_overall_score: 'Overall Score', eval_verdict: 'Verdict', profit_factor: 'Profit Factor', r_multiple: 'R Multiple',
  proposed_entry: 'Entry', proposed_target1: 'Target', proposed_stop: 'Stop', strategy_id: 'Strategy',
  object_type: 'Type', object_id: 'ID', tradeai_original: 'TradeAI Original', hermes_audit: 'Hermes Audit',
  hermes_enhancement: 'Hermes Enhancement', hermes_agreement_status: 'Agreement', hermes_confidence: 'Hermes Confidence',
  recommended_operator_choice: 'Recommended Choice', operator_choice: 'Operator Choice', created_at: 'Created',
  no_overwrite: 'No Overwrite', advisory_only: 'Advisory Only', rows_written: 'Rows Written', last_active: 'Last Active',
  run_mode: 'Run Mode', effective_state: 'Effective State', approval_state: 'Approval State', allowed_reads: 'Allowed Reads',
  allowed_writes: 'Allowed Writes', handoff_targets: 'Handoff Targets', activation_phase: 'Activation Phase',
}
const ACRONYMS = /\b(Pnl|Rsi|Raci|Id|Url|Llm|Atr|Mfe|Mae|Vwap|Macd|Adx|Pf|Wr|Rr|Cio|Tca|Pct|Bb|Rvol)\b/gi
function humanizeKey(k: string): string {
  if (KEY_LABELS[k]) return KEY_LABELS[k]
  return k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    .replace(ACRONYMS, m => ({ pnl: 'P&L', rsi: 'RSI', raci: 'RACI', id: 'ID', url: 'URL', llm: 'LLM', atr: 'ATR', mfe: 'MFE', mae: 'MAE', vwap: 'VWAP', macd: 'MACD', adx: 'ADX', pf: 'PF', wr: 'WR', rr: 'R:R', cio: 'CIO', tca: 'TCA', pct: '%', bb: 'BB', rvol: 'RVOL' }[m.toLowerCase()] || m))
}
const SECTION_RE = /^[—\-]{1,2}\s*(.+?)\s*[—\-]{1,2}$/
function statusColor(s: string): string | null {
  const t = s.toLowerCase()
  if (/\b(agree|proposal[_ ]allowed|operational|completed|promoted|approved|win|good|pass|active|on)\b/.test(t)) return '#22c55e'
  if (/\b(disagree|disabled|error|rejected|failed|loss|blocked|critical|naked|off)\b/.test(t)) return '#ef4444'
  if (/\b(wait|caution|shadow|staged|pending|designed|warning|review|not approved|dry.?run|small|weak)\b/.test(t)) return '#f59e0b'
  return null
}
function fmtScalar(v: any): { text: string; color?: string } {
  if (v === null || v === undefined || v === '') return { text: '—', color: 'var(--text3)' }
  if (typeof v === 'boolean') return { text: v ? 'yes' : 'no', color: v ? '#22c55e' : 'var(--text3)' }
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T[\d:.]/.test(v)) {
    const d = new Date(v); if (!isNaN(d.getTime())) return { text: d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  }
  const s = String(v)
  return { text: s, color: statusColor(s) || undefined }
}
function parseMaybeJson(v: any): any {
  if (v && typeof v === 'object') return v
  if (typeof v === 'string') { const t = v.trim(); if ((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))) { try { return JSON.parse(t) } catch { /* not json */ } } }
  return null
}
function Field({ k, v }: { k: string; v: any }) {
  const sec = k.match(SECTION_RE)
  if (sec) return <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text2)', margin: '10px 0 4px', paddingBottom: 3, borderBottom: '1px solid var(--border)' }}>{sec[1]}</div>
  const obj = parseMaybeJson(v)
  if (obj && typeof obj === 'object') {
    const entries = Array.isArray(obj) ? obj.map((x, i) => [String(i + 1), x]) : Object.entries(obj)
    return (
      <div style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px', marginBottom: 3 }}>{humanizeKey(k)}</div>
        <div style={{ paddingLeft: 8, borderLeft: '2px solid var(--border)' }}>
          {entries.length === 0 && <div style={{ fontSize: 10, color: 'var(--text3)' }}>(none)</div>}
          {entries.map(([kk, vv]: any) => {
            const inner = parseMaybeJson(vv)
            if (Array.isArray(inner)) return <div key={kk} style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0' }}><span style={{ fontSize: 9, color: 'var(--text3)' }}>{humanizeKey(String(kk))}</span><span style={{ fontSize: 10, color: 'var(--text1)', textAlign: 'right', maxWidth: 230 }}>{inner.length ? inner.map((x: any) => typeof x === 'object' ? JSON.stringify(x) : String(x)).join(', ') : '—'}</span></div>
            const f = fmtScalar(typeof vv === 'object' ? JSON.stringify(vv) : vv)
            return <div key={kk} style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0', gap: 10 }}><span style={{ fontSize: 9, color: 'var(--text3)' }}>{humanizeKey(String(kk))}</span><span style={{ fontSize: 10, color: f.color || 'var(--text1)', textAlign: 'right', maxWidth: 230, wordBreak: 'break-word' }}>{f.text}</span></div>
          })}
        </div>
      </div>
    )
  }
  const f = fmtScalar(v)
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ color: 'var(--text3)', fontSize: 10 }}>{humanizeKey(k)}</span>
      <span style={{ color: f.color || 'var(--text0)', fontSize: 11, fontWeight: f.color ? 600 : 400, maxWidth: 250, textAlign: 'right', wordBreak: 'break-word' }}>{f.text}</span>
    </div>
  )
}

export default function DetailDrawer({ ctx, onClose }: Props) {
  const [bt, setBt] = useState<any>(null)
  const [btState, setBtState] = useState<'idle' | 'loading' | 'none'>('idle')

  useEffect(() => {
    setBt(null); setBtState('idle')
    if (!ctx) return
    // Skip if the row already IS backtest-grade data
    if (ctx.rows[0]?.entry_grade != null) return
    const key = deriveTradeKey(ctx.rows)
    if (!key) return
    setBtState('loading')
    let cancelled = false
    fetch(`/api/v2/journal/backtest/${encodeURIComponent(key).replace(/%3A/gi, '__').replace(/:/g, '__')}`)
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (!cancelled) { if (j?.ok && j.data) { setBt(j.data); setBtState('idle') } else setBtState('none') } })
      .catch(() => { if (!cancelled) setBtState('none') })
    return () => { cancelled = true }
  }, [ctx])

  if (!ctx) return null

  const series = extractSeries(ctx.rows)
  const grade = ctx.rows[0]?.entry_grade ?? bt?.entry_grade
  const exitGrade = ctx.rows[0]?.exit_grade ?? bt?.exit_grade
  // Holding rows carry data_available — render a technical-analysis panel for them.
  const h0 = ctx.rows[0]
  const isHolding = h0 != null && h0.data_available !== undefined
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }} onClick={onClose}>
      <div style={{
        width: 420, maxWidth: '90vw', height: '100vh', background: 'var(--bg1)',
        borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column',
        boxShadow: '-4px 0 20px rgba(0,0,0,.5)',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{ctx.title}</div>
            {ctx.subtitle && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{ctx.subtitle}</div>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 18, padding: '0 4px' }}>{'\u00d7'}</button>
        </div>
        {/* Provenance badge — read-only */}
        <div style={{ padding: '6px 16px', background: 'rgba(59,130,246,.04)', borderBottom: '1px solid var(--border)', fontSize: 9, color: 'var(--text3)', fontFamily: 'monospace' }}>
          Source: {ctx.endpoint}
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
          {/* Navigation links (read-only — go act elsewhere) */}
          {ctx.links && ctx.links.length > 0 && (
            <div style={{ marginBottom: 12, padding: '8px 10px', background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.25)', borderRadius: 6 }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>Where to act</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {ctx.links.map((l, i) => (
                  <a key={i} href={l.href} title={l.note} style={{ fontSize: 11, fontWeight: 600, color: '#60a5fa', textDecoration: 'none', padding: '4px 10px', borderRadius: 5, background: 'rgba(96,165,250,.12)', border: '1px solid rgba(96,165,250,.3)' }}>{l.label} →</a>
                ))}
              </div>
            </div>
          )}
          {/* Enrichment: sparkline */}
          {series && series.length > 2 && (
            <div style={{ marginBottom: 12, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>Series</div>
              <ResponsiveContainer width="100%" height={48}>
                <LineChart data={series.map((v, i) => ({ i, v }))}>
                  <ReferenceLine y={0} stroke="var(--border)" />
                  <Line type="monotone" dataKey="v" dot={false} stroke={series[series.length - 1] >= series[0] ? '#22c55e' : '#ef4444'} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          {/* Enrichment: entry/exit grade badges (own row or fetched backtest link) */}
          {(grade || exitGrade) && (
            <div style={{ marginBottom: 12, padding: '8px 10px', background: 'rgba(96,165,250,.05)', border: '1px solid rgba(96,165,250,.2)', borderRadius: 6 }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>How was our entry {bt && !ctx.rows[0]?.entry_grade && <span style={{ color: 'var(--text3)', textTransform: 'none' }}>· from backtest grading</span>}</div>
              <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                {grade && <Badge label="Entry" g={grade} />}
                {exitGrade && <Badge label="Exit" g={exitGrade} />}
                {(bt?.entry_rsi != null) && <Stat k="Entry RSI" v={Number(bt.entry_rsi).toFixed(0)} />}
                {(bt?.left_on_table_20d != null) && <Stat k="Left 20d" v={`$${Number(bt.left_on_table_20d).toLocaleString()}`} />}
                {(bt?.better_entry_existed != null) && <Stat k="Better entry?" v={bt.better_entry_existed ? `yes ($${Number(bt.best_entry_price).toFixed(2)})` : 'no'} />}
              </div>
            </div>
          )}
          {isHolding && <HoldingAnalysis h={h0} />}
          {btState === 'loading' && <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Looking up backtest entry grade…</div>}
          {ctx.rows.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 11 }}>No data rows</div>}
          {ctx.rows.map((row, i) => (
            <div key={i} style={{ marginBottom: 10, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }}>
              {Object.entries(row).map(([k, v]) => <Field key={k} k={k} v={v} />)}
            </div>
          ))}
        </div>
        {/* Read-only footer */}
        <div style={{ padding: '8px 16px', borderTop: '1px solid var(--border)', fontSize: 8, color: 'var(--text3)', textAlign: 'center' }}>
          Read-only drill view. No action controls. Level 7 prohibited.
        </div>
      </div>
    </div>
  )
}

export function DrawerStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: color || 'var(--text0)' }}>{value}</div>
    </div>
  )
}

function Badge({ label, g }: { label: string; g: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: GRADE_C[g] ?? 'var(--text2)', lineHeight: 1 }}>{g}</div>
      <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{label}</div>
    </div>
  )
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text0)' }}>{v}</div>
      <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k}</div>
    </div>
  )
}

// Technical-analysis panel for a portfolio holding: RSI zone, fib retracement ladder, ratings.
function HoldingAnalysis({ h }: { h: Record<string, any> }) {
  const refreshed = h.enrichment_as_of ? new Date(h.enrichment_as_of) : null
  const refreshTxt = refreshed && !isNaN(refreshed.getTime())
    ? refreshed.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'
  const card: CSSProperties = { marginBottom: 12, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }
  const head = (t: string) => <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px', marginBottom: 6, display: 'flex', justifyContent: 'space-between' }}><span>{t}</span><span style={{ textTransform: 'none' }}>data as of {refreshTxt}</span></div>

  if (!h.data_available) {
    return (
      <div style={card}>
        {head('Technical Analysis')}
        <div style={{ fontSize: 11, color: 'var(--text3)', lineHeight: 1.5 }}>{h.analysis_note || 'No market data available for this symbol.'}</div>
      </div>
    )
  }

  const rsi = h.rsi
  const zone = h.rsi_status as string | undefined
  const zoneColor = zone === 'oversold' ? '#22c55e' : zone === 'overbought' ? '#ef4444' : 'var(--text2)'
  const fib = h.fib
  const ratings: [string, any][] = [
    ['Signal', h.signal], ['Analyst', h.analyst_rating],
    ['Recom (1=buy)', h.recom_score], ['PI score', h.pi_score],
  ].filter(([, v]) => v != null && v !== '') as [string, any][]

  return (
    <div style={card}>
      {head('Technical Analysis')}
      {/* RSI + zone */}
      {rsi != null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: fib ? 10 : 4 }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: zoneColor }}>{Number(rsi).toFixed(0)}</div>
          <div>
            <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>RSI (14)</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: zoneColor, textTransform: 'capitalize' }}>
              {zone === 'oversold' ? 'Oversold — potential buy zone' : zone === 'overbought' ? 'Overbought — caution' : (zone || 'neutral')}
            </div>
          </div>
          {/* RSI track */}
          <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'linear-gradient(90deg,#22c55e33 0 30%,var(--bg1) 30% 70%,#ef444433 70% 100%)', position: 'relative' }}>
            <div style={{ position: 'absolute', left: `${Math.min(100, Math.max(0, Number(rsi)))}%`, top: -2, width: 2, height: 10, background: zoneColor }} />
          </div>
        </div>
      )}
      {/* Fib retracement ladder */}
      {fib && fib.levels && (
        <div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
            Fibonacci retracement · {fib.retracement_from_high_pct}% off 52w high · nearest <span style={{ color: 'var(--text1)', fontWeight: 700 }}>{fib.nearest_level}</span>
          </div>
          {Object.entries(fib.levels).map(([label, price]: any) => {
            const isNear = label === fib.nearest_level
            return (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 6px', borderRadius: 4, fontSize: 10, background: isNear ? 'rgba(96,165,250,.12)' : 'transparent', color: isNear ? '#60a5fa' : 'var(--text2)', fontWeight: isNear ? 700 : 400 }}>
                <span>{label}</span><span style={{ fontFamily: 'monospace' }}>${Number(price).toFixed(2)}</span>
              </div>
            )
          })}
        </div>
      )}
      {/* Ratings */}
      {ratings.length > 0 && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
          {ratings.map(([k, v]) => (
            <div key={k}><span style={{ fontSize: 9, color: 'var(--text3)' }}>{k}: </span><span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text1)' }}>{typeof v === 'number' ? Number(v).toFixed(typeof v === 'number' && v % 1 ? 2 : 0) : String(v)}</span></div>
          ))}
        </div>
      )}
    </div>
  )
}

export function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 6, paddingBottom: 4, borderBottom: '1px solid var(--border)' }}>{title}</div>
      {children}
    </div>
  )
}
