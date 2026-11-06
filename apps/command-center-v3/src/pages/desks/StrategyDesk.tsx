import { useMemo, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import DeskPage from '../../components/DeskPage'
import W7DetailSheet, { useW7Detail } from '../../components/W7DetailSheet'
import type { DrillContext } from '../../components/DetailDrawer'
import { useApi } from '../../hooks/useApi'
import { earningsQuality, groupTrades, realTrades, summarizeTrades, type ClosedTrade, type TradeGroup } from '../../lib/intelConsolidation'

/**
 * /v3/strategy — Strategy (strategy/v001 as narrowed by the Intel consolidation, operator-approved 2026-11-06).
 * Two tabs, both on real data only (no Alpaca / paper content):
 *  - Setups: closed broker round trips (/api/v2/rec-intel/lifecycle-performance, built from trade_closed) grouped by
 *    setup and by discovery source ("By discovery source" moved here from Rec Intelligence).
 *  - Earnings quality: trailing vs forward P/E for what I hold (/api/v2/portfolio/holdings).
 * Advisory only: no order, size or stop level. No verdict labels — there is no configured threshold for them yet.
 * The paper-trade lab stays reachable at /strategy/classic; it is not linked from here.
 */
export const STRATEGY_TABS = [
  { id: 'setups', label: 'Setups' },
  { id: 'earnings', label: 'Earnings quality' },
] as const

// Every former tab id lands on Setups (bookmarks / deep links).
const TAB_ALIASES: Record<string, string> = {
  leaderboard: 'setups', 'plan-vs-performance': 'setups', 'plan-vs-perf': 'setups', planner: 'setups', desk: 'setups',
  incubator: 'setups', backtests: 'setups', backtesting: 'setups', analytics: 'setups', 'by-source': 'setups', earnings_quality: 'earnings',
}

const WINDOWS = [
  { id: 'all', label: 'All', days: null },
  { id: '90', label: '90 d', days: 90 },
  { id: '30', label: '30 d', days: 30 },
] as const

const card: CSSProperties = { border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg2)', padding: 12, minWidth: 0 }
const usd = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? '—' : `${n < 0 ? '−' : n > 0 ? '+' : ''}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`)
const pct = (n: number | null | undefined, signed = false) => (n == null || !Number.isFinite(n) ? '—' : `${signed && n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(1)}%`)
const tone = (n: number | null | undefined) => (n == null ? 'var(--text2)' : n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--text2)')
const pf = (n: number | null) => (n == null ? '—' : n.toFixed(2))

function GroupRow({ g, onOpen, testId }: { g: TradeGroup; onOpen: () => void; testId: string }) {
  return (
    <button type="button" data-testid={testId} onClick={onOpen}
      style={{ textAlign: 'left', minHeight: 48, width: '100%', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)', padding: '8px 10px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', minWidth: 0 }}>
      <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
        <b style={{ textTransform: 'capitalize' }}>{g.key.replace(/_/g, ' ')}</b>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--text2)' }}>{g.trades} trade{g.trades === 1 ? '' : 's'} · {pct(g.winRatePct)} won · PF {pf(g.profitFactor)}</span>
      </span>
      <span style={{ whiteSpace: 'nowrap', fontWeight: 700, color: tone(g.total) }}>{usd(g.total)}</span>
    </button>
  )
}

