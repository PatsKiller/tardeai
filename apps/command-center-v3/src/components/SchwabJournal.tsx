import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { laneLabel } from '../lib/laneLabels'
import TradeReplayChart from './TradeReplayChart'
import { buildReplayTrade } from '../lib/replayTrade'

// Real-account (Schwab) round-trips — API-authoritative ledger, 5-min fill aggregation, FIFO pairing,
// LLM strategy/grade/lesson. Separate from paper trades (the live-trading gate stays paper-only).
const GRADE: Record<string, string> = { A: '#22c55e', B: '#84cc16', C: '#f59e0b', D: '#f97316', F: '#ef4444' }

// Explain entry/exit letter grades (A best → F worst, backtest-replay grading) from execution-quality signals.
function gradeExplain(t: any, eq: any): string {
  const lines = ['Letter grades A (best) → F (worst), from backtest-replay grading.', '']
  const ew: string[] = []
  if (eq) {
    if (eq.entry_timing_grade) ew.push(`${eq.entry_timing_grade} timing`)
    if (eq.entry_volume_ratio != null) ew.push(`RVOL ${eq.entry_volume_ratio}${eq.entry_volume_ratio < 1 ? ' (below avg)' : ''}`)
    if (eq.entry_above_vwap === false) ew.push('below VWAP'); else if (eq.entry_above_vwap === true) ew.push('above VWAP')
  }
  lines.push(`ENTRY grade ${t.entry_grade ?? '—'}${ew.length ? ' — ' + ew.join(', ') : ''}`)
  const xw: string[] = []
  if (eq) {
    if (eq.exit_timing_grade) xw.push(`${eq.exit_timing_grade} timing`)
    if (eq.capture_ratio != null) xw.push(`captured ${Math.round((eq.capture_ratio ?? 0) * 100)}% of the in-hold move`)
    if (eq.missed_opportunity_grade === 'severe') xw.push('severe missed runner')
  }
  lines.push(`EXIT grade ${t.exit_grade ?? '—'}${xw.length ? ' — ' + xw.join(', ') : ''}`)
  if (eq?.grok_what_to_do_next_time) lines.push('', `Coach: ${eq.grok_what_to_do_next_time}`)
  return lines.join('\n')
}

const EXEC: Record<string, string> = { good: '#22c55e', ok: '#84cc16', weak: '#f59e0b', poor: '#ef4444' }

