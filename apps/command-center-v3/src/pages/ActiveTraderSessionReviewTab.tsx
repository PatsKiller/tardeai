import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import './activeTrader.css';

// Active Trader session review (operator 2026-10-05): what the engine did vs what "should have been",
// your fills, and the automated mode run as a SIMULATION (no order path exists). Read-only:
// GET /api/v3/active-trader/session-review?day=YYYY-MM-DD. Method: docs/active_trader/ACTIVE_TRADER_SOUL.md.

type Row = { ts: number; time: string; price: number | null; engine: string; should: string; source: string };
type Ideal = { kind: string; ts: number; price: number; stop: number; exit_ts: number; exit_price: number; exit_reason: string; pnl_pct: number; why: string };
type SymReview = {
  symbol: string; bars: number; table: Row[]; ideal_trades: Ideal[];
  metrics: { latency_s: number[]; latency_max_s: number | null; missed: { reasons: string[] }[]; chases: unknown[];
             correct_heads_up: number; ideal_pnl_pct: number; ideal_pnl_per_share: number; your_pnl: number | null };
};
type SimTrade = { status: string; kind: string; entry_ts: number; fill?: number; exit_price?: number; exit_reason?: string; pnl?: number; reason?: string; symbol: string };
type SimSource = { metrics: { attempted: number; filled: number; fill_feasibility: number | null; win_rate: number | null; net_pnl: number; avg_r: number | null; max_drawdown: number };
                   trades: SimTrade[] };
type Review = {
  day: string; symbols: SymReview[];
  auto_sim?: { mode: string; size_shares: number | null; size_notional_usd?: number | null; improved_timing_label: string;
               compare: { manual_pnl: number; engine_sim_pnl: number; improved_sim_pnl: number; should_have_been_pnl: number };
               sources: Record<string, SimSource> };
};
type Feed = { day: string | null; days: string[]; review: Review | null };

const money = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(v).toFixed(2)}`);
const px = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(2));
const hhmm = (ts?: number) => (ts ? new Date(ts * 1000).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }) : '—');

export default function ActiveTraderSessionReviewTab() {
  const [day, setDay] = useState('');
  const { data, error, loading } = useApi<Feed>(`/api/v3/active-trader/session-review${day ? `?day=${day}` : ''}`, 60_000);
  if (loading && !data) return <div className="active-trader-page at-review"><div className="at-fullstate">Loading session review…</div></div>;
  if (error && !data) return <div className="active-trader-page at-review"><div className="at-fullstate at-fullstate--fail">Session review unavailable: {String(error)}</div></div>;
  const rv = data?.review;
  const cmp = rv?.auto_sim?.compare;
  return (
    <div className="active-trader-page at-review" data-testid="at-session-review">
      <header className="at-alerts__hero">
        <div>
          <h1>Session review <small>engine vs should have been</small></h1>
          <p>Every decision is replayed against the minute bars and graded against a fixed method: enter on a base breakout or a pullback into the zone, exit on evidence or the stop, never chase. The automated mode runs here as a simulation only.</p>
        </div>
        <label className="at-alerts__select">
          <span>Day</span>
          <select id="at-review-day" value={day || data?.day || ''} onChange={e => setDay(e.target.value)}>
            {(data?.days?.length ? data.days : [data?.day ?? '']).map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
      </header>

      {!rv ? (
        <div className="at-empty-card" data-testid="at-review-empty">
          <strong>No review for this day yet.</strong>
          <p>The review runs after the engine window (12:05 ET) and at the close.</p>
        </div>
      ) : (
        <>
          {cmp && (
            <section className="at-review__compare" aria-label="P&L comparison" data-testid="at-review-compare">
              <div className="at-review__cell"><small>You (manual)</small><strong>{money(cmp.manual_pnl)}</strong><span>your fills</span></div>
              <div className="at-review__cell"><small>Auto-sim · engine timing</small><strong>{money(cmp.engine_sim_pnl)}</strong><span>{rv.auto_sim?.size_notional_usd ? `$${rv.auto_sim.size_notional_usd.toLocaleString()} per entry` : `${rv.auto_sim?.size_shares ?? '—'} sh per entry`}</span></div>
              <div className="at-review__cell"><small>Auto-sim · improved timing</small><strong>{money(cmp.improved_sim_pnl)}</strong><span>{rv.auto_sim?.improved_timing_label}</span></div>
              <div className="at-review__cell"><small>Should have been</small><strong>{money(cmp.should_have_been_pnl)}</strong><span>same sizing, no costs</span></div>
            </section>
          )}
          {rv.symbols.map(s => <SymbolReview key={s.symbol} s={s} sim={rv.auto_sim?.sources} />)}
          <p className="at-alerts__note">Simulation only — no order, size or stop is created from this page. Mode: {rv.auto_sim?.mode ?? 'manual'}.</p>
        </>
      )}
    </div>
  );
}

function SymbolReview({ s, sim }: { s: SymReview; sim?: Record<string, SimSource> }) {
  const m = s.metrics;
  const simTrades = Object.entries(sim ?? {}).flatMap(([src, b]) => b.trades.filter(t => t.symbol === s.symbol).map(t => ({ ...t, src })));
  return (
    <section className="at-panel at-review__sym" data-testid="at-review-symbol">
      <header className="at-panel__header">
        <h2>{s.symbol} <small>ideal {m.ideal_pnl_pct >= 0 ? '+' : ''}{m.ideal_pnl_pct.toFixed(1)}% · {s.ideal_trades.length} entries{m.your_pnl != null ? ` · you ${money(m.your_pnl)}` : ''}</small></h2>
        <div className="at-inline at-wrap">
          {m.latency_max_s != null && <span className="at-chip at-chip--warning">buy alert late {Math.round(m.latency_max_s / 60)}m{m.latency_max_s % 60}s</span>}
          {m.missed.length > 0 && <span className="at-chip at-chip--fail">{m.missed.length} entry missed ({Array.from(new Set(m.missed.flatMap(x => x.reasons))).join(', ')})</span>}
          {m.chases.length > 0 && <span className="at-chip at-chip--fail">{m.chases.length} chase</span>}
          {m.correct_heads_up > 0 && <span className="at-chip at-chip--pass">{m.correct_heads_up} heads-up on time</span>}
        </div>
      </header>
      <div className="at-review__tablewrap">
        <table className="at-review__table">
          <thead><tr><th>Time (ET)</th><th>Price</th><th>Engine</th><th>Should have been</th></tr></thead>
          <tbody>
            {s.table.map((r, i) => (
              <tr key={`${r.ts}-${i}`} className={`is-${r.source}`}>
                <td className="mono">{r.time}</td><td className="mono">{px(r.price)}</td><td>{r.engine}</td><td>{r.should}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {simTrades.length > 0 && (
        <div className="at-review__sim">
          <b>Auto-sim</b>
          {simTrades.map((t, i) => (
            <span key={i} className="at-source">
              {t.src === 'engine' ? 'engine' : 'improved'} · {t.kind} {hhmm(t.entry_ts)} {t.status === 'FILLED' ? `${px(t.fill)} → ${px(t.exit_price)} (${t.exit_reason}) ${money(t.pnl)}` : `refused: ${t.reason}`}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