function SetupsTab({ positions }: { positions: ClosedTrade[] }) {
  const [win, setWin] = useState<(typeof WINDOWS)[number]['id']>('all')
  const detail = useW7Detail()
  const days = WINDOWS.find(w => w.id === win)?.days ?? null
  const real = useMemo(() => realTrades(positions), [positions])
  const book = useMemo(() => {
    const now = Date.now()
    const rows = days ? real.filter(r => { const t = r.close_date ? Date.parse(r.close_date) : NaN; return Number.isFinite(t) && now - t <= days * 86_400_000 }) : real
    return summarizeTrades('book', rows)
  }, [real, days])
  const bySetup = useMemo(() => groupTrades(real, 'setup', { days, untagged: 'Not yet tagged' }), [real, days])
  const byOrigin = useMemo(() => groupTrades(real, 'origin', { days, untagged: 'Origin not detected' }), [real, days])

  const sel = detail.selected || ''
  const [kind, key] = sel.startsWith('setup:') ? ['setup', sel.slice(6)] as const : sel.startsWith('origin:') ? ['origin', sel.slice(7)] as const : [null, ''] as const
  const selRows = kind ? real.filter(r => (String((kind === 'setup' ? r.setup : r.origin) || '').trim() || (kind === 'setup' ? 'Not yet tagged' : 'Origin not detected')) === key) : []
  const byWindow = kind ? WINDOWS.map(w => ({ w, g: groupTrades(selRows, kind, { days: w.days, untagged: key })[0] ?? summarizeTrades(key, []) })) : []
  const recent = [...selRows].sort((a, b) => String(b.close_date || '').localeCompare(String(a.close_date || ''))).slice(0, 12)

  return (
    <div data-testid="strategy-setups" style={{ display: 'grid', gap: 14, minWidth: 0 }}>
      <div role="group" aria-label="Window" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {WINDOWS.map(w => (
          <button key={w.id} type="button" aria-pressed={win === w.id} onClick={() => setWin(w.id)}
            style={{ minHeight: 44, minWidth: 56, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', background: win === w.id ? 'var(--accent-dim)' : 'var(--bg2)', color: win === w.id ? 'var(--accent)' : 'var(--text2)' }}>{w.label}</button>
        ))}
      </div>
      <section style={card} aria-label="Realized book">
        <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 700 }}>CLOSED BROKER ROUND TRIPS · {WINDOWS.find(w => w.id === win)?.label}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 120px), 1fr))', gap: 10, marginTop: 8 }}>
          <div><div style={{ fontSize: 11, color: 'var(--text3)' }}>Trades</div><b>{book.trades}</b></div>
          <div><div style={{ fontSize: 11, color: 'var(--text3)' }}>Realized</div><b style={{ color: tone(book.total) }}>{usd(book.total)}</b></div>
          <div><div style={{ fontSize: 11, color: 'var(--text3)' }}>Win rate</div><b>{pct(book.winRatePct)}</b></div>
          <div><div style={{ fontSize: 11, color: 'var(--text3)' }}>Profit factor</div><b>{pf(book.profitFactor)}</b></div>
          <div><div style={{ fontSize: 11, color: 'var(--text3)' }}>Per trade</div><b style={{ color: tone(book.perTrade) }}>{usd(book.perTrade)}</b></div>
        </div>
      </section>
      <section style={card} aria-label="By setup">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Setups</div>
        <div style={{ display: 'grid', gap: 6 }}>
          {bySetup.map(g => <GroupRow key={g.key} g={g} testId={`setup-${g.key}`} onOpen={() => detail.open(`setup:${g.key}`)} />)}
          {!bySetup.length && <div style={{ fontSize: 12, color: 'var(--text2)' }}>No closed trades in this window.</div>}
        </div>
      </section>
      <section style={card} aria-label="By discovery source" data-testid="strategy-by-source">
        <div style={{ fontWeight: 800 }}>By discovery source</div>
        <div style={{ fontSize: 11, color: 'var(--text3)', margin: '2px 0 8px' }}>Where the idea came from → closed round trip. Moved here from Rec Intelligence.</div>
        <div style={{ display: 'grid', gap: 6 }}>
          {byOrigin.map(g => <GroupRow key={g.key} g={g} testId={`origin-${g.key}`} onOpen={() => detail.open(`origin:${g.key}`)} />)}
          {!byOrigin.length && <div style={{ fontSize: 12, color: 'var(--text2)' }}>No closed trades in this window.</div>}
        </div>
      </section>
      <div style={{ fontSize: 11, color: 'var(--text3)' }}>Source: rec-intel/lifecycle-performance (trade_closed, broker round trips; paper accounts excluded). Advisory only.</div>
      {kind && (
        <W7DetailSheet title={key.replace(/_/g, ' ')} onClose={detail.close}>
          <div style={{ display: 'grid', gap: 12, padding: 4, minWidth: 0 }}>
            <div style={{ fontSize: 12, color: 'var(--text2)' }}>{kind === 'setup' ? 'Setup' : 'Discovery source'} · closed broker round trips</div>
            <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead><tr><th style={{ textAlign: 'left' }}>Window</th>{byWindow.map(({ w }) => <th key={w.id} style={{ textAlign: 'right' }}>{w.label}</th>)}</tr></thead>
                <tbody>
                  <tr><td>Trades</td>{byWindow.map(({ w, g }) => <td key={w.id} style={{ textAlign: 'right' }}>{g.trades}</td>)}</tr>
                  <tr><td>Win rate</td>{byWindow.map(({ w, g }) => <td key={w.id} style={{ textAlign: 'right' }}>{pct(g.winRatePct)}</td>)}</tr>
                  <tr><td>Profit factor</td>{byWindow.map(({ w, g }) => <td key={w.id} style={{ textAlign: 'right' }}>{pf(g.profitFactor)}</td>)}</tr>
                  <tr><td>Per trade</td>{byWindow.map(({ w, g }) => <td key={w.id} style={{ textAlign: 'right', color: tone(g.perTrade) }}>{usd(g.perTrade)}</td>)}</tr>
                  <tr><td>Realized</td>{byWindow.map(({ w, g }) => <td key={w.id} style={{ textAlign: 'right', color: tone(g.total) }}>{usd(g.total)}</td>)}</tr>
                </tbody>
              </table>
            </div>
            <div style={{ fontWeight: 700 }}>Recent closes</div>
            <div style={{ display: 'grid', gap: 4 }}>
              {recent.map((r, i) => (
                <Link key={i} to={`/prospectus/${encodeURIComponent(String(r.symbol || ''))}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, minHeight: 44, alignItems: 'center', color: 'var(--text)', textDecoration: 'none', minWidth: 0 }}>
                  <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{String(r.close_date || '').slice(0, 10)} · <b>{r.symbol}</b> <span style={{ fontSize: 11, color: 'var(--text3)' }}>{r.account || ''}</span></span>
                  <span style={{ color: tone(r.pnl), whiteSpace: 'nowrap' }}>{usd(r.pnl)}</span>
                </Link>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>Advisory read only. No position, size or level is suggested.</div>
          </div>
        </W7DetailSheet>
      )}
    </div>
  )
}

function EarningsTab({ holdings }: { holdings: any[] }) {
  const rows = useMemo(() => earningsQuality(holdings), [holdings])
  const detail = useW7Detail()
  const sel = detail.selected?.startsWith('eq:') ? detail.selected.slice(3) : null
  const row = sel ? rows.find(r => r.symbol === sel) : null
  return (
    <div data-testid="strategy-earnings" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
      <div style={{ fontSize: 12, color: 'var(--text2)' }}>
        Is the “E” real? For each held name: trailing vs forward P/E and the EPS growth the forward multiple assumes (same price). Facts only — names with no earnings data say so.
      </div>
      <section style={card} aria-label="Held names">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Held · {rows.length} names</div>
        <div style={{ display: 'grid', gap: 6 }}>
          {rows.map(r => (
            <button key={r.symbol} type="button" data-testid={`eq-${r.symbol}`} onClick={() => detail.open(`eq:${r.symbol}`)}
              style={{ textAlign: 'left', minHeight: 48, width: '100%', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)', padding: '8px 10px', cursor: 'pointer', display: 'grid', gap: 2, minWidth: 0 }}>
              <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
                <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}><b>{r.symbol}</b> <span style={{ fontSize: 11, color: 'var(--text3)' }}>{r.sector}</span></span>
                <span style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{r.pe != null ? r.pe.toFixed(1) : '—'} → {r.forwardPe != null ? r.forwardPe.toFixed(1) : '—'}</span>
              </span>
              <span style={{ fontSize: 11, color: 'var(--text2)' }}>{r.note}</span>
            </button>
          ))}
          {!rows.length && <div style={{ fontSize: 12, color: 'var(--text2)' }}>No holdings on file.</div>}
        </div>
      </section>
      <div style={{ fontSize: 11, color: 'var(--text3)' }}>Source: portfolio/holdings (P/E and forward P/E as stored on each holding). Estimate revisions, beat-then-cut and guidance checks need data the house does not store yet.</div>
      {row && (
        <W7DetailSheet title={`${row.symbol} · earnings quality`} onClose={detail.close}>
          <div style={{ display: 'grid', gap: 10, padding: 4 }}>
            <div style={{ fontSize: 13 }}>{row.company}</div>
            <div style={card}>
              <div>Trailing P/E: <b>{row.pe != null ? row.pe.toFixed(1) : 'no data'}</b></div>
              <div>Forward P/E: <b>{row.forwardPe != null ? row.forwardPe.toFixed(1) : 'no data'}</b></div>
              <div>PEG: <b>{row.peg != null ? row.peg.toFixed(2) : 'no data'}</b></div>
              <div>EPS growth implied by the forward multiple: <b>{pct(row.impliedEpsGrowthPct, true)}</b></div>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text2)' }}>{row.note}</div>
            <Link to={`/prospectus/${encodeURIComponent(row.symbol)}`} style={{ color: 'var(--accent)', minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Open prospectus →</Link>
          </div>
        </W7DetailSheet>
      )}
    </div>
  )
}

export default function StrategyDesk(_props: { onDrill: (ctx: DrillContext) => void }) {
  const life = useApi<any>('/api/v2/rec-intel/lifecycle-performance?limit=300', 300_000)
  const hold = useApi<any>('/api/v2/portfolio/holdings', 300_000)
  const positions: ClosedTrade[] = life.data?.positions ?? []
  const holdings: any[] = hold.data?.data?.holdings ?? hold.data?.holdings ?? []
  const lastClose = positions.map(p => String(p.close_date || '')).sort().pop() || null
  const lifeErr = life.error || (life.data?.ok === false ? String(life.data?.error || 'error') : null)
  return (
    <div data-testid="strategy-desk" style={{ padding: '16px', maxWidth: 1240, minWidth: 0, boxSizing: 'border-box' }}>
      <DeskPage title="Strategy" purpose="Which of my real trading styles are making money, and whether the earnings behind what I hold are real."
        tabs={STRATEGY_TABS} defaultTab="setups" tabAliases={TAB_ALIASES}
        sources={[
          { id: 'round-trips', label: 'Closed broker round trips', clockOnly: true, note: lastClose ? `Latest close ${lastClose.slice(0, 10)}` : undefined, gap: lifeErr ? `Unavailable: ${lifeErr}` : undefined },
          { id: 'holdings', label: 'Holdings fundamentals', asOf: hold.data?.data?.as_of ?? hold.data?.as_of ?? null, laneIds: ['schwab-position-sync'] },
        ]}
        decisionGap="Advisory read only — nothing here needs a decision.">
        {(tab: string) => (
          tab === 'earnings'
            ? (hold.loading && !holdings.length ? <div style={{ color: 'var(--text2)' }}>Loading holdings…</div> : <EarningsTab holdings={holdings} />)
            : (life.loading && !positions.length ? <div style={{ color: 'var(--text2)' }}>Loading round trips…</div>
              : lifeErr && !positions.length ? <div style={{ color: 'var(--amber)' }}>Round trips unavailable: {lifeErr}</div>
                : <SetupsTab positions={positions} />)
        )}
      </DeskPage>
    </div>
  )
}