export default function SchwabJournal() {
  const { data } = useApi<any>('/api/v2/journal/schwab-round-trips', 60_000)
  const { data: eqData } = useApi<any>('/api/v2/journal/execution-quality?source=schwab_round_trip&limit=300', 120_000)
  const d = data ?? {}
  const trips: any[] = d.round_trips ?? []
  const eqMap: Record<string, any> = {}
  const tk = (sym: string, t: any) => `${sym}|${String(t ?? '').slice(0, 19).replace('T', ' ')}`
  for (const e of (eqData?.trades ?? [])) eqMap[tk(e.symbol, e.entry_time)] = e
  const [acct, setAcct] = useState('all')
  const [cls, setCls] = useState('all')
  const [chartTrade, setChartTrade] = useState<any>(null)
  if (!trips.length) return <div style={{ padding: 20, color: 'var(--text3)', fontSize: 12 }}>No Schwab round-trips yet — the ledger ingest + journal builder populate this (read-only).</div>

  const accts = ['all', ...Array.from(new Set(trips.map(t => t.account)))]
  const view = trips.filter(t => !t.basis_status && (acct === 'all' || t.account === acct) && (cls === 'all' || t.classification === cls))

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {[['Round-trips', d.count], ['Win rate', (d.win_rate ?? 0) + '%'], ['Net P&L', fmt$(d.net_pnl ?? 0)]].map(([k, v]: any) => (
          <div key={k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 14px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: k === 'Net P&L' ? ((d.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444') : 'var(--text0)' }}>{v}</div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>active trading</div>
          </div>
        ))}
        {Object.entries(d.by_account ?? {}).map(([a, v]: any) => (
          <div key={a} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{a.replace('schwab_', '')}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: (v.net ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(v.net)} <span style={{ fontSize: 9, color: 'var(--text3)' }}>({v.count})</span></div>
          </div>
        ))}
      </div>
      {(d.long_term_trims?.count > 0 || d.basis_unknown?.count > 0) && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          {d.long_term_trims?.count > 0 && (
            <div style={{ background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.3)', borderRadius: 8, padding: '6px 12px', fontSize: 11 }}>
              <b style={{ color: '#22c55e' }}>Long-term trims: {fmt$(d.long_term_trims.realized)}</b> realized ({d.long_term_trims.count}) — pre-window lots at authoritative basis (e.g. V at ~$10.75 IPO). <span style={{ color: 'var(--text3)' }}>Not trading P&L.</span>
            </div>
          )}
          {d.basis_unknown?.count > 0 && (
            <div title={(d.basis_unknown.symbols || []).join(', ')} style={{ background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 8, padding: '6px 12px', fontSize: 11 }}>
              <b style={{ color: '#f59e0b' }}>basis_unknown: {d.basis_unknown.count}</b> sells — opening lot predates the data; <span style={{ color: 'var(--text3)' }}>flagged, excluded from P&L (never fabricated as losses).</span>
            </div>
          )}
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Active trading stats only · API-authoritative · 5-min fill aggregation · FIFO · long-term trims &amp; basis_unknown excluded · LLM grade/lesson. Read-only — separate from the paper-only live-trading gate.</div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {accts.map(a => <button key={a} onClick={() => setAcct(a)} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', background: acct === a ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: acct === a ? '#60a5fa' : 'var(--text2)' }}>{a.replace('schwab_', '') || a}</button>)}
        <span style={{ flex: 1 }} />
        {['all', 'day_trade', 'swing'].map(c => <button key={c} onClick={() => setCls(c)} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', background: cls === c ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: cls === c ? '#60a5fa' : 'var(--text2)' }}>{c}</button>)}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 600, overflowY: 'auto' }}>
        {view.map((t, i) => { const eq = eqMap[tk(t.symbol, t.entry_time)]; return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: 'var(--bg2)', borderRadius: 7, border: '1px solid var(--border)', fontSize: 11 }}>
            <span style={{ flex: '0 0 56px', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text0)' }}>{t.symbol}</span>
            <span style={{ flex: '0 0 64px', fontSize: 9, color: 'var(--text3)' }}>{t.account?.replace('schwab_', '')}</span>
            <span style={{ flex: '0 0 96px', fontSize: 9, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 3 }}>
              {t.strategy_tag || t.classification}
              {t.review_lane === 'grok' && <span title={`Reviewed by ${laneLabel(t.review_lane)} — tighter, trade-specific lesson`} style={{ fontSize: 7, fontWeight: 700, color: '#a855f7', border: '1px solid rgba(168,85,247,.5)', borderRadius: 3, padding: '0 2px', lineHeight: 1.4 }}>grok</span>}
              {t.review_lane === 'local' && <span title="Reviewed by local LLM" style={{ fontSize: 7, color: 'var(--text3)', border: '1px solid var(--border)', borderRadius: 3, padding: '0 2px', lineHeight: 1.4 }}>local</span>}
            </span>
            <span style={{ flex: '0 0 70px', fontSize: 9, color: 'var(--text3)' }}>{t.hold_minutes < 390 ? `${t.hold_minutes}m` : `${Math.round(t.hold_minutes / 1440)}d`}</span>
            {t.entry_grade && <span title={gradeExplain(t, eq)} style={{ flex: '0 0 80px', fontSize: 9, cursor: 'help' }}>E:<b style={{ color: GRADE[t.entry_grade] }}>{t.entry_grade}</b> X:<b style={{ color: GRADE[t.exit_grade] }}>{t.exit_grade}</b> ⓘ</span>}
            {eq ? (
              <span style={{ flex: '0 0 132px', fontSize: 8, display: 'flex', alignItems: 'center', gap: 3 }}
                title={`Outcome ${eq.outcome_grade} / Execution ${eq.execution_grade}\nentry ${eq.entry_timing_grade}, exit ${eq.exit_timing_grade}, capture ${Math.round((eq.capture_ratio ?? 0) * 100)}%${eq.runner_type === 'parabolic_pump' ? '\n⚡ post-exit move was a PARABOLIC PUMP — selling was correct, do not chase' : eq.runner_type === 'sustained_trend' || eq.runner_type === 'trend_top' ? '\n↗ post-exit move was a REAL runner — scale-out opportunity' : ''}\n${eq.grok_what_to_do_next_time || eq.computed_summary || ''}`}>
                <span style={{ fontWeight: 700, padding: '0 4px', borderRadius: 3, background: `${EXEC[eq.execution_grade] || 'var(--text3)'}22`, color: EXEC[eq.execution_grade] || 'var(--text3)' }}>{eq.execution_grade}</span>
                <span style={{ color: 'var(--text3)' }}>cap {Math.round((eq.capture_ratio ?? 0) * 100)}%</span>
                {eq.missed_opportunity_grade === 'severe' && <span title="severe missed runner" style={{ color: '#ef4444' }}>⚠</span>}
              </span>) : <span style={{ flex: '0 0 132px' }} />}
            <span style={{ flex: '0 0 80px', textAlign: 'right', fontWeight: 700, color: (t.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(t.net_pnl)}</span>
            <span style={{ flex: '1 1 auto', fontSize: 9, color: 'var(--text3)', fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title={eq?.grok_what_to_do_next_time ? `Execution coach: ${eq.grok_what_to_do_next_time}${t.lesson ? `\n\nEntry/exit lesson: ${t.lesson}` : ''}` : t.lesson}>
              {eq?.grok_what_to_do_next_time || t.lesson || ''}</span>
            <button title="Replay chart with entry/exit" onClick={() => setChartTrade(buildReplayTrade({ ...t, entry_time: t.entry_time, exit_time: t.exit_time, entry_price: t.entry_price, exit_price: t.exit_price, account: t.account, exec: eq }))}
              style={{ flex: '0 0 auto', fontSize: 11, padding: '1px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)', cursor: 'pointer' }}>📈</button>
          </div>
        ) })}
      </div>
      {chartTrade && <TradeReplayChart trade={chartTrade} onClose={() => setChartTrade(null)} />}
    </div>
  )
}
