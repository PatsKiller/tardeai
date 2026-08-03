import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import FinvizSectorPanel from '../components/FinvizSectorPanel'
import InstitutionalRotationBrief from '../components/rotation/InstitutionalRotationBrief'
import type { DrillContext } from '../components/DetailDrawer'
import { BB, T, TYPE, RAIL, numStyle, terminalButton, statePill, metricChip } from '../lib/watchTokens'
import { Chip } from '../components/TerminalChip'
import { laneLabel } from '../lib/laneLabels'

// Sector & Industry Monitor — deterministic monitoring and governed recommendations.
// External-model badges are narrative critiques, never the source of price, portfolio or permission truth.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const card: React.CSSProperties = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14 }

const SECTOR_ALIASES: Record<string, string> = {
  'financial services': 'Financials', financial: 'Financials',
  'consumer cyclical': 'Consumer Discretionary',
  'consumer defensive': 'Consumer Staples',
  'basic materials': 'Materials',
  'communication services': 'Communications',
}
const canonicalSector = (value?: string | null) => {
  const clean = String(value || '').trim()
  return SECTOR_ALIASES[clean.toLowerCase()] || clean
}

const rsSpark = (ser?: number[]) => {
  if (!ser || ser.length < 5) return null
  const min = Math.min(...ser), max = Math.max(...ser)
  const G = '▁▂▃▄▅▆▇█'
  if (max === min) return G[3].repeat(Math.min(ser.length, 30))
  return ser.slice(-30).map(v => G[Math.min(7, Math.round(((v - min) / (max - min)) * 7))]).join('')
}
const trendArrow = (t?: string) => t === 'improving' ? '↗' : t === 'deteriorating' ? '↘' : t === 'flat' ? '→' : ''
const momRail = (m?: string) => (({ leading: RAIL.favorable, lagging: RAIL.breach, neutral: RAIL.neutral } as any)[m || ''] || RAIL.neutral)
const momColor = (m?: string) => (({ leading: BB.green, lagging: BB.red, neutral: BB.text3 } as any)[m || ''] || BB.text3)
const trendTone = (t?: string): 'green' | 'red' | 'amber' | 'slate' =>
  (({ bullish: 'green', bearish: 'red', neutral: 'amber' } as any)[(t || '').toLowerCase()] || 'slate')

