import { useState } from 'react'
import '../pages/OpsEvidencePages.css'
import { BB, T, TYPE, numCell, statePill } from '../lib/watchTokens'
import { hubPanel } from '../lib/terminalHubChrome'
import { useApi } from '../hooks/useApi'

/**
 * Real paid AI + search spend (operator ask 2026-09-14): dollars and tokens by provider, model and
 * process (scheduled vs ad hoc), the peak / off-peak split, and what the cap ledger counted.
 * Source: GET /api/v2/consumption/spend?period=… (lib/llm_spend.build_report). Read-only.
 */

type Period = 'today' | 'yesterday' | 'week' | 'last_week' | 'month' | 'last_month'
const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'yesterday', label: 'Yesterday' },
  { key: 'week', label: '7 days' },
  { key: 'last_week', label: 'Last week' },
  { key: 'month', label: 'Month to date' },
  { key: 'last_month', label: 'Last month' },
]

function usd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const n = v
  if (!n) return '$0'
  return n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`
}

function tok(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const n = v
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function pct(part: number, whole: number): string {
  return whole ? `${Math.round((100 * part) / whole)}%` : '—'
}

const th = { padding: '6px 8px', textAlign: 'left' as const, color: BB.text3, fontSize: TYPE.xs, fontWeight: 700, textTransform: 'uppercase' as const, letterSpacing: '.04em' }
const td = { padding: '6px 8px', borderTop: `1px solid ${BB.border}`, color: BB.text1, fontSize: TYPE.sm }
const num = { ...td, ...numCell }

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div style={{ padding: 12, borderRadius: 8, background: BB.bgShift, border: `1px solid ${BB.border}`, minWidth: 0 }}>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: tone || BB.text0, fontVariantNumeric: 'tabular-nums', marginTop: 4 }}>{value}</div>
      {sub ? <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>{sub}</div> : null}
    </div>
  )
}

export default function SpendPanel() {
  const [period, setPeriod] = useState<Period>('week')
  const read = useApi<any>(`/api/v2/consumption/spend?period=${period}`, 90_000)
  const report = read.data?.report
  const loading = read.loading
  const error = read.error || (read.data?.ok === false ? read.data.error || 'spend report unavailable' : '')

  const t = report?.totals
  const cap = report?.global_cap_usd_per_day
  const offShare = t ? (t.usd ? t.usd_offpeak / t.usd : 1) : 1

  return (
    <div className="cc-panel ops-evidence-page" style={{ ...hubPanel(true), marginBottom: 16 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}>Spend — paid AI &amp; search</div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            {report?.label ?? '…'} · real = provider tokens × price schedule
          </div>
        </div>
        <div role="tablist" aria-label="Spend period" style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {PERIODS.map(p => (
            <button key={p.key} role="tab" aria-selected={period === p.key} onClick={() => setPeriod(p.key)}
              style={{
                fontSize: TYPE.xs, fontWeight: 700, padding: '4px 8px', borderRadius: 4, cursor: 'pointer',
                border: `1px solid ${period === p.key ? BB.amber : BB.border}`,
                background: period === p.key ? BB.amberDim : 'transparent',
                color: period === p.key ? BB.amber : BB.text2,
              }}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error || read.stale ? <div role="alert" style={{ ...statePill('red'), marginBottom: 8 }}>Spend {report ? 'out of date' : 'unavailable'}: {error || 'refresh pending'}. Retrying automatically.</div> : null}
      {loading && !report ? <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Loading spend…</div> : null}

      {t ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginBottom: 12 }}>
            <Kpi label="Real spend" value={usd(t.usd)} sub={`${usd(t.usd_per_day)} / day`} />
            <Kpi label="Counted by caps" value={usd(report.counted_by_caps_usd)} sub="reservation ledger" tone={BB.text2} />
            <Kpi label="Daily cap" value={cap != null ? usd(cap) : '—'} sub="global, per day" tone={BB.text2} />
            <Kpi label="Calls" value={Number(t.calls).toLocaleString()} sub={`${Number(t.paid_calls).toLocaleString()} paid · ${t.failures} failed`} />
            <Kpi label="Tokens" value={`${tok(t.tokens_in)} in`} sub={`${tok(t.tokens_out)} out`} />
            <Kpi label="Brave search" value={report.brave?.requests != null ? String(report.brave.requests) : '—'} sub="requests (paid plan)" />
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: TYPE.xs, color: BB.text3, marginBottom: 4 }}>
              <span>🌙 Off-peak {usd(t.usd_offpeak)} · {pct(t.usd_offpeak, t.usd)} · {Number(t.calls_offpeak).toLocaleString()} calls</span>
              <span>☀️ Peak {usd(t.usd_peak)} · {pct(t.usd_peak, t.usd)} · {Number(t.calls_peak).toLocaleString()} calls</span>
            </div>
            <div aria-label="Off-peak versus peak spend" style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', background: BB.bgPanel, border: `1px solid ${BB.border}` }}>
              <div style={{ width: `${Math.round(offShare * 100)}%`, background: BB.green }} />
              <div style={{ flex: 1, background: BB.amber }} />
            </div>
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>{report.definitions?.peak}</div>
          </div>

          {report.scheduled_on_peak?.length ? (
            <div style={{ padding: 10, borderRadius: 6, background: BB.amberDim, border: `1px solid ${BB.amber}`, marginBottom: 12, fontSize: TYPE.sm, color: BB.text1 }}>
              <b style={{ color: BB.amber }}>Scheduled work ran on peak.</b> Scheduled work should run off-peak:{' '}
              {report.scheduled_on_peak.slice(0, 5).map((x: any) => `${x.process_name} (${Number(x.calls_peak).toLocaleString()} calls, ${usd(x.usd_peak)})`).join(' · ')}
            </div>
          ) : null}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 12, marginBottom: 12 }}>
            <div style={{ overflowX: 'auto' }}>
              <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, marginBottom: 4 }}>By provider</div>
              <table className="ops-evidence-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th style={th}>Provider</th><th style={{ ...th, textAlign: 'right' }}>Spend</th><th style={{ ...th, textAlign: 'right' }}>Calls</th><th style={{ ...th, textAlign: 'right' }}>Tokens</th></tr></thead>
                <tbody>
                  {(report.by_provider || []).map((p: any) => (
                    <tr key={p.provider}>
                      <td data-label="Provider" style={td}>{p.provider}</td>
                      <td data-label="Spend" style={num}>{usd(p.usd)}</td>
                      <td data-label="Calls" style={num}>{Number(p.calls).toLocaleString()}</td>
                      <td data-label="Tokens" style={num}>{tok(Number(p.tokens_in) + Number(p.tokens_out))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, marginBottom: 4 }}>By model</div>
              <table className="ops-evidence-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th style={th}>Model</th><th style={th}>Lane</th><th style={{ ...th, textAlign: 'right' }}>Spend</th><th style={{ ...th, textAlign: 'right' }}>Calls</th><th style={{ ...th, textAlign: 'right' }}>In / out</th></tr></thead>
                <tbody>
                  {(report.by_model || []).map((m: any, i: number) => (
                    <tr key={`${m.model}-${m.lane}-${i}`}>
                      <td data-label="Model" style={td}>{m.model || '—'}</td>
                      <td data-label="Lane" style={{ ...td, color: BB.text3 }}>{m.lane || '—'}</td>
                      <td data-label="Spend" style={num}>{usd(m.usd)}</td>
                      <td data-label="Calls" style={num}>{Number(m.calls).toLocaleString()}</td>
                      <td data-label="In / out" style={num}>{tok(m.tokens_in)} / {tok(m.tokens_out)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, marginBottom: 4 }}>By process</div>
            <table className="ops-evidence-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Process</th><th style={th}>Kind</th>
                  <th style={{ ...th, textAlign: 'right' }}>Spend</th><th style={{ ...th, textAlign: 'right' }}>Calls</th>
                  <th style={{ ...th, textAlign: 'right' }}>Tokens in / out</th><th style={{ ...th, textAlign: 'right' }}>On peak</th>
                  <th style={th}>Models</th><th style={{ ...th, textAlign: 'right' }}>Process cap</th><th style={th}>Last call</th>
                </tr>
              </thead>
              <tbody>
                {(report.by_process || []).map((p: any) => (
                  <tr key={`${p.process_id}-${p.kind}`}>
                    <td data-label="Process" style={td} title={p.process_id}>{p.process_name}</td>
                    <td data-label="Kind" style={td}><span style={statePill(p.kind === 'scheduled' ? 'green' : 'slate')}>{p.kind === 'scheduled' ? 'Scheduled' : 'Ad hoc'}</span></td>
                    <td data-label="Spend" style={num}>{usd(p.usd)}</td>
                    <td data-label="Calls" style={num}>{Number(p.calls).toLocaleString()}{p.failures ? <span style={{ color: BB.red }}> · {p.failures} failed</span> : null}</td>
                    <td data-label="Tokens in / out" style={num}>{tok(p.tokens_in)} / {tok(p.tokens_out)}</td>
                    <td data-label="On peak" style={{ ...num, color: p.kind === 'scheduled' && p.calls_peak ? BB.amber : BB.text2 }}>
                      {p.calls_peak ? `${Number(p.calls_peak).toLocaleString()} · ${usd(p.usd_peak)}` : '—'}
                    </td>
                    <td data-label="Models" style={{ ...td, color: BB.text3 }}>{p.models || '—'}</td>
                    <td data-label="Process cap" style={num}>{p.daily_cost_cap_usd != null ? `${usd(p.daily_cost_cap_usd)}/day` : '—'}</td>
                    <td data-label="Last call" style={{ ...td, color: BB.text3, whiteSpace: 'nowrap' }}>{p.last_call || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>
            {report.definitions?.scheduled} · {report.definitions?.real_vs_counted} ·{' '}
            <span style={{ color: T.link }}>{report.brave?.note}</span>
          </div>
        </>
      ) : null}
    </div>
  )
}
