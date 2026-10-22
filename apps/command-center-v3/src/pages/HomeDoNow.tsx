/** Home — "Do now" layout (operator-APPROVED Home redesign, gate-3 mockup Home.dc.html, 2026-10-22).
 *
 *  Slim header (portfolio, today, YTD, market, positions STALE badge + Refresh positions) → ONE Do-now queue
 *  (components/home/DoNowQueue.tsx over GET /api/v2/home/do-now) beside Accounts / What moved your book today / three
 *  numbers → Best opportunities, Market in one look, System pulse → collapsed drawers (AI briefing, Release train with
 *  STOP, Agents & Hermes, News & movers). Drawer bodies mount only when opened, so a closed drawer polls nothing.
 *
 *  Sources (every number's tooltip names its own): /api/v2/overview (header, movers, cash; holdings.json),
 *  /api/v2/portfolio/performance (accounts, YTD), /api/v2/home/do-now (queue, unprotected, heat; risk snapshot +
 *  desk-truth coverage), /api/v2/risk-regime/latest, /api/v2/trade-ai/summary, /api/v2/defense/posture,
 *  /api/v3/opportunities, /api/v2/system/platform-health, release-train summary, /api/v2/command.
 *  positions_current is not read: no approved reader batch covers Home (batch #1 = Watch held flag).
 *  The previous Home stays reachable at ?view=classic for one release. */
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars, type Tone } from '../lib/designTokens'
import {
  doNowFrom, positionsFreshness, moversBars, accountRows, cashPct, money, pct, ageLabel,
} from '../lib/homeDoNow'
import { platformHealthFrom, countsLabel } from '../lib/platformHealth'
import { renderSetupCounts } from '../lib/setupRunSummary'
import { tradeAiSurfaceFreshness } from '../lib/surfaceFreshness'
import { runLabel } from '../lib/homeLabels'
import { RELEASE_TRAIN_PATHS, freshness, summaryFrom, type ReleaseTrainSummaryWire } from '../lib/releaseTrain'
import DoNowQueue from '../components/home/DoNowQueue'
import ReleaseTrainCard from '../components/home/ReleaseTrainCard'
import MarketMoversBoard from '../components/home/MarketMoversBoard'
import MajorNewsGrid from '../components/home/MajorNewsGrid'
import { AiIntelligenceBriefing, ExecutiveBriefCard, HermesGatewayLine } from '../components/home/HomeTrustRender'
import { useOpenSymbol } from '../components/opportunity/OpportunityContext'

const unwrap = (d: any) => (d?.data && typeof d.data === 'object' && !Array.isArray(d.data) ? d.data : d)
const signTone = (v: number | null | undefined): string => (v == null ? TOKENS.text[2] : v < 0 ? TOKENS.danger : v > 0 ? TOKENS.success : TOKENS.text[2])

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id) }, [ms])
  return now
}

const card = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: '12px 14px', display: 'flex', flexDirection: 'column' as const, gap: 8, minWidth: 0 }
const label = { fontSize: TYPE.xs, color: TOKENS.text[2], textTransform: 'uppercase' as const, letterSpacing: '0.06em' }

function CardHead({ title, to, linkText }: { title: string; to: string; linkText: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
      <h2 style={{ margin: 0, fontSize: TYPE.md, fontWeight: 700, color: TOKENS.text[0] }}>{title}</h2>
      <Link to={to} style={{ fontSize: TYPE.sm, color: TOKENS.info, textDecoration: 'none' }}>{linkText} ›</Link>
    </div>
  )
}

function HeadFact({ name, value, color, tip, big, testId }: { name: string; value: ReactNode; color?: string; tip: string; big?: boolean; testId?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, cursor: 'help' }} title={tip} data-testid={testId}>
      <span style={label}>{name}</span>
      <span style={{ ...numStyle, fontSize: big ? TYPE.xl : TYPE.lg, fontWeight: 600, color: color ?? TOKENS.text[0] }}>{value}</span>
    </div>
  )
}