export default function SectorsHub({ onDrill, embedded }: Props) {
  const { data, refetch } = useApi<any>('/api/v2/sectors/monitor', 120_000)
  const { data: secExt } = useApi<any>('/api/v2/hermes/subject-intel-map?type=sector', 120_000)
  const { data: defensePosture } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: defenseIndustries } = useApi<any>('/api/v2/defense/industries', 300_000)
  const { data: recsData } = useApi<any>('/api/v2/defense/recommendations', 120_000)
  const secExtMap: Record<string, any[]> = secExt?.map ?? {}
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const sectors: any[] = data?.sectors ?? []
  const spy = data?.spy_change_pct
  const rotationRows: any[] = defensePosture?.momentum?.rows || []
  const industryRows: any[] = defenseIndustries?.industries || []
  const recommendations = recsData?.recommendations

  const industriesBySector = useMemo(() => {
    const out = new Map<string, any[]>()
    industryRows.forEach(industry => {
      const key = canonicalSector(industry.sector)
      const list = out.get(key) || []
      list.push(industry)
      out.set(key, list)
    })
    out.forEach(list => list.sort((a, b) => Number(b.rel1m ?? -999) - Number(a.rel1m ?? -999)))
    return out
  }, [industryRows])

  const recommendationByEtf = useMemo(() => {
    const out = new Map<string, any>()
    for (const rec of recommendations?.groups?.get_into || []) {
      const etf = (rec.instruments || []).find((instrument: any) => instrument.kind === 'sector ETF')?.symbol
      if (etf) out.set(etf, rec)
    }
    return out
  }, [recommendations])

  const watchSector = async (sector: string) => {
    setBusy(sector); setMsg(null)
    try {
      const r = await fetch('/api/v2/watch/directives', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'sector', label: `sector ${sector}`, spec: { finviz_sector: sector }, rationale: 'watched from sector monitor' }),
      })
      const j = await r.json()
      setMsg(j.ok ? `✓ Now watching ${sector} (directive #${j.directive_id}) — constituents stage for one-tap review` : `Error: ${j.error}`)
      refetch()
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(null)
  }

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: BB.text0 }}>Sectors & Industries</div>
        <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>
          {sectors.length} GICS sectors · ETF momentum vs SPY ({spy != null ? `${Number(spy) >= 0 ? '+' : ''}${Number(spy).toFixed(2)}%` : '—'} today) · recommendations remain advisory and governed
        </div>
      </div>

      {msg && <div style={{ fontSize: TYPE.sm, color: msg.startsWith('Error') ? BB.red : BB.green, marginBottom: 12 }}>{msg}</div>}

      <div style={{ fontSize: TYPE.xs, color: BB.text3, margin: '2px 0 8px' }}>
        Monitoring lens (RS history · book overlay · screen matches) plus an evidence-linked rotation brief. Allocation workflow →{' '}
        <a href="/v3/rotation" style={{ color: T.link }}>Rotation Intelligence</a>. Order staging remains a separate governed action.
      </div>

      <InstitutionalRotationBrief
        sectors={rotationRows}
        industries={industryRows}
        recommendations={recommendations}
        generatedAt={defensePosture?.momentum?.generated_at}
        industryCapturedAt={defenseIndustries?.captured_at}
        compact
      />

      <div style={{ marginTop: 12 }}><FinvizSectorPanel /></div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
        {sectors.map((s: any) => {
          const isOpen = expanded === s.sector
          const rec = recommendationByEtf.get(s.etf)
          const sectorIndustries = industriesBySector.get(canonicalSector(s.sector)) || []
          const improvingIndustries = sectorIndustries
            .filter((industry: any) => ['LEADING', 'IMPROVING'].includes(String(industry.state || '').toUpperCase()))
            .slice(0, 3)
          const weakeningIndustries = [...sectorIndustries]
            .filter((industry: any) => ['WEAKENING', 'LAGGING'].includes(String(industry.state || '').toUpperCase()))
            .sort((a, b) => Number(a.rel1m ?? 999) - Number(b.rel1m ?? 999))
            .slice(0, 2)
          const postureLabel = rec ? 'ADD ON PULLBACK' : s.momentum === 'lagging' ? 'UNDERWEIGHT / REVIEW' : 'RESEARCH WATCH'
          const postureTone: 'green' | 'amber' | 'red' | 'slate' = rec ? 'green' : s.momentum === 'lagging' ? 'red' : s.momentum === 'leading' ? 'amber' : 'slate'
          return (
            <div key={s.sector} style={{ ...card, borderLeft: `3px solid ${momRail(s.momentum)}`, opacity: String(s.momentum).startsWith('n/a') ? 0.7 : 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    {s.sector}
                    {s.is_watched && <Chip kind="state" tone="amber" title={s.directive?.label}>WATCHING</Chip>}
                    <span style={statePill(postureTone)}>{postureLabel}</span>
                    {(secExtMap[`SECTOR:${s.sector}`] || []).map((e: any, i: number) => (
                      <span key={i} onClick={(ev) => { ev.stopPropagation(); onDrill({ title: `${s.sector} — model critique`, subtitle: `${laneLabel(e.lane)} narrative · not recommendation authority`, endpoint: 'derived', rows: [s], subjectType: 'sector', subjectKey: `SECTOR:${s.sector}` }) }}
                        title={`${laneLabel(e.lane)} critique: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}\nNarrative context only — deterministic state and governed recommendation cards remain authoritative.`}
                        style={{ fontSize: TYPE.xs, fontWeight: 700, color: e.lane === 'grok' ? T.extIntel.grok : e.lane === 'chatgpt' ? T.extIntel.gpt : T.extIntel.gpt, cursor: 'pointer' }}>✦ {laneLabel(e.lane)} critique</span>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 5, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Chip kind="metric" title="sector ETF">{s.etf}</Chip>
                    <Chip kind="metric" title={s.rel_strength != null ? `ETF vs SPY: ${s.rel_strength > 0 ? '+' : ''}${s.rel_strength}% (day)` : 'no ETF data'}>
                      <span style={{ color: momColor(s.momentum) }}>{s.momentum}</span>
                    </Chip>
                    {s.etf_change_pct != null && <span style={{ ...numStyle, fontSize: TYPE.xs, color: Number(s.etf_change_pct) >= 0 ? BB.green : BB.red }}>{Number(s.etf_change_pct) >= 0 ? '+' : ''}{Number(s.etf_change_pct).toFixed(2)}%</span>}
                    {s.book_weight_pct != null && (
                      <Chip kind="metric" title="actual effective book weight, including configured fund look-through where available">
                        book {s.book_weight_pct}%
                      </Chip>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 5, alignItems: 'baseline', flexWrap: 'wrap' }}>
                    <span style={{ ...numStyle, fontSize: TYPE.xs, color: s.rs_trend === 'improving' ? BB.green : s.rs_trend === 'deteriorating' ? BB.red : BB.text3 }}>
                      RS {trendArrow(s.rs_trend)} {s.rs_20d_pct != null ? `20d ${s.rs_20d_pct > 0 ? '+' : ''}${s.rs_20d_pct}%` : 'n/a'}{s.rs_60d_pct != null ? ` · 60d ${s.rs_60d_pct > 0 ? '+' : ''}${s.rs_60d_pct}%` : ''}
                    </span>
                    {rsSpark(s.rs_series) && <span title={`ETF/SPY ratio, last ${Math.min(30, s.rs_n)} sessions (n=${s.rs_n})`}
                          style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text3 }}>{rsSpark(s.rs_series)}</span>}
                  </div>
                  <div style={{ marginTop: 7 }}>
                    <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, textTransform: 'uppercase', marginBottom: 3 }}>industries underneath</div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {improvingIndustries.map((industry: any) => (
                        <span key={industry.industry} style={{ ...metricChip(), color: BB.green }} title={`${industry.state} · rel 1m ${industry.rel1m ?? '—'}% · rel 1w ${industry.rel1w ?? '—'}%`}>
                          {industry.industry}
                        </span>
                      ))}
                      {weakeningIndustries.map((industry: any) => (
                        <span key={industry.industry} style={{ ...metricChip(), color: BB.red }} title={`${industry.state} · rel 1m ${industry.rel1m ?? '—'}% · rel 1w ${industry.rel1w ?? '—'}%`}>
                          {industry.industry}
                        </span>
                      ))}
                      {!sectorIndustries.length && <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>industry snapshot unavailable</span>}
                    </div>
                  </div>
                  {s.book_flag === 'overweight_lagging' && (
                    <div style={{ marginTop: 7, padding: '4px 8px', background: BB.amberDim, border: `1px solid ${BB.amber}55`, borderLeft: `3px solid ${RAIL.attention}`, borderRadius: 2, fontSize: TYPE.xs, color: BB.amber, fontWeight: 700 }}>
                      ⚠ Overweight ({s.book_weight_pct}%) while relative strength deteriorates — review funding and rotation candidates
                    </div>
                  )}
                  {!rec && s.momentum === 'leading' && (
                    <div style={{ marginTop: 7, padding: '4px 8px', background: BB.bgShift, borderLeft: `3px solid ${BB.amber}`, fontSize: TYPE.xs, color: BB.text3 }}>
                      Leading monitor signal only — no governed add card is active for this sector.
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 700, color: s.setup_count > 0 ? T.link : BB.text3 }}>{s.setup_count}</div>
                  <div title="screen matches = enriched watch-universe names satisfying broad strategy filters; this is not an expected-return, conviction or recommendation score" style={{ fontSize: TYPE.xs, color: BB.text3 }}>screen matches / {s.constituent_count} tracked</div>
                </div>
              </div>

              {rec && (
                <div style={{ marginTop: 8, borderLeft: `3px solid ${BB.green}`, background: BB.bgShift, padding: '6px 8px', fontSize: TYPE.sm, color: BB.text2 }}>
                  <div><b style={{ color: BB.text1 }}>Current governed card:</b> {rec.entry_logic}</div>
                  <div style={{ color: BB.amber, marginTop: 2 }}><b>Invalidation:</b> {rec.invalidation}</div>
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                {s.setup_count > 0 && (
                  <button onClick={() => setExpanded(isOpen ? null : s.sector)} style={terminalButton('secondary')}>
                    {isOpen ? 'Hide screen matches' : `Screened names (${s.setup_count})`}
                  </button>
                )}
                {!s.is_watched && (
                  <button disabled={busy === s.sector} onClick={() => watchSector(s.sector)}
                          title="Creates a governed watch directive. It does not create a recommendation, proposal or order."
                          style={{ ...terminalButton('primary'), cursor: busy === s.sector ? 'wait' : 'pointer' }}>Watch sector</button>
                )}
              </div>

              {isOpen && (
                <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(s.candidates || []).map((c: any) => (
                    <div key={c.symbol} onClick={() => onDrill({ title: c.symbol, subtitle: `${s.sector} screen match · not a recommendation`, endpoint: `/api/v2/watch/provenance/${c.symbol}`, rows: [c] })}
                      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: BB.bgShift, borderLeft: `3px solid ${RAIL.neutral}`, borderRadius: 2, cursor: 'pointer' }}>
                      <span style={{ ...numStyle, fontWeight: 700, color: BB.text0, fontSize: TYPE.sm }}>{c.symbol}</span>
                      <span style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                        {c.rsi != null && <Chip kind="metric" title="RSI-14 from enriched watchlist"><span style={{ color: Number(c.rsi) >= 70 ? BB.red : Number(c.rsi) < 40 ? BB.green : BB.text2 }}>RSI {Number(c.rsi).toFixed(0)}</span></Chip>}
                        {c.trend && <Chip kind="state" tone={trendTone(c.trend)}>{c.trend}</Chip>}
                        {c.score != null && <Chip kind="metric" title={`${c.watch_score_kind || 'screen'} eligibility score — not conviction or expected return`}><span style={{ color: BB.text2 }}>screen {Number(c.score).toFixed(0)}</span></Chip>}
                        {c.thin_coverage && <Chip kind="state" tone="amber" title="Thin analyst/evidence coverage; do not elevate this screen match without additional diligence">THIN COVERAGE</Chip>}
                        {!c.cio_view && <Chip kind="state" tone="slate" title="No CIO synthesis is attached to this screen match">NO CIO VIEW</Chip>}
                        {c.analyst_opinions != null && <Chip kind="metric" title="analyst opinion count available to the screen">{c.analyst_opinions} analysts</Chip>}
                      </span>
                    </div>
                  ))}
                  <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>These are enriched watch-universe screen matches. Repeated scores reflect filter eligibility, not equal conviction. Click for provenance; only a complete governed recommendation card can carry an add posture.</div>
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 12 }}>
        Sources: sector monitor, deterministic defense posture, Finviz industry snapshot, portfolio look-through and complete recommendation cards. Screen-match scores are not forecasts or conviction. Industry relative windows currently mix Finviz week/month with local SPY 5/21-session baselines; close rankings should be treated as approximate until normalized.
      </div>
    </div>
  )
}
