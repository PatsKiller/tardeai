import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import FinvizSectorPanel from '../components/FinvizSectorPanel'
import type { DrillContext } from '../components/DetailDrawer'

// v3 Sector Monitor — standing view of each GICS sector: ETF, momentum vs SPY, setup counts,
// watch candidates. Advisory; "+ Watch this sector" stages constituents via the governed path.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const momColor = (m?: string) => (({ leading: '#22c55e', lagging: '#ef4444', neutral: '#94a3b8', unknown: 'var(--text3)' } as any)[m || ''] || 'var(--text3)')
const trendBadge = (t?: string) => (({ bullish: '#22c55e', bearish: '#ef4444', neutral: '#f59e0b', unknown: 'var(--text3)' } as any)[(t || '').toLowerCase()] || 'var(--text3)')
const Pill = ({ text, color, tip }: any) => (
  <span title={tip} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: color + '22', color, border: `1px solid ${color}55`, whiteSpace: 'nowrap' }}>{text}</span>
)

export default function SectorsHub({ onDrill, embedded }: Props) {
  const { data, refetch } = useApi<any>('/api/v2/sectors/monitor', 120_000)
  const { data: secExt } = useApi<any>('/api/v2/hermes/subject-intel-map?type=sector', 120_000)
  const secExtMap: Record<string, any[]> = secExt?.map ?? {}
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const sectors: any[] = data?.sectors ?? []
  const spy = data?.spy_change_pct

  const watchSector = async (sector: string) => {
    setBusy(sector); setMsg(null)
    try {
      const r = await fetch('/api/v2/watch/directives', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'sector', label: `sector ${sector}`, spec: { finviz_sector: sector }, rationale: 'watched from sector monitor' }),
      })
      const j = await r.json()
      setMsg(j.ok ? `✓ Now watching ${sector} (directive #${j.directive_id}) — constituents stage for one-tap` : `Error: ${j.error}`)
      refetch()
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(null)
  }

  return (
    <div>
      {!embedded && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Sector Monitor</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {sectors.length} GICS sectors · momentum vs SPY ({spy != null ? `${Number(spy) >= 0 ? '+' : ''}${Number(spy).toFixed(2)}%` : '—'} today) · advisory — adding a sector stages constituents (governor owns promotion)
          </div>
        </div>
      )}

      {msg && <div style={{ fontSize: 11, color: msg.startsWith('Error') ? '#ef4444' : '#22c55e', marginBottom: 12 }}>{msg}</div>}

      <FinvizSectorPanel />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 12 }}>
        {sectors.map((s: any) => {
          const isOpen = expanded === s.sector
          return (
            <div key={s.sector} style={{ ...card, padding: 14, borderLeft: `3px solid ${momColor(s.momentum)}`, opacity: String(s.momentum).startsWith('n/a') ? 0.7 : 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', display: 'flex', gap: 6, alignItems: 'center' }}>
                    {s.sector}
                    {s.is_watched && <Pill text="watching" color="#a855f7" tip={s.directive?.label} />}
                    {(secExtMap[`SECTOR:${s.sector}`] || []).map((e: any, i: number) => (
                      <span key={i} onClick={(ev) => { ev.stopPropagation(); onDrill({ title: `${s.sector} — LLM narrative`, subtitle: `${e.lane === 'grok' ? 'Grok' : 'ChatGPT'} · ${s.momentum}`, endpoint: 'derived', rows: [s], subjectType: 'sector', subjectKey: `SECTOR:${s.sector}` }) }}
                        title={`${e.lane === 'grok' ? 'Grok' : 'ChatGPT'}: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`}
                        style={{ fontSize: 9, fontWeight: 700, color: e.lane === 'grok' ? '#1d9bf0' : '#10a37f', cursor: 'pointer' }}>✦ {e.lane === 'grok' ? 'Grok' : 'ChatGPT'}</span>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 5, alignItems: 'center' }}>
                    <Pill text={s.etf} color="#60a5fa" tip="sector ETF" />
                    <Pill text={s.momentum} color={momColor(s.momentum)} tip={s.rel_strength != null ? `ETF vs SPY: ${s.rel_strength > 0 ? '+' : ''}${s.rel_strength}%` : 'no ETF data'} />
                    {s.etf_change_pct != null && <span style={{ fontSize: 10, color: Number(s.etf_change_pct) >= 0 ? '#22c55e' : '#ef4444' }}>{Number(s.etf_change_pct) >= 0 ? '+' : ''}{Number(s.etf_change_pct).toFixed(2)}%</span>}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: s.setup_count > 0 ? '#60a5fa' : 'var(--text3)' }}>{s.setup_count}</div>
                  <div title="setups = score-ranked candidates surviving CIO-verdict + coverage filters; denominator = tracked constituents for this sector" style={{ fontSize: 8, color: 'var(--text3)' }}>setups / {s.constituent_count} tracked</div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                {s.setup_count > 0 && (
                  <button onClick={() => setExpanded(isOpen ? null : s.sector)} style={{ fontSize: 10, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>
                    {isOpen ? 'Hide' : `Candidates (${s.setup_count})`}
                  </button>
                )}
                {!s.is_watched && (
                  <button disabled={busy === s.sector} onClick={() => watchSector(s.sector)} style={{ fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 5, border: 'none', background: '#a855f7', color: '#fff', cursor: busy === s.sector ? 'wait' : 'pointer' }}>+ Watch this sector</button>
                )}
              </div>

              {isOpen && (
                <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(s.candidates || []).map((c: any) => (
                    <div key={c.symbol} onClick={() => onDrill({ title: c.symbol, subtitle: `${s.sector} candidate`, endpoint: `/api/v2/watch/provenance/${c.symbol}`, rows: [c] })}
                      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: 'var(--bg2)', borderRadius: 6, cursor: 'pointer' }}>
                      <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text0)', fontSize: 11 }}>{c.symbol}</span>
                      <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                        {c.rsi != null && <Pill text={`RSI ${Number(c.rsi).toFixed(0)}`} color={Number(c.rsi) >= 70 ? '#ef4444' : Number(c.rsi) < 40 ? '#22c55e' : '#60a5fa'} />}
                        {c.trend && <Pill text={c.trend} color={trendBadge(c.trend)} />}
                        {c.score != null && <Pill text={`${Number(c.score).toFixed(0)}`} color={c.watch_score_kind === 'strategy_qualified' ? '#22c55e' : 'var(--text3)'} tip={c.watch_score_kind} />}
                      </span>
                    </div>
                  ))}
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>Candidates from the enriched watchlist within this sector. Click for provenance. Adding the sector stages these for one-tap promote.</div>
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 12 }}>{data?.legend || 'Source: /api/v2/sectors/monitor.'} Advisory — momentum is informational; promotion stays governed.</div>
    </div>
  )
}
