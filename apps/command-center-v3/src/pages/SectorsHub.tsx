import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import FinvizSectorPanel from '../components/FinvizSectorPanel'
import type { DrillContext } from '../components/DetailDrawer'
import { BB, T, TYPE, RAIL, numStyle, terminalButton } from '../lib/watchTokens'
import { Chip } from '../components/TerminalChip'

// v3 Sector Monitor — standing view of each GICS sector: ETF, momentum vs SPY, setup counts,
// watch candidates. Advisory; "+ Watch this sector" stages constituents via the governed path.
// v4 (WS-A): swept onto watchTokens — zero raw hexes, type floor 10, rails per momentum.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const card: React.CSSProperties = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14 }
const momRail = (m?: string) => (({ leading: RAIL.favorable, lagging: RAIL.breach, neutral: RAIL.neutral } as any)[m || ''] || RAIL.neutral)
const momColor = (m?: string) => (({ leading: BB.green, lagging: BB.red, neutral: BB.text3 } as any)[m || ''] || BB.text3)
const trendTone = (t?: string): 'green' | 'red' | 'amber' | 'slate' =>
  (({ bullish: 'green', bearish: 'red', neutral: 'amber' } as any)[(t || '').toLowerCase()] || 'slate')

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
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: BB.text0 }}>Sector Monitor</div>
          <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>
            {sectors.length} GICS sectors · momentum vs SPY ({spy != null ? `${Number(spy) >= 0 ? '+' : ''}${Number(spy).toFixed(2)}%` : '—'} today) · advisory — adding a sector stages constituents (governor owns promotion)
          </div>
        </div>
      )}

      {msg && <div style={{ fontSize: TYPE.sm, color: msg.startsWith('Error') ? BB.red : BB.green, marginBottom: 12 }}>{msg}</div>}

      <FinvizSectorPanel />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 12 }}>
        {sectors.map((s: any) => {
          const isOpen = expanded === s.sector
          return (
            <div key={s.sector} style={{ ...card, borderLeft: `3px solid ${momRail(s.momentum)}`, opacity: String(s.momentum).startsWith('n/a') ? 0.7 : 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0, display: 'flex', gap: 6, alignItems: 'center' }}>
                    {s.sector}
                    {s.is_watched && <Chip kind="state" tone="amber" title={s.directive?.label}>WATCHING</Chip>}
                    {(secExtMap[`SECTOR:${s.sector}`] || []).map((e: any, i: number) => (
                      <span key={i} onClick={(ev) => { ev.stopPropagation(); onDrill({ title: `${s.sector} — LLM narrative`, subtitle: `${e.lane === 'grok' ? 'Grok' : 'ChatGPT'} · ${s.momentum}`, endpoint: 'derived', rows: [s], subjectType: 'sector', subjectKey: `SECTOR:${s.sector}` }) }}
                        title={`${e.lane === 'grok' ? 'Grok' : 'ChatGPT'}: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`}
                        style={{ fontSize: TYPE.xs, fontWeight: 700, color: e.lane === 'grok' ? T.extIntel.grok : T.extIntel.gpt, cursor: 'pointer' }}>✦ {e.lane === 'grok' ? 'Grok' : 'ChatGPT'}</span>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 5, alignItems: 'center' }}>
                    <Chip kind="metric" title="sector ETF">{s.etf}</Chip>
                    <Chip kind="metric" title={s.rel_strength != null ? `ETF vs SPY: ${s.rel_strength > 0 ? '+' : ''}${s.rel_strength}%` : 'no ETF data'}>
                      <span style={{ color: momColor(s.momentum) }}>{s.momentum}</span>
                    </Chip>
                    {s.etf_change_pct != null && <span style={{ ...numStyle, fontSize: TYPE.xs, color: Number(s.etf_change_pct) >= 0 ? BB.green : BB.red }}>{Number(s.etf_change_pct) >= 0 ? '+' : ''}{Number(s.etf_change_pct).toFixed(2)}%</span>}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 700, color: s.setup_count > 0 ? T.link : BB.text3 }}>{s.setup_count}</div>
                  <div title="setups = score-ranked candidates surviving CIO-verdict + coverage filters; denominator = tracked constituents for this sector" style={{ fontSize: TYPE.xs, color: BB.text3 }}>setups / {s.constituent_count} tracked</div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                {s.setup_count > 0 && (
                  <button onClick={() => setExpanded(isOpen ? null : s.sector)} style={terminalButton('secondary')}>
                    {isOpen ? 'Hide' : `Candidates (${s.setup_count})`}
                  </button>
                )}
                {!s.is_watched && (
                  <button disabled={busy === s.sector} onClick={() => watchSector(s.sector)}
                          style={{ ...terminalButton('primary'), cursor: busy === s.sector ? 'wait' : 'pointer' }}>Watch sector</button>
                )}
              </div>

              {isOpen && (
                <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(s.candidates || []).map((c: any) => (
                    <div key={c.symbol} onClick={() => onDrill({ title: c.symbol, subtitle: `${s.sector} candidate`, endpoint: `/api/v2/watch/provenance/${c.symbol}`, rows: [c] })}
                      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: BB.bgShift, borderLeft: `3px solid ${RAIL.neutral}`, borderRadius: 2, cursor: 'pointer' }}>
                      <span style={{ ...numStyle, fontWeight: 700, color: BB.text0, fontSize: TYPE.sm }}>{c.symbol}</span>
                      <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                        {c.rsi != null && <Chip kind="metric" title="RSI-14 — hover source: enriched watchlist"><span style={{ color: Number(c.rsi) >= 70 ? BB.red : Number(c.rsi) < 40 ? BB.green : BB.text2 }}>RSI {Number(c.rsi).toFixed(0)}</span></Chip>}
                        {c.trend && <Chip kind="state" tone={trendTone(c.trend)}>{c.trend}</Chip>}
                        {c.score != null && <Chip kind="metric" title={c.watch_score_kind}><span style={{ color: c.watch_score_kind === 'strategy_qualified' ? BB.green : BB.text3 }}>{Number(c.score).toFixed(0)}</span></Chip>}
                      </span>
                    </div>
                  ))}
                  <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>Candidates from the enriched watchlist within this sector. Click for provenance. Adding the sector stages these for one-tap promote.</div>
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 12 }}>{data?.legend || 'Source: /api/v2/sectors/monitor.'} Advisory — momentum is informational; promotion stays governed.</div>
    </div>
  )
}
