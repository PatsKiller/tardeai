import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import SchwabAccountsMonitor from '../components/SchwabAccountsMonitor'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'
// ProposalsRich retired — the old "Proposals" tab now renders the unified <BrokerProposals/>.
// Kept in the repo (src/components/ProposalsRich.tsx) for reference / fallback; intentionally unused here.
import BrokerOrders from '../components/BrokerOrders'
import TimeExitProposals from '../components/TimeExitProposals'
import ATMControlPanel from '../components/ATMControlPanel'
import OpenTradesIntelligence from '../components/OpenTradesIntelligence'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import ManualTosDesk from './ManualTosDesk'
import BrokerProposals from '../components/BrokerProposals'
import OptionsHub from './OptionsHub'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trade AI', 'Options', 'Open Trades', 'Proposals', 'Manual ToS', 'Execution', 'Broker Recon', 'Scalp', 'ATM Controls', 'Broker Orders', 'Schwab Accounts'] as const

// GO / WAIT / NO-GO decision color
const decisionColor = (d?: string) => d === 'GO' ? '#22c55e' : d === 'WAIT' ? '#f59e0b' : '#ef4444'

export default function TradingHub({ onDrill }: Props) {
  // Deep-link support (Stage 2a): /trading?tab=Broker+Orders&intent=<id> — the Telegram approval
  // message links the operator straight to the exact order item.
  const [searchParams] = useSearchParams()
  // Proposals unified into a single tab — old "Broker Proposals" deep-links land on "Proposals".
  const rawUrlTab = searchParams.get('tab')
  const urlTab = rawUrlTab === 'Broker Proposals' ? 'Proposals' : rawUrlTab
  const [tab, setTab] = useState<typeof TABS[number]>(
    (TABS as readonly string[]).includes(urlTab ?? '') ? (urlTab as typeof TABS[number]) : 'Trade AI')
  // C2 monitor → "edit as DRAFT" hands a seeded intent to the Broker Orders Active Trader panel
  const [draftSeed, setDraftSeed] = useState<any | null>(null)
  const [tradeFilter, setTradeFilter] = useState<'ALL' | 'GO' | 'WAIT'>('ALL')
  const [copied, setCopied] = useState<string | null>(null)
  // Broker desk tab: skip heavy hub polls so single-threaded API can serve broker-proposals first.
  const brokerDesk = tab === 'Proposals' || tab === 'Broker Orders' || tab === 'Schwab Accounts'
  const { data: tradeAi, error: tradeAiError, loading: tradeAiLoading } = useApi<any>('/api/v2/trade-ai', 60_000, { enabled: tab === 'Trade AI' })
  const paMap = useProAnalystMap()
  const { data: openTrades } = useApi<any>('/api/v2/open-trades', 30_000, { enabled: tab === 'Open Trades' || !brokerDesk })
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000, { enabled: tab === 'Proposals' || tab === 'Trade AI' })
  const { data: paperStatus } = useApi<any>('/api/v2/paper-status', 30_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000, { enabled: !brokerDesk })
  const { data: execState } = useApi<any>('/api/v2/execution/current-state', 120_000, { enabled: !brokerDesk })
  const { data: execQual } = useApi<any>('/api/v2/execution-quality', 120_000, { enabled: tab === 'Execution' })
  const { data: scalpData } = useApi<any>('/api/v2/scalp/live', 120_000, { enabled: tab === 'Scalp' })
  const { data: scalpExt } = useApi<any>('/api/v2/hermes/subject-intel-map?type=scalp', 120_000, { enabled: tab === 'Scalp' })
  const scalpExtMap: Record<string, any[]> = scalpExt?.map ?? {}
  const { data: setupAdvisory } = useApi<any>('/api/v2/atm/setup-advisory', 120_000, { enabled: tab === 'Open Trades' || tab === 'ATM Controls' })
  const { data: recon } = useApi<any>('/api/v2/broker-reconciliation', 120_000, { enabled: tab === 'Broker Recon' })

  const advMap: Record<string, any> = {}
  const advBySym: Record<string, any> = {}
  for (const a of (setupAdvisory?.advisories ?? [])) {
    advMap[String(a.proposal_id)] = a
    // Map advisory to symbol for open-position enrichment; prefer non-expired / higher-confidence
    const prev = advBySym[a.symbol]
    if (!prev || (prev.status === 'EXPIRED' && a.status !== 'EXPIRED')) advBySym[a.symbol] = a
  }
  const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'

  const trades = openTrades?.trades ?? []
  const execList: any[] = Array.isArray(execQual) ? execQual : []
  const propList = proposals?.proposals ?? []
  const pending = propList.filter((p: any) => p.status === 'PENDING' || p.status === 'APPROVED_FOR_PAPER_TEST')
  const alpaca = paperStatus?.alpaca ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Trading</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {/* hub-wide strip: "paper (Alpaca)" = the automated-trading PAPER pipeline's brokerage —
                unrelated to Schwab. On the Schwab tabs, show the Schwab program state instead. */}
            {(tab === 'Broker Orders' || tab === 'Schwab Accounts')
              ? <span>{trades.length} open (automated) · Schwab program: <b style={{ color: '#f59e0b' }}>READ-ONLY — execution disabled</b> · automated acct (Alpaca) {alpaca.account_status ?? '—'}</span>
              : <span>{trades.length} open · {brokerDesk ? 'broker queue active' : `${pending.length} pending proposals`} · automated acct (Alpaca) {alpaca.account_status ?? '—'}</span>}
            {readiness && <span> · P-level: {readiness.level?.replace(/_/g, ' ')}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {/* Readiness bar */}
      {readiness && tab !== 'Proposals' && tab !== 'Broker Orders' && (
        <div style={{ marginBottom: 14, padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, display: 'flex', gap: 20, alignItems: 'center', fontSize: 10 }}>
          <span style={{ color: 'var(--text3)' }}>Automated Readiness:</span>
          <span style={{ fontWeight: 700, color: '#f59e0b' }}>{readiness.level?.replace(/_/g, ' ')}</span>
          <span style={{ color: 'var(--text3)' }}>{readiness.closed_usable}/{readiness.target_2000} trades</span>
          <div style={{ flex: 1, height: 4, background: 'var(--bg2)', borderRadius: 2 }}>
            <div style={{ width: `${Math.min(100, readiness.pct_to_2000 ?? 0)}%`, height: '100%', background: '#f59e0b', borderRadius: 2, minWidth: 2 }} />
          </div>
          <span
            title={execState?.operator_status_label || ''}
            style={{ color: execState?.operator_live_via_2fa_allowed ? '#22c55e' : '#f59e0b', fontWeight: 700, fontSize: 9 }}
          >
            {execState?.operator_live_via_2fa_allowed ? '2FA LIVE ON' : 'AUTO LIVE BLOCKED'}
          </span>
        </div>
      )}
      {tab === 'Proposals' && (
        <div style={{ marginBottom: 14, padding: '8px 14px', background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.25)', borderRadius: 8, fontSize: 10, color: '#fbbf24' }}>
          Path B operator route — P0/paper caps are advisory only. <b>Auto route (2FA)</b> opens trade review (edit size/risk) before Schwab approval.
        </div>
      )}

      {tab === 'Trade AI' && (() => {
        // Phase 203: do NOT render the KPI grid as 0/0/0/no-run when the API fetch is loading or
        // errored — that silently masks a transient backend issue (e.g. DB contention) as an empty
        // scanner. Show an explicit state instead. Genuine empty data still renders below.
        if (!tradeAi) {
          const errored = !!tradeAiError
          return (
            <div style={{ background: 'var(--bg1)', border: `1px solid ${errored ? '#ef4444' : 'var(--border)'}`, borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Market Opportunities Scanner</div>
              <div style={{ fontSize: 12, color: errored ? '#ef4444' : 'var(--text3)' }}>
                {tradeAiLoading && !errored ? 'Loading latest scanner run…'
                  : errored ? '⚠ Scanner data temporarily unavailable — /api/v2/trade-ai did not respond (auto-retrying every 60s). This is an API/data-availability issue, not necessarily an empty scan. Check backend load (e.g. a long-running backup) if it persists.'
                  : 'No scanner data yet.'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/trade-ai{tradeAiError ? ` · error: ${String(tradeAiError).slice(0, 80)}` : ''}</div>
            </div>
          )
        }
        const tickers: any[] = (tradeAi?.tickers ?? []).slice().sort((a: any, b: any) => (b.score ?? 0) - (a.score ?? 0))
        const filtered = tradeFilter === 'ALL' ? tickers : tickers.filter((t: any) => t.decision === tradeFilter)
        const copyBoxes = (['GO', 'WAIT', 'ALL'] as const).map(type => {
          const syms = (type === 'ALL' ? tickers : tickers.filter((t: any) => t.decision === type)).map((t: any) => t.symbol)
          return { type, label: type === 'ALL' ? 'Universe' : type, syms, text: syms.join(','), color: type === 'GO' ? '#22c55e' : type === 'WAIT' ? '#f59e0b' : 'var(--text2)' }
        })
        const doCopy = (type: string, text: string) => {
          const done = () => { setCopied(type); setTimeout(() => setCopied(null), 1500) }
          if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(done)
          else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done() }
        }
        // Source badge config (parity with v2 Source column)
        const srcCfg: Record<string, { icon: string; color: string; label: string }> = {
          social: { icon: '💬', color: '#d97706', label: 'Social' },
          portfolio: { icon: '💼', color: '#6366f1', label: 'Portfolio' },
          personal_watchlist: { icon: '👤', color: '#6366f1', label: 'Personal' },
          ai_discovered: { icon: '🤖', color: '#059669', label: 'AI' },
          ai_watchlist: { icon: '🔍', color: '#059669', label: 'AI Watch' },
          screener: { icon: '📊', color: '#0891b2', label: 'Finviz' },
        }
        const srcBadge = (t: any) => {
          const c = srcCfg[t.source || 'screener'] || srcCfg.screener
          return { ...c, label: t.source === 'social' && t.source_detail ? `Social ${t.source_detail}` : c.label }
        }
        const pctColor = (v: any) => { const n = parseFloat(v); return isNaN(n) ? 'var(--text3)' : n >= 0 ? '#22c55e' : '#ef4444' }
        const pctText = (v: any) => (v === '' || v == null) ? '—' : `${v}%`
        // Richer ticker table layout
        const gridCols = '52px 72px 1fr 60px 30px 48px 64px 58px 58px 50px 1.3fr 1fr 1.6fr'
        const runHistory: any[] = tradeAi?.run_history ?? []
        const sectors: Record<string, number> = tradeAi?.sectors ?? {}
        const sectorEntries = Object.entries(sectors).sort((a, b) => (b[1] as number) - (a[1] as number))
        const sectorMax = sectorEntries.length ? Math.max(...sectorEntries.map(e => e[1] as number)) : 1
        const runGoMax = runHistory.length ? Math.max(1, ...runHistory.map((r: any) => r.go ?? 0)) : 1
        // KPI counts reflect the displayed universe (matching copy lists / filter / table),
        // NOT the current-run-only go_count/wait_count which read 0 on an underfilled run.
        const goN = tradeAi?.universe_go ?? tickers.filter((t: any) => t.decision === 'GO').length
        const waitN = tradeAi?.universe_wait ?? tickers.filter((t: any) => t.decision === 'WAIT').length
        const universeN = tradeAi?.universe_count ?? tickers.length
        const noGoN = tradeAi?.universe_nogo ?? Math.max(0, universeN - goN - waitN)
        const scannedN = tradeAi?.current_run_scanned ?? tradeAi?.latest_run_symbols_scanned ?? tradeAi?.ticker_count
        const kpis = [
          { label: 'GO', value: goN, color: '#22c55e' },
          { label: 'WAIT', value: waitN, color: '#f59e0b' },
          { label: 'NO-GO', value: noGoN, color: '#ef4444' },
          { label: 'Universe', value: universeN, color: 'var(--text0)' },
          { label: 'VIX', value: tradeAi?.vix != null ? Number(tradeAi.vix).toFixed(1) : '—', color: '#60a5fa' },
          { label: 'Regime', value: tradeAi?.market_regime ?? '—', color: '#a855f7' },
        ]
        return (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Market Opportunities Scanner</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                {tradeAi?.latest_run_label || tradeAi?.run_label || 'no run'}
                {tradeAi?.latest_run_timestamp && ` · ${new Date(tradeAi.latest_run_timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
                {scannedN != null && ` · ${scannedN} scanned this run`}
                {tradeAi?.run_health_status && <span style={{ marginLeft: 6, color: /healthy/i.test(tradeAi.run_health_status) ? '#22c55e' : '#ef4444' }}>· {tradeAi.run_health_status}</span>}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 8, margin: '10px 0 14px' }}>
              {kpis.map(k => (
                <div key={k.label} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 6px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k.label}</div>
                </div>
              ))}
            </div>

            {/* Copy lists (GO / WAIT / Universe) — paste into broker watchlist / ToS */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              {copyBoxes.map(b => (
                <div key={b.type} style={{ flex: 1, padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                    <span style={{ fontSize: 8, color: b.color, fontWeight: 700 }}>{b.label} ({b.syms.length})</span>
                    {b.syms.length > 0 && (
                      <button onClick={() => doCopy(b.type, b.text)} style={{
                        fontSize: 8, padding: '2px 8px', borderRadius: 4, cursor: 'pointer', fontWeight: 600,
                        border: `1px solid ${copied === b.type ? '#22c55e' : 'var(--border)'}`,
                        background: copied === b.type ? 'rgba(34,197,94,.12)' : 'var(--bg1)',
                        color: copied === b.type ? '#22c55e' : 'var(--text2)',
                      }}>{copied === b.type ? '✓ Copied' : 'Copy'}</button>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text0)', fontFamily: 'monospace', wordBreak: 'break-all', userSelect: 'all', cursor: 'text', minHeight: 16, maxHeight: 54, overflowY: 'auto' }}>
                    {b.text || '—'}
                  </div>
                </div>
              ))}
            </div>

            {/* Decision filter */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
              {(['ALL', 'GO', 'WAIT'] as const).map(f => {
                const active = tradeFilter === f
                const fc = f === 'GO' ? '#22c55e' : f === 'WAIT' ? '#f59e0b' : '#60a5fa'
                const count = f === 'ALL' ? tickers.length : tickers.filter((t: any) => t.decision === f).length
                return (
                  <button key={f} onClick={() => setTradeFilter(f)} style={{
                    padding: '4px 12px', fontSize: 10, borderRadius: 5, cursor: 'pointer', fontWeight: active ? 700 : 500,
                    border: `1px solid ${active ? fc : 'var(--border)'}`,
                    background: active ? `${fc}22` : 'var(--bg2)', color: active ? fc : 'var(--text3)', fontFamily: 'monospace',
                  }}>{f === 'ALL' ? 'Universe' : f} ({count})</button>
                )
              })}
            </div>

            <div style={{ overflowX: 'auto' }}>
            <div style={{ minWidth: 1080 }}>
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 6, fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
              <span>Decision</span><span>Source</span><span>Symbol</span><span>Score</span><span>Grd</span><span>RVOL</span><span>Price</span><span>Chg%</span><span>Gap%</span><span>Float</span><span>Sector</span><span>Social</span><span>Catalyst</span>
            </div>
            {filtered.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12 }}>No {tradeFilter === 'ALL' ? '' : tradeFilter + ' '}tickers in the latest run.</div> :
            filtered.slice(0, 60).map((t: any, i: number) => {
              const sb = srcBadge(t)
              const country = t.country || ''
              const flag = (!country || country === '🇺🇸' || country === 'United States') ? '' : country
              const social = t.social_sentiment || ''
              const socialColor = social.includes('Very Bullish') ? '#4ade80' : social.includes('Bullish') ? '#86efac' : social.includes('Bearish') ? '#f87171' : 'var(--text3)'
              const score = t.score ?? 0
              return (
              <div key={`${t.symbol}-${i}`} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.decision ?? ''} · score ${t.score ?? '—'} · ${t.sector ?? ''}`, endpoint: '/api/v2/trade-ai', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 6, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center', borderLeft: `3px solid ${decisionColor(t.decision)}` }}>
                <span style={{ fontWeight: 700, fontSize: 9, color: decisionColor(t.decision) }}>{t.decision || 'NO-GO'}</span>
                <span title={sb.label} style={{ fontSize: 8, fontWeight: 600, padding: '1px 4px', borderRadius: 3, border: `1px solid ${sb.color}40`, color: sb.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sb.icon} {sb.label}</span>
                <div style={{ overflow: 'hidden' }}>
                  <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                  {t.decision_changed && <span title={`critic changed from ${t.original_decision}`} style={{ fontSize: 8, color: '#f59e0b', marginLeft: 4 }}>⟳</span>}
                  {' '}<ProAnalystPill symbol={t.symbol} map={paMap} compact />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 24, height: 4, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden', flexShrink: 0 }}>
                    <div style={{ width: `${Math.min(score, 50) * 2}%`, height: '100%', background: score >= 40 ? '#22c55e' : score >= 30 ? '#f59e0b' : 'var(--text3)' }} />
                  </div>
                  <span style={{ fontWeight: 600, color: score >= 40 ? '#22c55e' : score >= 30 ? '#f59e0b' : 'var(--text2)' }}>{t.score ?? '—'}</span>
                </div>
                <span style={{ fontWeight: 600, color: t.grade === 'A' ? '#22c55e' : 'var(--text2)' }}>{t.grade || '—'}</span>
                <span style={{ color: (t.rvol ?? 0) >= 5 ? '#22c55e' : 'var(--text2)' }}>{t.rvol ? Number(t.rvol).toFixed(1) + 'x' : '—'}</span>
                <span style={{ color: 'var(--text2)' }}>{t.price ? `$${Number(t.price).toFixed(2)}` : '—'}</span>
                <span style={{ color: pctColor(t.change_pct), fontWeight: 600 }}>{pctText(t.change_pct)}</span>
                <span style={{ color: pctColor(t.gap_pct) }}>{pctText(t.gap_pct)}</span>
                <span style={{ color: 'var(--text2)' }}>{t.float_m != null && t.float_m !== '' ? `${t.float_m}M` : '—'}</span>
                <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1, overflow: 'hidden' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{flag}{flag ? ' ' : ''}{t.sector || '—'}</span>
                  {t.vs_sector_pct != null && <span style={{ fontSize: 8, color: t.vs_sector_pct >= 0 ? '#4ade80' : '#f87171' }}>vs {t.sector_etf || 'sector'}: {t.vs_sector_pct >= 0 ? '+' : ''}{t.vs_sector_pct}%</span>}
                </span>
                {social ? (
                  <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <span style={{ fontWeight: 600, color: socialColor }}>{social}</span>
                    {(t.social_reddit || t.social_stocktwits) ? <span style={{ fontSize: 8, color: 'var(--text3)' }}>R:{t.social_reddit || 0} ST:{t.social_stocktwits || 0}{t.social_bullish_pct != null ? ` (${Math.round(t.social_bullish_pct)}% bull)` : ''}</span> : null}
                  </span>
                ) : <span style={{ fontSize: 9, color: 'var(--text3)' }}>—</span>}
                <span style={{ fontSize: 9, color: t.disqualified ? '#fca5a5' : t.catalyst_verified === false ? '#f59e0b' : 'var(--text3)', display: 'flex', alignItems: 'center', gap: 4, overflow: 'hidden' }} title={t.catalyst}>
                  {t.disqualified && <span style={{ fontSize: 7, background: '#7f1d1d', color: '#fca5a5', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>DQ</span>}
                  {!t.disqualified && t.catalyst_verified === false && <span style={{ fontSize: 7, background: '#78350f', color: '#fcd34d', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>?</span>}
                  {!t.disqualified && t.catalyst_verified === true && <span style={{ fontSize: 7, background: '#052e16', color: '#86efac', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>V</span>}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.catalyst || '—'}</span>
                </span>
              </div>
            )})}
            </div>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/trade-ai (orchestrator scan: screener → enrichment → scalp critic → GO/WAIT/NO-GO). Click a row for full scan detail. Showing top {Math.min(60, filtered.length)} of {filtered.length}{tradeFilter !== 'ALL' ? ` ${tradeFilter}` : ''} by score{tradeFilter !== 'ALL' ? ` (${tickers.length} universe)` : ''}.</div>

            {/* Run History + Sector Distribution */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Run History <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({runHistory.length})</span></div>
                {runHistory.length <= 1 ? <div style={{ color: 'var(--text3)', fontSize: 10 }}>Single run only</div> : (
                  <>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 60 }}>
                      {runHistory.slice().reverse().map((r: any, i: number) => (
                        <div key={i} title={`${r.label} · GO ${r.go} · WAIT ${r.wait}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
                          <div style={{ width: '100%', height: `${((r.go ?? 0) / runGoMax) * 100}%`, minHeight: (r.go ?? 0) > 0 ? 3 : 0, background: (r.go ?? 0) > 0 ? '#22c55e' : 'var(--border)', borderRadius: '2px 2px 0 0' }} />
                          <span style={{ fontSize: 7, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap' }}>{r.label}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                      {runHistory.map((r: any, i: number) => (
                        <div key={i} style={{ fontSize: 9, color: 'var(--text3)' }}><span style={{ fontWeight: 600, color: 'var(--text2)' }}>{r.label}</span> GO:{r.go} W:{r.wait}</div>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Sector Distribution <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({sectorEntries.length})</span></div>
                {sectorEntries.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 10 }}>No sector data available</div> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
                    {sectorEntries.map(([sec, count]) => (
                      <div key={sec} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 110, fontSize: 9, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec}</span>
                        <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${((count as number) / sectorMax) * 100}%`, height: '100%', background: '#60a5fa', opacity: 0.7, borderRadius: 3 }} />
                        </div>
                        <span style={{ width: 28, fontSize: 9, color: 'var(--text1)', textAlign: 'right', fontWeight: 600 }}>{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {tab === 'Options' && <OptionsHub onDrill={onDrill} />}

      {tab === 'Open Trades' && (
        <>
          <TimeExitProposals />
          <OpenTradesIntelligence onDrill={onDrill} focusSymbol={searchParams.get('symbol') || undefined} />
          <details style={{ marginTop: 14 }}>
            <summary style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', cursor: 'pointer' }}>Protection Advisory (all proposals)</summary>
            <div style={{ marginTop: 10 }}><ProtectionPanel onDrill={onDrill} /></div>
          </details>
        </>
      )}

      {tab === 'Proposals' && <BrokerProposals focusSymbol={searchParams.get('symbol') || undefined} />}
      {tab === 'Broker Orders' && <BrokerOrders draftSeed={draftSeed} />}
      {tab === 'Schwab Accounts' && (
        <SchwabAccountsMonitor onEditDraft={(intent: any) => { setDraftSeed(intent); setTab('Broker Orders') }} />
      )}

      {tab === 'Execution' && execQual && (() => {
        // ── Transaction Cost Analysis: aggregate the rich per-fill data into a clear, actionable view ──
        const QC = (q?: string) => { const u = (q || '').toUpperCase(); return u === 'EXCELLENT' ? '#22c55e' : u === 'GOOD' ? '#4ade80' : u === 'ACCEPTABLE' ? '#f59e0b' : u === 'POOR' ? '#ef4444' : 'var(--text3)' }
        const ex = execList
        const n = ex.length
        const q = { EXCELLENT: 0, GOOD: 0, ACCEPTABLE: 0, POOR: 0, OTHER: 0 } as Record<string, number>
        ex.forEach((e: any) => { const u = (e.fill_quality || '').toUpperCase(); if (q[u] != null) q[u]++; else q.OTHER++ })
        const slips = ex.map((e: any) => e.slippage_pct).filter((v: any) => v != null)
        const avgSlip = slips.length ? slips.reduce((a: number, b: number) => a + Math.abs(b), 0) / slips.length : null
        const totSlipD = ex.reduce((a: number, e: any) => a + (e.slippage_dollars || 0), 0)
        const ttf = ex.map((e: any) => e.time_to_fill_seconds).filter((v: any) => v != null)
        const avgTtf = ttf.length ? ttf.reduce((a: number, b: number) => a + b, 0) / ttf.length : null
        const partials = ex.filter((e: any) => e.partial_fill).length
        const improved = ex.filter((e: any) => (e.price_improvement_pct || 0) > 0).length
        const poor = ex.filter((e: any) => (e.fill_quality || '').toUpperCase() === 'POOR')
          .sort((a: any, b: any) => Math.abs(b.slippage_pct || 0) - Math.abs(a.slippage_pct || 0))
        const ordered = [...ex].sort((a: any, b: any) => {
          const pa = (a.fill_quality || '').toUpperCase() === 'POOR' ? 1 : 0, pb = (b.fill_quality || '').toUpperCase() === 'POOR' ? 1 : 0
          if (pa !== pb) return pb - pa
          return Math.abs(b.slippage_pct || 0) - Math.abs(a.slippage_pct || 0)
        })
        const Tip = ({ t, children }: { t: string; children: any }) => (
          <span title={t} style={{ cursor: 'help', borderBottom: '1px dotted var(--text3)' }}>{children}</span>
        )
        const Metric = ({ label, value, color, tip }: { label: string; value: any; color?: string; tip: string }) => (
          <div title={tip} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', cursor: 'help', minWidth: 110, flex: '1 1 110px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label} ⓘ</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: color || 'var(--text0)', marginTop: 2 }}>{value}</div>
          </div>
        )
        return (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Execution Quality — Transaction Cost Analysis</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>How well orders filled vs. intended. Clean execution (low slippage, tight fills) is part of the live-readiness case.</div>

          {n === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No execution quality data yet.</div> : (<>

          {/* POOR-fill alert */}
          {poor.length > 0 && (
            <div style={{ background: 'rgba(239,68,68,.1)', border: '1px solid rgba(239,68,68,.4)', borderRadius: 8, padding: '8px 12px', marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444' }}>⚠ {poor.length} POOR fill{poor.length > 1 ? 's' : ''} — investigate</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {poor.slice(0, 6).map((e: any) => (
                  <span key={e.id} onClick={() => onDrill({ title: `${e.symbol} TCA`, subtitle: `POOR · slip ${e.slippage_pct?.toFixed(2)}%`, endpoint: '/api/v2/execution-quality', rows: [e] })} style={{ cursor: 'pointer', textDecoration: 'underline dotted' }}>
                    <b style={{ fontFamily: 'monospace' }}>{e.symbol}</b> {e.slippage_pct != null ? `${e.slippage_pct.toFixed(2)}%` : ''} {e.market_session ? `(${e.market_session})` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Summary band */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <Metric label="Fills" value={n} tip="Total recorded fills in this window." />
            <Metric label="Avg Slippage" value={avgSlip != null ? `${avgSlip.toFixed(3)}%` : '—'} color={avgSlip == null ? undefined : avgSlip < 0.1 ? '#22c55e' : avgSlip < 0.3 ? '#f59e0b' : '#ef4444'} tip="Average absolute difference between intended and actual fill price, as % of price. Lower is better; under ~0.1% is excellent." />
            <Metric label="Total Slip $" value={fmt$(totSlipD)} color={totSlipD <= 0 ? '#22c55e' : '#ef4444'} tip="Net dollar cost (or gain) from slippage across all fills. Negative/zero = you paid no cost; positive = slippage ate into returns." />
            <Metric label="Avg Time-to-Fill" value={avgTtf != null ? `${avgTtf.toFixed(1)}s` : '—'} tip="Average seconds from order submit to fill. Faster reduces adverse price drift." />
            <Metric label="Partial Fills" value={`${partials}/${n}`} color={partials === 0 ? '#22c55e' : '#f59e0b'} tip="Orders that filled only partially. Frequent partials suggest thin liquidity or sizing too large." />
            <Metric label="Price Improved" value={`${improved}/${n}`} color={improved > 0 ? '#22c55e' : undefined} tip="Fills that executed BETTER than intended (positive price improvement)." />
          </div>

          {/* Graphical quality distribution bar */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}><Tip t="Distribution of fill-quality grades. Aim for mostly EXCELLENT/GOOD; any POOR is worth a look.">FILL QUALITY DISTRIBUTION ⓘ</Tip></div>
            <div style={{ display: 'flex', height: 22, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
              {(['EXCELLENT', 'GOOD', 'ACCEPTABLE', 'POOR', 'OTHER'] as const).map(k => q[k] > 0 && (
                <div key={k} title={`${k}: ${q[k]} (${((q[k] / n) * 100).toFixed(0)}%)`} style={{ width: `${(q[k] / n) * 100}%`, background: QC(k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>
                  {(q[k] / n) > 0.08 ? q[k] : ''}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 9, color: 'var(--text2)', flexWrap: 'wrap' }}>
              {(['EXCELLENT', 'GOOD', 'ACCEPTABLE', 'POOR'] as const).map(k => q[k] > 0 && (
                <span key={k}><span style={{ color: QC(k) }}>■</span> {k} {q[k]}</span>
              ))}
            </div>
          </div>

          {/* Fills table — poor first, color-coded */}
          <div style={{ display: 'flex', fontSize: 9, color: 'var(--text3)', padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 64px' }}>Symbol</span>
            <span style={{ flex: '0 0 90px' }}><Tip t="Fill-quality grade for this order.">Quality</Tip></span>
            <span style={{ flex: '0 0 80px' }}><Tip t="Slippage: intended vs actual fill price as %.">Slip %</Tip></span>
            <span style={{ flex: '0 0 80px' }}><Tip t="Bid-ask spread at submit, as %. Wider spreads make good fills harder.">Spread</Tip></span>
            <span style={{ flex: '0 0 70px' }}><Tip t="Seconds from submit to fill.">Fill (s)</Tip></span>
            <span style={{ flex: '1 1 auto' }}>Session · Strategy</span>
          </div>
          {ordered.slice(0, 30).map((e: any) => {
            const isPoor = (e.fill_quality || '').toUpperCase() === 'POOR'
            return (
            <div key={e.id} onClick={() => onDrill({ title: `${e.symbol} — Transaction Cost Analysis`, subtitle: `${e.fill_quality ?? '—'} · slip ${e.slippage_pct != null ? e.slippage_pct.toFixed(2) + '%' : '—'} · intended ${e.intended_entry ?? '—'} → fill ${e.fill_price ?? '—'}`, endpoint: '/api/v2/execution-quality', rows: [e] })}
              style={{ display: 'flex', alignItems: 'center', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, background: isPoor ? 'rgba(239,68,68,.06)' : undefined }}>
              <span style={{ flex: '0 0 64px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{e.symbol}</span>
              <span style={{ flex: '0 0 90px' }}><span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: QC(e.fill_quality), color: '#0a0a0a' }}>{e.fill_quality ?? '—'}</span></span>
              <span style={{ flex: '0 0 80px', color: e.slippage_pct == null ? 'var(--text3)' : Math.abs(e.slippage_pct) < 0.1 ? '#22c55e' : Math.abs(e.slippage_pct) < 0.5 ? '#f59e0b' : '#ef4444' }}>{e.slippage_pct != null ? `${e.slippage_pct.toFixed(2)}%` : '—'}</span>
              <span style={{ flex: '0 0 80px', color: 'var(--text2)' }}>{e.spread_pct != null ? `${e.spread_pct.toFixed(2)}%` : '—'}</span>
              <span style={{ flex: '0 0 70px', color: 'var(--text2)' }}>{e.time_to_fill_seconds != null ? `${e.time_to_fill_seconds.toFixed(0)}s` : '—'}</span>
              <span style={{ flex: '1 1 auto', fontSize: 9, color: 'var(--text3)' }}>{e.market_session ?? '—'}{e.strategy_id ? ` · ${e.strategy_id}` : ''}</span>
            </div>
          )})}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/execution-quality · click any row for full TCA (intended → arrival → fill, spread, shares, data-quality). Hover ⓘ for definitions.</div>
          </>)}
        </div>
        )
      })()}

      {tab === 'Broker Recon' && (() => {
        const r = recon?.data ?? recon ?? {}
        const runs = r.runs ?? []
        const items = r.items ?? []
        const latest = runs[0] ?? {}
        const stClr = (s: string) => /ok|matched|clean/i.test(s || '') ? '#22c55e' : /unmatched|mismatch|orphan|issue/i.test(s || '') ? '#ef4444' : 'var(--text3)'
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {[
                { k: 'Orders seen', v: latest.orders_seen ?? '—', c: 'var(--text0)' },
                { k: 'Trades matched', v: latest.trades_matched ?? '—', c: '#22c55e' },
                { k: 'Unmatched broker', v: latest.unmatched_broker_orders ?? 0, c: (latest.unmatched_broker_orders ?? 0) > 0 ? '#ef4444' : 'var(--text3)' },
                { k: 'Unmatched local', v: latest.unmatched_local_trades ?? 0, c: (latest.unmatched_local_trades ?? 0) > 0 ? '#ef4444' : 'var(--text3)' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Reconciliation items ({items.length})</div>
              {items.length === 0 ? <div style={{ color: '#22c55e', fontSize: 11 }}>No unmatched items — broker and local in sync.</div> :
              items.slice(0, 20).map((it: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: it.symbol ?? it.broker_order_id, subtitle: it.reconciliation_state, endpoint: '/api/v2/broker-reconciliation', rows: [it] })}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr 1fr', gap: 8, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text0)' }}>{it.symbol ?? '—'}</span>
                  <span style={{ color: stClr(it.reconciliation_state), fontSize: 9 }}>{it.reconciliation_state ?? ''}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 9 }}>{it.issue_code ?? it.broker ?? ''}</span>
                </div>
              ))}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/broker-reconciliation — DB vs Alpaca. Latest run: {latest.broker ?? ''} {latest.run_status ?? ''} {latest.started_at ? new Date(latest.started_at).toLocaleString() : ''}</div>
            </div>
          </div>
        )
      })()}

      {tab === 'Scalp' && scalpData && (() => {
        // ── Live scalp signals: unwrap {timestamp,data:{...}} and present clearly + actionably ──
        const GC = (g?: string) => { const u = (g || '').toUpperCase(); return u === 'A' ? '#22c55e' : u === 'B' ? '#84cc16' : u === 'C' ? '#f59e0b' : u === 'D' || u === 'F' ? '#ef4444' : 'var(--text3)' }
        // Social Scout pill — operator-awareness ONLY. Distinct violet (var(--social-scout)), never
        // green/GO. No execution/validate/buy affordance: it is a watch/surface state, never tradeable.
        const SCOUT_COLOR = 'var(--social-scout)'
        const ScoutPill = ({ d }: { d: any }) => {
          if (d.scout_status !== 'SOCIAL_SCOUT' || !d.operator_pill) return null
          const hints = (d.operator_tooltip_hints || []).join(' · ')
          const tip = `${d.operator_subtitle || 'Not quite there yet'}${hints ? ' — ' + hints : ''}\n`
            + 'Awareness only — not a GO, not validation-fast-path eligible, not a standard momentum_scalp trade.'
          return (
            <span title={tip} style={{ fontSize: 8.5, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
              background: 'var(--social-scout-dim)', color: SCOUT_COLOR, border: `1px solid ${SCOUT_COLOR}`,
              whiteSpace: 'nowrap', cursor: 'help', marginRight: 6 }}>{d.operator_pill}</span>
          )
        }
        const raw: any[] = scalpData.signals ?? []
        const sigs = raw.map((s: any) => ({ ...(s.data || s), _ts: s.timestamp })).filter((d: any) => d.symbol)
        const n = sigs.length
        const byG: Record<string, number> = {}; sigs.forEach((d: any) => { const g = (d.grade || '?').toUpperCase(); byG[g] = (byG[g] || 0) + 1 })
        const byD = { GO: 0, WAIT: 0, 'NO-GO': 0 } as Record<string, number>
        sigs.forEach((d: any) => { const k = (d.decision || '').toUpperCase().replace('_', '-'); if (byD[k] != null) byD[k]++ })
        const catalyst = sigs.filter((d: any) => d.catalyst_verified).length
        const scouts = sigs.filter((d: any) => d.scout_status === 'SOCIAL_SCOUT').length
        const avgScore = n ? Math.round(sigs.reduce((a: number, d: any) => a + (d.score || 0), 0) / n) : 0
        // "prime" actionable scalp = GO + grade A + catalyst verified (the criteria that actually matter)
        const prime = sigs.filter((d: any) => (d.decision || '').toUpperCase() === 'GO' && (d.grade || '').toUpperCase() === 'A' && d.catalyst_verified)
        const gradeRank: Record<string, number> = { A: 4, B: 3, C: 2, D: 1, F: 0 }
        const ordered = [...sigs].sort((a: any, b: any) => {
          const da = (a.decision || '').toUpperCase() === 'GO' ? 1 : 0, db = (b.decision || '').toUpperCase() === 'GO' ? 1 : 0
          if (da !== db) return db - da
          const ga = gradeRank[(a.grade || '').toUpperCase()] ?? -1, gb = gradeRank[(b.grade || '').toUpperCase()] ?? -1
          if (ga !== gb) return gb - ga
          return (b.score || 0) - (a.score || 0)
        })
        const Tip = ({ t, children }: { t: string; children: any }) => (
          <span title={t} style={{ cursor: 'help', borderBottom: '1px dotted var(--text3)' }}>{children}</span>
        )
        const Metric = ({ label, value, color, tip }: { label: string; value: any; color?: string; tip: string }) => (
          <div title={tip} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', cursor: 'help', minWidth: 100, flex: '1 1 100px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label} ⓘ</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: color || 'var(--text0)', marginTop: 2 }}>{value}</div>
          </div>
        )
        return (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Scalp Live — Signal Screen</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>Live scalp candidates, graded. Prime setups = GO · grade A · catalyst-verified (with high RVOL). These are advisory — execution is gated.</div>

          {n === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No live scalp signals.</div> : (<>

          {/* Prime-setup alert */}
          <div style={{ background: prime.length ? 'rgba(34,197,94,.1)' : 'var(--bg2)', border: `1px solid ${prime.length ? 'rgba(34,197,94,.4)' : 'var(--border)'}`, borderRadius: 8, padding: '8px 12px', marginBottom: 12 }}>
            {prime.length ? (<>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#22c55e' }}>✦ {prime.length} prime setup{prime.length > 1 ? 's' : ''} — GO · A · catalyst</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {prime.slice(0, 8).map((d: any, i: number) => (
                  <span key={i} onClick={() => onDrill({ title: `${d.symbol} — Scalp Signal`, subtitle: `GO · A · score ${d.score} · RVOL ${d.rvol}`, endpoint: '/api/v2/scalp/live', rows: [d], subjectType: 'scalp', subjectKey: d.symbol })} style={{ cursor: 'pointer', textDecoration: 'underline dotted' }}>
                    <b style={{ fontFamily: 'monospace' }}>{d.symbol}</b> {d.change_percent ? `${d.change_percent}` : ''} {d.rvol ? `RVOL ${d.rvol}` : ''}
                  </span>
                ))}
              </div>
            </>) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No prime setups right now (need GO + grade A + verified catalyst). Watching {n} candidates.</div>}
          </div>

          {/* Summary band */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <Metric label="Signals" value={n} tip="Live scalp candidates on the screen." />
            <Metric label="GO" value={byD.GO} color={byD.GO > 0 ? '#22c55e' : undefined} tip="Candidates graded GO — passed the scalp decision gate." />
            <Metric label="Grade A" value={byG['A'] || 0} color={(byG['A'] || 0) > 0 ? '#22c55e' : undefined} tip="Top-grade setups. Grade reflects setup quality (float/RVOL/catalyst/structure)." />
            <Metric label="Catalyst ✓" value={`${catalyst}/${n}`} tip="Signals with a verified catalyst. A real catalyst is required for a prime scalp." />
            <Metric label="Social Scouts" value={scouts} color={scouts > 0 ? 'var(--social-scout)' : undefined} tip="Partial social setups meeting ≥2 of 5 scout pillars — interesting, not there yet. Awareness only: never GO, never validation-eligible, never a standard momentum_scalp." />
            <Metric label="Avg Score" value={avgScore} tip="Mean composite score across candidates (higher = stronger setup)." />
          </div>

          {/* Decision + grade distribution bars */}
          <div style={{ marginBottom: 14, display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 240px' }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}><Tip t="GO = actionable, WAIT = watch, NO-GO = rejected.">DECISION ⓘ</Tip></div>
              <div style={{ display: 'flex', height: 20, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {(['GO', 'WAIT', 'NO-GO'] as const).map(k => byD[k] > 0 && (
                  <div key={k} title={`${k}: ${byD[k]}`} style={{ width: `${(byD[k] / n) * 100}%`, background: decisionColor(k === 'NO-GO' ? 'NO' : k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>{(byD[k] / n) > 0.08 ? byD[k] : ''}</div>
                ))}
              </div>
            </div>
            <div style={{ flex: '1 1 240px' }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}><Tip t="Setup-quality grade distribution. A is best.">GRADE ⓘ</Tip></div>
              <div style={{ display: 'flex', height: 20, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {['A', 'B', 'C', 'D', 'F', '?'].map(k => (byG[k] || 0) > 0 && (
                  <div key={k} title={`${k}: ${byG[k]}`} style={{ width: `${(byG[k] / n) * 100}%`, background: GC(k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>{(byG[k] / n) > 0.08 ? `${k}:${byG[k]}` : ''}</div>
                ))}
              </div>
            </div>
          </div>

          {/* Signals table — GO + best grade first */}
          <div style={{ display: 'flex', fontSize: 9, color: 'var(--text3)', padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 66px' }}>Symbol</span>
            <span style={{ flex: '0 0 48px' }}>Grade</span>
            <span style={{ flex: '0 0 56px' }}>Decision</span>
            <span style={{ flex: '0 0 50px' }}>Score</span>
            <span style={{ flex: '0 0 60px' }}><Tip t="Relative volume vs average. Scalps want high RVOL (5x+).">RVOL</Tip></span>
            <span style={{ flex: '0 0 60px' }}>Chg %</span>
            <span style={{ flex: '0 0 54px' }}><Tip t="Catalyst verified?">Catalyst</Tip></span>
            <span style={{ flex: '1 1 auto' }}>Source</span>
          </div>
          {ordered.slice(0, 30).map((d: any, i: number) => {
            const isGo = (d.decision || '').toUpperCase() === 'GO'
            return (
            <div key={i} onClick={() => onDrill({ title: `${d.symbol} — Scalp Signal`, subtitle: `${d.decision ?? '—'} · grade ${d.grade ?? '—'} · score ${d.score ?? '—'} · RVOL ${d.rvol ?? '—'}${d.critic_verdict ? ' · ' + d.critic_verdict : ''}`, endpoint: '/api/v2/scalp/live', rows: [d], subjectType: 'scalp', subjectKey: d.symbol })}
              style={{ display: 'flex', alignItems: 'center', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, background: isGo ? 'rgba(34,197,94,.05)' : undefined }}>
              <span style={{ flex: '0 0 66px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{d.symbol}
                {(scalpExtMap[d.symbol] || []).map((e: any, j: number) => <span key={j} title={`${e.lane === 'grok' ? 'Grok' : e.lane === 'chatgpt' ? 'ChatGPT' : e.lane}: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`} style={{ marginLeft: 4, fontSize: 8, fontWeight: 700, color: e.lane === 'grok' ? '#1d9bf0' : '#10a37f', cursor: 'help' }}>✦</span>)}</span>
              <span style={{ flex: '0 0 48px' }}><span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: GC(d.grade), color: '#0a0a0a' }}>{d.grade ?? '—'}</span></span>
              <span style={{ flex: '0 0 56px', fontWeight: 600, color: decisionColor((d.decision || '').toUpperCase().startsWith('NO') ? 'NO' : (d.decision || '').toUpperCase()), fontSize: 10 }}>{d.decision ?? '—'}</span>
              <span style={{ flex: '0 0 50px', color: 'var(--text2)' }}>{d.score ?? '—'}</span>
              <span style={{ flex: '0 0 60px', color: (d.rvol || 0) >= 5 ? '#22c55e' : (d.rvol || 0) >= 2 ? '#f59e0b' : 'var(--text3)' }}>{d.rvol != null ? `${d.rvol}x` : '—'}</span>
              <span style={{ flex: '0 0 60px', color: 'var(--text2)' }}>{d.change_percent || '—'}</span>
              <span style={{ flex: '0 0 54px', textAlign: 'center' }}>{d.catalyst_verified ? <span style={{ color: '#22c55e' }}>✓</span> : <span style={{ color: 'var(--text3)' }}>—</span>}</span>
              <span style={{ flex: '1 1 auto', fontSize: 9, color: 'var(--text3)', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}><ScoutPill d={d} />{d.source ?? '—'}</span>
            </div>
          )})}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/scalp/live · click any row for the full signal. Hover ⓘ for definitions. Advisory only — scalp execution is gated.</div>
          </>)}
        </div>
        )
      })()}
      {tab === 'Manual ToS' && <ManualTosDesk />}
      {tab === 'ATM Controls' && <ATMControlPanel />}
    </div>
  )
}