function Drawer({ id, title, summary, right, children }: { id: string; title: string; summary: ReactNode; right?: (open: () => void, isOpen: boolean) => ReactNode; children: () => ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div data-testid={`home-drawer-${id}`} style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', paddingRight: right ? 12 : 0 }}>
        <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)}
          style={{ flex: '1 1 260px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none',
            color: TOKENS.text[0], padding: '12px 14px', cursor: 'pointer', fontSize: TYPE.md, minHeight: 46, textAlign: 'left', fontFamily: 'inherit', minWidth: 0 }}>
          <span style={{ minWidth: 0 }}><b>{title}</b> <span style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>· {summary}</span></span>
          <span aria-hidden style={{ color: TOKENS.info, whiteSpace: 'nowrap', fontSize: TYPE.base }}>{open ? 'Hide ▴' : 'Show ▾'}</span>
        </button>
        {right?.(() => setOpen(true), open)}
      </div>
      {open && <div style={{ borderTop: `1px solid ${TOKENS.border}`, padding: '12px 14px', fontSize: TYPE.base, lineHeight: 1.6, color: TOKENS.text[1] }}>{children()}</div>}
    </div>
  )
}

function HermesDrawerBody({ cmd }: { cmd: any }) {
  const { data } = useApi<any>('/api/v2/hermes/health', 300_000)
  const h = unwrap(data) ?? {}
  const sc = h.staging_counts ?? {}
  const agents: any[] = cmd?.agent_health ?? []
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
      <div>
        <div style={label}>Agents · runs (30 d)</div>
        {agents.length === 0 && <div style={{ color: TOKENS.text[3] }}>No agent activity reported by /api/v2/command.</div>}
        {agents.slice(0, 8).map((a: any) => (
          <div key={a.agent} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: `1px solid ${TOKENS.borderSubtle}` }}
            title={`Source: ${a.count_source ?? 'watchlist_agent_results'} — watchlist runs only; the Agents page counts each agent's home table`}>
            <span style={numStyle}>{a.agent}</span><span style={numStyle}>{a.total_30d ?? a.runs ?? 0}</span>
          </div>
        ))}
      </div>
      <div>
        <div style={label}>Hermes · /api/v2/hermes/health</div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Research staged</span><span style={numStyle}>{sc.hermes_research_intelligence ?? '—'}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Validation findings</span><span style={numStyle}>{sc.hermes_validation_findings ?? '—'}</span></div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Autonomous loop</span><span>{data ? (h.autonomous_loop_active ? 'on' : 'idle') : '—'}</span></div>
        {data && <HermesGatewayLine status={h.gateway_status} loopActive={h.autonomous_loop_active} />}
        <Link to="/agents" style={{ fontSize: TYPE.sm, color: TOKENS.info, textDecoration: 'none' }}>Agents ›</Link>
      </div>
    </div>
  )
}

export default function HomeDoNow() {
  const now = useNow(30_000)
  const openSymbol = useOpenSymbol()
  const doNowApi = useApi<any>('/api/v2/home/do-now', 60_000)
  const { data: overview, loading: ovLoading } = useApi<any>('/api/v2/overview', 60_000)
  const { data: perf } = useApi<any>('/api/v2/portfolio/performance', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 60_000)
  const { data: posture } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: oppTop } = useApi<any>('/api/v3/opportunities?preset=top5', 300_000)
  const platformApi = useApi<any>('/api/v2/system/platform-health', 60_000)
  const rtApi = useApi<ReleaseTrainSummaryWire>(RELEASE_TRAIN_PATHS.summary, 120_000)
  const { data: command } = useApi<any>('/api/v2/command', 300_000)
  const cmd = command?.data ?? command ?? {}

  const dn = doNowFrom(doNowApi.data, { loading: doNowApi.loading, error: doNowApi.error, nowMs: now })
  const pos = positionsFreshness(overview, now)
  const pv: number | null = overview?.portfolio_value ?? null
  const todayChg: number | null = overview?.today_change ?? null
  const todayPct: number | null = overview?.today_pct ?? null
  const ytd = perf?.periods?.YTD
  const ytdPreferDisp = Boolean(ytd?.nav_is_not_market_only || ytd?.display_change != null)
  const ytdChg: number | null = (ytdPreferDisp && ytd?.display_change != null ? ytd.display_change : ytd?.change) ?? null
  const ytdPct: number | null = (ytdPreferDisp && ytd?.display_change_pct != null ? ytd.display_change_pct : ytd?.change_pct) ?? null
  const vix = tradeAi?.vix
  const regimeLabel: string = String(regime?.regime_label ?? '').replace(/_/g, ' ')
  const postureRows: any[] = posture?.momentum?.rows || []
  const lagging = postureRows.filter((r: any) => r.state === 'LAGGING')
  const leading = postureRows.filter((r: any) => r.state === 'LEADING')
  const movers = moversBars(overview)
  const accounts = accountRows(perf, overview)
  const cash = cashPct(overview)
  const n = dn.numbers
  const opps: any[] = (unwrap(oppTop)?.items || []).slice(0, 5)
  const ph = platformHealthFrom(platformApi.data, { error: platformApi.error, loading: platformApi.loading, nowMs: now })
  const scanStale = tradeAiSurfaceFreshness(tradeAi).stale
  const setup = renderSetupCounts(tradeAi?.setup_run_summary, { stale: scanStale, staleLabel: 'STALE' })
  const rtF = freshness(rtApi.data?.generated_at, !!rtApi.data, { nowMs: now, loading: rtApi.loading, error: rtApi.error })
  const rt = summaryFrom(rtApi.data, rtF, now)
  const notFresh: string[] = overview?.observation?.not_fresh_datasets ?? []

  const pulse: { k: string; v: string; tone: Tone; tip: string; to: string }[] = [
    { k: 'Platform', v: ph.state === 'LOADING' ? '…' : ph.state === 'UNAVAILABLE' ? 'UNAVAILABLE' : countsLabel(ph.counts), to: '/system?tab=Platform',
      tone: ph.state === 'OK' ? 'success' : ph.state === 'CRIT' ? 'danger' : 'warning', tip: `/api/v2/system/platform-health · ${ph.state}${ph.reason ? ` · ${ph.reason}` : ''}` },
    { k: 'Latest scan', v: tradeAi ? `${runLabel(tradeAi.run_label, tradeAi.run_date)} · ${setup.counts}` : '—', to: '/trading',
      tone: scanStale || setup.degraded || setup.healthDegraded ? 'warning' : 'success', tip: `/api/v2/trade-ai/summary · ${setup.population || 'population unknown'}${setup.runHealthStatus ? ` · ${setup.runHealthStatus}` : ''}` },
    { k: 'Data health', v: overview ? `${overview.pipeline_status ?? 'unknown'}${notFresh.length ? ` · ${notFresh.length} not fresh` : ''}` : '—', to: '/system?tab=Data%20Sources',
      tone: overview?.pipeline_status === 'fresh' && !notFresh.length ? 'success' : 'warning', tip: `/api/v2/overview observation.surface_status${notFresh.length ? ` · not fresh: ${notFresh.join(', ')}` : ''}` },
    { k: 'Do-now sources', v: dn.state === 'LOADING' ? '…' : `${dn.sources.length - dn.unavailableSources.length}/${dn.sources.length} answered`, to: '/health',
      tone: dn.unavailableSources.length ? 'warning' : 'success', tip: dn.sources.map(s => `${s.name}: ${s.status}`).join(' · ') || 'not loaded' },
    { k: 'Release train', v: `${rt.stop.text} · next ${rt.nextWindow.text}`, to: '/coordination?tab=release',
      tone: rt.stop.effective ? 'danger' : rtF.state === 'OK' ? 'neutral' : 'warning', tip: `release-train summary · ${rtF.state}${rtF.reason ? ` · ${rtF.reason}` : ''}` },
  ]

  const llm = cmd.llm_intelligence
  const briefSummary = llm?.portfolio_risk ? String(llm.portfolio_risk).replace(/\s+/g, ' ').slice(0, 110) + '…' : command ? 'no briefing in /api/v2/command' : 'loading…'
  const agentsN = (cmd.agent_health ?? []).length
  const newsN = (cmd.top_news ?? []).length

  return (
    <div data-testid="home-do-now-page" style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 1392, margin: '0 auto' }}>
      {/* Slim header */}
      <header data-testid="home-header" style={{ ...card, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '12px 24px', flexDirection: 'row' }}>
        <HeadFact name="Portfolio" big testId="home-portfolio" value={pv != null ? money(pv) : ovLoading ? '…' : '—'}
          tip={`Total of all accounts, broker-reported and repriced (/api/v2/overview portfolio_value; holdings.json). ${overview?.position_count ?? '?'} positions.`} />
        <HeadFact name="Today" testId="home-today" color={signTone(todayChg)} value={todayChg != null ? `${money(todayChg, true)} · ${pct(todayPct)}` : '—'}
          tip="Today's change across all accounts (/api/v2/overview today_change / today_pct: broker snapshot day change, repriced when missing)." />
        <HeadFact name="YTD" testId="home-ytd" color={signTone(ytdChg)} value={ytdChg != null ? `${money(ytdChg, true)}${ytdPct != null ? ` · ${pct(ytdPct)}` : ''}${ytdPreferDisp ? ' ≈' : ''}` : '—'}
          tip={`Year to date, all accounts (/api/v2/portfolio/performance periods.YTD).${ytdPreferDisp ? ' ≈ = market change excluding transfers (display_change), the same rule as Portfolio → Returns.' : ''}${ytd?.adjustment_note ? ` ${ytd.adjustment_note}` : ''}`} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, cursor: 'help' }}
          title={`Regime from /api/v2/risk-regime/latest; VIX from /api/v2/trade-ai/summary; sectors from /api/v2/defense/posture.`}>
          <span style={label}>Market</span>
          <span data-testid="home-market" style={{ fontSize: TYPE.md, color: TOKENS.text[0] }}>
            {regimeLabel || 'regime unknown'}{vix != null ? ` · VIX ${vix}` : ''}{lagging.length ? ` · ${lagging.map((r: any) => String(r.sector).toLowerCase()).slice(0, 2).join(', ')} lagging` : ''}
          </span>
        </div>
        <span style={{ flex: 1 }} />
        <span data-testid="positions-freshness" title={pos.tip}
          style={{ fontSize: TYPE.sm, fontWeight: 700, borderRadius: RADIUS.sm, padding: '4px 8px', cursor: 'help',
            ...(pos.stale ? { color: toneVars('warning').color, background: toneVars('warning').bg, border: `1px solid ${toneVars('warning').border}` }
              : { color: TOKENS.text[2], border: `1px solid ${TOKENS.border}` }) }}>
          {pos.label}
        </span>
        <Link to="/portfolio" data-testid="refresh-positions" title="Opens Portfolio, where the manual broker sync (read-only holdings pull) is started. Home itself never calls a broker."
          style={{ fontSize: TYPE.sm, color: TOKENS.info, textDecoration: 'none' }}>Refresh positions</Link>
        <Link to="/?view=classic" data-testid="classic-view-link" title="The previous Home layout, kept for one release."
          style={{ fontSize: TYPE.sm, color: TOKENS.text[3], textDecoration: 'none' }}>Classic view</Link>
      </header>

      {/* Do now + right column */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'flex-start' }}>
        <DoNowQueue model={dn} />
        <aside aria-label="Portfolio" style={{ flex: '1 1 380px', maxWidth: 480, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <section style={card} data-testid="home-accounts" aria-label="Accounts">
            <CardHead title="Accounts" to="/portfolio?tab=Returns" linkText="Full returns" />
            {accounts.length === 0 ? (
              <div style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>{perf || overview ? 'Account performance not available.' : 'Loading…'}</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPE.sm }}>
                <thead>
                  <tr style={{ ...label, textAlign: 'right' }}>
                    <th style={{ textAlign: 'left', fontWeight: 600, padding: '2px 0' }}>Account</th>
                    <th style={{ fontWeight: 600 }} title="Current value (/api/v2/portfolio/performance current_value)">Value</th>
                    <th style={{ fontWeight: 600 }} title="Today's $ change">1D</th>
                    <th style={{ fontWeight: 600 }} title="Year-to-date $ change; ≈ = excluding transfers">YTD</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map(a => (
                    <tr key={a.key} title={a.tip} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, fontWeight: a.key === 'all' ? 700 : 400 }}>
                      <td style={{ padding: '4px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 130, color: TOKENS.text[1] }}>{a.name}</td>
                      <td style={{ ...numStyle, textAlign: 'right', paddingLeft: 8, whiteSpace: 'nowrap' }}>{money(a.value)}</td>
                      <td style={{ ...numStyle, textAlign: 'right', paddingLeft: 8, whiteSpace: 'nowrap', color: signTone(a.d1) }}>{money(a.d1, true)}</td>
                      <td style={{ ...numStyle, textAlign: 'right', paddingLeft: 8, whiteSpace: 'nowrap', color: signTone(a.ytd) }}>{money(a.ytd, true)}{a.ytdApprox ? ' ≈' : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </section>

          <section style={card} data-testid="home-movers" aria-label="What moved your book today">
            <CardHead title="What moved your book today" to="/portfolio" linkText="Portfolio" />
            {movers.bars.length === 0 && <div style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>{overview ? 'No position moved today.' : 'Loading…'}</div>}
            {movers.bars.map(b => (
              <button key={b.sym} type="button" onClick={() => openSymbol(b.sym)} data-testid="mover-row"
                title={`${b.sym}: ${money(b.amount, true)} today${b.dayPct != null ? ` (${pct(b.dayPct)})` : ''} · dollar day change of the holding (/api/v2/overview top_movers). Bar length is relative to the largest move shown.`}
                style={{ display: 'grid', gridTemplateColumns: '56px minmax(0, 1fr) 84px', gap: 10, alignItems: 'center', fontSize: TYPE.base, background: 'none', border: 'none', padding: 0, color: TOKENS.text[0], cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left' }}>
                <span style={{ ...numStyle, fontWeight: 600 }}>{b.sym}</span>
                <span style={{ height: 8, background: TOKENS.bg[3], borderRadius: RADIUS.sm, overflow: 'hidden', display: 'flex', justifyContent: b.negative ? 'flex-end' : 'flex-start' }}>
                  <span style={{ display: 'block', height: 8, width: `${b.widthPct}%`, background: b.negative ? TOKENS.danger : TOKENS.success }} />
                </span>
                <span style={{ ...numStyle, textAlign: 'right', color: b.negative ? TOKENS.danger : TOKENS.success }}>{money(b.amount, true)}</span>
              </button>
            ))}
            {movers.total != null && movers.bars.length > 0 && (
              <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}
                title="The rows shown are the largest movers; 'rest of the book' is every other holding, so the two always sum to today's change in the header.">
                Shown {money(movers.shownSum, true)} · rest of the book {money(movers.total - movers.shownSum, true)} · day {money(movers.total, true)}
              </span>
            )}
          </section>

          <section data-testid="home-numbers" aria-label="Three numbers" style={{ ...card, display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, textAlign: 'center' }}>
            <div title={n.available ? `${n.unprotected} positions, ${money(n.unprotectedValue)} in total. Basis: ${n.unprotectedBasis}. Positions: ${n.positionsSource}.${n.stale ? ' STALE.' : ''}` : 'Unavailable: the do-now risk source did not answer.'}
              style={{ display: 'flex', flexDirection: 'column', gap: 2, cursor: 'help' }} data-testid="num-unprotected">
              <span style={{ ...numStyle, fontSize: TYPE.xl, fontWeight: 600, color: n.unprotected ? TOKENS.danger : TOKENS.text[0] }}>{n.unprotected ?? '—'}</span>
              <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>unprotected positions</span>
            </div>
            <div title={n.available ? `Portfolio heat ${n.heatPct ?? '—'}%: ${n.heatBasis}. Limit ${n.heatLimitPct}%.${n.stale ? ' STALE.' : ''}` : 'Unavailable: the do-now risk source did not answer.'}
              style={{ display: 'flex', flexDirection: 'column', gap: 2, cursor: 'help' }} data-testid="num-heat">
              <span style={{ ...numStyle, fontSize: TYPE.xl, fontWeight: 600, color: n.heatPct != null && n.heatPct > n.heatLimitPct ? TOKENS.warning : TOKENS.text[0] }}>{n.heatPct != null ? `${n.heatPct.toFixed(1)}%` : '—'}</span>
              <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>portfolio heat (limit {n.heatLimitPct}%)</span>
            </div>
            <div title={cash != null ? `Cash ${money(overview?.total_cash)} of ${money(pv)} (/api/v2/overview total_cash ÷ portfolio_value; holdings.json, positions_current not yet approved for Home).` : 'Unavailable: /api/v2/overview has no total_cash or portfolio_value.'}
              style={{ display: 'flex', flexDirection: 'column', gap: 2, cursor: 'help' }} data-testid="num-cash">
              <span style={{ ...numStyle, fontSize: TYPE.xl, fontWeight: 600 }}>{cash != null ? `${cash.toFixed(1)}%` : '—'}</span>
              <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>cash</span>
            </div>
          </section>
        </aside>
      </div>

      {/* Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 14 }}>
        <section style={card} data-testid="home-opportunities" aria-label="Best opportunities">
          <CardHead title="Best opportunities" to="/watch?tab=opportunities&preset=top5" linkText="All" />
          {opps.length === 0 && <div style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>{oppTop ? 'Nothing clears the bar right now.' : 'Loading…'}</div>}
          {opps.map((o: any) => (
            <button key={o.symbol} type="button" onClick={() => openSymbol(o.symbol)}
              title={`${o.symbol}: conviction ${o.conviction != null ? Math.round(o.conviction) : '—'} of 100 · reward-to-risk ${o.risk_reward?.rr != null ? Number(o.risk_reward.rr).toFixed(1) : '—'}× (/api/v3/opportunities, CIO opportunity ranking). Advisory only.`}
              style={{ display: 'grid', gridTemplateColumns: '60px minmax(0, 1fr) 64px 36px', gap: 8, alignItems: 'center', fontSize: TYPE.base, padding: '4px 0', borderBottom: `1px solid ${TOKENS.borderSubtle}`, background: 'none', border: 'none', color: TOKENS.text[0], cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left' }}>
              <span style={{ ...numStyle, fontWeight: 600 }}>{o.symbol}</span>
              <span style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{String(o.type ?? '').replace(/_/g, ' ')}</span>
              <span style={{ ...numStyle, fontSize: TYPE.sm, textAlign: 'right' }}>R:R {o.risk_reward?.rr != null ? `${Number(o.risk_reward.rr).toFixed(1)}×` : '—'}</span>
              <span style={{ ...numStyle, fontWeight: 600, color: TOKENS.success, textAlign: 'right' }}>{o.conviction != null ? Math.round(o.conviction) : '—'}</span>
            </button>
          ))}
        </section>

        <section style={card} data-testid="home-market-card" aria-label="Market in one look">
          <CardHead title="Market in one look" to="/defense" linkText="Defense desk" />
          <div style={{ fontSize: TYPE.base, lineHeight: 1.6, color: TOKENS.text[1] }}
            title="Regime: /api/v2/risk-regime/latest. Sectors and hedge: /api/v2/defense/posture (momentum rows, hedge_state). 'You hold' is the sector's share of your book from the same posture rows.">
            Regime <b style={{ color: TOKENS.text[0] }}>{regimeLabel || 'unknown'}</b>{vix != null ? `, VIX ${vix}` : ''}.
            {postureRows.length > 0 && <> Sectors: {leading.length} leading, {lagging.length} lagging{lagging.length ? <> (<b>{lagging.map((r: any) => `${String(r.sector).toLowerCase()}${r.book_pct != null ? `, you hold ${r.book_pct}%` : ''}`).slice(0, 3).join('; ')}</b>)</> : ''}.</>}
            {posture?.hedge_state?.line ? <> Hedge: {posture.hedge_state.line}.</> : null}
            {posture?.inverse_stoplights?.line ? <> {posture.inverse_stoplights.line}.</> : null}
            {!postureRows.length && !regime && ' Loading…'}
          </div>
        </section>

        <section style={card} data-testid="home-pulse" aria-label="System pulse">
          <CardHead title="System pulse" to="/health" linkText="Health" />
          {pulse.map(p => (
            <Link key={p.k} to={p.to} title={p.tip} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: TYPE.base, textDecoration: 'none' }}>
              <span style={{ color: TOKENS.text[1] }}>{p.k}</span>
              <span style={{ fontWeight: 600, textAlign: 'right', color: p.tone === 'neutral' ? TOKENS.text[2] : toneVars(p.tone).color }}>{p.v}</span>
            </Link>
          ))}
        </section>
      </div>

      {/* Collapsed drawers — bodies mount (and poll) only when open */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Drawer id="briefing" title="AI briefing" summary={briefSummary}>
          {() => (llm || cmd.executive_brief) ? <>{llm && <AiIntelligenceBriefing llm={llm} />}{cmd.executive_brief && <ExecutiveBriefCard brief={cmd.executive_brief} />}</>
            : <span style={{ color: TOKENS.text[3] }}>No briefing in /api/v2/command yet.</span>}
        </Drawer>
        <Drawer id="release" title="Release train" summary={`${rt.stop.text} · next ${rt.nextWindow.text} · ready ${rt.ready.text} · held ${rt.held.text}`}
          right={(openDrawer, isOpen) => isOpen ? null : (
            <button type="button" data-testid="home-release-stop-shortcut" onClick={openDrawer}
              title="Opens the release-train drawer with the STOP RELEASES control (it asks for a reason and confirms). Not the trading kill switch."
              style={{ fontSize: TYPE.sm, fontWeight: 700, padding: '6px 12px', borderRadius: RADIUS.md, cursor: 'pointer', fontFamily: 'inherit', minHeight: 32,
                color: toneVars('danger').color, background: toneVars('danger').bg, border: `1px solid ${toneVars('danger').border}` }}>
              STOP releases…
            </button>
          )}>
          {() => <ReleaseTrainCard />}
        </Drawer>
        <Drawer id="agents" title="Agents and Hermes" summary={agentsN ? `${agentsN} agents reporting runs (30 d)` : 'agent runs and Hermes status'}>
          {() => <HermesDrawerBody cmd={cmd} />}
        </Drawer>
        <Drawer id="news" title="News and market movers" summary={newsN ? `${newsN} portfolio headlines · market movers` : 'portfolio headlines · market movers'}>
          {() => <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}><MajorNewsGrid /><MarketMoversBoard /></div>}
        </Drawer>
      </div>
      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}
        title="Positions, cash and movers read holdings.json through /api/v2/overview and the risk snapshot. positions_current (the broker-synced store) is approved for the Watch held flag only; Home moves to it when the operator approves a reader batch that covers Home.">
        Do-now as of {dn.asOf ?? '—'}{dn.asOf ? ` (${ageLabel((now - Date.parse(dn.asOf)) / 1000)} ago)` : ''} · positions from holdings.json (positions_current not yet approved for Home)
      </div>
    </div>
  )
}
